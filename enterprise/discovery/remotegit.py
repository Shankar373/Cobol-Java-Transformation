"""Remote Git ingestion over HTTPS / SSH (Stage 1 design, section 4).

Threat model: the URL, the repository and the server are all attacker
influenced.  Address validation, the SSRF rules and credential scrubbing live
in :mod:`enterprise.discovery.remotegit_policy`; this module does the git work:

1. **Ref -> exact commit** (:func:`resolve_ref`) before any content is
   fetched; annotated tags are peeled, a 40-hex value is the pin itself.
2. **Environment**: protocol allow-list, resolved-IP pinning, redirects off,
   proxies ignored, and the optional token.  The token (``SYSTEMAOPS_GIT_TOKEN``)
   travels only in ``GIT_CONFIG_COUNT`` / ``GIT_CONFIG_KEY_n`` /
   ``GIT_CONFIG_VALUE_n`` environment entries scoped to the exact host,
   never in an argument vector.  SSH is locked down with ``BatchMode``,
   strict host keys and ``IdentitiesOnly``.
3. **Fetch the pinned commit** into a fresh repository under a size
   watchdog, then hand it to the existing safe checkout path
   (:func:`enterprise.discovery.gitingest.checkout_verify_inventory`).

Limitations stated up front: HTTP(S) proxies from the environment are
deliberately ignored (a proxy would bypass address pinning), and SSH host
resolution is pinned through ``HostName``/``HostKeyAlias``, so the
``known_hosts`` file must carry the host name, not the IP.
"""

from __future__ import annotations

import base64
import os
import shlex
from pathlib import Path
from typing import Mapping

from . import gitingest
from .errors import DiagnosticSink, IngestionError
from .gitingest import (
    SizeWatch,
    _git,
    _hardened_env,
    _rev_parse,
    checkout_verify_inventory,
)
from .limits import DEFAULT_LIMITS, Limits
from .model import IngestionResult
from .remotegit_policy import (
    _DEFAULT_PORTS,
    _SHA40_RE,
    _SHA_ABBREV_RE,
    NetworkPolicy,
    RemoteSpec,
    ResolvedRef,
    _literal_ip,
    _scrub_error,
    check_host_public,
    parse_remote_url,
    scrub,
    validate_ref_name,
)

_MIN_PINNING_GIT = (2, 37, 0)

__all__ = [
    "NetworkPolicy",
    "RemoteSpec",
    "ResolvedRef",
    "check_host_public",
    "ingest_remote_git",
    "parse_remote_url",
    "resolve_ref",
    "scrub",
    "validate_ref_name",
]


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------


def _parse_ls_remote(output: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    for line in output.splitlines():
        sha, _, name = line.partition("\t")
        if _SHA40_RE.match(sha) and name:
            refs[name.strip()] = sha.lower()
    return refs


def _select_ref(name: str, refs: Mapping[str, str]) -> ResolvedRef:
    if name == "HEAD":
        if "HEAD" not in refs:
            raise IngestionError("remote has no HEAD", code="REF_NOT_FOUND")
        return ResolvedRef(refs["HEAD"], "head", "HEAD")
    if name.startswith("refs/"):
        candidates = [name]
    else:
        candidates = [f"refs/heads/{name}", f"refs/tags/{name}"]
    found: list[ResolvedRef] = []
    for full in candidates:
        sha = refs.get(f"{full}^{{}}") or refs.get(full)  # peel annotated tags
        if sha is None:
            continue
        kind = (
            "branch" if full.startswith("refs/heads/")
            else "tag" if full.startswith("refs/tags/") else "ref"
        )
        found.append(ResolvedRef(sha, kind, full))
    if not found:
        raise IngestionError("ref not found on remote", code="REF_NOT_FOUND")
    if len({r.sha for r in found}) > 1:
        raise IngestionError(
            "ref name matches both a branch and a tag with different commits; "
            "use the full ref name or the 40-hex commit",
            code="REF_AMBIGUOUS",
        )
    return found[0]


def _ls_patterns(name: str) -> list[str]:
    if name == "HEAD":
        return ["HEAD"]
    fulls = [name] if name.startswith("refs/") else [
        f"refs/heads/{name}", f"refs/tags/{name}"
    ]
    return [p for full in fulls for p in (full, f"{full}^{{}}")]


def resolve_ref(
    spec: RemoteSpec,
    ref: str | None,
    env: dict[str, str],
    policy: NetworkPolicy,
) -> ResolvedRef:
    """Resolve *ref* (branch, tag, ``HEAD`` or 40-hex SHA) to a commit.

    A 40-hex value is the pin itself and needs no network.  Abbreviated SHAs
    are ambiguous for a remote and refused.  Annotated tags are peeled.
    *policy* is accepted for interface symmetry: the host check and address
    pinning already happened when *env* was built.
    """

    del policy
    name = ref if ref else "HEAD"
    if _SHA40_RE.match(name):
        return ResolvedRef(name.lower(), "commit", "")
    if _SHA_ABBREV_RE.match(name):
        raise IngestionError(
            "abbreviated commit names are ambiguous for a remote; use the "
            "full 40-hex SHA",
            code="REF_AMBIGUOUS",
        )
    validate_ref_name(name)
    try:
        proc = _git(
            ["ls-remote", "--", spec.fetch_url, *_ls_patterns(name)],
            env,
            what="ls-remote",
        )
    except IngestionError as exc:
        _scrub_error(exc, _secrets_from_env(env))
        if exc.code == "GIT_FAILED":
            raise IngestionError(
                f"remote could not be queried: {exc.message}",
                code="REMOTE_UNREACHABLE",
            ) from None
        raise
    return _select_ref(name, _parse_ls_remote(proc.stdout))


# ---------------------------------------------------------------------------
# Environment (credentials, pinning, protocol allow-list)
# ---------------------------------------------------------------------------


def _basic_header(token: str) -> str:
    raw = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    return f"Authorization: Basic {raw}"


def _token_secrets(token: str) -> tuple[str, ...]:
    """Every textual form a token can take on the wire."""

    if not token:
        return ()
    header = _basic_header(token)
    return (token, header, header.rsplit(" ", 1)[-1])


def _secrets_from_env(env: Mapping[str, str]) -> tuple[str, ...]:
    """Credentials present in *env* (config-entry headers, plain variables)."""

    found: set[str] = set()
    count = env.get("GIT_CONFIG_COUNT", "0")
    for index in range(int(count) if count.isdigit() else 0):
        key = env.get(f"GIT_CONFIG_KEY_{index}", "")
        value = env.get(f"GIT_CONFIG_VALUE_{index}", "")
        if key.lower().endswith(".extraheader") and value:
            found.add(value)
            blob = value.rsplit(" ", 1)[-1]
            found.add(blob)
            try:
                found.add(base64.b64decode(blob).decode().split(":", 1)[1])
            except (ValueError, IndexError, UnicodeDecodeError):
                pass
    token = env.get("SYSTEMAOPS_GIT_TOKEN", "")
    if token:
        found.add(token)
    return tuple(found)


def _curl_address(address: str) -> str:
    return f"[{address}]" if ":" in address else address


def _url_scope(spec: RemoteSpec) -> str:
    host = f"[{spec.host}]" if ":" in spec.host else spec.host
    port = "" if spec.port == _DEFAULT_PORTS[spec.scheme] else f":{spec.port}"
    return f"{spec.scheme}://{host}{port}/"


def token_for(spec: RemoteSpec, os_env: Mapping[str, str]) -> str:
    """The token to send to *spec*, or ``""``.

    The token is attached only when the operator listed the exact host in
    ``SYSTEMAOPS_GIT_TOKEN_HOSTS`` (comma separated, case-insensitive, no wildcards):
    the URL comes from the requester, so without this list any requester could
    point the token at a host they control.
    """

    token = os_env.get("SYSTEMAOPS_GIT_TOKEN", "")
    listed = {
        h.strip().lower()
        for h in os_env.get("SYSTEMAOPS_GIT_TOKEN_HOSTS", "").split(",")
        if h.strip()
    }
    return token if token and spec.host.lower() in listed else ""


def _config_entries(
    spec: RemoteSpec, ips: tuple[str, ...], token: str
) -> list[tuple[str, str]]:
    entries = [
        ("protocol.allow", "never"),
        (f"protocol.{spec.scheme}.allow", "always"),
        ("http.followRedirects", "false"),
        ("http.proxy", ""),
        ("credential.helper", ""),
        ("transfer.fsckObjects", "true"),
        ("fetch.recurseSubmodules", "false"),
        ("submodule.recurse", "false"),
        ("gc.auto", "0"),
        ("core.fsmonitor", "false"),
    ]
    if spec.scheme in ("http", "https"):
        entries.append(("http.sslVerify", "true"))
        if _literal_ip(spec.host) is None:
            addresses = ",".join(_curl_address(a) for a in ips)
            entries.append(
                ("http.curloptResolve", f"{spec.host}:{spec.port}:{addresses}")
            )
        if token and spec.scheme == "https":
            entries.append(
                (f"http.{_url_scope(spec)}.extraHeader", _basic_header(token))
            )
    return entries


def _apply_config(env: dict[str, str], entries: list[tuple[str, str]]) -> None:
    env["GIT_CONFIG_COUNT"] = str(len(entries))
    for index, (key, value) in enumerate(entries):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value


def _ssh_files(os_env: Mapping[str, str]) -> tuple[str, str]:
    key = os_env.get("SYSTEMAOPS_GIT_SSH_KEY", "")
    known = os_env.get("SYSTEMAOPS_GIT_KNOWN_HOSTS", "")
    if not (key and known and Path(key).is_file() and Path(known).is_file()):
        raise IngestionError(
            "SSH requires SYSTEMAOPS_GIT_SSH_KEY and SYSTEMAOPS_GIT_KNOWN_HOSTS to name "
            "existing files",
            code="SSH_NOT_CONFIGURED",
        )
    return key, known


def _ssh_command(
    spec: RemoteSpec, ips: tuple[str, ...], key: str, known_hosts: str
) -> str:
    options = [
        "IdentitiesOnly=yes",
        "IdentityAgent=none",
        "UpdateHostKeys=no",
        "CheckHostIP=no",
        f"GlobalKnownHostsFile={os.devnull}",
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        f"UserKnownHostsFile={known_hosts}",
        "ForwardAgent=no",
        "ClearAllForwardings=yes",
        "ProxyCommand=none",
        "ProxyJump=none",
        "PasswordAuthentication=no",
        f"HostName={ips[0]}",
        f"HostKeyAlias={spec.host}",
    ]
    parts = ["ssh", "-F", os.devnull, "-i", key]
    for option in options:
        parts += ["-o", option]
    return " ".join(shlex.quote(p) for p in parts)


def _build_env(
    spec: RemoteSpec,
    ips: tuple[str, ...],
    staging: Path,
    os_env: Mapping[str, str],
) -> dict[str, str]:
    """Hardened environment plus protocol allow-list, pinning and credentials."""

    env = _hardened_env(staging)
    for key in list(env):
        lowered = key.lower()
        if (
            lowered.startswith("systemaops_git_")
            or lowered.endswith("_proxy")
            or lowered in ("ssh_auth_sock", "ssh_askpass")
        ):
            env.pop(key, None)
    env["GIT_ALLOW_PROTOCOL"] = spec.scheme
    _apply_config(env, _config_entries(spec, ips, token_for(spec, os_env)))
    if spec.scheme == "ssh":
        key_path, known = _ssh_files(os_env)
        env["GIT_SSH_COMMAND"] = _ssh_command(spec, ips, key_path, known)
        env["GIT_SSH_VARIANT"] = "ssh"
    return env


# ---------------------------------------------------------------------------
# Fetch and ingest
# ---------------------------------------------------------------------------


def _fetch_commit(
    dest: Path,
    resolved: ResolvedRef,
    env: dict[str, str],
    limits: Limits,
) -> str:
    """Fetch the pinned commit into *dest*; return the verified commit id."""

    watch = SizeWatch(dest / ".git", limits.max_total_bytes)
    base = ["fetch", "--depth=1", "--no-tags", "--no-recurse-submodules", "origin"]
    try:
        _git([*base, resolved.sha], env, cwd=dest, what="fetch", watch=watch)
    except IngestionError as exc:
        if exc.code != "GIT_FAILED":
            raise
        _fetch_by_ref(dest, resolved, env, base, watch)
    return _rev_parse(dest, env, f"{resolved.sha}^{{commit}}", resolved.sha)


def _fetch_by_ref(
    dest: Path,
    resolved: ResolvedRef,
    env: dict[str, str],
    base: list[str],
    watch: SizeWatch,
) -> None:
    """Fallback for servers that refuse to serve a commit by SHA."""

    if not resolved.ref_name:
        raise IngestionError(
            "server did not provide the pinned commit",
            code="COMMIT_NOT_FOUND",
            path=resolved.sha,
        )
    _git([*base, resolved.ref_name], env, cwd=dest, what="fetch", watch=watch)
    head = _rev_parse(dest, env, "FETCH_HEAD^{commit}", "FETCH_HEAD")
    if head.lower() != resolved.sha:
        raise IngestionError(
            f"ref {resolved.ref_name} moved from {resolved.sha} to {head} "
            "between resolution and fetch",
            code="COMMIT_MOVED",
            path=resolved.sha,
        )


def _init_repository(staging: Path, spec: RemoteSpec, env: dict[str, str]) -> Path:
    template = staging / ".discovery-empty-template"
    template.mkdir(parents=True, exist_ok=True)
    dest = staging / "repo"
    _git(["init", "-q", f"--template={template}", str(dest)], env, what="init")
    _git(["remote", "add", "origin", spec.fetch_url], env, cwd=dest, what="remote")
    return dest


def _require_modern_git(spec: RemoteSpec) -> None:
    """``http.curloptResolve`` (address pinning) needs git 2.37+: fail closed."""

    if _literal_ip(spec.host) is not None or spec.scheme == "ssh":
        return
    if gitingest.git_version() < _MIN_PINNING_GIT:
        raise IngestionError(
            "git is older than 2.37, which cannot pin the resolved address "
            "for HTTPS; refusing rather than fetching unpinned",
            code="GIT_TOO_OLD",
        )


def _note_unsent_token(
    spec: RemoteSpec, os_env: Mapping[str, str], sink: DiagnosticSink
) -> None:
    if (
        os_env.get("SYSTEMAOPS_GIT_TOKEN")
        and spec.scheme != "ssh"
        and not token_for(spec, os_env)
    ):
        sink.info(
            "REMOTE_TOKEN_NOT_SENT",
            "token not sent: host not in SYSTEMAOPS_GIT_TOKEN_HOSTS",
        )


def _ingest(
    url: str,
    staging: Path,
    ref: str | None,
    allow_ssh: bool,
    policy: NetworkPolicy,
    limits: Limits,
    sink: DiagnosticSink,
    os_env: Mapping[str, str],
) -> IngestionResult:
    spec = parse_remote_url(
        url,
        allow_ssh=allow_ssh,
        allow_insecure_http=policy.allow_insecure_http_for_tests,
    )
    if spec.scheme == "ssh":
        _ssh_files(os_env)
    ips = check_host_public(spec.host, policy)
    _require_modern_git(spec)
    _note_unsent_token(spec, os_env, sink)
    env = _build_env(spec, ips, staging, os_env)
    resolved = resolve_ref(spec, ref, env, policy)
    sink.info(
        "REMOTE_REF_RESOLVED",
        f"{spec.display_url} {ref or 'HEAD'} resolved to {resolved.sha}",
    )
    dest = _init_repository(staging, spec, env)
    pinned = _fetch_commit(dest, resolved, env, limits)
    result = checkout_verify_inventory(
        dest,
        pinned,
        env,
        no_hooks=staging / ".discovery-no-hooks",
        origin=spec.display_url,
        sink=sink,
        limits=limits,
        watch=SizeWatch(
            dest, limits.max_total_bytes, (".git",), limits.max_entries
        ),
    )
    result.ref = ref or "HEAD"
    result.remote = spec.display_url
    return result


def ingest_remote_git(
    url: str,
    staging: Path,
    *,
    ref: str | None = None,
    allow_ssh: bool = False,
    policy: NetworkPolicy = NetworkPolicy(),
    limits: Limits = DEFAULT_LIMITS,
    sink: DiagnosticSink | None = None,
) -> IngestionResult:
    """Fetch *ref* of the remote at *url* into *staging* and inventory it.

    *staging* must be a fresh directory the caller owns and can discard.  The
    result's ``commit`` is the exact 40-hex SHA fetched; ``tree_id``, ``ref``
    and ``remote`` (credential-free URL) are set too.  Every raised
    :class:`IngestionError` has been scrubbed of credentials.
    """

    staging = Path(staging).resolve()
    sink = sink if sink is not None else DiagnosticSink(limits.max_diagnostics)
    os_env = dict(os.environ)
    secrets = _token_secrets(os_env.get("SYSTEMAOPS_GIT_TOKEN", ""))
    try:
        return _ingest(
            url, staging, ref, allow_ssh, policy, limits, sink, os_env
        )
    except IngestionError as exc:
        _scrub_error(exc, secrets)
        raise

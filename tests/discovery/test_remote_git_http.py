"""End-to-end remote Git over a real smart-HTTP transport.

A tiny threaded HTTP server on ``127.0.0.1`` serves a bare repository through
``git http-backend`` (CGI), so the code under test runs the genuine
``git ls-remote`` / ``git fetch`` smart-HTTP protocol.  Loopback is only
reachable because the test passes ``NetworkPolicy(allow_hosts=("127.0.0.1",),
allow_insecure_http_for_tests=True)``; both default to closed.

If ``git http-backend`` cannot be found the HTTP tests are skipped with a
reason, and ``test_fetch_flow_through_a_local_path_remote`` still exercises
the fetch -> verify -> inventory flow through a ``file://`` remote.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.discovery.helpers import REPO_ROOT, codes_of, expect_refusal, make_zip, read_json, write_enterprise_app, write_tree  # noqa: F401

from enterprise.discovery import remotegit
from enterprise.discovery.errors import DiagnosticSink
from enterprise.discovery.gitingest import _hardened_env, checkout_verify_inventory
from enterprise.discovery.limits import DEFAULT_LIMITS
from enterprise.discovery.remotegit import (
    NetworkPolicy,
    RemoteSpec,
    ingest_remote_git,
    parse_remote_url,
    resolve_ref,
)

GIT = shutil.which("git")
COMMITTER = (
    "-c", "user.email=discovery@example.invalid",
    "-c", "user.name=P1",
    "-c", "commit.gpgsign=false",
)
POLICY = NetworkPolicy(
    allow_hosts=("127.0.0.1",), allow_insecure_http_for_tests=True
)


def _http_backend_available() -> bool:
    if GIT is None:
        return False
    proc = subprocess.run(
        [GIT, "--exec-path"], capture_output=True, text=True, timeout=60
    )
    exec_path = Path(proc.stdout.strip())
    return any(
        (exec_path / name).exists()
        for name in ("git-http-backend", "git-http-backend.exe")
    )


needs_http = pytest.mark.skipif(
    not _http_backend_available(),
    reason="git http-backend is not installed under `git --exec-path`",
)
pytestmark = pytest.mark.skipif(GIT is None, reason="git is required")


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        [str(GIT), *COMMITTER, *args],
        cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# A CGI bridge to `git http-backend`
# ---------------------------------------------------------------------------


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    if handler.headers.get("Transfer-Encoding", "").lower() == "chunked":
        chunks = []
        while True:
            size = int(handler.rfile.readline().split(b";")[0].strip() or b"0", 16)
            if size == 0:
                handler.rfile.readline()
                return b"".join(chunks)
            chunks.append(handler.rfile.read(size))
            handler.rfile.readline()
    length = int(handler.headers.get("Content-Length") or 0)
    return handler.rfile.read(length) if length else b""


class _GitCgiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    project_root: Path
    speak_v0 = False
    requests: list[str]

    def log_message(self, *args: object) -> None:  # silence the test log
        return None

    def _serve(self) -> None:
        parts = urlsplit(self.path)
        body = _read_body(self)
        env = dict(os.environ)
        env.update(
            GIT_PROJECT_ROOT=str(self.project_root),
            GIT_HTTP_EXPORT_ALL="1",
            REQUEST_METHOD=self.command,
            PATH_INFO=parts.path,
            QUERY_STRING=parts.query,
            CONTENT_TYPE=self.headers.get("Content-Type", ""),
            CONTENT_LENGTH=str(len(body)),
            REMOTE_ADDR="127.0.0.1",
            SERVER_PROTOCOL="HTTP/1.1",
        )
        if self.headers.get("Content-Encoding"):
            env["HTTP_CONTENT_ENCODING"] = self.headers["Content-Encoding"]
        if self.headers.get("Git-Protocol") and not self.speak_v0:
            env["GIT_PROTOCOL"] = self.headers["Git-Protocol"]
        self.requests.append(f"{self.command} {parts.path}?{parts.query}")
        proc = subprocess.run(
            [str(GIT), "http-backend"], input=body, env=env,
            capture_output=True, timeout=120,
        )
        split = re.search(rb"\r?\n\r?\n", proc.stdout)
        assert split is not None, proc.stderr.decode("utf-8", "replace")
        head = proc.stdout[: split.start()]
        payload = proc.stdout[split.end():]
        status = "200 OK"
        headers: list[tuple[str, str]] = []
        for line in head.decode("latin-1").splitlines():
            name, _, value = line.partition(":")
            if name.lower() == "status":
                status = value.strip()
            elif name:
                headers.append((name, value.strip()))
        code, _, reason = status.partition(" ")
        self.send_response(int(code), reason or None)
        for name, value in headers:
            if name.lower() != "content-length":
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _serve
    do_POST = _serve


class _Remote:
    """A served bare repository plus the work repository that feeds it."""

    def __init__(self, root: Path) -> None:
        root.mkdir(exist_ok=True)
        self.work = root / "work"
        self.bare_root = root / "served"
        self.bare_root.mkdir()
        self.bare = self.bare_root / "repo.git"
        self.requests: list[str] = []
        self._build()
        handler = type(
            "Handler", (_GitCgiHandler,),
            {"project_root": self.bare_root, "requests": self.requests},
        )
        self.handler = handler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/repo.git"

    def _build(self) -> None:
        self.work.mkdir()
        _git(self.work, "init", "-q", "-b", "main")
        _git(self.work, "config", "core.autocrlf", "false")
        write_enterprise_app(self.work)
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", "initial")
        self.main_sha = _git(self.work, "rev-parse", "HEAD")
        _git(self.work, "tag", "v-light")
        _git(self.work, "tag", "-a", "v1.0", "-m", "release 1.0")
        _git(self.work, "checkout", "-q", "-b", "feature")
        (self.work / "FEATURE.txt").write_text("feature\n", encoding="utf-8")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", "feature")
        self.feature_sha = _git(self.work, "rev-parse", "HEAD")
        _git(self.work, "checkout", "-q", "main")
        _git(self.work.parent, "clone", "-q", "--bare", str(self.work), str(self.bare))

    def advance_main(self) -> str:
        """Push a new commit to ``main`` and return its SHA."""

        (self.work / "NEXT.txt").write_text("next\n", encoding="utf-8")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", "next")
        _git(self.work, "push", "-q", str(self.bare), "main")
        return _git(self.work, "rev-parse", "HEAD")

    def create_topic(self) -> str:
        """Publish ``topic``: a commit reachable from no other ref."""

        _git(self.work, "checkout", "-q", "-b", "topic", "main")
        (self.work / "TOPIC.txt").write_text("topic\n", encoding="utf-8")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", "topic")
        _git(self.work, "push", "-q", str(self.bare), "topic")
        return _git(self.work, "rev-parse", "HEAD")

    def rewrite_topic(self) -> str:
        """Force-push a rewritten ``topic``; the old tip becomes unreachable."""

        _git(self.work, "commit", "-q", "--amend", "-m", "rewritten")
        _git(self.work, "push", "-q", "-f", str(self.bare), "topic")
        return _git(self.work, "rev-parse", "HEAD")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory):
    """Read-only remote shared by the tests that never change it."""

    served = _Remote(tmp_path_factory.mktemp("shared-remote"))
    yield served
    served.close()


@pytest.fixture()
def mutable_remote(tmp_path: Path):
    """A private remote for tests that move refs or change the protocol."""

    served = _Remote(tmp_path / "private-remote")
    yield served
    served.close()


def _stage(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _records(result) -> list[tuple[str, str, int]]:
    return sorted((f.path, f.sha256, f.size) for f in result.files)


def _resolve(remote: _Remote, tmp_path: Path, ref: str | None):
    spec = parse_remote_url(
        remote.url, allow_ssh=False, allow_insecure_http=True
    )
    ips = remotegit.check_host_public(spec.host, POLICY)
    env = remotegit._build_env(spec, ips, _stage(tmp_path, f"r-{ref or 'head'}".replace("/", "_")), os.environ)
    return resolve_ref(spec, ref, env, POLICY)


# ---------------------------------------------------------------------------
# Ref resolution over smart HTTP
# ---------------------------------------------------------------------------


@needs_http
def test_branch_resolves_to_its_commit(remote, tmp_path) -> None:
    resolved = _resolve(remote, tmp_path, "feature")
    assert (resolved.sha, resolved.ref_kind, resolved.ref_name) == (
        remote.feature_sha, "branch", "refs/heads/feature"
    )


@needs_http
def test_default_head_resolves_to_main(remote, tmp_path) -> None:
    resolved = _resolve(remote, tmp_path, None)
    assert resolved.sha == remote.main_sha and resolved.ref_kind == "head"


@needs_http
def test_lightweight_tag_resolves(remote, tmp_path) -> None:
    resolved = _resolve(remote, tmp_path, "v-light")
    assert (resolved.sha, resolved.ref_kind) == (remote.main_sha, "tag")


@needs_http
def test_annotated_tag_is_peeled_to_the_commit(remote, tmp_path) -> None:
    tag_object = _git(remote.work, "rev-parse", "v1.0")
    assert tag_object != remote.main_sha
    resolved = _resolve(remote, tmp_path, "v1.0")
    assert resolved.sha == remote.main_sha
    assert resolved.sha != tag_object


@needs_http
def test_unknown_ref_is_refused(remote, tmp_path) -> None:
    assert expect_refusal(_resolve, remote, tmp_path, "nope") == "REF_NOT_FOUND"


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


@needs_http
def test_branch_is_ingested_at_its_exact_commit(remote, tmp_path) -> None:
    result = ingest_remote_git(
        remote.url, _stage(tmp_path, "s"), ref="feature", policy=POLICY
    )
    assert result.kind == "git"
    assert result.commit == remote.feature_sha
    assert result.tree_id == _git(remote.work, "rev-parse", "feature^{tree}")
    assert result.ref == "feature"
    assert result.remote == remote.url
    paths = {f.path for f in result.files}
    assert "FEATURE.txt" in paths and "src/cobol/PAYROLL.cbl" in paths
    assert not any(p == ".git" or p.startswith(".git/") for p in paths)
    assert not (result.staging_root / ".git").exists()


@needs_http
def test_pinned_sha_is_ingested_without_ls_remote(remote, tmp_path) -> None:
    result = ingest_remote_git(
        remote.url, _stage(tmp_path, "s"), ref=remote.main_sha, policy=POLICY
    )
    assert result.commit == remote.main_sha
    assert "FEATURE.txt" not in {f.path for f in result.files}


@needs_http
def test_annotated_tag_is_ingested_as_its_commit(remote, tmp_path) -> None:
    result = ingest_remote_git(
        remote.url, _stage(tmp_path, "s"), ref="v1.0", policy=POLICY
    )
    assert result.commit == remote.main_sha


@needs_http
def test_same_sha_twice_gives_byte_identical_inventories(
    remote, tmp_path
) -> None:
    first = ingest_remote_git(
        remote.url, _stage(tmp_path, "s1"), ref=remote.main_sha, policy=POLICY
    )
    second = ingest_remote_git(
        remote.url, _stage(tmp_path, "s2"), ref="main", policy=POLICY
    )
    assert _records(first) == _records(second)
    assert first.commit == second.commit == remote.main_sha
    assert first.tree_id == second.tree_id
    assert first.total_bytes == second.total_bytes


@needs_http
def test_branch_moving_after_resolution_keeps_the_pin(
    mutable_remote, tmp_path, monkeypatch
) -> None:
    """Protocol v2 serves the pinned commit even though the branch moved."""

    real = remotegit.resolve_ref

    def moving(*args, **kwargs):
        resolved = real(*args, **kwargs)
        mutable_remote.advance_main()
        return resolved

    monkeypatch.setattr(remotegit, "resolve_ref", moving)
    old = mutable_remote.main_sha
    result = ingest_remote_git(
        mutable_remote.url, _stage(tmp_path, "s"), ref="main", policy=POLICY
    )
    assert result.commit == old
    assert "NEXT.txt" not in {f.path for f in result.files}


@needs_http
def test_branch_moving_between_resolve_and_fetch_is_commit_moved(
    mutable_remote, tmp_path, monkeypatch
) -> None:
    """Without SHA fetch support (protocol v0) a rewritten ref is detected."""

    mutable_remote.create_topic()
    mutable_remote.handler.speak_v0 = True
    real = remotegit.resolve_ref

    def moving(*args, **kwargs):
        resolved = real(*args, **kwargs)
        mutable_remote.rewrite_topic()
        return resolved

    monkeypatch.setattr(remotegit, "resolve_ref", moving)
    assert expect_refusal(
        ingest_remote_git, mutable_remote.url, _stage(tmp_path, "s"),
        ref="topic", policy=POLICY,
    ) == "COMMIT_MOVED"


@needs_http
def test_unmoved_branch_works_over_the_ref_fallback(
    mutable_remote, tmp_path
) -> None:
    mutable_remote.handler.speak_v0 = True
    result = ingest_remote_git(
        mutable_remote.url, _stage(tmp_path, "s"), ref="feature", policy=POLICY
    )
    assert result.commit == mutable_remote.feature_sha


@needs_http
def test_loopback_and_plain_http_are_refused_by_default(
    remote, tmp_path
) -> None:
    assert expect_refusal(
        ingest_remote_git, remote.url, _stage(tmp_path, "a"),
        policy=NetworkPolicy(allow_hosts=("127.0.0.1",)),
    ) == "UNSUPPORTED_SCHEME"
    assert expect_refusal(
        ingest_remote_git, remote.url, _stage(tmp_path, "b"),
        policy=NetworkPolicy(allow_insecure_http_for_tests=True),
    ) == "HOST_NOT_PUBLIC"


@needs_http
def test_symlink_in_remote_tree_is_refused(mutable_remote, tmp_path) -> None:
    blob = subprocess.run(
        [str(GIT), "hash-object", "-w", "--stdin"], cwd=str(mutable_remote.work),
        input=b"../../outside", capture_output=True, timeout=60,
    ).stdout.decode().strip()
    _git(mutable_remote.work, "update-index", "--add", "--cacheinfo",
         f"120000,{blob},escape.pas")
    _git(mutable_remote.work, "commit", "-q", "-m", "link")
    _git(mutable_remote.work, "push", "-q", str(mutable_remote.bare), "main")
    assert expect_refusal(
        ingest_remote_git, mutable_remote.url, _stage(tmp_path, "s"),
        ref="main", policy=POLICY,
    ) == "SYMLINK_ENTRY"


# ---------------------------------------------------------------------------
# Flow through a local-path remote (no HTTP server needed)
# ---------------------------------------------------------------------------


def test_fetch_flow_through_a_local_path_remote(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    write_enterprise_app(work)
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "initial")
    sha = _git(work, "rev-parse", "HEAD")

    staging = _stage(tmp_path, "s")
    spec = RemoteSpec(
        scheme="file", host="", port=0, path=work.as_posix(),
        display_url=str(work),
    )
    env = _hardened_env(staging)
    env["GIT_ALLOW_PROTOCOL"] = "file"
    resolved = remotegit.ResolvedRef(sha, "commit", "")
    dest = remotegit._init_repository(staging, spec, env)
    pinned = remotegit._fetch_commit(dest, resolved, env, DEFAULT_LIMITS)
    result = checkout_verify_inventory(
        dest, pinned, env, no_hooks=staging / ".discovery-no-hooks",
        origin="local", sink=DiagnosticSink(), limits=DEFAULT_LIMITS,
    )
    assert result.commit == sha
    assert result.tree_id == _git(work, "rev-parse", "HEAD^{tree}")
    assert "src/cobol/PAYROLL.cbl" in {f.path for f in result.files}
    assert not (dest / ".git").exists()


def test_discovery_over_real_smart_http(remote, tmp_path) -> None:
    """Whole discovery workflow from an HTTPS-style remote, pinned to a tag."""

    from enterprise.discovery.discover import DiscoveryRequest, discover

    request = DiscoveryRequest(
        "git", remote.url, ref="v1.0",
        network_policy=NetworkPolicy(
            allow_hosts=("127.0.0.1",), allow_insecure_http_for_tests=True),
    )
    result = discover(request, tmp_path / "store")
    source = result.report["provenance"]
    assert source["commit"] == remote.main_sha
    assert source["ref"] == "v1.0"
    assert result.checkpoint.commit == remote.main_sha

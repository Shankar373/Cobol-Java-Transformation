"""Remote Git policy: address validation, SSRF rules, ref names, scrubbing.

Pure functions and frozen data types with no process or network side effects
other than the optional DNS lookup in :func:`check_host_public`:

* :func:`parse_remote_url` accepts ``https://`` (and, when enabled,
  ``ssh://`` / scp-style) and refuses userinfo, control characters,
  option-like text, odd hosts and every other scheme.  Error text never
  echoes the raw URL.
* :func:`check_host_public` resolves a host and refuses it unless *every*
  answer is a public address (or the host is on the operator allow-list).
* :func:`validate_ref_name` applies ``git check-ref-format`` rules plus a
  strict character allow-list.
* :func:`scrub` removes credentials from any text leaving the module.

``enterprise.discovery.remotegit`` re-exports the public names and does the git work.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable, Iterable

from .errors import IngestionError

__all__ = [
    "NetworkPolicy",
    "RemoteSpec",
    "ResolvedRef",
    "check_host_public",
    "parse_remote_url",
    "scrub",
    "validate_ref_name",
]

#: Longest URL accepted.
MAX_URL_LENGTH = 2048
#: Longest ref name accepted (git itself allows more; nobody needs it).
MAX_REF_LENGTH = 255

_DEFAULT_PORTS = {"https": 443, "http": 80, "ssh": 22}
_REDACTED = "[REDACTED]"

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$", re.S)
_TRANSPORT_RE = re.compile(r"^[A-Za-z0-9+.-]+::")
_SCP_RE = re.compile(r"^([^/:@\[\]]+)@(\[[0-9A-Fa-f:.]+\]|[^/:@\[\]]+):(.*)$", re.S)
_SSH_USER_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]*\Z")
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\Z"
)
_PERCENT_RE = re.compile(r"%([0-9A-Fa-f]{2})")
_REF_CHARS_RE = re.compile(r"^[A-Za-z0-9._/@+-]+\Z", re.ASCII)
_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}\Z")
_SHA_ABBREV_RE = re.compile(r"^[0-9a-fA-F]{7,64}\Z")
_USERINFO_RE = re.compile(r"(?<=://)[^/@\s]+@")
_AUTH_HEADER_RE = re.compile(
    r"(?i)authorization:[ \t]*\S+(?:[ \t]+\S+)?"
)

Resolver = Callable[..., Iterable[tuple]]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NetworkPolicy:
    """Operator network policy for remote Git.

    ``allow_hosts`` exempts exact host names from the public-address rule.
    ``allow_insecure_http_for_tests`` permits ``http://`` and exists only so a
    test can use a local smart-HTTP server; no CLI or server option sets it.
    ``resolver`` replaces ``socket.getaddrinfo`` (tests need no DNS).
    """

    allow_hosts: tuple[str, ...] = ()
    allow_insecure_http_for_tests: bool = False
    resolver: Resolver | None = None


@dataclass(frozen=True)
class RemoteSpec:
    """A validated remote address.  ``display_url`` never carries credentials."""

    scheme: str
    host: str
    port: int
    path: str
    display_url: str
    user: str = ""

    @property
    def fetch_url(self) -> str:
        """URL handed to git (identical to the display URL: it has no secrets)."""

        return self.display_url


@dataclass(frozen=True)
class ResolvedRef:
    """A ref pinned to an exact commit.

    ``ref_kind`` is ``commit``, ``head``, ``branch``, ``tag`` or ``ref``;
    ``ref_name`` is the full remote ref name (``""`` for a bare commit).
    """

    sha: str
    ref_kind: str
    ref_name: str


# ---------------------------------------------------------------------------
# Errors and scrubbing
# ---------------------------------------------------------------------------


class RemoteUrlError(IngestionError):
    """The remote address is malformed or outside the allow-list."""

    code = "INVALID_REMOTE_URL"


class HostNotPublicError(IngestionError):
    """The host resolves to an address the SSRF policy refuses."""

    code = "HOST_NOT_PUBLIC"


def scrub(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove credentials from *text*: known secrets, userinfo, auth headers."""

    out = text
    known = sorted({s for s in secrets if s and s.strip()}, key=len, reverse=True)
    for secret in known:
        out = out.replace(secret, _REDACTED)
    out = _AUTH_HEADER_RE.sub(f"Authorization: {_REDACTED}", out)
    return _USERINFO_RE.sub("", out)


def _scrub_error(exc: IngestionError, secrets: Iterable[str]) -> None:
    """Rewrite *exc* in place so none of its text carries a credential."""

    secrets = tuple(secrets)
    exc.message = scrub(exc.message, secrets)
    exc.args = (exc.message,)
    if exc.path is not None:
        exc.path = scrub(exc.path, secrets)


def _bad_url(reason: str, code: str = "INVALID_REMOTE_URL") -> IngestionError:
    return IngestionError(f"remote URL refused: {reason}", code=code)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


def _check_characters(url: object) -> str:
    """Refuse non-strings, overlong text, control/non-ASCII/space, leading '-'."""

    if not isinstance(url, str) or not url:
        raise _bad_url("empty or non-text value")
    if len(url) > MAX_URL_LENGTH:
        raise _bad_url(f"longer than {MAX_URL_LENGTH} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise _bad_url("control character")
    if url.startswith("-"):
        raise _bad_url("starts with '-' (option injection)")
    if _TRANSPORT_RE.match(url):
        raise _bad_url("git transport helper syntax", "UNSUPPORTED_SCHEME")
    if any(ord(ch) > 126 for ch in url):
        raise _bad_url("non-ASCII character (use punycode for hosts)")
    if any(ch.isspace() for ch in url):
        raise _bad_url("whitespace")
    return url


def _check_delimiters(url: str) -> None:
    """Refuse backslash, query and fragment in an https/ssh URL."""

    if any(ch in url for ch in ("\\", "?", "#")):
        raise _bad_url("backslash, query or fragment")


def _validate_host(raw: str) -> str:
    """Return a normalised host (DNS name, IPv4 or IPv6 literal) or refuse."""

    host = raw.lower()
    if host.startswith("[") and host.endswith("]"):
        if "%" in host:
            raise _bad_url("IPv6 zone identifier not accepted")
        try:
            return str(ipaddress.IPv6Address(host[1:-1]))
        except ValueError:
            raise _bad_url("invalid IPv6 literal") from None
    if _IPV4_RE.match(host):
        return host
    labels = host.split(".")
    if len(host) > 253 or not all(_DNS_LABEL_RE.match(x) for x in labels):
        raise _bad_url("invalid host name")
    last = labels[-1]
    if last.isdigit() or last.startswith("0x"):
        # inet_aton would read these as numeric addresses (127.1, 0x7f.1).
        raise _bad_url("numeric host form not accepted")
    return host


def _parse_port(raw: str, scheme: str) -> int:
    if raw == "":
        return _DEFAULT_PORTS[scheme]
    if not re.fullmatch(r"[0-9]{1,5}", raw) or not 1 <= int(raw) <= 65535:
        raise _bad_url("invalid port")
    return int(raw)


def _split_host_port(hostport: str) -> tuple[str, str]:
    if hostport.startswith("["):
        close = hostport.find("]")
        if close < 0:
            raise _bad_url("unterminated IPv6 literal")
        rest = hostport[close + 1:]
        if rest and not rest.startswith(":"):
            raise _bad_url("garbage after IPv6 literal")
        return hostport[: close + 1], rest[1:]
    if hostport.count(":") > 1:
        raise _bad_url("too many ':' in authority")
    host, _, port = hostport.partition(":")
    if ":" in hostport and port == "":
        raise _bad_url("empty port")
    return host, port


def _check_path(path: str) -> str:
    """Refuse empty paths, dot segments, option-like segments, encoded control."""

    if path in ("", "/"):
        raise _bad_url("no repository path")
    for match in _PERCENT_RE.finditer(path):
        value = int(match.group(1), 16)
        if value < 32 or value == 127:
            raise _bad_url("encoded control character in path")
    if re.search(r"%(?![0-9A-Fa-f]{2})", path):
        raise _bad_url("malformed percent escape")
    decoded = _PERCENT_RE.sub(lambda m: chr(int(m.group(1), 16)), path)
    for segment in decoded.split("/"):
        if segment in (".", "..") or segment.startswith("-"):
            raise _bad_url("path segment not accepted")
    return path


def _ssh_user(userinfo: str) -> str:
    if ":" in userinfo:
        raise _bad_url("password in URL", "CREDENTIALS_IN_URL")
    if not _SSH_USER_RE.match(userinfo):
        raise _bad_url("invalid ssh user")
    return userinfo


def _display(scheme: str, user: str, host: str, port: int, path: str) -> str:
    shown = f"[{host}]" if ":" in host else host
    port_part = "" if port == _DEFAULT_PORTS[scheme] else f":{port}"
    user_part = f"{user}@" if user else ""
    return f"{scheme}://{user_part}{shown}{port_part}{path}"


def _build_spec(
    scheme: str, user: str, hostport: str, path: str
) -> RemoteSpec:
    raw_host, raw_port = _split_host_port(hostport)
    host = _validate_host(raw_host)
    port = _parse_port(raw_port, scheme)
    path = _check_path(path)
    return RemoteSpec(
        scheme=scheme,
        host=host.strip("[]"),
        port=port,
        path=path,
        display_url=_display(scheme, user, host.strip("[]"), port, path),
        user=user,
    )


def _parse_hierarchical(
    scheme: str, rest: str, *, allow_ssh: bool, allow_insecure_http: bool
) -> RemoteSpec:
    if scheme == "ssh":
        if not allow_ssh:
            raise _bad_url("SSH is not enabled", "SSH_NOT_CONFIGURED")
    elif scheme == "http":
        if not allow_insecure_http:
            raise _bad_url("plain http is refused", "UNSUPPORTED_SCHEME")
    elif scheme != "https":
        raise _bad_url(f"scheme {scheme!r} is not allowed", "UNSUPPORTED_SCHEME")
    _check_delimiters(rest)
    authority, slash, tail = rest.partition("/")
    user = ""
    if "@" in authority:
        userinfo, _, authority = authority.rpartition("@")
        if scheme != "ssh":
            raise _bad_url("userinfo in URL", "CREDENTIALS_IN_URL")
        user = _ssh_user(userinfo)
    return _build_spec(scheme, user, authority, slash + tail)


def _parse_scp(text: str, *, allow_ssh: bool) -> RemoteSpec:
    match = _SCP_RE.match(text)
    if match is None:
        raise _bad_url("not a recognised remote URL", "UNSUPPORTED_SCHEME")
    if not allow_ssh:
        raise _bad_url("SSH is not enabled", "SSH_NOT_CONFIGURED")
    _check_delimiters(text)
    user = _ssh_user(match.group(1))
    path = match.group(3)
    if path.startswith("-"):
        raise _bad_url("path starts with '-'")
    if not path.startswith("/"):
        path = "/~/" + path  # scp paths are relative to the remote home
    return _build_spec("ssh", user, match.group(2), path)


def parse_remote_url(
    url: str, *, allow_ssh: bool, allow_insecure_http: bool = False
) -> RemoteSpec:
    """Validate *url* and return a :class:`RemoteSpec`, or raise.

    ``allow_insecure_http`` is for tests only (see :class:`NetworkPolicy`).
    """

    text = _check_characters(url)
    match = _SCHEME_RE.match(text)
    if match is not None:
        return _parse_hierarchical(
            match.group(1).lower(),
            match.group(2),
            allow_ssh=allow_ssh,
            allow_insecure_http=allow_insecure_http,
        )
    return _parse_scp(text, allow_ssh=allow_ssh)


# ---------------------------------------------------------------------------
# SSRF policy
# ---------------------------------------------------------------------------


def _literal_ip(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        return None


def _default_resolver(host: str, port: int | str | None, *_a: object, **_k: object):
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _resolve(host: str, policy: NetworkPolicy) -> tuple[str, ...]:
    resolver = policy.resolver or _default_resolver
    try:
        infos = list(resolver(host, None))
    except (OSError, UnicodeError):
        raise IngestionError(
            f"host {host!r} could not be resolved", code="HOST_UNRESOLVABLE"
        ) from None
    found: set[str] = set()
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        try:
            found.add(str(ipaddress.ip_address(address)))
        except ValueError:
            raise HostNotPublicError(
                f"host {host!r} resolved to an unparseable address",
            ) from None
    if not found:
        raise IngestionError(
            f"host {host!r} resolved to no addresses", code="HOST_UNRESOLVABLE"
        )
    return tuple(sorted(found))


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """IPv4 carried inside an IPv6 address (mapped, compatible, 6to4, NAT64)."""

    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    value = int(ip)
    nat64 = ipaddress.IPv6Network("64:ff9b::/96")
    if ip in nat64 or (value >> 32 == 0 and value > 1):
        return ipaddress.IPv4Address(value & 0xFFFFFFFF)
    return None


def _address_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_v4(ip)
        if inner is not None:
            return _address_is_public(inner)
        if ip.is_site_local:
            return False
    return not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def check_host_public(host: str, policy: NetworkPolicy) -> tuple[str, ...]:
    """Resolve *host* and return its addresses if the policy allows them.

    Raises ``HOST_NOT_PUBLIC`` when *any* address is non-public and the host
    is not in ``policy.allow_hosts``; ``HOST_UNRESOLVABLE`` on DNS failure.
    """

    literal = _literal_ip(host)
    ips = (literal,) if literal is not None else _resolve(host, policy)
    allowed = {h.lower() for h in policy.allow_hosts}
    if host.lower().strip("[]") in allowed:
        return ips
    for address in ips:
        if not _address_is_public(ipaddress.ip_address(address)):
            raise HostNotPublicError(
                f"host {host!r} resolves to non-public address {address}; "
                "refused by the network policy"
            )
    return ips


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------


def validate_ref_name(ref: str) -> str:
    """Return *ref* if it is a safe, ``check-ref-format``-valid name."""

    def refuse() -> IngestionError:
        return IngestionError("ref name refused", code="INVALID_REF")

    if not isinstance(ref, str) or not 1 <= len(ref) <= MAX_REF_LENGTH:
        raise refuse()
    if not _REF_CHARS_RE.match(ref) or ref == "@":
        raise refuse()
    if ref.startswith(("-", "/")) or ref.endswith(("/", ".")):
        raise refuse()
    if "//" in ref or ".." in ref:
        raise refuse()
    for part in ref.split("/"):
        if part.startswith(".") or part.endswith(".lock"):
            raise refuse()
    return ref



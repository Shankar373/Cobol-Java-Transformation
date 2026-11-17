"""Remote Git policy: URL parsing, SSRF matrix, ref validation, scrubbing.

Nothing here touches the network: DNS is replaced by an injected resolver.
"""

from __future__ import annotations

import os
import socket

import pytest

from tests.discovery.helpers import REPO_ROOT, codes_of, expect_refusal, make_zip, read_json, write_enterprise_app, write_tree  # noqa: F401

from enterprise.discovery.remotegit import (
    NetworkPolicy,
    RemoteSpec,
    check_host_public,
    parse_remote_url,
    resolve_ref,
    scrub,
    validate_ref_name,
)


def _resolver(*addresses: str):
    """A getaddrinfo stand-in returning *addresses* for any host."""

    def resolve(host, port, *args, **kwargs):
        out = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            out.append((family, socket.SOCK_STREAM, 6, "", (address, 0)))
        return out

    return resolve


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


def test_https_url_is_parsed() -> None:
    spec = parse_remote_url(
        "https://Example.COM/owner/repo.git", allow_ssh=False
    )
    assert isinstance(spec, RemoteSpec)
    assert (spec.scheme, spec.host, spec.port) == ("https", "example.com", 443)
    assert spec.path == "/owner/repo.git"
    assert spec.display_url == "https://example.com/owner/repo.git"


def test_explicit_port_is_kept_in_display_url() -> None:
    spec = parse_remote_url("https://example.com:8443/a/b", allow_ssh=False)
    assert spec.port == 8443
    assert spec.display_url == "https://example.com:8443/a/b"


def test_ipv6_literal_host() -> None:
    spec = parse_remote_url("https://[2001:db8::1]:444/a/b", allow_ssh=False)
    assert spec.host == "2001:db8::1"
    assert spec.display_url == "https://[2001:db8::1]:444/a/b"


@pytest.mark.parametrize(
    "url,code",
    [
        ("http://example.com/a/b", "UNSUPPORTED_SCHEME"),
        ("git://example.com/a/b", "UNSUPPORTED_SCHEME"),
        ("file:///etc/passwd", "UNSUPPORTED_SCHEME"),
        ("ftp://example.com/a", "UNSUPPORTED_SCHEME"),
        ("ftps://example.com/a", "UNSUPPORTED_SCHEME"),
        ("ext::sh -c touch% /tmp/pwn", "UNSUPPORTED_SCHEME"),
        ("fd::17/foo", "UNSUPPORTED_SCHEME"),
        ("javascript://example.com/a", "UNSUPPORTED_SCHEME"),
        ("/local/path/repo", "UNSUPPORTED_SCHEME"),
        ("C:\\repos\\app", "UNSUPPORTED_SCHEME"),
        ("example.com/owner/repo", "UNSUPPORTED_SCHEME"),
    ],
)
def test_scheme_allow_list(url: str, code: str) -> None:
    assert expect_refusal(parse_remote_url, url, allow_ssh=False) == code


@pytest.mark.parametrize(
    "url",
    [
        "https://user@example.com/a/b",
        "https://user:pw@example.com/a/b",
        "https://:pw@example.com/a/b",
        "https://ghp_abcdef@example.com/a/b",
        "https://example.com@evil.com/a/b",
        "ssh://git:secret@example.com/a/b",
    ],
)
def test_userinfo_is_refused(url: str) -> None:
    assert expect_refusal(parse_remote_url, url, allow_ssh=True) == (
        "CREDENTIALS_IN_URL"
    )


def test_credential_value_is_not_echoed_in_the_error() -> None:
    with pytest.raises(Exception) as excinfo:
        parse_remote_url("https://u:hunter2secret@example.com/a", allow_ssh=False)
    assert "hunter2secret" not in str(excinfo.value)
    assert "hunter2secret" not in getattr(excinfo.value, "message", "")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a\nb",
        "https://example.com/a\x00b",
        "https://example.com/a\tb",
        "https://exa mple.com/a",
        "https://example.com/a b",
        " https://example.com/a",
        "https://example.com/a ",
        "-https://example.com/a",
        "--upload-pack=touch/tmp/x",
        "https://example.com/a\x7f",
        "https://example.com/a%0ab",
        "https://example.com/a%00b",
        "https://example.com/a\\b",
        "https://example.com/a?x=1",
        "https://example.com/a#frag",
        "https://exämple.com/a",
        "https://example.com/../etc",
        "https://example.com/a/./b",
        "https://example.com",
        "https://example.com/",
        "https://",
        "",
        "https://example.com/" + "a" * 3000,
    ],
)
def test_malformed_urls_are_refused(url: str) -> None:
    code = expect_refusal(parse_remote_url, url, allow_ssh=False)
    assert code in ("INVALID_REMOTE_URL", "UNSUPPORTED_SCHEME")


@pytest.mark.parametrize(
    "host",
    [
        "-evil.com",
        "evil-.com",
        "a..b",
        ".example.com",
        "exa_mple.com",
        "127.1",
        "0x7f.1",
        "2130706433",
        "010.0.0.1",
        "1.2.3.4.5",
        "example.123",
        "a" * 64 + ".com",
        "[::1",
        "[zzzz]",
        "exa$mple.com",
    ],
)
def test_bad_hosts_are_refused(host: str) -> None:
    assert expect_refusal(
        parse_remote_url, f"https://{host}/a/b", allow_ssh=False
    ) == "INVALID_REMOTE_URL"


@pytest.mark.parametrize("port", ["0", "65536", "abc", "-1", "99999999"])
def test_bad_ports_are_refused(port: str) -> None:
    assert expect_refusal(
        parse_remote_url, f"https://example.com:{port}/a/b", allow_ssh=False
    ) == "INVALID_REMOTE_URL"


def test_http_is_accepted_only_with_the_explicit_test_switch() -> None:
    spec = parse_remote_url(
        "http://127.0.0.1:8080/a.git",
        allow_ssh=False,
        allow_insecure_http=True,
    )
    assert spec.scheme == "http"
    assert expect_refusal(
        parse_remote_url, "http://127.0.0.1:8080/a.git", allow_ssh=False
    ) == "UNSUPPORTED_SCHEME"


def test_ssh_is_refused_when_not_enabled() -> None:
    for url in ("ssh://git@example.com/a/b.git", "git@example.com:a/b.git"):
        assert expect_refusal(parse_remote_url, url, allow_ssh=False) == (
            "SSH_NOT_CONFIGURED"
        )


def test_ssh_forms_are_normalised_when_enabled() -> None:
    url = parse_remote_url("ssh://git@Example.com:2222/a/b.git", allow_ssh=True)
    assert (url.scheme, url.host, url.port, url.user) == (
        "ssh", "example.com", 2222, "git"
    )
    scp = parse_remote_url("git@example.com:owner/repo.git", allow_ssh=True)
    assert (scp.scheme, scp.host, scp.port, scp.user) == (
        "ssh", "example.com", 22, "git"
    )
    assert scp.path == "/~/owner/repo.git"
    assert "secret" not in scp.display_url


@pytest.mark.parametrize(
    "url",
    [
        "-oProxyCommand=x@example.com:a/b",
        "git@example.com:-oProxyCommand=x",
        "git@-evil.com:a/b",
        "ssh://-oProxyCommand=x@example.com/a/b",
        "ssh://git@example.com/-x",
    ],
)
def test_ssh_option_injection_is_refused(url: str) -> None:
    code = expect_refusal(parse_remote_url, url, allow_ssh=True)
    assert code in ("INVALID_REMOTE_URL", "UNSUPPORTED_SCHEME")


# ---------------------------------------------------------------------------
# SSRF policy
# ---------------------------------------------------------------------------

NON_PUBLIC = [
    "127.0.0.1",
    "127.255.255.254",
    "10.0.0.1",
    "172.16.5.4",
    "172.31.255.255",
    "192.168.1.1",
    "169.254.169.254",
    "169.254.0.1",
    "100.64.0.1",
    "100.127.255.254",
    "0.0.0.0",
    "224.0.0.1",
    "239.255.255.250",
    "240.0.0.1",
    "255.255.255.255",
    "192.0.2.1",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd12:3456::1",
    "ff02::1",
    "::ffff:127.0.0.1",
    "::ffff:10.1.2.3",
    "::ffff:169.254.169.254",
    "::ffff:7f00:1",
    "64:ff9b::7f00:1",
    "fec0::1",
]


@pytest.mark.parametrize("address", NON_PUBLIC)
def test_non_public_addresses_are_refused(address: str) -> None:
    policy = NetworkPolicy(resolver=_resolver(address))
    assert expect_refusal(check_host_public, "repo.example.com", policy) == (
        "HOST_NOT_PUBLIC"
    )


@pytest.mark.parametrize("address", NON_PUBLIC)
def test_non_public_ip_literals_are_refused(address: str) -> None:
    policy = NetworkPolicy(resolver=_resolver("93.184.216.34"))
    assert expect_refusal(check_host_public, address, policy) == (
        "HOST_NOT_PUBLIC"
    )


def test_any_non_public_answer_poisons_the_host() -> None:
    policy = NetworkPolicy(resolver=_resolver("93.184.216.34", "10.0.0.5"))
    assert expect_refusal(check_host_public, "mixed.example.com", policy) == (
        "HOST_NOT_PUBLIC"
    )


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::1", "1.1.1.1"]
)
def test_public_addresses_are_returned_sorted_and_deduplicated(
    address: str,
) -> None:
    policy = NetworkPolicy(resolver=_resolver(address, "1.0.0.1", address))
    ips = check_host_public("repo.example.com", policy)
    assert ips == tuple(sorted({address, "1.0.0.1"}))


def test_allow_hosts_overrides_the_policy_case_insensitively() -> None:
    policy = NetworkPolicy(
        allow_hosts=("Internal.Example.com",), resolver=_resolver("10.0.0.5")
    )
    assert check_host_public("internal.example.com", policy) == ("10.0.0.5",)
    assert expect_refusal(check_host_public, "other.example.com", policy) == (
        "HOST_NOT_PUBLIC"
    )


def test_allow_hosts_ip_literal_needs_no_resolver() -> None:
    policy = NetworkPolicy(allow_hosts=("127.0.0.1",))
    assert check_host_public("127.0.0.1", policy) == ("127.0.0.1",)


def test_resolution_failure_is_a_typed_refusal() -> None:
    def failing(host, port, *args, **kwargs):
        raise socket.gaierror(socket.EAI_NONAME, "nope")

    assert expect_refusal(
        check_host_public, "nx.example.com", NetworkPolicy(resolver=failing)
    ) == "HOST_UNRESOLVABLE"


def test_empty_resolution_is_refused() -> None:
    assert expect_refusal(
        check_host_public, "x.example.com", NetworkPolicy(resolver=_resolver())
    ) == "HOST_UNRESOLVABLE"


def test_network_policy_defaults_are_closed() -> None:
    policy = NetworkPolicy()
    assert policy.allow_hosts == ()
    assert policy.allow_insecure_http_for_tests is False
    assert policy.resolver is None


# ---------------------------------------------------------------------------
# Ref validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref",
    ["main", "release/1.2", "v1.0.0", "feature/x_y-z", "refs/heads/main",
     "refs/tags/v1", "a.b", "HEAD", "user@host"],
)
def test_valid_ref_names(ref: str) -> None:
    assert validate_ref_name(ref) == ref


@pytest.mark.parametrize(
    "ref",
    ["-x", "--upload-pack=x", "a..b", "a b", "a\nb", "a/", "/a", "a//b",
     "a.lock", "x/.hidden", "a~1", "a^", "a:b", "a?b", "a*b", "a[b", "a\\b",
     "a@{1}", "@", "end.", "", "a" * 300, "a\x00b", "äb", "a;b", "a$(x)",
     "a`b", "a|b", "a&b", "a'b", 'a"b', "a<b", "a>b", "a b", "a\tb"],
)
def test_invalid_ref_names_are_refused(ref: str) -> None:
    assert expect_refusal(validate_ref_name, ref) == "INVALID_REF"


@pytest.mark.parametrize(
    "ref", ["abcdef1", "deadbeef", "0123456789abcdef0123456789abcde"]
)
def test_abbreviated_shas_are_ambiguous_for_remotes(ref: str) -> None:
    spec = parse_remote_url("https://example.com/a/b", allow_ssh=False)
    assert expect_refusal(resolve_ref, spec, ref, {}, NetworkPolicy()) == (
        "REF_AMBIGUOUS"
    )


def test_full_sha_is_used_directly_without_network() -> None:
    spec = parse_remote_url("https://example.com/a/b", allow_ssh=False)
    sha = "0123456789ABCDEF0123456789abcdef01234567"
    resolved = resolve_ref(spec, sha, {}, NetworkPolicy())
    assert resolved.sha == sha.lower()
    assert resolved.ref_kind == "commit"


def test_invalid_ref_is_refused_before_any_git_call() -> None:
    spec = parse_remote_url("https://example.com/a/b", allow_ssh=False)
    assert expect_refusal(
        resolve_ref, spec, "--upload-pack=x", {}, NetworkPolicy()
    ) == "INVALID_REF"


# ---------------------------------------------------------------------------
# Credential scrubbing
# ---------------------------------------------------------------------------


def test_scrub_removes_secrets_and_url_userinfo() -> None:
    text = (
        "fatal: unable to access 'https://bob:hunter2@example.com/x': "
        "Authorization: Basic eC1hY2Nlc3MtdG9rZW46aHVudGVyMg== tok-123"
    )
    cleaned = scrub(text, ("tok-123",))
    assert "hunter2" not in cleaned
    assert "bob" not in cleaned
    assert "eC1hY2Nlc3MtdG9rZW46aHVudGVyMg" not in cleaned
    assert "tok-123" not in cleaned
    assert "example.com" in cleaned


def test_scrub_ignores_empty_secrets() -> None:
    assert scrub("plain text", ("", "   ")) == "plain text"


# ---------------------------------------------------------------------------
# Anchoring, environment construction, selection of refs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["main\n", "v1\n", "feature/x\r"])
def test_trailing_newline_is_not_tolerated_in_refs(ref: str) -> None:
    assert expect_refusal(validate_ref_name, ref) == "INVALID_REF"


def test_sha_with_trailing_newline_is_not_a_pin() -> None:
    spec = parse_remote_url("https://example.com/a/b", allow_ssh=False)
    sha = "0123456789abcdef0123456789abcdef01234567\n"
    code = expect_refusal(resolve_ref, spec, sha, {}, NetworkPolicy())
    assert code in ("INVALID_REF", "REF_AMBIGUOUS")


def test_environment_pins_the_resolved_address_and_scopes_the_token(
    tmp_path, monkeypatch
) -> None:
    from enterprise.discovery import remotegit

    spec = parse_remote_url("https://Example.com:8443/o/r.git", allow_ssh=False)
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN", "tok-xyz")
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN_HOSTS", "example.com")
    env = remotegit._build_env(
        spec, ("2606:2800:220:1::1", "93.184.216.34"), tmp_path, dict(os.environ)
    )
    pairs = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert pairs["http.curloptResolve"] == (
        "example.com:8443:[2606:2800:220:1::1],93.184.216.34"
    )
    assert "http.https://example.com:8443/.extraHeader" in pairs
    assert "SYSTEMAOPS_GIT_TOKEN" not in env
    assert "tok-xyz" not in " ".join(
        v for k, v in env.items() if not k.startswith("GIT_CONFIG_VALUE_")
    )
    assert any("tok-xyz" in x for x in remotegit._secrets_from_env(env))


def test_ip_literal_hosts_need_no_resolve_entry(tmp_path) -> None:
    from enterprise.discovery import remotegit

    spec = parse_remote_url("https://203.0.113.5/o/r.git", allow_ssh=False)
    entries = dict(remotegit._config_entries(spec, ("203.0.113.5",), ""))
    assert "http.curloptResolve" not in entries


def test_branch_and_tag_with_the_same_name_must_agree() -> None:
    from enterprise.discovery import remotegit

    refs = {
        "refs/heads/rel": "a" * 40,
        "refs/tags/rel": "b" * 40,
    }
    assert expect_refusal(remotegit._select_ref, "rel", refs) == "REF_AMBIGUOUS"
    agreeing = {"refs/heads/rel": "a" * 40, "refs/tags/rel^{}": "a" * 40}
    assert remotegit._select_ref("rel", agreeing).sha == "a" * 40
    assert expect_refusal(remotegit._select_ref, "HEAD", {}) == "REF_NOT_FOUND"
    full = remotegit._select_ref("refs/notes/x", {"refs/notes/x": "c" * 40})
    assert full.ref_kind == "ref"


def test_ipv6_zone_identifiers_are_refused() -> None:
    for host in ("[fe80::1%eth0]", "[fe80::1%25eth0]", "[::1%1]"):
        assert expect_refusal(
            parse_remote_url, f"https://{host}/a/b", allow_ssh=False
        ) == "INVALID_REMOTE_URL"

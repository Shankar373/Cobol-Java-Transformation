"""Remote Git security: credentials, redaction, SSH gating, ref safety, limits.

A stand-in ``git`` program (a tiny Python script) is substituted through the
``p1.gitingest._GIT_COMMAND`` seam.  It logs every invocation (argv plus the
``GIT_CONFIG_*`` environment), delegates local plumbing (``init``,
``remote add``) to the real git, and impersonates the network commands.  No
test needs a network.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from tests.discovery.helpers import REPO_ROOT, codes_of, expect_refusal, make_zip, read_json, write_enterprise_app, write_tree  # noqa: F401

from enterprise.discovery import gitingest
from enterprise.discovery.errors import DiagnosticSink, IngestionError
from enterprise.discovery.limits import Limits
from enterprise.discovery.remotegit import NetworkPolicy, ingest_remote_git

REAL_GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(REAL_GIT is None, reason="git is required")

TOKEN = "tok-SECRET-0123456789"
SHA_A = "a" * 40
SHA_B = "b" * 40

FAKE_GIT = textwrap.dedent(
    '''
    import json, os, subprocess, sys, time
    args = sys.argv[1:]
    mode = os.environ.get("FAKE_GIT_MODE", "")
    config = {k: v for k, v in os.environ.items() if k.startswith("GIT_CONFIG_")}
    seen = {k: os.environ.get(k) for k in (
        "SYSTEMAOPS_GIT_TOKEN", "SYSTEMAOPS_GIT_TOKEN_HOSTS", "HTTPS_PROXY", "https_proxy", "GIT_ALLOW_PROTOCOL",
        "GIT_SSH_COMMAND")}
    with open(os.environ["FAKE_GIT_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": args, "config": config, "seen": seen}) + "\\n")
    verb = next((a for a in args if a in (
        "ls-remote", "fetch", "rev-parse", "init", "remote")), "")
    leak = os.environ.get("FAKE_GIT_LEAK", "")
    if verb == "ls-remote" and mode == "ls_remote_fails":
        sys.stderr.write("fatal: unable to access 'https://bob:hunter2@repo.example.com/o/r.git': " + leak + "\\n")
        sys.exit(128)
    if verb == "ls-remote" and mode in ("moved", "ls_remote_ok"):
        print(os.environ["FAKE_GIT_SHA_A"] + "\\trefs/heads/main")
        sys.exit(0)
    if verb == "fetch" and mode == "moved":
        if os.environ["FAKE_GIT_SHA_A"] in args:
            sys.stderr.write("fatal: not our ref\\n")
            sys.exit(128)
        sys.exit(0)
    if verb == "rev-parse" and mode == "moved" and "FETCH_HEAD^{commit}" in args:
        print(os.environ["FAKE_GIT_SHA_B"])
        sys.exit(0)
    if verb == "fetch" and mode == "fetch_fails":
        sys.stderr.write("fatal: server said no " + leak + "\\n")
        sys.exit(128)
    if verb == "fetch" and mode == "big":
        target = os.path.join(os.getcwd(), ".git", "payload.bin")
        with open(target, "wb") as fh:
            fh.write(b"\\0" * (3 * 1024 * 1024))
        time.sleep(60)
        sys.exit(0)
    proc = subprocess.run([os.environ["FAKE_GIT_REAL"], *args])
    sys.exit(proc.returncode)
    '''
)


def _public(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


POLICY = NetworkPolicy(resolver=_public)


@pytest.fixture()
def fake_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = tmp_path / "fake_git.py"
    script.write_text(FAKE_GIT, encoding="utf-8")
    log = tmp_path / "git-calls.jsonl"
    monkeypatch.setattr(gitingest, "_GIT_COMMAND", (sys.executable, str(script)))
    monkeypatch.setattr(gitingest, "git_version", lambda: (2, 55, 0))
    # The environment is an allow-list; let the stand-in's own control
    # variables through (and nothing else).
    monkeypatch.setattr(
        gitingest, "_ENV_ALLOW",
        gitingest._ENV_ALLOW | {
            "FAKE_GIT_LOG", "FAKE_GIT_REAL", "FAKE_GIT_SHA_A", "FAKE_GIT_SHA_B",
            "FAKE_GIT_MODE", "FAKE_GIT_LEAK",
        },
    )
    monkeypatch.setenv("FAKE_GIT_LOG", str(log))
    monkeypatch.setenv("FAKE_GIT_REAL", str(REAL_GIT))
    monkeypatch.setenv("FAKE_GIT_SHA_A", SHA_A)
    monkeypatch.setenv("FAKE_GIT_SHA_B", SHA_B)

    def calls() -> list[dict]:
        if not log.exists():
            return []
        return [json.loads(x) for x in log.read_text("utf-8").splitlines()]

    return calls


@pytest.fixture()
def staging(tmp_path: Path) -> Path:
    path = tmp_path / "stage"
    path.mkdir()
    return path


@pytest.fixture()
def popen_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record the argument vector of every subprocess started."""

    recorded: list[list[str]] = []
    real_popen = subprocess.Popen

    class RecordingPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args, *a, **kw):
            recorded.append([str(x) for x in args])
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", RecordingPopen)
    return recorded


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_token_travels_only_in_config_environment(
    fake_git, staging, monkeypatch, popen_calls
) -> None:
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN", TOKEN)
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN_HOSTS", "other.example.com, REPO.example.com")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("FAKE_GIT_MODE", "fetch_fails")
    blob = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()

    with pytest.raises(IngestionError):
        ingest_remote_git(
            "https://repo.example.com/o/r.git", staging,
            ref=SHA_A, policy=POLICY,
        )

    assert popen_calls, "no subprocess observed"
    for argv in popen_calls:
        joined = " ".join(argv)
        assert TOKEN not in joined and blob not in joined
    calls = fake_git()
    assert calls
    for call in calls:
        assert TOKEN not in " ".join(call["argv"])
        assert call["seen"]["SYSTEMAOPS_GIT_TOKEN"] is None
        assert call["seen"]["SYSTEMAOPS_GIT_TOKEN_HOSTS"] is None
        assert call["seen"]["HTTPS_PROXY"] is None
        assert call["seen"]["GIT_ALLOW_PROTOCOL"] == "https"
    fetch = next(c for c in calls if "fetch" in c["argv"])
    pairs = {
        fetch["config"][f"GIT_CONFIG_KEY_{i}"]: fetch["config"][f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(fetch["config"]["GIT_CONFIG_COUNT"]))
    }
    header_key = "http.https://repo.example.com/.extraHeader"
    assert pairs[header_key] == f"Authorization: Basic {blob}"
    assert pairs["http.followRedirects"] == "false"
    assert pairs["protocol.allow"] == "never"
    assert pairs["protocol.https.allow"] == "always"
    assert pairs["http.curloptResolve"] == "repo.example.com:443:93.184.216.34"
    assert pairs["http.proxy"] == ""


def test_no_token_means_no_authorization_entry(
    fake_git, staging, monkeypatch
) -> None:
    monkeypatch.delenv("SYSTEMAOPS_GIT_TOKEN", raising=False)
    monkeypatch.setenv("FAKE_GIT_MODE", "fetch_fails")
    with pytest.raises(IngestionError):
        ingest_remote_git(
            "https://repo.example.com/o/r.git", staging,
            ref=SHA_A, policy=POLICY,
        )
    for call in fake_git():
        assert "extraheader" not in json.dumps(call["config"]).lower()


def test_leaked_credentials_are_scrubbed_from_errors(
    fake_git, staging, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN", TOKEN)
    monkeypatch.setenv("FAKE_GIT_MODE", "ls_remote_fails")
    monkeypatch.setenv("FAKE_GIT_LEAK", f"token={TOKEN} Authorization: Basic abc123def456")
    with pytest.raises(IngestionError) as excinfo:
        ingest_remote_git(
            "https://repo.example.com/o/r.git", staging,
            ref="main", policy=POLICY,
        )
    exc = excinfo.value
    assert exc.code == "REMOTE_UNREACHABLE"
    for text in (exc.message, str(exc), repr(exc)):
        assert TOKEN not in text
        assert "hunter2" not in text
        assert "abc123def456" not in text
        assert "bob" not in text


def test_url_credentials_are_refused_and_never_echoed(staging) -> None:
    with pytest.raises(IngestionError) as excinfo:
        ingest_remote_git(
            "https://alice:s3cr3tpw@repo.example.com/o/r.git", staging,
            policy=POLICY,
        )
    assert excinfo.value.code == "CREDENTIALS_IN_URL"
    assert "s3cr3tpw" not in str(excinfo.value)
    assert list(staging.iterdir()) == []


# ---------------------------------------------------------------------------
# Network policy at ingest level
# ---------------------------------------------------------------------------


def test_private_host_is_refused_before_any_git_process(
    fake_git, staging
) -> None:
    policy = NetworkPolicy(
        resolver=lambda h, p, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))
        ]
    )
    code = expect_refusal(
        ingest_remote_git, "https://metadata.example.com/o/r.git", staging,
        policy=policy,
    )
    assert code == "HOST_NOT_PUBLIC"
    assert fake_git() == []


@pytest.mark.parametrize(
    "url,code",
    [
        ("http://repo.example.com/o/r.git", "UNSUPPORTED_SCHEME"),
        ("git://repo.example.com/o/r.git", "UNSUPPORTED_SCHEME"),
        ("file:///tmp/x", "UNSUPPORTED_SCHEME"),
        ("ext::sh -c id", "UNSUPPORTED_SCHEME"),
        ("--upload-pack=id", "INVALID_REMOTE_URL"),
    ],
)
def test_refused_schemes_never_start_git(
    fake_git, staging, url: str, code: str
) -> None:
    assert expect_refusal(
        ingest_remote_git, url, staging, policy=POLICY
    ) == code
    assert fake_git() == []


def test_insecure_http_flag_defaults_closed() -> None:
    assert NetworkPolicy().allow_insecure_http_for_tests is False


# ---------------------------------------------------------------------------
# SSH gating
# ---------------------------------------------------------------------------


def test_ssh_is_refused_when_not_enabled(fake_git, staging) -> None:
    assert expect_refusal(
        ingest_remote_git, "ssh://git@repo.example.com/o/r.git", staging,
        policy=POLICY,
    ) == "SSH_NOT_CONFIGURED"
    assert fake_git() == []


def test_ssh_without_key_material_is_not_configured(
    fake_git, staging, monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("SYSTEMAOPS_GIT_SSH_KEY", raising=False)
    monkeypatch.delenv("SYSTEMAOPS_GIT_KNOWN_HOSTS", raising=False)
    url = "git@repo.example.com:o/r.git"
    assert expect_refusal(
        ingest_remote_git, url, staging, allow_ssh=True, policy=POLICY
    ) == "SSH_NOT_CONFIGURED"
    monkeypatch.setenv("SYSTEMAOPS_GIT_SSH_KEY", str(tmp_path / "missing_key"))
    monkeypatch.setenv("SYSTEMAOPS_GIT_KNOWN_HOSTS", str(tmp_path / "missing_hosts"))
    assert expect_refusal(
        ingest_remote_git, url, staging, allow_ssh=True, policy=POLICY
    ) == "SSH_NOT_CONFIGURED"
    assert fake_git() == []


def test_ssh_command_is_locked_down(
    fake_git, staging, monkeypatch, tmp_path
) -> None:
    key = tmp_path / "id_test"
    known = tmp_path / "known_hosts"
    key.write_text("not a real key", encoding="utf-8")
    known.write_text("repo.example.com ssh-ed25519 AAAA", encoding="utf-8")
    monkeypatch.setenv("SYSTEMAOPS_GIT_SSH_KEY", str(key))
    monkeypatch.setenv("SYSTEMAOPS_GIT_KNOWN_HOSTS", str(known))
    monkeypatch.setenv("FAKE_GIT_MODE", "fetch_fails")

    with pytest.raises(IngestionError):
        ingest_remote_git(
            "ssh://git@repo.example.com/o/r.git", staging,
            ref=SHA_A, allow_ssh=True, policy=POLICY,
        )
    fetch = next(c for c in fake_git() if "fetch" in c["argv"])
    command = fetch["seen"]["GIT_SSH_COMMAND"]
    assert fetch["seen"]["GIT_ALLOW_PROTOCOL"] == "ssh"
    for needle in (
        "BatchMode=yes", "StrictHostKeyChecking=yes", "IdentitiesOnly=yes",
        "ForwardAgent=no", "ClearAllForwardings=yes", "IdentityAgent=none",
        "UpdateHostKeys=no", "CheckHostIP=no", "GlobalKnownHostsFile=",
        "HostName=93.184.216.34",
        "HostKeyAlias=repo.example.com", "UserKnownHostsFile=",
    ):
        assert needle in command, needle
    assert "-F" in command and os.devnull in command


# ---------------------------------------------------------------------------
# Ref safety and pinning
# ---------------------------------------------------------------------------


def test_abbreviated_sha_is_ambiguous(fake_git, staging) -> None:
    assert expect_refusal(
        ingest_remote_git, "https://repo.example.com/o/r.git", staging,
        ref="abcdef1", policy=POLICY,
    ) == "REF_AMBIGUOUS"
    assert fake_git() == []


def test_option_like_ref_is_refused(fake_git, staging) -> None:
    assert expect_refusal(
        ingest_remote_git, "https://repo.example.com/o/r.git", staging,
        ref="--upload-pack=id", policy=POLICY,
    ) == "INVALID_REF"
    assert fake_git() == []


def test_moved_branch_without_sha_fetch_is_commit_moved(
    fake_git, staging, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_GIT_MODE", "moved")
    with pytest.raises(IngestionError) as excinfo:
        ingest_remote_git(
            "https://repo.example.com/o/r.git", staging,
            ref="main", policy=POLICY,
        )
    assert excinfo.value.code == "COMMIT_MOVED"
    assert SHA_A in excinfo.value.message and SHA_B in excinfo.value.message


def test_sha_pin_refused_by_server_is_commit_not_found(
    fake_git, staging, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_GIT_MODE", "fetch_fails")
    assert expect_refusal(
        ingest_remote_git, "https://repo.example.com/o/r.git", staging,
        ref=SHA_A, policy=POLICY,
    ) == "COMMIT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Resource bounds
# ---------------------------------------------------------------------------


def test_watchdog_kills_git_when_staging_grows_past_the_limit(
    fake_git, staging, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_GIT_MODE", "big")
    limits = Limits(max_total_bytes=1024 * 1024)
    started = time.monotonic()
    with pytest.raises(IngestionError) as excinfo:
        ingest_remote_git(
            "https://repo.example.com/o/r.git", staging,
            ref=SHA_A, policy=POLICY, limits=limits,
        )
    assert excinfo.value.code == "LIMIT_EXCEEDED"
    assert time.monotonic() - started < 40, "watchdog did not stop the process"


# ---------------------------------------------------------------------------
# Token scoping (operator allow-list) and git version
# ---------------------------------------------------------------------------


def _header_keys(fetch_call: dict) -> list[str]:
    config = fetch_call["config"]
    return [
        config[f"GIT_CONFIG_KEY_{i}"]
        for i in range(int(config["GIT_CONFIG_COUNT"]))
        if config[f"GIT_CONFIG_KEY_{i}"].lower().endswith(".extraheader")
    ]


@pytest.mark.parametrize("hosts", [None, "", "other.example.com", "*", ",,"])
def test_token_is_never_sent_to_an_unlisted_host(
    fake_git, staging, monkeypatch, hosts
) -> None:
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN", TOKEN)
    if hosts is None:
        monkeypatch.delenv("SYSTEMAOPS_GIT_TOKEN_HOSTS", raising=False)
    else:
        monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN_HOSTS", hosts)
    monkeypatch.setenv("FAKE_GIT_MODE", "fetch_fails")
    sink = DiagnosticSink()
    with pytest.raises(IngestionError):
        ingest_remote_git(
            "https://repo.example.com/o/r.git", staging,
            ref=SHA_A, policy=POLICY, sink=sink,
        )
    calls = fake_git()
    assert calls
    for call in calls:
        assert not _header_keys(call)
        assert TOKEN not in json.dumps(call)
    codes = [d["code"] for d in sink.to_list()]
    assert "REMOTE_TOKEN_NOT_SENT" in codes
    message = next(
        d["message"] for d in sink.to_list() if d["code"] == "REMOTE_TOKEN_NOT_SENT"
    )
    assert "SYSTEMAOPS_GIT_TOKEN_HOSTS" in message and TOKEN not in message


def test_token_is_sent_to_a_listed_host_in_config_only(
    fake_git, staging, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN", TOKEN)
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN_HOSTS", " Repo.Example.com ,x.example.com")
    monkeypatch.setenv("FAKE_GIT_MODE", "fetch_fails")
    sink = DiagnosticSink()
    with pytest.raises(IngestionError):
        ingest_remote_git(
            "https://repo.example.com/o/r.git", staging,
            ref=SHA_A, policy=POLICY, sink=sink,
        )
    fetch = next(c for c in fake_git() if "fetch" in c["argv"])
    assert _header_keys(fetch) == ["http.https://repo.example.com/.extraHeader"]
    for call in fake_git():
        assert TOKEN not in " ".join(call["argv"])
    assert "REMOTE_TOKEN_NOT_SENT" not in [d["code"] for d in sink.to_list()]


def test_no_token_configured_emits_no_token_diagnostic(
    fake_git, staging, monkeypatch
) -> None:
    monkeypatch.delenv("SYSTEMAOPS_GIT_TOKEN", raising=False)
    monkeypatch.setenv("FAKE_GIT_MODE", "fetch_fails")
    sink = DiagnosticSink()
    with pytest.raises(IngestionError):
        ingest_remote_git(
            "https://repo.example.com/o/r.git", staging,
            ref=SHA_A, policy=POLICY, sink=sink,
        )
    assert "REMOTE_TOKEN_NOT_SENT" not in [d["code"] for d in sink.to_list()]


def test_old_git_fails_closed_for_https_but_not_ssh(
    fake_git, staging, monkeypatch, tmp_path
) -> None:
    from enterprise.discovery import gitingest

    monkeypatch.setattr(gitingest, "git_version", lambda: (2, 30, 0))
    assert expect_refusal(
        ingest_remote_git, "https://repo.example.com/o/r.git", staging,
        ref=SHA_A, policy=POLICY,
    ) == "GIT_TOO_OLD"
    assert fake_git() == []
    key = tmp_path / "k"
    known = tmp_path / "h"
    key.write_text("k", encoding="utf-8")
    known.write_text("h", encoding="utf-8")
    monkeypatch.setenv("SYSTEMAOPS_GIT_SSH_KEY", str(key))
    monkeypatch.setenv("SYSTEMAOPS_GIT_KNOWN_HOSTS", str(known))
    monkeypatch.setenv("FAKE_GIT_MODE", "fetch_fails")
    code = expect_refusal(
        ingest_remote_git, "ssh://git@repo.example.com/o/r.git", staging,
        ref=SHA_A, allow_ssh=True, policy=POLICY,
    )
    assert code != "GIT_TOO_OLD"


def test_real_git_version_is_detected_and_modern_enough() -> None:
    from enterprise.discovery import gitingest as real

    real._version_of.cache_clear()
    version = real.git_version()
    assert len(version) == 3 and version >= (2, 37, 0)

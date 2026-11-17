"""Process-level hardening: environment allow-list, output caps, timeouts,
and rejection of exotic local sources."""

from __future__ import annotations

import shutil
import sys
import textwrap
import time
from pathlib import Path

import pytest

from tests.discovery.helpers import REPO_ROOT, codes_of, expect_refusal, make_zip, read_json, write_enterprise_app, write_tree  # noqa: F401

from enterprise.discovery import gitingest
from enterprise.discovery.gitingest import _git, _hardened_env, resolve_git_source

GIT = shutil.which("git")

NOISY = textwrap.dedent(
    """
    import sys, time
    mode = sys.argv[1]
    if mode == "stdout":
        sys.stdout.write("x" * 400000)
    elif mode == "stderr":
        sys.stderr.write("y" * 400000)
    elif mode == "sleep":
        time.sleep(60)
    """
)


@pytest.fixture()
def staging(tmp_path: Path) -> Path:
    path = tmp_path / "stage"
    path.mkdir()
    return path


@pytest.fixture()
def noisy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "noisy.py"
    script.write_text(NOISY, encoding="utf-8")
    monkeypatch.setattr(gitingest, "_GIT_COMMAND", (sys.executable, str(script)))


# ---------------------------------------------------------------------------
# Environment allow-list
# ---------------------------------------------------------------------------


def test_environment_is_built_from_an_allow_list(
    staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cret")
    monkeypatch.setenv("MY_APP_TOKEN", "t0ken")
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN", "tok")
    monkeypatch.setenv("SYSTEMAOPS_GIT_TOKEN_HOSTS", "example.com")
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("SSL_CERT_FILE", "/certs/ca.pem")
    env = _hardened_env(staging)
    for leaked in ("AWS_SECRET_ACCESS_KEY", "MY_APP_TOKEN", "SYSTEMAOPS_GIT_TOKEN",
                   "SYSTEMAOPS_GIT_TOKEN_HOSTS"):
        assert leaked not in env
    assert env["LC_ALL"] == "C"
    assert env["SSL_CERT_FILE"] == "/certs/ca.pem"
    assert "PATH" in {k.upper() for k in env}


@pytest.mark.skipif(GIT is None, reason="git is required")
def test_git_still_runs_in_the_restricted_environment(staging: Path) -> None:
    out = _git(["--version"], _hardened_env(staging), what="version")
    assert out.stdout.startswith("git version")


# ---------------------------------------------------------------------------
# Output caps and timeouts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["stdout", "stderr"])
def test_runaway_output_is_capped(
    noisy, staging: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(gitingest, "_OUTPUT_CAP_BYTES", 64 * 1024)
    assert expect_refusal(
        _git, [mode], _hardened_env(staging), what="noisy"
    ) == "LIMIT_EXCEEDED"


def test_a_hung_process_times_out_with_a_typed_error(
    noisy, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gitingest, "_GIT_TIMEOUT_SECONDS", 1)
    started = time.monotonic()
    code = expect_refusal(_git, ["sleep"], _hardened_env(staging), what="hang")
    assert code == "GIT_TIMEOUT"
    assert time.monotonic() - started < 30


# ---------------------------------------------------------------------------
# Local source classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        r"\\host\share\repo",
        "//host/share/repo",
        "ext::sh -c id",
        "fd::17",
        "foo::bar",
        "javascript:alert(1)",
        "data:text/plain,hi",
        "myscheme+x:thing",
    ],
)
def test_exotic_local_sources_are_unsupported(source: str) -> None:
    assert expect_refusal(resolve_git_source, source) == "UNSUPPORTED_SOURCE"


@pytest.mark.parametrize("source", [r"C:\repos\app","c:/repos/app", "relative/path"])
def test_drive_letters_and_relative_paths_still_work(source: str) -> None:
    assert resolve_git_source(source) == ("local", source)

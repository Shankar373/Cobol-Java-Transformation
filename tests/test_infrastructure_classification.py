"""Build/run failures caused by Docker are infrastructure, not FAILED (audit V4).

B4 flagged an unavailable build image as infrastructure, but a build timeout,
a staging exception, or Docker's own exit statuses 125-127 still came back
as the program's failure, were compared against the oracle and derived
FAILED. Those are now ``infrastructure_error`` (build) or an ``error``
termination (run), which derive ERROR - never a verdict about the program.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engine.candidate.adapter import CandidateManifest
from engine.docker_cli import is_docker_infrastructure_exit
from engine.domain.identities import AdapterStatus

DAEMON_ERROR = b"docker: Error response from daemon: failed to create task\n"


@pytest.mark.parametrize("code,stderr,build,expected", [
    (125, DAEMON_ERROR, False, True),
    (126, b"Error response from daemon: OCI runtime exec failed", False, True),
    (125, b"", False, False),          # a program's own RETURN-CODE 125
    (127, b"sh: mvn: not found", True, True),
    (1, DAEMON_ERROR, True, False),     # javac/Maven failure: the program's
    (0, b"", True, False),
    (None, b"", False, False),
])
def test_is_docker_infrastructure_exit(code, stderr, build, expected):
    assert is_docker_infrastructure_exit(code, stderr, build=build) is expected


def _manifest(name: str) -> CandidateManifest:
    return CandidateManifest(
        candidate_id="v4", workload_id="v4", source_hash="x",
        generated_files={name: "x"}, entrypoint="Main",
    )


def _spring(monkeypatch, outcome):
    import engine.candidate.docker_spring_boot_adapter as mod

    adapter = object.__new__(mod.DockerSpringBootCandidateAdapter)
    adapter._status = AdapterStatus.AVAILABLE
    adapter._config = mod.DockerSpringBootConfig()
    monkeypatch.setattr(adapter, "_fresh_build_ref", lambda: ("img@sha256:" + "a" * 64, ""))
    monkeypatch.setattr(adapter, "_cleanup_container", lambda name: (True, "removed"))
    monkeypatch.setattr(mod.subprocess, "run", outcome)
    return adapter


def _java(monkeypatch, outcome):
    import engine.candidate.docker_java_adapter as mod

    adapter = object.__new__(mod.DockerJavaCandidateAdapter)
    adapter._status = AdapterStatus.AVAILABLE
    adapter._config = mod.DockerJavaConfig()
    adapter._resolved_digest = "sha256:" + "a" * 64
    monkeypatch.setattr(adapter, "_cleanup_container", lambda name: (True, "removed"))
    monkeypatch.setattr(mod.subprocess, "run", outcome)
    return adapter


def _exit(code: int, stderr: bytes = b""):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, b"", stderr)


def _timeout(cmd, **kw):
    raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)


@pytest.mark.parametrize("lane", ["spring", "java"])
@pytest.mark.parametrize("outcome,infrastructure", [
    (_exit(125, DAEMON_ERROR), True),
    (_exit(127, b"sh: mvn: not found"), True),
    (_timeout, True),
    (_exit(1, b"Main.java:1: error: ';' expected"), False),
])
def test_build_failure_classification(tmp_path: Path, monkeypatch, lane, outcome, infrastructure):
    if lane == "spring":
        (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
        adapter, manifest = _spring(monkeypatch, outcome), _manifest("pom.xml")
    else:
        (tmp_path / "Main.java").write_text("class Main {}", encoding="utf-8")
        adapter, manifest = _java(monkeypatch, outcome), _manifest("Main.java")

    result = adapter.compile(str(tmp_path), manifest)

    assert result.success is False
    assert result.infrastructure_error is infrastructure


def test_staging_exception_is_infrastructure(tmp_path: Path, monkeypatch):
    import engine.candidate.docker_java_adapter as mod

    adapter = _java(monkeypatch, _exit(0))

    def broken_staging(prefix=""):
        raise OSError("no space left on device")

    monkeypatch.setattr(mod, "sandbox_staging_dir", broken_staging)
    result = adapter.compile(str(tmp_path), _manifest("Main.java"))
    assert result.success is False and result.infrastructure_error is True

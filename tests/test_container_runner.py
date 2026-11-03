"""Audit V15 (C2): one container-run lifecycle for the candidate adapters.

``DockerJavaCandidateAdapter`` and ``DockerSpringBootAdapter`` each carried
a copy of the run/timeout/cleanup/infrastructure-exit logic (~230 lines).
``run_container`` is that logic once; the adapters pass only their command,
stdin, budget and label.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from engine.execution import container_runner
from engine.execution.container_runner import ContainerRun, run_container


def _patch_run(monkeypatch, behaviour):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"], calls["kwargs"] = cmd, kwargs
        return behaviour(cmd, kwargs)

    monkeypatch.setattr(container_runner.subprocess, "run", fake_run)
    return calls


def _cleanup(monkeypatch, detail="removed"):
    seen = []

    def cleanup(name):
        seen.append(name)
        return True, detail

    return seen, cleanup


def test_normal_exit(monkeypatch):
    calls = _patch_run(monkeypatch, lambda c, k: SimpleNamespace(stdout=b"out", stderr=b"", returncode=0))
    result = run_container(["docker", "run"], input_data=b"in", timeout_seconds=10,
                           container_name="c1", label="Java", cleanup=lambda n: (True, ""))
    assert result == ContainerRun(b"out", b"", 0, "normal")
    assert calls["kwargs"]["input"] == b"in"
    assert calls["kwargs"]["timeout"] == 15  # budget + 5 s of start-up


def test_nonzero_exit_is_the_programs_own(monkeypatch):
    _patch_run(monkeypatch, lambda c, k: SimpleNamespace(stdout=b"", stderr=b"boom", returncode=3))
    result = run_container(["docker"], input_data=None, timeout_seconds=1,
                           container_name="c", label="Java", cleanup=lambda n: (True, ""))
    assert (result.exit_code, result.termination) == (3, "nonzero_exit")


def test_docker_refusing_the_run_is_an_error_not_a_program_result(monkeypatch):
    _patch_run(monkeypatch, lambda c, k: SimpleNamespace(
        stdout=b"", stderr=b"docker: Error response from daemon: boom", returncode=125))
    result = run_container(["docker"], input_data=None, timeout_seconds=1,
                           container_name="c", label="Java", cleanup=lambda n: (True, ""))
    assert (result.exit_code, result.termination) == (None, "error")


def test_timeout_removes_the_container_and_says_so(monkeypatch):
    def behaviour(cmd, kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], output=b"partial")

    _patch_run(monkeypatch, behaviour)
    seen, cleanup = _cleanup(monkeypatch, detail="removed")
    result = run_container(["docker"], input_data=None, timeout_seconds=2,
                           container_name="c-timeout", label="Spring Boot", cleanup=cleanup)
    assert seen == ["c-timeout"]
    assert result.termination == "timeout" and result.exit_code is None
    assert result.stdout == b"partial"
    assert result.stderr == b"Spring Boot execution timeout; cleanup=removed"


def test_unexpected_failure_is_an_error(monkeypatch):
    def behaviour(cmd, kwargs):
        raise OSError("no docker")

    _patch_run(monkeypatch, behaviour)
    result = run_container(["docker"], input_data=None, timeout_seconds=1,
                           container_name="c", label="Java", cleanup=lambda n: (True, ""))
    assert (result.exit_code, result.termination) == (None, "error")
    assert result.stderr == b"no docker"


def test_both_adapters_use_the_shared_runner():
    import inspect

    from engine.candidate import docker_java_adapter, docker_spring_boot_adapter

    for module in (docker_java_adapter, docker_spring_boot_adapter):
        source = inspect.getsource(module)
        assert "run_container(" in source
        assert "except subprocess.TimeoutExpired as exc" not in source

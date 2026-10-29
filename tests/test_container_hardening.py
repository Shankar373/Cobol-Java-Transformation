"""P0 container-hardening regression suite.

Pins the approved hardening plan item 1 for every ``docker run`` site:

* all lanes carry ``--security-opt no-new-privileges=true``,
  ``--cap-drop ALL`` and a non-root ``--user 10001:10001`` — produced by
  the single shared helper so run sites cannot drift apart (the P0 audit
  found 9 of 10 sites missing ``no-new-privileges`` entirely);
* no lane silently falls back to root
  (``NON_ROOT_EXEMPT_LANES`` stays empty unless a limitation is
  explicitly recorded and reviewed);
* ``prepare_host_tree`` makes host staging trees accessible to the
  container identity (POSIX permission bits; advisory on Windows where
  Docker Desktop maps identities);
* a Docker-gated runtime proof runs a real container with the exact
  flags and asserts the process is uid/gid 10001 and can write through a
  prepared bind mount — gated with the fail-closed idiom
  (``RUN_DOCKER_TESTS`` unset -> skip; set without a working Docker ->
  FAIL, never a silent skip).

The source-drift guard walks every engine module that issues
``"docker", "run"`` and requires the shared helper to be used exactly as
many times as there are run sites — a new site added without hardening
fails the suite.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from engine.execution.container_hardening import (
    CONTAINER_GID,
    CONTAINER_UID,
    CONTAINER_USER,
    NON_ROOT_EXEMPT_LANES,
    container_run_hardening_flags,
    prepare_host_tree,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Every engine module that issues a `docker run` invocation.
RUN_SITE_MODULES = (
    "engine/oracle/docker_adapter.py",
    "engine/candidate/docker_java_adapter.py",
    "engine/candidate/docker_spring_boot_adapter.py",
    "engine/transformation/producers/opensource4j.py",
    "engine/execution/docker_runner.py",
)


# ---------------------------------------------------------------------------
# Shared flag helper contract
# ---------------------------------------------------------------------------


class TestHardeningFlagsContract:
    def test_flags_are_exactly_the_hardening_set(self):
        assert container_run_hardening_flags("oracle") == [
            "--security-opt", "no-new-privileges=true",
            "--cap-drop", "ALL",
            "--user", "10001:10001",
        ]

    def test_dedicated_identity_is_10001(self):
        assert (CONTAINER_UID, CONTAINER_GID) == (10001, 10001)
        assert CONTAINER_USER == "10001:10001"

    def test_every_call_returns_an_independent_list(self):
        first = container_run_hardening_flags("oracle")
        first.append("--mutable")
        assert "--mutable" not in container_run_hardening_flags("oracle")

    def test_no_lane_is_exempt_from_non_root_execution(self):
        """No silent root fallback: exemptions must be explicit + reviewed."""
        assert NON_ROOT_EXEMPT_LANES == frozenset()


# ---------------------------------------------------------------------------
# Host tree preparation
# ---------------------------------------------------------------------------


class TestPrepareHostTree:
    def test_missing_path_is_a_no_op(self):
        path = Path("/definitely/not/here-42")
        assert not path.exists()
        prepare_host_tree(path, writable=True)  # must not raise
        assert not path.exists()  # still absent: a missing path is a no-op

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX permission bits are not meaningful on Windows hosts",
    )
    def test_directories_and_files_gain_other_read_bits(self, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "f.cob").write_bytes(b"x")
        os.chmod(tmp_path / "a", 0o700)
        os.chmod(nested / "f.cob", 0o600)

        prepare_host_tree(tmp_path, writable=False)

        for directory in (tmp_path, tmp_path / "a", nested):
            assert stat.S_IMODE(directory.stat().st_mode) & 0o005, (
                f"{directory} not traversable by the container user"
            )
        assert stat.S_IMODE((nested / "f.cob").stat().st_mode) & 0o004

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX permission bits are not meaningful on Windows hosts",
    )
    def test_writable_trees_gain_other_write_bits(self, tmp_path):
        (tmp_path / "out").mkdir()

        prepare_host_tree(tmp_path / "out", writable=True)

        assert stat.S_IMODE((tmp_path / "out").stat().st_mode) & 0o002

    def test_calling_it_on_windows_is_safe(self, tmp_path):
        """Best-effort preparation must never raise on any platform."""
        (tmp_path / "x").mkdir()
        (tmp_path / "x" / "f").write_bytes(b"y")
        before = sorted(p.name for p in (tmp_path / "x").iterdir())
        prepare_host_tree(tmp_path, writable=True)  # must not raise
        after = sorted(p.name for p in (tmp_path / "x").iterdir())
        assert before == after  # no files lost during preparation


# ---------------------------------------------------------------------------
# Producer argv (runtime capture — the r1 idiom)
# ---------------------------------------------------------------------------


def _capture_producer_argv(monkeypatch) -> list[str]:
    import subprocess as sp

    from engine.transformation.producers import opensource4j as mod

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001 - argv is the contract under test
        calls.append(list(cmd))
        raise sp.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    adapter = mod.OpenSourceCOBOL4JProducerAdapter()
    result = adapter.transform(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. PROG1.\n",
        program_id="PROG1",
    )
    assert result is not None
    for argv in calls:
        if len(argv) >= 2 and argv[0] == "docker" and argv[1] == "run":
            return argv
    raise AssertionError(f"no `docker run` invocation among: {calls}")


class TestProducerRunSiteHardening:
    def test_producer_container_drops_all_capabilities(self, monkeypatch):
        argv = _capture_producer_argv(monkeypatch)
        assert "--cap-drop" in argv
        assert argv[argv.index("--cap-drop") + 1] == "ALL"

    def test_producer_container_runs_as_dedicated_non_root_user(
        self, monkeypatch
    ):
        argv = _capture_producer_argv(monkeypatch)
        assert "--user" in argv
        assert argv[argv.index("--user") + 1] == CONTAINER_USER


# ---------------------------------------------------------------------------
# Source drift guard — no run site may skip the shared helper
# ---------------------------------------------------------------------------


class TestNoRunSiteDriftsFromTheSharedHelper:
    @pytest.mark.parametrize("module", RUN_SITE_MODULES)
    def test_every_run_site_uses_the_helper(self, module):
        source = (REPO_ROOT / module).read_text(encoding="utf-8")
        run_sites = source.count('"docker", "run"')
        helper_calls = source.count("container_run_hardening_flags(")
        assert run_sites >= 1, f"{module} no longer issues docker run?"
        assert helper_calls == run_sites, (
            f"{module} has {run_sites} docker run site(s) but only"
            f" {helper_calls} hardening-flag call(s): a new or edited site"
            " must use container_run_hardening_flags() — never run an"
            " unhardened container"
        )

    def test_engine_has_no_unhardened_docker_run_literal(self):
        """Scan every engine module, not just the known list."""
        engine_root = REPO_ROOT / "engine"
        offenders = []
        for path in engine_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if '"docker", "run"' in source and (
                "container_run_hardening_flags(" not in source
            ):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == [], (
            f"docker run sites without the shared hardening helper: {offenders}"
        )


# ---------------------------------------------------------------------------
# Docker-gated runtime proof (fail-closed gating)
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10, text=True
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


DOCKER_AVAILABLE = _docker_available()
RUNTIME_REQUESTED = bool(os.environ.get("RUN_DOCKER_TESTS"))


@pytest.mark.skipif(
    not RUNTIME_REQUESTED,
    reason="RUN_DOCKER_TESTS not set (runtime proof not requested)",
)
def test_requested_runtime_proof_has_a_runtime():
    """``RUN_DOCKER_TESTS=1`` without Docker must fail, never silently skip."""
    if not DOCKER_AVAILABLE:
        pytest.fail(
            "RUN_DOCKER_TESTS=1 but the Docker runtime is unavailable:"
            " the non-root runtime proof cannot execute and an unexecuted"
            " test must not be reported as proof"
        )


@pytest.mark.skipif(
    not RUNTIME_REQUESTED,
    reason="RUN_DOCKER_TESTS not set (runtime proof not requested)",
)
@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")
def test_hardened_container_runs_as_dedicated_non_root_user(tmp_path):
    """Real container, exact helper flags: uid/gid 10001 + writable mount."""
    out = tmp_path / "out"
    out.mkdir()
    prepare_host_tree(out, writable=True)

    argv = [
        "docker", "run", "--rm",
        *container_run_hardening_flags("hardening-proof"),
        "--network", "none",
        "--memory", "256m",
        "--cpus", "0.5",
        "--pids-limit", "64",
        "-v", f"{out}:/out",
        "eclipse-temurin:21-jdk",
        "sh", "-c",
        'test "$(id -u)" = "10001" && test "$(id -g)" = "10001"'
        " && touch /out/non-root-write && echo NON_ROOT_OK",
    ]
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=300
    )

    assert result.returncode == 0, (
        f"hardened container failed: rc={result.returncode}"
        f" stderr={result.stderr[-800:]}"
    )
    assert "NON_ROOT_OK" in result.stdout
    assert (out / "non-root-write").exists(), (
        "the non-root container user could not write through the prepared"
        " bind mount"
    )

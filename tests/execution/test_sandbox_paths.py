"""Regression tests for host-visible sandbox staging (Phase E-A, R1).

The API container reaches the Docker daemon through the daemon socket, so
``docker run -v <path>:...`` bind sources are resolved on the HOST
filesystem. Every Docker adapter must therefore stage bind-mounted inputs
under ``SANDBOX_STAGING_DIR`` and translate them to
``SANDBOX_HOST_STAGING_DIR``. Staging under the container-private tmpfs
(``/app/tmp``) or an untranslated named-volume path is invisible to the
host daemon and fails the oracle/candidate lanes closed in production.

These tests pin:
1. path translation (identity without config, prefix rewrite with config,
   non-staging paths untouched);
2. staging root validation (missing/unwritable root fails closed);
3. every Docker ``-v`` construction site in the engine routes through the
   translation helper (static guarantee against future direct
   ``os.path.abspath(...)`` bind sources);
4. a real Docker bind mount through the helper (host-parity proof).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from engine.execution import sandbox_paths
from engine.execution.sandbox_paths import (
    HOST_STAGING_DIR_ENV,
    STAGING_DIR_ENV,
    docker_volume_arg,
    ensure_staging_root,
    sandbox_staging_dir,
    to_host_path,
)


@pytest.fixture
def clean_staging_env(monkeypatch):
    """Run with neither staging variable configured (dev/host parity)."""
    monkeypatch.delenv(STAGING_DIR_ENV, raising=False)
    monkeypatch.delenv(HOST_STAGING_DIR_ENV, raising=False)
    return monkeypatch


@pytest.fixture
def configured_staging(monkeypatch, tmp_path):
    """Run with a container/host staging pair configured."""
    container_root = tmp_path / "container-staging"
    host_root = tmp_path / "host-staging"
    container_root.mkdir()
    host_root.mkdir()
    monkeypatch.setenv(STAGING_DIR_ENV, str(container_root))
    monkeypatch.setenv(HOST_STAGING_DIR_ENV, str(host_root))
    return container_root, host_root


# ---------------------------------------------------------------------------
# 1. Path translation
# ---------------------------------------------------------------------------


class TestToHostPath:
    def test_identity_without_configuration(self, clean_staging_env):
        with tempfile.TemporaryDirectory() as tmp:
            probe = os.path.join(tmp, "src")
            assert to_host_path(probe) == os.path.abspath(probe)

    def test_identity_when_only_staging_configured(
        self, monkeypatch, tmp_path
    ):
        root = tmp_path / "staging"
        root.mkdir()
        monkeypatch.setenv(STAGING_DIR_ENV, str(root))
        monkeypatch.delenv(HOST_STAGING_DIR_ENV, raising=False)
        probe = root / "job-1" / "src"
        assert to_host_path(probe) == os.path.abspath(str(probe))

    def test_staging_prefix_rewritten(self, configured_staging):
        container_root, host_root = configured_staging
        staged = container_root / "oracle-abc123" / "src"
        assert to_host_path(staged) == str(host_root / "oracle-abc123" / "src")

    def test_staging_root_itself_rewritten(self, configured_staging):
        container_root, host_root = configured_staging
        assert to_host_path(container_root) == os.path.abspath(str(host_root))

    def test_non_staging_paths_untouched(self, configured_staging, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        probe = elsewhere / "input.dat"
        assert to_host_path(probe) == os.path.abspath(str(probe))

    def test_sibling_prefix_not_rewritten(self, configured_staging):
        """A path that merely shares a string prefix must not translate."""
        container_root, host_root = configured_staging
        sibling = Path(str(container_root) + "-other") / "src"
        assert to_host_path(sibling) == os.path.abspath(str(sibling))
        assert not to_host_path(sibling).startswith(
            os.path.abspath(str(host_root))
        )

    def test_tmpfs_paths_untouched(self, configured_staging):
        """Container-private tmpfs paths are never staging paths."""
        probe = Path("/app/tmp/ingest-xyz/input.dat")
        assert to_host_path(probe) == os.path.abspath(str(probe))


class TestDockerVolumeArg:
    def test_readonly_suffix(self, configured_staging):
        container_root, host_root = configured_staging
        staged = container_root / "job" / "src"
        assert docker_volume_arg(staged, "/workspace/src") == [
            "-v",
            f"{host_root / 'job' / 'src'}:/workspace/src:ro",
        ]

    def test_writable_mount(self, configured_staging):
        container_root, host_root = configured_staging
        staged = container_root / "job" / "output"
        assert docker_volume_arg(staged, "/workspace/output", readonly=False) == [
            "-v",
            f"{host_root / 'job' / 'output'}:/workspace/output",
        ]

    def test_identity_without_configuration(self, clean_staging_env, tmp_path):
        staged = tmp_path / "src"
        assert docker_volume_arg(staged, "/workspace/src") == [
            "-v",
            f"{os.path.abspath(str(staged))}:/workspace/src:ro",
        ]


# ---------------------------------------------------------------------------
# 2. Staging root validation
# ---------------------------------------------------------------------------


class TestStagingRoot:
    def test_sandbox_staging_dir_uses_configured_root(
        self, configured_staging
    ):
        container_root, _ = configured_staging
        with sandbox_staging_dir(prefix="oracle-") as staged:
            assert Path(staged).parent == container_root
            assert Path(staged).name.startswith("oracle-")
            # File I/O uses the container-visible path.
            probe = Path(staged) / "src" / "MAIN.cob"
            probe.parent.mkdir(parents=True)
            probe.write_text("IDENTIFICATION DIVISION.", encoding="utf-8")
            assert probe.is_file()

    def test_sandbox_staging_dir_falls_back_without_config(
        self, clean_staging_env
    ):
        with sandbox_staging_dir(prefix="javaexec-") as staged:
            assert Path(staged).name.startswith("javaexec-")
            assert Path(staged).is_dir()

    def test_uncreatable_root_fails_closed(self, monkeypatch, tmp_path):
        """A configured root that cannot be created must raise loudly."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        monkeypatch.setenv(
            STAGING_DIR_ENV, str(blocker / "staging")
        )
        with pytest.raises(RuntimeError, match="cannot be created"):
            ensure_staging_root()
        with pytest.raises(RuntimeError):
            with sandbox_staging_dir():
                pass  # pragma: no cover


# ---------------------------------------------------------------------------
# 3. Static guarantee: every engine bind source routes through the helper
# ---------------------------------------------------------------------------


def _bind_sources(source: str) -> list[str]:
    """Return raw ``-v`` bind-source expressions from engine source text."""
    import re

    return re.findall(r'"-v",\s*f"([^"]+)"', source)


@pytest.mark.parametrize(
    "module",
    [
        "engine/oracle/docker_adapter.py",
        "engine/candidate/docker_java_adapter.py",
        "engine/candidate/docker_spring_boot_adapter.py",
        "engine/execution/docker_runner.py",
        "engine/transformation/producers/opensource4j.py",
    ],
)
def test_no_untranslated_bind_sources(module):
    """Docker ``-v`` sources must use docker_volume_arg/to_host_path.

    A raw ``os.path.abspath(...)`` bind source bypasses the host
    translation and reintroduces the invisible-workspace failure in
    production, where the host daemon resolves a container-private path.
    """
    from engine.execution.sandbox_paths import (  # noqa: F401 (import surface)
        docker_volume_arg,
        to_host_path,
    )

    root = Path(sandbox_paths.__file__).resolve().parent.parent.parent
    text = (root / module).read_text(encoding="utf-8")
    raw = [expr for expr in _bind_sources(text) if "abspath" in expr]
    assert raw == [], f"{module} has untranslated bind sources: {raw}"


# ---------------------------------------------------------------------------
# 4. Real Docker bind mount through the helper (host-parity proof)
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@pytest.mark.skipif(
    not _docker_available(), reason="Docker daemon is not available"
)
def test_real_bind_mount_through_helper(configured_staging, monkeypatch):
    """A file staged via the helper is visible inside the sandbox.

    Both names point at the same directory here, mirroring production
    where the bind mount makes SANDBOX_STAGING_DIR and
    SANDBOX_HOST_STAGING_DIR the same directory (and mirroring dev hosts,
    where no translation is configured at all).
    """
    container_root, _ = configured_staging
    monkeypatch.setenv(HOST_STAGING_DIR_ENV, str(container_root))
    with sandbox_staging_dir(prefix="e2e-") as staged:
        staged_src = Path(staged) / "src"
        staged_src.mkdir()
        (staged_src / "hello.txt").write_text("hello-sandbox", encoding="utf-8")
        volume = docker_volume_arg(staged_src, "/workspace/src", readonly=True)
        proc = subprocess.run(
            [
                "docker", "run", "--rm",
                "--network", "none",
                "--memory", "128m",
                "--cpus", "0.5",
                "--pids-limit", "32",
                *volume,
                "alpine:3.20",
                "cat", "/workspace/src/hello.txt",
            ],
            capture_output=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr.decode(errors="replace")
        assert proc.stdout.decode(errors="replace").strip() == "hello-sandbox"

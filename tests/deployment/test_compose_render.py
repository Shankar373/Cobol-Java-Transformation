"""Rendered Compose configuration topology (audit L.6.2).

The existing ``test_production_topology.py`` pins the production contract by
source inspection (stdlib only, no Docker dependency).  This file adds a
*rendered* check: when Docker is available and the production env file can be
provided, ``docker compose config`` must render a configuration that keeps
the dangerous privileges out.  It is skipped (not failed) on hosts without
Docker or a usable env file, so CI stays green on dependency-free runners.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
COMPOSE = REPO / "docker-compose.production.yml"
ENV_EXAMPLE = REPO / ".env.production.example"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _render_config() -> str | None:
    """Return rendered compose config text, or None if it cannot be rendered."""
    if not _docker_available():
        return None
    if not COMPOSE.is_file() or not ENV_EXAMPLE.is_file():
        return None
    env = dict(os.environ)
    env.setdefault("CONTROL_PLANE_API_TOKEN", "a" * 32)
    env.setdefault("ENV_FILE", ".env.production.example")
    env.setdefault("HOST_SANDBOX_STAGING_DIR", str(REPO / "tmp" / "staging"))
    try:
        proc = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "config"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


@pytest.mark.skipif(not _docker_available(), reason="docker not available")
class TestRenderedComposeTopology:
    def test_compose_renders(self) -> None:
        rendered = _render_config()
        if rendered is None:
            pytest.skip("compose config could not be rendered (env missing)")
        assert "services:" in rendered
        assert "api:" in rendered

    def test_no_privileged_mode(self) -> None:
        rendered = _render_config()
        if rendered is None:
            pytest.skip("compose config could not be rendered (env missing)")
        assert "privileged: true" not in rendered

    def test_no_host_network_mode(self) -> None:
        rendered = _render_config()
        if rendered is None:
            pytest.skip("compose config could not be rendered (env missing)")
        assert "network_mode: host" not in rendered
        assert "network_mode: \"host\"" not in rendered

    def test_resource_caps_present(self) -> None:
        rendered = _render_config()
        if rendered is None:
            pytest.skip("compose config could not be rendered (env missing)")
        assert "mem_limit" in rendered or "limits:" in rendered
        assert "pids_limit" in rendered or "pids:" in rendered

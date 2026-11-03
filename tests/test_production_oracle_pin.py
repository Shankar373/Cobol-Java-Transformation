"""Production refuses an unpinned GnuCOBOL oracle (audit 2026-11-03, V5).

With ``SYSTEMAOPS_ORACLE_DIGEST`` empty the engine auto-pinned whatever image
the ``gnucobol-ocesql:latest`` tag named at run time, so a rebuilt or
replaced oracle - the ground truth of every verdict - was accepted silently.
Production now requires the digest at API startup, compose refuses to start
without it, and the start script resolves it from the deployed image.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from api.app import verify_production_oracle_pin

REPO = Path(__file__).resolve().parent.parent
PIN = "sha256:" + "a" * 64


@pytest.mark.parametrize("value", [None, "", "latest", "sha256:abc", "gnucobol-ocesql@" + PIN])
def test_production_without_a_sha256_pin_refuses_to_start(monkeypatch, value):
    monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
    if value is None:
        monkeypatch.delenv("SYSTEMAOPS_ORACLE_DIGEST", raising=False)
    else:
        monkeypatch.setenv("SYSTEMAOPS_ORACLE_DIGEST", value)
    with pytest.raises(RuntimeError, match="SYSTEMAOPS_ORACLE_DIGEST"):
        verify_production_oracle_pin()


def test_production_with_a_pin_starts(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
    monkeypatch.setenv("SYSTEMAOPS_ORACLE_DIGEST", PIN)
    verify_production_oracle_pin()


def test_development_keeps_auto_pin(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_ENV", raising=False)
    monkeypatch.delenv("SYSTEMAOPS_ORACLE_DIGEST", raising=False)
    verify_production_oracle_pin()


def test_import_time_gate_is_wired():
    source = (REPO / "api" / "app.py").read_text(encoding="utf-8")
    assert "\nverify_production_oracle_pin()\n" in source


def test_compose_and_start_script_carry_the_pin():
    compose = (REPO / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert "SYSTEMAOPS_ORACLE_DIGEST: ${SYSTEMAOPS_ORACLE_DIGEST:?" in compose
    start = (REPO / "scripts" / "deploy" / "start-production.sh").read_text(encoding="utf-8")
    assert "oracle_image_digest()" in start
    assert "export SYSTEMAOPS_ORACLE_DIGEST" in start


def test_oracle_image_digest_matches_the_adapter_identity():
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    from engine.oracle.adapter import OracleAdapterConfig
    from engine.oracle.docker_adapter import DockerOracleAdapter, oracle_image_digest

    digest = oracle_image_digest()
    assert digest.startswith("sha256:")
    adapter = DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2", image_digest=digest, compiler_version="3.1.2.0",
    ))
    # The declared pin equals what the adapter resolves, so it is accepted.
    assert adapter.probe().value == "AVAILABLE"

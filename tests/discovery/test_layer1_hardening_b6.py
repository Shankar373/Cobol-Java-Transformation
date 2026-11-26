"""B6: production requires a checkpoint seal key (D4); a crash leaves no stale staging for good (D7)."""

from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import discovery_routes
from api.app import app
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService, STALE_STAGING_SECONDS
from tests.discovery.helpers import COBOL_ESTATE


def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in COBOL_ESTATE.items():
            archive.writestr(name, text)
    return buffer.getvalue()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS", "SYSTEMAOPS_STORE_KEY"):
        monkeypatch.delenv(name, raising=False)
    service = DiscoveryRunService(tmp_path / "discovery", workers=1)
    discovery_routes.reset_service_for_tests(service)
    yield TestClient(app)
    service.shutdown()
    discovery_routes.reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


def submit(client: TestClient):
    return client.post("/discovery/runs/zip", files={"file": ("estate.zip", _zip(), "application/zip")})


def test_no_key_problem_outside_production(client, monkeypatch) -> None:
    monkeypatch.setattr(discovery_routes, "_production_active", lambda: False)
    assert discovery_routes.seal_key_problem() is None
    assert submit(client).status_code == 202


def test_production_without_a_store_key_refuses_new_discovery(client, monkeypatch) -> None:
    monkeypatch.setattr(discovery_routes, "_production_active", lambda: True)
    assert "SYSTEMAOPS_STORE_KEY" in (discovery_routes.seal_key_problem() or "")
    refused = submit(client)
    assert refused.status_code == 503 and "SYSTEMAOPS_STORE_KEY" in refused.json()["detail"]
    git = client.post("/discovery/runs/git", json={"url": "https://example.invalid/r.git"})
    assert git.status_code == 503


def test_production_with_a_store_key_accepts_discovery(client, monkeypatch) -> None:
    monkeypatch.setattr(discovery_routes, "_production_active", lambda: True)
    monkeypatch.setenv("SYSTEMAOPS_STORE_KEY", "k" * 32)
    assert discovery_routes.seal_key_problem() is None
    assert submit(client).status_code == 202


def test_readiness_assessment_is_blocked_without_the_key_in_production(tmp_path: Path, monkeypatch) -> None:
    from api import readiness

    monkeypatch.delenv("SYSTEMAOPS_STORE_KEY", raising=False)
    monkeypatch.setattr(discovery_routes, "_production_active", lambda: True)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "A.cbl").write_text("x\n", encoding="utf-8")
    record = readiness.assess_workspace(tree, "t")
    assert record["status"] == "BLOCKED" and record["blockers"][0]["id"] == "discovery-failed:STORE_KEY_REQUIRED"


def _age(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_a_restart_sweeps_stale_staging_but_keeps_fresh_and_published_work(tmp_path: Path) -> None:
    root = tmp_path / "discovery"
    store = root / "store"
    stale_stage, fresh_stage = store / "discovery-stage-old", store / "discovery-stage-new"
    stale_tmp, fresh_tmp = store / "checkpoints" / ".CP-aaa.tmp-1", store / "checkpoints" / ".CP-bbb.tmp-2"
    published = store / "checkpoints" / "CP-0123"
    for path in (stale_stage, fresh_stage, stale_tmp, fresh_tmp, published):
        path.mkdir(parents=True)
        (path / "file").write_text("x", encoding="utf-8")
    for path in (stale_stage, stale_tmp, published):
        _age(path, STALE_STAGING_SECONDS + 60)
    service = DiscoveryRunService(root, workers=1)
    try:
        assert not stale_stage.exists() and not stale_tmp.exists()
        assert fresh_stage.exists() and fresh_tmp.exists() and published.exists()
    finally:
        service.shutdown()
        rmtree_force(root)

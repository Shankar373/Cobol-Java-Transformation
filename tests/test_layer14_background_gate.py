"""Layer 14 (control plane): the background workers re-check the readiness gate (L14-P1).

The entry points (``modernize``, ``revalidate``) pass the gate before a run exists, but
the audit recorded that the workers which actually do the work never consult it again
(`docs/discovery/LAYER_AUDIT.md`, open item: "the engine and background workers do not
re-check the gate").  A source tree that changes - or disappears - between the request
and the worker therefore still reached generation.

Fail closed by name: a blocked tree must fail the run with the readiness refusal,
before any generation or validation work starts, and the API must serve that refusal.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import _svc, app
from api.discovery_routes import reset_service_for_tests
from api.models import RunStage
from api.service import Service
from api.store import RunRecord
from enterprise.discovery.compilers import ToolchainConfig
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService
from tests.discovery.test_compilers_applications import FakeCobc
from tests.discovery.test_readiness_gating import COMPLETE, FAKE, ingest, modernize, new_app

#: The one line whose mutation turns the COMPLETE tree BLOCKED (program:VANISHED).
BLOCKING_EDIT = ("CALL 'SUB'.", "CALL 'VANISHED'.")


@pytest.fixture()
def api(tmp_path: Path, monkeypatch):
    """Same harness as the readiness-gating suite: a verifying fake compiler, isolated discovery store."""
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCOVERY_COMPILER_BACKEND", "none")
    monkeypatch.setattr(ToolchainConfig, "from_environment", classmethod(lambda cls: FAKE))
    svc = DiscoveryRunService(tmp_path / "discovery")
    reset_service_for_tests(svc)
    yield TestClient(app)
    svc.shutdown()
    reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


def _make_run_for(api_client: TestClient, app_id: str) -> tuple[str, Path]:
    """Ingest COMPLETE, start a modernize with the worker no-oped, return ``(run_id, source_workspace)``."""
    assert ingest(api_client, app_id, COMPLETE).status_code == 201
    started = modernize(api_client, app_id)
    assert started.status_code == 202, started.text
    workspace = Path(_svc().get_application(app_id).cobol_source_path)
    assert workspace.is_dir()
    return started.json()["run_id"], workspace


def test_the_modernize_worker_fails_a_run_whose_source_tree_is_gone(api: TestClient) -> None:
    """Mutation: the tree the gate approved disappears before the worker runs (the F5 re-ingest race)."""
    app_id = new_app(api, "l14-gate-gone")
    run_id, workspace = _make_run_for(api, app_id)
    shutil.rmtree(workspace)

    # Generation must not be attempted for a source the gate refuses.
    with patch.object(
        Service, "_generate_application", side_effect=AssertionError("generation ran for a blocked source")
    ):
        _svc()._modernize_background(app_id, run_id, False)

    run = _svc().get_run(run_id)
    assert run.stage == RunStage.FAILED
    assert run.generated_app_path is None
    error = run.error or ""
    assert "blocked until discovery is complete" in error
    assert "source directory no longer exists" in error

    # e2e: the API serves the same refusal, not an internal error.
    body = api.get(f"/runs/{run_id}").json()
    assert body["stage"] == "FAILED"
    assert "blocked until discovery is complete" in body["error"]


def test_the_modernize_worker_refuses_a_tree_that_became_blocked_after_the_gate(api: TestClient) -> None:
    """Mutation: an unresolved CALL appears after the entry gate passed; the worker must refuse by name."""
    app_id = new_app(api, "l14-gate-mutated")
    run_id, workspace = _make_run_for(api, app_id)
    (workspace / "src/MAIN.cbl").write_text(
        COMPLETE["src/MAIN.cbl"].replace(*BLOCKING_EDIT), encoding="utf-8"
    )

    with patch.object(
        Service, "_generate_application", side_effect=AssertionError("generation ran for a blocked source")
    ):
        _svc()._modernize_background(app_id, run_id, False)

    run = _svc().get_run(run_id)
    assert run.stage == RunStage.FAILED
    assert run.generated_app_path is None
    error = run.error or ""
    assert "blocked until discovery is complete" in error
    assert "program:VANISHED" in error


def test_the_revalidate_worker_refuses_a_tree_that_became_blocked(api: TestClient, tmp_path: Path) -> None:
    """The revalidation worker carries the same gate: no re-validation of a tree discovery blocks."""
    app_id = new_app(api, "l14-revalidate-gate")
    assert ingest(api, app_id, COMPLETE).status_code == 201
    svc = _svc()
    source = Path(svc.get_application(app_id).cobol_source_path)

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "Main.java").write_text("class Main {}", encoding="utf-8")
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    svc._store.add_run(
        RunRecord(
            id=run_id,
            application_id=app_id,
            workload_id="wl-l14",
            stage=RunStage.FAILED,
            source_path=str(source),
            generated_app_path=str(bundle),
            generated_entrypoint="Main",
        )
    )

    (source / "src/MAIN.cbl").write_text(
        COMPLETE["src/MAIN.cbl"].replace(*BLOCKING_EDIT), encoding="utf-8"
    )

    with patch.object(
        Service, "_run_validation", side_effect=AssertionError("validation ran for a blocked source")
    ):
        svc._revalidate_background(run_id)

    run = svc.get_run(run_id)
    assert run.stage == RunStage.FAILED
    error = run.error or ""
    assert "blocked until discovery is complete" in error
    assert "program:VANISHED" in error

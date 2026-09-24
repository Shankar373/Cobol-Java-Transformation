"""Focused API tests for the control-plane endpoints.

Strategy:
  - Unit tests mock the service layer to exercise HTTP boundary only.
  - Mocked pipeline tests verify API behavior without Docker overhead.
"""

from __future__ import annotations

import io
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.models import RunStage
from api.service import Service, ServiceError
from api.store import ApplicationRecord, RunRecord, Store


client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       PROCEDURE DIVISION.
       DISPLAY "HELLO".
       STOP RUN.
"""


def _mock_generate(self_svc, app, run):
    """Fast mock: set real stages, return a fake generated dir."""
    run.stage = RunStage.DISCOVERING
    run.stage = RunStage.DISCOVERY_COMPLETED
    run.stage = RunStage.TRANSFORMING
    run.stage = RunStage.GENERATING
    app.generated_app_path = "/tmp/mock-generated"
    app.generated_entrypoint = "com.example.Main"
    app.java_candidate_path = "/tmp/mock-generated"
    self_svc._store.update_application(app)
    return Path("/tmp/mock-generated"), "com.example.Main"


class _StubVerdict:
    """Picklable verdict double.

    The SQLite store persists verdicts as blobs, so doubles must be
    serializable like the real engine Verdict (a plain dataclass).
    """

    def __init__(self, run_id: str, workload_id: str) -> None:
        self._run_id = run_id
        self._workload_id = workload_id

    def to_dict(self) -> dict:
        return {
            "run_id": f"engine-{self._run_id}",
            "state": "UNPROVEN",
            "workload_id": self._workload_id,
            "source_hash": "mock-source-hash",
            "candidate_hash": "mock-candidate-hash",
            "oracle_id": "mock-oracle",
            "oracle_digest": "mock-digest",
            "executed_check_count": 0,
            "skipped_count": 0,
            "unavailable_count": 0,
            "supported_scope_statement": "mock scope",
            "evidence_manifest_hash": "mock-manifest-hash",
            "derivation_timestamp": "2024-01-01T00:00:00Z",
            "differences": [],
        }


def _mock_validation(self_svc, app, run, java_dir, entrypoint, adapter=None):
    """Fast mock: set evidence stage and persist a mock verdict."""
    run.stage = RunStage.VALIDATING_EVIDENCE
    run.verdict = _StubVerdict(run.id, run.workload_id)


@pytest.fixture()
def fresh_service():
    """Reset module-level singletons for isolation."""
    import api.app as app_mod
    import api.service as svc_mod

    store = Store()
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    svc_mod._store = store
    svc_mod._service = svc
    return svc


@pytest.fixture()
def sample_cobol_bytes():
    return SAMPLE_COBOL.encode("utf-8")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, fresh_service):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /applications
# ---------------------------------------------------------------------------

class TestCreateApplication:
    def test_create_returns_201(self, fresh_service):
        resp = client.post("/applications", json={
            "name": "test-app",
            "workload_id": "wl-test",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "test-app"
        assert body["workload_id"] == "wl-test"
        assert body["id"].startswith("app-")
        assert body["java_entrypoint"] == "Main"

    def test_create_with_description(self, fresh_service):
        resp = client.post("/applications", json={
            "name": "desc-app",
            "workload_id": "wl-desc",
            "description": "A test application",
        })
        assert resp.status_code == 201
        assert resp.json()["description"] == "A test application"

    def test_create_empty_name_fails(self, fresh_service):
        resp = client.post("/applications", json={
            "name": "",
            "workload_id": "wl-x",
        })
        assert resp.status_code == 422

    def test_create_missing_workload_id_fails(self, fresh_service):
        resp = client.post("/applications", json={
            "name": "no-wl",
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /applications/{id}/upload
# ---------------------------------------------------------------------------

class TestUploadSource:
    def test_upload_returns_201(self, fresh_service):
        app_resp = client.post("/applications", json={
            "name": "upload-test",
            "workload_id": "wl-upload",
        })
        app_id = app_resp.json()["id"]

        resp = client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("TEST.cob", io.BytesIO(SAMPLE_COBOL.encode()), "text/plain"))],
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["application_id"] == app_id
        assert body["files_received"] == 1

    def test_upload_unknown_app_returns_404(self, fresh_service):
        resp = client.post(
            "/applications/app-nonexistent/upload",
            files=[("files", ("X.cob", io.BytesIO(b"DATA"), "text/plain"))],
        )
        assert resp.status_code == 404

    def test_upload_multiple_files(self, fresh_service):
        app_resp = client.post("/applications", json={
            "name": "multi",
            "workload_id": "wl-multi",
        })
        app_id = app_resp.json()["id"]

        resp = client.post(
            f"/applications/{app_id}/upload",
            files=[
                ("files", ("A.cob", io.BytesIO(b"A"), "text/plain")),
                ("files", ("B.cob", io.BytesIO(b"B"), "text/plain")),
            ],
        )
        assert resp.status_code == 201
        assert resp.json()["files_received"] == 2


# ---------------------------------------------------------------------------
# POST /applications/{id}/modernize
# ---------------------------------------------------------------------------

class TestModernize:
    def test_modernize_unknown_app_returns_400(self, fresh_service):
        resp = client.post("/applications/app-nope/modernize")
        assert resp.status_code == 400

    def test_modernize_no_upload_returns_400(self, fresh_service):
        app_resp = client.post("/applications", json={
            "name": "no-upload",
            "workload_id": "wl-noup",
        })
        app_id = app_resp.json()["id"]

        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 400
        assert "No COBOL source" in resp.json()["detail"]

    def test_modernize_with_source_returns_202(self, fresh_service, sample_cobol_bytes):
        app_resp = client.post("/applications", json={
            "name": "mod-test",
            "workload_id": "wl-mod",
        })
        app_id = app_resp.json()["id"]

        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("MOD.cob", io.BytesIO(sample_cobol_bytes), "text/plain"))],
        )

        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 202
        body = resp.json()
        assert body["run_id"].startswith("run-")
        assert body["application_id"] == app_id
        # Immediate response returns CREATED — background thread advances stages
        assert body["stage"] == "CREATED"


# ---------------------------------------------------------------------------
# GET /runs/{id}
# ---------------------------------------------------------------------------

class TestGetRun:
    def test_get_run_not_found(self, fresh_service):
        resp = client.get("/runs/run-nonexistent")
        assert resp.status_code == 404

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_get_run_after_modernize(self, fresh_service, sample_cobol_bytes):
        app_resp = client.post("/applications", json={
            "name": "run-test",
            "workload_id": "wl-run",
        })
        app_id = app_resp.json()["id"]

        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("R.cob", io.BytesIO(sample_cobol_bytes), "text/plain"))],
        )

        mod_resp = client.post(f"/applications/{app_id}/modernize")
        run_id = mod_resp.json()["run_id"]

        # Poll until background worker completes
        for _ in range(30):
            resp = client.get(f"/runs/{run_id}")
            body = resp.json()
            if body["stage"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.3)

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == run_id
        assert body["application_id"] == app_id
        assert body["stage"] in ("COMPLETED", "FAILED")


# ---------------------------------------------------------------------------
# GET /runs/{id}/artifacts
# ---------------------------------------------------------------------------

class TestGetArtifacts:
    def test_artifacts_not_found(self, fresh_service):
        resp = client.get("/runs/run-ghost/artifacts")
        assert resp.status_code == 404

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_artifacts_after_modernize(self, fresh_service, sample_cobol_bytes):
        app_resp = client.post("/applications", json={
            "name": "art-test",
            "workload_id": "wl-art",
        })
        app_id = app_resp.json()["id"]

        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("A.cob", io.BytesIO(sample_cobol_bytes), "text/plain"))],
        )

        mod_resp = client.post(f"/applications/{app_id}/modernize")
        run_id = mod_resp.json()["run_id"]

        # Wait for background modernization to complete
        for _ in range(30):
            run_resp = client.get(f"/runs/{run_id}")
            if run_resp.json()["stage"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.3)

        resp = client.get(f"/runs/{run_id}/artifacts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == run_id
        assert isinstance(body["artifacts"], list)


# ---------------------------------------------------------------------------
# GET /runs/{id}/verdict
# ---------------------------------------------------------------------------

class TestGetVerdict:
    def test_verdict_not_found(self, fresh_service):
        resp = client.get("/runs/run-ghost/verdict")
        assert resp.status_code == 404

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_verdict_after_modernize(self, fresh_service, sample_cobol_bytes):
        app_resp = client.post("/applications", json={
            "name": "verdict-test",
            "workload_id": "wl-verd",
        })
        app_id = app_resp.json()["id"]

        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("V.cob", io.BytesIO(sample_cobol_bytes), "text/plain"))],
        )

        mod_resp = client.post(f"/applications/{app_id}/modernize")
        run_id = mod_resp.json()["run_id"]

        # Wait for background modernization to complete
        for _ in range(30):
            run_resp = client.get(f"/runs/{run_id}")
            if run_resp.json()["stage"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.3)

        resp = client.get(f"/runs/{run_id}/verdict")
        assert resp.status_code == 200
        body = resp.json()
        # The verdict's run_id is the API run-record ID so verdicts
        # correlate with GET /runs/{id} polling; the engine's internal
        # pipeline run ID (when different) is exposed as engine_run_id.
        assert body["run_id"] == run_id
        assert body["state"] in (
            "VERIFIED", "PARTIAL", "FAILED", "UNPROVEN",
            "UNAVAILABLE", "UNSUPPORTED", "ERROR",
        )
        assert "executed_check_count" in body


# ---------------------------------------------------------------------------
# POST /runs/{id}/validate
# ---------------------------------------------------------------------------

class TestValidateRun:
    def test_validate_not_found(self, fresh_service):
        resp = client.post("/runs/run-ghost/validate")
        assert resp.status_code == 400

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_validate_after_modernize(self, fresh_service, sample_cobol_bytes):
        app_resp = client.post("/applications", json={
            "name": "val-test",
            "workload_id": "wl-val",
        })
        app_id = app_resp.json()["id"]

        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("V.cob", io.BytesIO(sample_cobol_bytes), "text/plain"))],
        )

        mod_resp = client.post(f"/applications/{app_id}/modernize")
        run_id = mod_resp.json()["run_id"]

        # Wait for background modernization to complete
        for _ in range(30):
            run_resp = client.get(f"/runs/{run_id}")
            if run_resp.json()["stage"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.3)

        resp = client.post(f"/runs/{run_id}/validate")
        assert resp.status_code == 202
        body = resp.json()
        assert body["run_id"] == run_id
        # Revalidation is asynchronous (same mechanism as modernize):
        # the response shows the stage at call time; poll to terminal.
        assert body["stage"] in (
            "CREATED", "EXECUTING_ORACLE", "BUILDING",
            "EXECUTING_GENERATED", "COMPARING", "VALIDATING_EVIDENCE",
            "COMPLETED", "FAILED",
        )
        for _ in range(30):
            run_resp = client.get(f"/runs/{run_id}")
            if run_resp.json()["stage"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.3)
        assert run_resp.json()["stage"] in ("COMPLETED", "FAILED")


# ---------------------------------------------------------------------------
# Full lifecycle (happy path)
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_create_upload_modernize_verdict(self, fresh_service, sample_cobol_bytes):
        # 1. Create application
        app_resp = client.post("/applications", json={
            "name": "lifecycle",
            "workload_id": "wl-lifecycle",
        })
        assert app_resp.status_code == 201
        app_id = app_resp.json()["id"]

        # 2. Upload COBOL source
        upload_resp = client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("MAIN.cob", io.BytesIO(sample_cobol_bytes), "text/plain"))],
        )
        assert upload_resp.status_code == 201

        # 3. Modernize (returns immediately with CREATED)
        mod_resp = client.post(f"/applications/{app_id}/modernize")
        assert mod_resp.status_code == 202
        run_id = mod_resp.json()["run_id"]
        assert mod_resp.json()["stage"] == "CREATED"

        # 4. Poll until terminal stage
        for _ in range(30):
            run_resp = client.get(f"/runs/{run_id}")
            if run_resp.json()["stage"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.3)

        assert run_resp.status_code == 200
        assert run_resp.json()["stage"] in ("COMPLETED", "FAILED")

        # 5. Get artifacts
        art_resp = client.get(f"/runs/{run_id}/artifacts")
        assert art_resp.status_code == 200

        # 6. Get verdict
        verd_resp = client.get(f"/runs/{run_id}/verdict")
        assert verd_resp.status_code == 200
        assert "state" in verd_resp.json()

        # 7. Re-validate
        val_resp = client.post(f"/runs/{run_id}/validate")
        assert val_resp.status_code == 202

"""Direct-upload resource limit tests.

The upload, candidate and ingest endpoints accept untrusted multipart bodies.
These tests pin the declared bounds and prove each failure path returns an
explicit 413 (not a silent accept, hang, or unbounded read).
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

import api.app as app_mod
import api.service as svc_mod
from api.app import app
from api.service import Service, ServiceError, UploadLimitError, enforce_upload_limits
from api.store import Store

client = TestClient(app)

SAMPLE_COBOL = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       PROCEDURE DIVISION.
       DISPLAY "HELLO".
       STOP RUN.
"""


@pytest.fixture()
def fresh_service():
    """Reset module-level singletons for isolation."""
    store = Store()
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    svc_mod._store = store
    svc_mod._service = svc
    return svc


@pytest.fixture()
def app_id(fresh_service):
    resp = client.post("/applications", json={
        "name": "upload-limits",
        "workload_id": "wl-upload-limits",
    })
    assert resp.status_code == 201
    return resp.json()["id"]


def _files(count: int, payload: bytes = b"DISPLAY 1\n"):
    return [("files", (f"F{i}.cob", io.BytesIO(payload), "text/plain"))
            for i in range(count)]


class TestFileCountLimit:
    def test_too_many_files_returns_413(self, app_id, monkeypatch):
        monkeypatch.setattr(app_mod, "MAX_UPLOAD_FILES", 3)
        resp = client.post(f"/applications/{app_id}/upload", files=_files(4))
        assert resp.status_code == 413
        assert "Too many files" in resp.json()["detail"]

    def test_candidate_endpoint_enforces_file_count(self, app_id, monkeypatch):
        monkeypatch.setattr(app_mod, "MAX_UPLOAD_FILES", 3)
        resp = client.post(f"/applications/{app_id}/candidate", files=_files(4))
        assert resp.status_code == 413
        assert "Too many files" in resp.json()["detail"]

    def test_default_bound_is_declared(self):
        assert app_mod.MAX_UPLOAD_FILES == 100
        assert app_mod.MAX_UPLOAD_FILE_BYTES == 50 * 1024 * 1024
        assert app_mod.MAX_UPLOAD_TOTAL_BYTES == 100 * 1024 * 1024


class TestFileSizeLimit:
    def test_oversized_file_returns_413(self, app_id, monkeypatch):
        monkeypatch.setattr(app_mod, "MAX_UPLOAD_FILE_BYTES", 8)
        resp = client.post(
            f"/applications/{app_id}/upload",
            files=_files(1, b"x" * 64),
        )
        assert resp.status_code == 413
        assert "exceeds maximum size" in resp.json()["detail"]

    def test_oversized_candidate_file_returns_413(self, app_id, monkeypatch):
        monkeypatch.setattr(app_mod, "MAX_UPLOAD_FILE_BYTES", 8)
        resp = client.post(
            f"/applications/{app_id}/candidate",
            files=_files(1, b"x" * 64),
        )
        assert resp.status_code == 413
        assert "exceeds maximum size" in resp.json()["detail"]

    def test_file_exactly_at_limit_is_accepted(self, app_id, monkeypatch):
        monkeypatch.setattr(app_mod, "MAX_UPLOAD_FILE_BYTES", 8)
        resp = client.post(f"/applications/{app_id}/upload", files=_files(1, b"12345678"))
        assert resp.status_code == 201


class TestTotalSizeLimit:
    def test_total_across_files_returns_413(self, app_id, monkeypatch):
        monkeypatch.setattr(app_mod, "MAX_UPLOAD_TOTAL_BYTES", 10)
        resp = client.post(
            f"/applications/{app_id}/upload",
            files=_files(4, b"01234567890123456789"),
        )
        assert resp.status_code == 413
        assert "Total upload size" in resp.json()["detail"]

    def test_total_under_limit_is_accepted(self, app_id, monkeypatch):
        monkeypatch.setattr(app_mod, "MAX_UPLOAD_TOTAL_BYTES", 100)
        resp = client.post(
            f"/applications/{app_id}/upload",
            files=_files(3, b"0123456789"),
        )
        assert resp.status_code == 201
        assert resp.json()["files_received"] == 3


class TestIngestArchiveLimit:
    def test_oversized_zip_body_returns_413(self, app_id, monkeypatch):
        monkeypatch.setattr(app_mod, "MAX_ZIP_ARCHIVE_BYTES", 16)
        resp = client.post(
            f"/applications/{app_id}/ingest",
            files=[("file", ("src.zip", io.BytesIO(b"z" * 4096), "application/zip"))],
        )
        assert resp.status_code == 413
        assert "exceeds maximum size" in resp.json()["detail"]


class TestServiceLayerDefenseInDepth:
    """The service layer enforces the same bounds independently of HTTP."""

    def test_oversized_file_rejected(self, monkeypatch):
        monkeypatch.setattr(svc_mod, "MAX_UPLOAD_FILE_BYTES", 8)
        store = Store()
        svc = Service(store)
        rec = svc.create_application("svc-limits", "", "wl-svc", "Main")
        with pytest.raises(UploadLimitError):
            svc.upload_cobol_source(rec.id, {"BIG.cob": b"x" * 64})

    def test_too_many_files_rejected(self, monkeypatch):
        monkeypatch.setattr(svc_mod, "MAX_UPLOAD_FILES", 2)
        store = Store()
        svc = Service(store)
        rec = svc.create_application("svc-count", "", "wl-svc2", "Main")
        with pytest.raises(UploadLimitError):
            svc.upload_java_candidate(
                rec.id, {f"M{i}.java": b"class A {}" for i in range(3)}
            )

    def test_total_size_rejected(self, monkeypatch):
        monkeypatch.setattr(svc_mod, "MAX_UPLOAD_TOTAL_BYTES", 10)
        store = Store()
        svc = Service(store)
        rec = svc.create_application("svc-total", "", "wl-svc3", "Main")
        with pytest.raises(UploadLimitError):
            svc.upload_cobol_source(
                rec.id, {f"F{i}.cob": b"01234567890123456789" for i in range(3)}
            )

    def test_limit_error_is_a_service_error(self):
        assert issubclass(UploadLimitError, ServiceError)

    def test_enforce_upload_limits_allows_valid_upload(self):
        enforce_upload_limits({"A.cob": b"DISPLAY 1"})

    def test_unknown_app_still_returns_404(self):
        resp = client.post(
            "/applications/app-nonexistent/upload",
            files=[("files", ("X.cob", io.BytesIO(b"DATA"), "text/plain"))],
        )
        assert resp.status_code == 404

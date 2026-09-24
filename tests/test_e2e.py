"""Real E2E integration test: ARITH workload through API -> engine -> verdict.

Tests the complete path:
  API application creation
  -> COBOL source upload
  -> Java candidate upload
  -> modernization pipeline
  -> real engine execution (oracle + candidate)
  -> real evidence manifest
  -> real verdict derivation
  -> API response with authoritative VERIFIED result

Uses the known VERIFIED ARITH workload with pre-existing Java candidate.
No mocks. No fake results. Real engine execution only.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.service import Service
from api.store import Store

client = TestClient(app)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "workload-arithmetic"
COBOL_SOURCE = FIXTURES / "cobol" / "ARITH.cob"
JAVA_CANDIDATE = FIXTURES / "java-candidate" / "Arithmetic.java"


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset module-level singletons for test isolation."""
    import api.app as app_mod
    import api.service as svc_mod

    store = Store()
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    svc_mod._store = store
    svc_mod._service = svc
    yield


# ---------------------------------------------------------------------------
# Real E2E: ARITH VERIFIED path
# ---------------------------------------------------------------------------

class TestArithRealE2E:
    """Full real E2E: upload COBOL + Java candidate, validate, get VERIFIED."""

    def test_arith_verified_through_api(self):
        # 1. Create application
        resp = client.post("/applications", json={
            "name": "arith-real",
            "workload_id": "arith",
            "java_entrypoint": "Arithmetic",
        })
        assert resp.status_code == 201
        app_id = resp.json()["id"]

        # 2. Upload COBOL source
        cobol_bytes = COBOL_SOURCE.read_bytes()
        resp = client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("ARITH.cob", io.BytesIO(cobol_bytes), "text/plain"))],
        )
        assert resp.status_code == 201
        assert resp.json()["files_received"] == 1

        # 3. Upload Java candidate (the known-good Arithmetic.java)
        java_bytes = JAVA_CANDIDATE.read_bytes()
        resp = client.post(
            f"/applications/{app_id}/candidate",
            files=[("files", ("Arithmetic.java", io.BytesIO(java_bytes), "text/plain"))],
        )
        assert resp.status_code == 201
        assert resp.json()["files_received"] == 1

        # 4. Start modernization (runs real pipeline)
        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]
        stage = resp.json()["stage"]
        assert stage in ("COMPLETED", "FAILED")

        # 5. Verify run status
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        run = resp.json()
        assert run["id"] == run_id
        assert run["stage"] == "COMPLETED", f"Run failed: {run.get('error')}"

        # 6. Get artifacts - must have real artifacts from engine
        resp = client.get(f"/runs/{run_id}/artifacts")
        assert resp.status_code == 200
        artifacts = resp.json()["artifacts"]
        assert len(artifacts) >= 4, f"Expected >=4 artifacts, got {len(artifacts)}"

        oracle_stdout = [a for a in artifacts if a["producer_role"] == "ORACLE" and a["artifact_type"] == "STDOUT"]
        candidate_stdout = [a for a in artifacts if a["producer_role"] == "CANDIDATE" and a["artifact_type"] == "STDOUT"]
        assert len(oracle_stdout) == 1, "Missing ORACLE stdout"
        assert len(candidate_stdout) == 1, "Missing CANDIDATE stdout"
        assert oracle_stdout[0]["size_bytes"] > 0, "Oracle stdout is empty"
        assert candidate_stdout[0]["size_bytes"] > 0, "Candidate stdout is empty"

        # 7. Get verdict - must be VERIFIED
        resp = client.get(f"/runs/{run_id}/verdict")
        assert resp.status_code == 200
        verdict = resp.json()
        assert verdict["state"] == "VERIFIED", (
            f"Expected VERIFIED, got {verdict['state']}. "
            f"Differences: {verdict.get('differences', [])}"
        )
        assert verdict["executed_check_count"] >= 2
        assert verdict["workload_id"] == "arith"
        assert verdict["oracle_id"] == "gnucobol-3.1.2"
        assert verdict["evidence_manifest_hash"].startswith("sha256:")

        # 8. Verify comparisons are all MATCH
        comparisons = verdict.get("comparisons", [])
        assert len(comparisons) >= 2
        for comp in comparisons:
            assert comp["result"] == "MATCH", (
                f"Comparison {comp['comparator_id']} failed: {comp['result']}"
            )

    def test_arith_candidate_upload_auto_entrypoint(self):
        """Verify entrypoint is auto-detected from uploaded Java file."""
        resp = client.post("/applications", json={
            "name": "arith-auto",
            "workload_id": "arith",
        })
        app_id = resp.json()["id"]

        cobol_bytes = COBOL_SOURCE.read_bytes()
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("ARITH.cob", io.BytesIO(cobol_bytes), "text/plain"))],
        )

        java_bytes = JAVA_CANDIDATE.read_bytes()
        client.post(
            f"/applications/{app_id}/candidate",
            files=[("files", ("Arithmetic.java", io.BytesIO(java_bytes), "text/plain"))],
        )

        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        resp = client.get(f"/runs/{run_id}/verdict")
        assert resp.status_code == 200
        assert resp.json()["state"] == "VERIFIED"


# ---------------------------------------------------------------------------
# Real E2E: transformation path (untrusted output)
# ---------------------------------------------------------------------------

class TestTransformRealE2E:
    """Transformation path: COBOL -> Java via engine -> validate.

    The TransformationProducer output for ARITH lacks field declarations
    and produces different output format. The pipeline will produce a
    non-VERIFIED verdict. This tests that the real engine runs and
    returns an honest verdict.
    """

    def test_transform_produces_real_verdict(self):
        resp = client.post("/applications", json={
            "name": "arith-transform",
            "workload_id": "arith",
            "java_entrypoint": "Arithmetic",
        })
        app_id = resp.json()["id"]

        cobol_bytes = COBOL_SOURCE.read_bytes()
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("ARITH.cob", io.BytesIO(cobol_bytes), "text/plain"))],
        )

        # No candidate upload -> engine transforms COBOL to Java
        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        resp = client.get(f"/runs/{run_id}")
        run = resp.json()

        # The run must complete (may be FAILED due to transform output)
        assert run["stage"] in ("COMPLETED", "FAILED")

        # Get verdict - whatever the real engine produces
        resp = client.get(f"/runs/{run_id}/verdict")
        assert resp.status_code == 200
        verdict = resp.json()
        # Verdict must be one of the 7 valid states
        assert verdict["state"] in (
            "VERIFIED", "PARTIAL", "FAILED", "UNPROVEN",
            "UNAVAILABLE", "UNSUPPORTED", "ERROR",
        )


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    """Verify error handling for missing/invalid inputs."""

    def test_missing_candidate_upload(self):
        resp = client.post("/applications", json={
            "name": "no-candidate",
            "workload_id": "wl-nc",
        })
        app_id = resp.json()["id"]

        # Upload COBOL but no candidate
        cobol_bytes = COBOL_SOURCE.read_bytes()
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("ARITH.cob", io.BytesIO(cobol_bytes), "text/plain"))],
        )

        # Modernize should still work (uses transformation)
        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 202

    def test_no_cobol_source_fails(self):
        resp = client.post("/applications", json={
            "name": "no-source",
            "workload_id": "wl-ns",
        })
        app_id = resp.json()["id"]

        # Modernize without uploading source
        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 400

    def test_unknown_run_verdict(self):
        resp = client.get("/runs/run-nonexistent/verdict")
        assert resp.status_code == 404

    def test_unknown_app_candidate_upload(self):
        resp = client.post(
            "/applications/app-nonexistent/candidate",
            files=[("files", ("X.java", io.BytesIO(b"class X{}"), "text/plain"))],
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Polling / run lifecycle
# ---------------------------------------------------------------------------

class TestRunLifecycle:
    """Verify run stages transition correctly."""

    def test_run_completes_with_all_stages(self):
        resp = client.post("/applications", json={
            "name": "lifecycle",
            "workload_id": "wl-lc",
        })
        app_id = resp.json()["id"]

        cobol_bytes = COBOL_SOURCE.read_bytes()
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("ARITH.cob", io.BytesIO(cobol_bytes), "text/plain"))],
        )

        java_bytes = JAVA_CANDIDATE.read_bytes()
        client.post(
            f"/applications/{app_id}/candidate",
            files=[("files", ("Arithmetic.java", io.BytesIO(java_bytes), "text/plain"))],
        )

        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        # Run must be completed
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        run = resp.json()
        assert run["stage"] == "COMPLETED"
        assert run["completed_at"] is not None
        assert run["error"] is None

    def test_verdict_rendering_fields(self):
        """Verify all verdict fields needed by the UI are present."""
        resp = client.post("/applications", json={
            "name": "render",
            "workload_id": "wl-r",
        })
        app_id = resp.json()["id"]

        cobol_bytes = COBOL_SOURCE.read_bytes()
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("ARITH.cob", io.BytesIO(cobol_bytes), "text/plain"))],
        )
        java_bytes = JAVA_CANDIDATE.read_bytes()
        client.post(
            f"/applications/{app_id}/candidate",
            files=[("files", ("Arithmetic.java", io.BytesIO(java_bytes), "text/plain"))],
        )

        resp = client.post(f"/applications/{app_id}/modernize")
        run_id = resp.json()["run_id"]

        resp = client.get(f"/runs/{run_id}/verdict")
        v = resp.json()

        # All fields required by frontend VerdictDisplay
        required_fields = [
            "run_id", "state", "workload_id", "source_hash",
            "oracle_id", "oracle_digest",
            "executed_check_count", "skipped_count", "unavailable_count",
            "supported_scope_statement", "evidence_manifest_hash",
            "derivation_timestamp", "differences", "comparisons",
        ]
        for field in required_fields:
            assert field in v, f"Missing verdict field: {field}"

        # Each comparison has required fields
        for comp in v["comparisons"]:
            assert "comparison_id" in comp
            assert "comparator_id" in comp
            assert "artifact_type" in comp
            assert "result" in comp
            assert "differences" in comp


# ---------------------------------------------------------------------------
# ZIP ingestion E2E
# ---------------------------------------------------------------------------

class TestZipIngestionE2E:
    """ZIP-based ingestion: create app -> upload ZIP -> ingest -> discover -> modernize."""

    def _make_arith_zip(self) -> bytes:
        """Create a ZIP archive from the ARITH COBOL source fixture."""
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("ARITH.cob", COBOL_SOURCE.read_text(encoding="utf-8"))
        return buf.getvalue()

    def test_ingest_zip_discovery(self):
        """Upload ZIP, run discovery, verify structure."""
        resp = client.post("/applications", json={
            "name": "arith-zip",
            "workload_id": "arith-zip",
        })
        app_id = resp.json()["id"]

        zip_bytes = self._make_arith_zip()
        resp = client.post(
            f"/applications/{app_id}/ingest",
            files=[("file", ("arith.zip", io.BytesIO(zip_bytes), "application/zip"))],
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["application_id"] == app_id
        assert data["source_file_count"] >= 1
        assert data["total_size_bytes"] > 0

        # Discovery endpoint should return same data
        resp = client.get(f"/applications/{app_id}/discovery")
        assert resp.status_code == 200
        disc = resp.json()
        assert disc["application_id"] == app_id

    def test_ingest_zip_then_modernize(self):
        """Full ZIP ingestion pipeline: ingest -> modernize -> verdict."""
        resp = client.post("/applications", json={
            "name": "arith-zip-mod",
            "workload_id": "arith",
            "java_entrypoint": "Arithmetic",
        })
        app_id = resp.json()["id"]

        zip_bytes = self._make_arith_zip()
        resp = client.post(
            f"/applications/{app_id}/ingest",
            files=[("file", ("arith.zip", io.BytesIO(zip_bytes), "application/zip"))],
        )
        assert resp.status_code == 201

        # Modernize (uses transformation, not uploaded candidate)
        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        resp = client.get(f"/runs/{run_id}")
        run = resp.json()
        assert run["stage"] in ("COMPLETED", "FAILED")

        # Verdict must be valid
        resp = client.get(f"/runs/{run_id}/verdict")
        assert resp.status_code == 200
        verdict = resp.json()
        assert verdict["state"] in (
            "VERIFIED", "PARTIAL", "FAILED", "UNPROVEN",
            "UNAVAILABLE", "UNSUPPORTED", "ERROR",
        )

    def test_download_endpoint(self):
        """Download generated ZIP after modernization."""
        resp = client.post("/applications", json={
            "name": "dl-test",
            "workload_id": "dl",
            "java_entrypoint": "Arithmetic",
        })
        app_id = resp.json()["id"]

        # Upload COBOL + Java candidate so download has content
        cobol_bytes = COBOL_SOURCE.read_bytes()
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("ARITH.cob", io.BytesIO(cobol_bytes), "text/plain"))],
        )
        java_bytes = JAVA_CANDIDATE.read_bytes()
        client.post(
            f"/applications/{app_id}/candidate",
            files=[("files", ("Arithmetic.java", io.BytesIO(java_bytes), "text/plain"))],
        )

        resp = client.post(f"/applications/{app_id}/modernize")
        run_id = resp.json()["run_id"]

        resp = client.get(f"/runs/{run_id}/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert len(resp.content) > 0

        # Verify it's a valid ZIP
        import zipfile
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert any("Arithmetic" in n for n in names)

    def test_invalid_zip_rejected(self):
        """Uploading a non-ZIP file should fail with a clear error."""
        resp = client.post("/applications", json={
            "name": "bad-zip",
            "workload_id": "bz",
        })
        app_id = resp.json()["id"]

        resp = client.post(
            f"/applications/{app_id}/ingest",
            files=[("file", ("bad.zip", io.BytesIO(b"not a zip"), "application/zip"))],
        )
        assert resp.status_code == 400

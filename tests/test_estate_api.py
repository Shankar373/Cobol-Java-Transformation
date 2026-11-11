"""Roadmap unit 17: GET /applications/{id}/estate -- read-only estate graph over a real ingested workspace."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.service import Service
from api.store import Store

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
DB2_SOURCE = ROOT / "fixtures" / "workload-db2" / "cobol" / "ACCOUNT-DB2.cob"

JCL = """//ACCTJOB  JOB CLASS=A
//STEP1    EXEC PGM=ACCOUNT-DB2
//STEP2    EXEC PGM=IEFBR14
//STEP3    EXEC PGM=NOSUCH
"""


@pytest.fixture(autouse=True)
def _reset_store():
    import api.app as app_mod

    store = Store()
    app_mod._store = store
    app_mod._service = Service(store)
    yield store


def _zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return buf.getvalue()


def _ingested_app(entries: dict[str, str]) -> str:
    response = client.post("/applications", json={ "target_runtime": "spring_boot","name": "estate", "workload_id": "estate-wl"})
    assert response.status_code == 201, response.text
    app_id = response.json()["id"]
    ingest = client.post(
        f"/applications/{app_id}/ingest",
        files=[("file", ("estate.zip", io.BytesIO(_zip(entries)), "application/zip"))])
    assert ingest.status_code == 201, ingest.text
    return app_id


def test_the_estate_links_programs_jobs_steps_and_db2_tables():
    app_id = _ingested_app({
        "cobol/ACCOUNT-DB2.cob": DB2_SOURCE.read_text(encoding="utf-8"),
        "jcl/ACCTJOB.jcl": JCL,
    })
    response = client.get(f"/applications/{app_id}/estate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["application_id"] == app_id
    kinds = body["summary"]["nodes_by_kind"]
    assert kinds["PROGRAM"] == 1 and kinds["JOB"] == 1 and kinds["STEP"] == 3
    edges = {(e["source"], e["relation"], e["target"]): e for e in body["edges"]}
    assert edges[("STEP:ACCTJOB.STEP1", "EXECUTES", "PROGRAM:ACCOUNT-DB2")]["proof_state"] == "PROVEN"
    assert edges[("STEP:ACCTJOB.STEP2", "EXECUTES", "UTILITY:IEFBR14")]["proof_state"] == "PARTIAL"
    assert edges[("STEP:ACCTJOB.STEP3", "EXECUTES", "EXTERNAL_PROGRAM:NOSUCH")]["proof_state"] == "BLOCKED"
    tables = [e for e in body["edges"] if e["relation"] == "USES_DB2"]
    assert tables and all(e["source"] == "PROGRAM:ACCOUNT-DB2" for e in tables)
    assert body["summary"]["edge_count"] == len(body["edges"])
    assert "NOSUCH" in " ".join(body["summary"]["blocked_edges"])


def test_the_endpoint_is_read_only_and_repeatable():
    app_id = _ingested_app({"cobol/ACCOUNT-DB2.cob": DB2_SOURCE.read_text(encoding="utf-8")})
    first = client.get(f"/applications/{app_id}/estate").json()
    assert first == client.get(f"/applications/{app_id}/estate").json()
    assert client.post(f"/applications/{app_id}/estate").status_code == 405
    assert client.put(f"/applications/{app_id}/estate").status_code == 405
    assert client.delete(f"/applications/{app_id}/estate").status_code == 405


def test_no_workspace_and_unknown_application_are_404():
    created = client.post("/applications", json={ "target_runtime": "spring_boot","name": "empty", "workload_id": "w"})
    assert client.get(f"/applications/{created.json()['id']}/estate").status_code == 404
    assert client.get("/applications/app-ghost/estate").status_code == 404


def test_the_decomposition_proposal_is_read_only_and_needs_review():
    app_id = _ingested_app({
        "cobol/ACCOUNT-DB2.cob": DB2_SOURCE.read_text(encoding="utf-8"),
        "jcl/ACCTJOB.jcl": JCL,
    })
    response = client.get(f"/applications/{app_id}/decomposition")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_required"] is True and body["service_count"] == 1
    service = body["services"][0]
    assert service["programs"] == ["PROGRAM:ACCOUNT-DB2"]
    assert service["entry_steps"] == ["ACCTJOB.STEP1"]
    assert any("no code, artifact or container is generated" in n for n in body["notes"])
    assert response.json() == client.get(f"/applications/{app_id}/decomposition").json()
    assert client.post(f"/applications/{app_id}/decomposition").status_code == 405
    assert client.get("/applications/app-ghost/decomposition").status_code == 404

"""Roadmap unit 40: the job lane inside the product validation workflow (API -> modernize -> validate -> proof).

``fixtures/enterprise/payroll-batch`` is uploaded as a ZIP and modernized for the plain Java target through the real
API. The validation stage must run every generated job runner against the GnuCOBOL reference run and store the
result on the run; the integrated proof carries the JCL entry. Jobs outside the certified subset stay unproven, so
the stream as a whole is never reported as proven while one of its jobs is not.
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as app_mod
import api.service as svc_mod
from api.service import Service
from api.store import Store
from tests.integration.test_jcl_orchestrator_oracle import _needs_docker

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "enterprise" / "payroll-batch"


@pytest.fixture()
def client():
    store = Store()
    service = Service(store)
    app_mod._store = store
    app_mod._service = service
    svc_mod._store = store
    svc_mod._service = service
    return TestClient(app_mod.app), store


def _zip(root: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.writestr(path.relative_to(root).as_posix(), path.read_bytes())
    return buffer.getvalue()


def _await(client: TestClient, run_id: str, timeout: float = 900.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/runs/{run_id}").json()
        if body.get("stage") in ("COMPLETED", "FAILED"):
            return body
        assert time.monotonic() < deadline, f"run {run_id} stuck at {body.get('stage')}"
        time.sleep(3)


def test_the_validation_workflow_runs_the_job_lane(client):
    _needs_docker()
    http, store = client
    app_id = http.post("/applications", json={
        "name": "payroll-batch", "workload_id": "e2e-payroll-batch", "target_runtime": "plain_java",
        "java_entrypoint": "RPTPRT"}).json()["id"]
    resp = http.post(f"/applications/{app_id}/ingest",
                     files=[("file", ("payroll.zip", io.BytesIO(_zip(FIXTURE)), "application/zip"))])
    assert resp.status_code == 201, resp.text
    resp = http.post(f"/applications/{app_id}/modernize")
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    _await(http, run_id)

    report = store.get_run(run_id).modernization_report
    verification = {v["job"]: v for v in report["jcl_verification"]}
    assert {j: verification[j]["verdict"] for j in verification} == {
        "NIGHTLY": "VERIFIED", "RECOVER": "VERIFIED", "COPYJOB": "VERIFIED", "BADREF": "VERIFIED",
        "UNSUPP": "UNAVAILABLE"}
    assert verification["NIGHTLY"]["steps"][-1] == "JCL job NIGHTLY MAXRC=4"
    assert verification["BADREF"]["exit_status"] == 255

    # one job outside the certified subset keeps the JCL entry of the integrated proof unproven
    proof = http.get(f"/runs/{run_id}/integrated-proof")
    assert proof.status_code == 200, proof.text
    jcl = [e for e in proof.json()["proof"]["dependency_ledger"] if e["kind"] == "JCL"]
    assert jcl and all(e["proof_state"] != "PROVEN" for e in jcl)


def test_a_fully_verified_job_stream_proves_the_jcl_entry(client):
    _needs_docker()
    http, store = client
    root = FIXTURE.parent / "app-jcl-job"
    app_id = http.post("/applications", json={
        "name": "app-jcl-job", "workload_id": "e2e-app-jcl-job", "target_runtime": "plain_java",
        "java_entrypoint": "PRODUCER"}).json()["id"]
    resp = http.post(f"/applications/{app_id}/ingest",
                     files=[("file", ("app.zip", io.BytesIO(_zip(root)), "application/zip"))])
    assert resp.status_code == 201, resp.text
    run_id = http.post(f"/applications/{app_id}/modernize").json()["run_id"]
    _await(http, run_id)
    verification = store.get_run(run_id).modernization_report["jcl_verification"]
    assert [(v["job"], v["verdict"], v["exit_status"]) for v in verification] == [("SEQJOB", "VERIFIED", 4)]
    ledger = http.get(f"/runs/{run_id}/integrated-proof").json()["proof"]["dependency_ledger"]
    (jcl,) = [e for e in ledger if e["kind"] == "JCL"]
    assert jcl["proof_state"] == "PROVEN" and "not an IBM JES result" in jcl["reason"]

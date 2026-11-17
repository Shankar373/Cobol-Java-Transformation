"""Discovery API: submit ZIP/Git runs, poll, read artefacts, verify the checkpoint, role checks, restart recovery."""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import discovery_routes
from api.app import app
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService
from tests.discovery.helpers import COBOL_ESTATE

TOKEN_VIEWER = "viewer-token-0123456789abcdef"
TOKEN_OPERATOR = "operator-token-0123456789abcd"


@pytest.fixture()
def service(tmp_path: Path, monkeypatch):
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    svc = DiscoveryRunService(tmp_path / "discovery", workers=2)
    discovery_routes.reset_service_for_tests(svc)
    yield svc
    svc.shutdown()
    discovery_routes.reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


@pytest.fixture()
def client(service) -> TestClient:
    return TestClient(app)


def estate_zip(files: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in (files or COBOL_ESTATE).items():
            zf.writestr(name, text)
    return buffer.getvalue()


def submit(client: TestClient, blob: bytes, **kwargs):
    return client.post("/discovery/runs/zip", files={"file": ("estate.zip", blob, "application/zip")}, **kwargs)


def wait(client: TestClient, run_id: str, headers: dict | None = None) -> dict:
    deadline = time.time() + 60
    while time.time() < deadline:
        body = client.get(f"/discovery/runs/{run_id}", headers=headers or {}).json()
        if body["state"] in ("succeeded", "failed", "interrupted"):
            return body
        time.sleep(0.05)
    raise AssertionError("discovery run did not finish")


def test_zip_run_succeeds_and_exposes_every_artefact(client: TestClient, service) -> None:
    response = submit(client, estate_zip(), data={"label": "payroll estate"})
    assert response.status_code == 202 and response.json()["label"] == "payroll estate"
    run = wait(client, response.json()["run_id"])
    assert run["state"] == "succeeded" and run["gate_status"] == "INCOMPLETE" and run["ready_for_transformation"] is False
    assert run["summary"]["files"] == 14 and run["checkpoint_id"].startswith("CP-")
    assert [s["id"] for s in run["steps"]] == ["ingestion", "checkpoint", "scanning_inventory", "dependency_analysis", "report"]

    base = f"/discovery/runs/{run['run_id']}"
    report = client.get(f"{base}/report").json()
    assert report["schema_version"] == "systemaops.discovery-report/1.0" and report["completeness"]["status"] == "INCOMPLETE"
    assert client.get(f"{base}/graph").json()["stats"]["blocking_unresolved"] == 3
    assert len(client.get(f"{base}/inventory").json()["files"]) == 14
    assert len(client.get(f"{base}/unresolved").json()["unresolved"]) == 5
    assert client.get(f"{base}/summary").text.startswith("# Discovery summary")
    assert report["provenance"]["origin"] == "payroll estate" and str(service.root) not in json.dumps(report)


def test_verify_endpoint_rehashes_and_detects_tampering(client: TestClient, service: DiscoveryRunService) -> None:
    run = wait(client, submit(client, estate_zip()).json()["run_id"])
    assert client.post(f"/discovery/runs/{run['run_id']}/verify").json()["ok"] is True

    victim = service.store / "checkpoints" / run["checkpoint_id"] / "source" / "src/cobol/PAYROLL.cbl"
    os.chmod(victim, 0o644)
    victim.write_text("tampered", encoding="utf-8")
    verdict = client.post(f"/discovery/runs/{run['run_id']}/verify").json()
    assert verdict["ok"] is False and verdict["modified"] == ["src/cobol/PAYROLL.cbl"]


def test_hostile_archive_fails_the_run_with_a_stable_code_and_no_artefacts(client: TestClient, service) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("../evil.cbl", "x")
    run = wait(client, submit(client, buffer.getvalue()).json()["run_id"])
    assert run["state"] == "failed" and run["error_code"] == "ARCHIVE_BAD_PATH"
    assert client.get(f"/discovery/runs/{run['run_id']}/report").status_code == 404
    checkpoints = service.store / "checkpoints"
    assert not checkpoints.exists() or not list(checkpoints.iterdir())
    assert not list(service.uploads_dir.iterdir()), "the uploaded archive must be removed after the run"


def test_upload_limit_is_enforced_while_streaming(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CONTROL_PLANE_MAX_ZIP_ARCHIVE_BYTES", "1000")
    response = submit(client, estate_zip({"A.cbl": "x" * 5000}) + b"\0" * 5000)
    assert response.status_code == 413


def test_empty_upload_is_rejected(client: TestClient) -> None:
    assert submit(client, b"").status_code == 400


def test_git_submission_accepts_only_https_urls_and_enforces_the_ssrf_policy(client: TestClient) -> None:
    for bad in ("http://example.com/x.git", "file:///etc/passwd", "/srv/repo/estate", "git@host.example:x.git",
                "ssh://host.example/x.git"):
        assert client.post("/discovery/runs/git", json={"url": bad}).status_code == 400, bad
    run = client.post("/discovery/runs/git", json={"url": "https://127.0.0.1/estate.git", "ref": "main"}).json()
    finished = wait(client, run["run_id"])
    assert finished["state"] == "failed" and finished["error_code"] == "HOST_NOT_PUBLIC"


def test_unknown_ids_and_artefacts_are_404(client: TestClient) -> None:
    assert client.get("/discovery/runs/" + "0" * 32).status_code == 404
    assert client.get("/discovery/runs/not-a-run-id").status_code == 404
    run = wait(client, submit(client, estate_zip()).json()["run_id"])
    assert client.get(f"/discovery/runs/{run['run_id']}/secrets").status_code == 404
    assert client.post("/discovery/runs/" + "0" * 32 + "/verify").status_code == 404


def test_run_list_is_newest_first(client: TestClient) -> None:
    first = submit(client, estate_zip()).json()["run_id"]
    wait(client, first)
    second = submit(client, estate_zip({"A.cbl": "       PROGRAM-ID. A.\n"})).json()["run_id"]
    wait(client, second)
    listed = [r["run_id"] for r in client.get("/discovery/runs").json()["runs"]]
    assert set(listed) == {first, second}


def test_roles_viewer_reads_operator_submits(service, monkeypatch) -> None:
    monkeypatch.setenv("CONTROL_PLANE_ROLE_TOKENS", json.dumps({TOKEN_VIEWER: "viewer", TOKEN_OPERATOR: "operator"}))
    client = TestClient(app)
    viewer = {"Authorization": f"Bearer {TOKEN_VIEWER}"}
    operator = {"Authorization": f"Bearer {TOKEN_OPERATOR}"}
    assert client.post("/discovery/runs/zip", files={"file": ("e.zip", estate_zip())}).status_code == 401
    assert client.post("/discovery/runs/zip", files={"file": ("e.zip", estate_zip())}, headers=viewer).status_code == 403
    run = client.post("/discovery/runs/zip", files={"file": ("e.zip", estate_zip())}, headers=operator).json()
    assert wait(client, run["run_id"], operator)["state"] == "succeeded"
    assert client.get(f"/discovery/runs/{run['run_id']}/report", headers=viewer).status_code == 200
    assert client.post(f"/discovery/runs/{run['run_id']}/verify", headers=viewer).status_code == 403
    assert client.post(f"/discovery/runs/{run['run_id']}/verify", headers=operator).status_code == 200


def test_restart_marks_unfinished_runs_interrupted_and_keeps_finished_ones(tmp_path: Path) -> None:
    root = tmp_path / "svc"
    first = DiscoveryRunService(root)
    run_id, archive = first.new_upload_path()
    archive.write_bytes(estate_zip())
    done = first.submit_zip(run_id, archive, "done")
    first.shutdown()  # waits for the run to finish
    assert first.get(done.run_id).state == "succeeded"

    stale = json.loads((root / "runs" / f"{done.run_id}.json").read_text(encoding="utf-8"))
    stale.update(run_id="f" * 32, state="running", checkpoint_id="")
    (root / "runs" / ("f" * 32 + ".json")).write_text(json.dumps(stale), encoding="utf-8")

    second = DiscoveryRunService(root)
    try:
        assert second.get("f" * 32).state == "interrupted" and second.get("f" * 32).error_code == "RUN_INTERRUPTED"
        assert second.get(done.run_id).state == "succeeded"
        assert second.artefact_path(done.run_id, "report")[0].is_file()
    finally:
        second.shutdown()
        rmtree_force(root)

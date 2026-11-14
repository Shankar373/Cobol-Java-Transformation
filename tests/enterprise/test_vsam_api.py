import time

import pytest
from fastapi.testclient import TestClient

import api.vsam_routes as vsam_routes
from api.app import app
from enterprise.jobs import JobState
from enterprise.quotas import VsamQuotas
from enterprise.vsam.jobs import VsamJobService
from tests.enterprise.vsam_support import fixed_export, ksds_records, make_manifest

client = TestClient(app)
SMALL = VsamQuotas(stream_buffer_bytes=4096)


@pytest.fixture()
def service(tmp_path):
    svc = VsamJobService(":memory:", tmp_path / "vsam", SMALL)
    previous = vsam_routes._service
    vsam_routes.configure(service=svc)
    yield svc
    svc.shutdown()
    vsam_routes._service = previous


@pytest.fixture()
def app_id():
    resp = client.post("/applications", json={"name": "vsam-app", "workload_id": "wl", "target_runtime": "plain_java"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _blob(n=30):
    return fixed_export(ksds_records(n))


def _create(app_id, blob, key="k1", **manifest_kw):
    manifest = make_manifest(blob, manifest_kw.pop("count", 30), **manifest_kw)
    return client.post(
        f"/applications/{app_id}/vsam/migrations",
        json={"idempotency_key": key, "runtime_path": "ks.dat",
              "manifest": manifest.model_dump(mode="json")},
    )


def _wait(job_id, want=("SUCCEEDED", "REFUSED", "FAILED"), timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/vsam/migrations/{job_id}").json()
        if body["state"] in want:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {body}")


def test_full_lifecycle_and_download(service, app_id):
    blob = _blob()
    created = _create(app_id, blob)
    assert created.status_code == 201
    job = created.json()
    assert job["state"] == "CREATED" and job["created"] is True
    put = client.put(job["upload_path"], content=blob)
    assert put.status_code == 202
    done = _wait(job["job_id"])
    assert done["state"] == "SUCCEEDED"
    assert done["records"] == 30 and done["bytes_processed"] == len(blob)
    download = client.get(f"/vsam/migrations/{job['job_id']}/download")
    assert download.status_code == 200
    assert download.headers["x-content-sha256"] == done["output_sha256"]
    assert download.content.decode().startswith("K4\n0001\u0001REC001\n")


def test_create_is_idempotent_and_detects_key_reuse(service, app_id):
    blob = _blob()
    first = _create(app_id, blob).json()
    again = _create(app_id, blob).json()
    assert again["job_id"] == first["job_id"] and again["created"] is False
    other = _create(app_id, fixed_export(ksds_records(5)), count=5)
    assert other.status_code == 409


def test_wrong_upload_size_keeps_job_retryable(service, app_id):
    blob = _blob()
    job = _create(app_id, blob).json()
    bad = client.put(job["upload_path"], content=blob[:-3])
    assert bad.status_code == 400
    assert client.get(f"/vsam/migrations/{job['job_id']}").json()["state"] == "CREATED"
    assert client.put(job["upload_path"], content=blob).status_code == 202
    assert _wait(job["job_id"])["state"] == "SUCCEEDED"


def test_second_upload_is_rejected(service, app_id):
    blob = _blob()
    job = _create(app_id, blob).json()
    assert client.put(job["upload_path"], content=blob).status_code == 202
    assert client.put(job["upload_path"], content=blob).status_code == 409


def test_checksum_mismatch_is_refused_and_has_no_artifact(service, app_id):
    blob = _blob()
    manifest = make_manifest(blob, 30).model_copy(update={"sha256": "0" * 64})
    job = client.post(
        f"/applications/{app_id}/vsam/migrations",
        json={"idempotency_key": "bad", "runtime_path": "ks.dat",
              "manifest": manifest.model_dump(mode="json")},
    ).json()
    client.put(job["upload_path"], content=blob)
    done = _wait(job["job_id"])
    assert done["state"] == "REFUSED" and done["error_code"] == "CHECKSUM_MISMATCH"
    assert client.get(f"/vsam/migrations/{job['job_id']}/download").status_code == 409


def test_unsupported_manifest_is_refused_at_creation(service, app_id):
    job = _create(app_id, _blob(), alternate_keys=((4, 2),)).json()
    assert job["state"] == "REFUSED" and job["error_code"] == "ALTERNATE_KEY_UNSUPPORTED"
    assert client.put(job["upload_path"], content=_blob()).status_code == 409


def test_unknown_resources_and_bad_runtime_path(service, app_id):
    blob = _blob()
    manifest = make_manifest(blob, 30).model_dump(mode="json")
    body = {"idempotency_key": "k", "runtime_path": "ks.dat", "manifest": manifest}
    assert client.post("/applications/nope/vsam/migrations", json=body).status_code == 404
    assert client.get("/vsam/migrations/" + "0" * 32).status_code == 404
    assert client.put("/vsam/migrations/" + "0" * 32 + "/data", content=b"x").status_code == 404
    body["runtime_path"] = "../escape"
    assert client.post(f"/applications/{app_id}/vsam/migrations", json=body).status_code == 400


def test_routes_require_the_api_token(service, app_id, monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")
    job = "0" * 32
    for method, path in (
        ("get", f"/vsam/migrations/{job}"),
        ("get", f"/vsam/migrations/{job}/download"),
        ("put", f"/vsam/migrations/{job}/data"),
        ("post", f"/applications/{app_id}/vsam/migrations"),
    ):
        assert getattr(client, method)(path).status_code == 401
    ok = client.get(f"/vsam/migrations/{job}", headers={"Authorization": "Bearer sekret-token"})
    assert ok.status_code == 404


def test_tampered_artifact_is_not_served(service, app_id):
    blob = _blob()
    job = _create(app_id, blob).json()
    client.put(job["upload_path"], content=blob)
    assert _wait(job["job_id"])["state"] == "SUCCEEDED"
    path = service.output_path(job["job_id"])
    path.write_bytes(path.read_bytes() + b"x")
    assert client.get(f"/vsam/migrations/{job['job_id']}/download").status_code == 500


def test_restart_recovers_interrupted_job(service, app_id):
    blob = _blob()
    job_id = _create(app_id, blob).json()["job_id"]
    # Simulate a crash after the upload landed but before the worker ran.
    service.accept_upload_slot(job_id)
    service.input_path(job_id).write_bytes(blob)
    service._transition(job_id, JobState.QUEUED)
    assert service.recover_interrupted() == 1
    assert _wait(job_id)["state"] == "SUCCEEDED"


def test_lost_input_after_restart_fails_instead_of_succeeding(service, app_id):
    blob = _blob()
    job = _create(app_id, blob).json()
    service.accept_upload_slot(job["job_id"])
    service._transition(job["job_id"], JobState.QUEUED)
    service.recover_interrupted()
    done = client.get(f"/vsam/migrations/{job['job_id']}").json()
    assert done["state"] == "FAILED" and done["error_code"] == "INPUT_LOST"


def test_application_lookup_follows_a_replaced_control_plane_service(service, monkeypatch):
    """Other suites swap ``api.app._service``; the VSAM routes must follow it."""
    import api.app as api_app
    from api.service import Service
    from api.store import Store

    monkeypatch.setattr(api_app, "_service", Service(Store(":memory:")))
    app_id = client.post("/applications", json={"name": "swapped", "workload_id": "wl", "target_runtime": "plain_java"}).json()["id"]
    resp = _create(app_id, _blob())
    assert resp.status_code == 201, resp.text

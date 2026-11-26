"""B2/B3: an ingested application is pinned to its checkpoint and blueprint, and every consumer fails closed when either moved."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import discovery_routes
from api.app import _svc, app
from enterprise.discovery.blueprint import verify_blueprint
from enterprise.discovery.checkpoint import checkpoint_dir, release
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService
from tests.discovery.helpers import COBOL_ESTATE, write_cobol_estate
from tests.discovery import test_readiness_gating as gating
from tests.discovery.test_readiness_gating import COMPLETE, ingest, modernize, new_app, zip_bytes

api = gating.api  # the ZIP/Git application fixture is shared with the gating tests


def _pin(app_id: str) -> dict:
    service = _svc()
    pin = service._store.get_pin(service.get_application(app_id).cobol_source_path)
    assert pin is not None
    return pin


def _workspace(app_id: str) -> Path:
    return Path(_svc().get_application(app_id).cobol_source_path)


def _discoveries(checkpoint_id: str) -> Path:
    return discovery_routes.get_service().store / "discoveries" / checkpoint_id


def test_ingest_pins_upload_checkpoint_and_blueprint(api: TestClient) -> None:
    app_id = new_app(api, "pin-ingest")
    blob = zip_bytes(COMPLETE)
    response = api.post(f"/applications/{app_id}/ingest", files={"file": ("estate.zip", blob, "application/zip")})
    readiness = response.json()["readiness"]
    pin = _pin(app_id)
    assert pin["origin_kind"] == "zip" and pin["origin_ref"] == hashlib.sha256(blob).hexdigest()
    assert pin["checkpoint_id"] == readiness["checkpoint_id"].strip() and pin["checkpoint_id"].startswith("CP-")
    assert pin["blueprint_id"] == readiness["blueprint_id"] and len(pin["blueprint_id"]) == 64
    assert pin["content_digest"] and pin["source_digest"] == readiness["source_digest"]


def test_application_blueprint_endpoint_serves_the_pinned_verified_document(api: TestClient) -> None:
    app_id = new_app(api, "pin-blueprint")
    ingest(api, app_id, COMPLETE)
    pin = _pin(app_id)
    response = api.get(f"/applications/{app_id}/blueprint")
    assert response.status_code == 200
    document = response.json()
    assert verify_blueprint(document) and document["blueprint_id"] == pin["blueprint_id"]
    assert document["identity"]["checkpoint_id"] == pin["checkpoint_id"]
    assert {"MAIN", "SUB"} <= {p["name"] for p in document["programs"]}
    empty = new_app(api, "pin-no-source")
    assert api.get(f"/applications/{empty}/blueprint").status_code == 404


def test_editing_the_workspace_after_ingest_fails_closed_and_refresh_does_not_heal_it(api: TestClient) -> None:
    app_id = new_app(api, "pin-edit")
    ingest(api, app_id, COMPLETE)
    target = _workspace(app_id) / "src/SUB.cbl"
    target.write_text(COMPLETE["src/SUB.cbl"] + "      * edited after ingest\n", encoding="utf-8")  # still a READY tree
    refused = modernize(api, app_id)
    assert refused.status_code == 409 and "changed after it was ingested" in refused.json()["detail"], refused.text
    api.post(f"/applications/{app_id}/readiness/refresh")
    assert modernize(api, app_id).status_code == 409
    ingest(api, app_id, COMPLETE)  # the sanctioned way to change the source: re-ingest, which pins afresh
    assert modernize(api, app_id).status_code == 202


def test_a_tampered_checkpoint_is_refused(api: TestClient) -> None:
    app_id = new_app(api, "pin-checkpoint")
    ingest(api, app_id, COMPLETE)
    checkpoint = checkpoint_dir(discovery_routes.get_service().store, _pin(app_id)["checkpoint_id"])
    release(checkpoint)
    (checkpoint / "source/src/SUB.cbl").write_text("tampered\n", encoding="utf-8")
    refused = modernize(api, app_id)
    assert refused.status_code == 409 and "checkpoint" in refused.json()["detail"].lower(), refused.text


def test_a_tampered_blueprint_is_refused(api: TestClient) -> None:
    app_id = new_app(api, "pin-blueprint-tamper")
    ingest(api, app_id, COMPLETE)
    path = _discoveries(_pin(app_id)["checkpoint_id"]) / "application-blueprint.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["estate"]["files"] += 1  # the id no longer covers the document
    path.write_text(json.dumps(document), encoding="utf-8")
    refused = modernize(api, app_id)
    assert refused.status_code == 409 and "blueprint" in refused.json()["detail"].lower(), refused.text
    assert api.get(f"/applications/{app_id}/blueprint").status_code == 409


def test_an_application_ingested_before_pins_existed_is_pinned_on_first_use(api: TestClient) -> None:
    app_id = new_app(api, "pin-legacy")
    ingest(api, app_id, COMPLETE)
    service = _svc()
    with service._store._lock:
        service._store._conn.execute("DELETE FROM source_pins")
        service._store._conn.commit()
    assert modernize(api, app_id).status_code == 202
    assert _pin(app_id)["origin_kind"] == "unpinned"
    _workspace(app_id).joinpath("src/SUB.cbl").write_text("x\n", encoding="utf-8")
    assert modernize(api, app_id).status_code == 409


@pytest.fixture()
def run_client(tmp_path: Path, monkeypatch):
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    service = DiscoveryRunService(tmp_path / "discovery", workers=1)
    discovery_routes.reset_service_for_tests(service)
    yield TestClient(app), service
    service.shutdown()
    discovery_routes.reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


def test_source_excerpt_refuses_bytes_that_no_longer_match_the_inventory(run_client, tmp_path: Path) -> None:
    http, service = run_client
    result = discover(DiscoveryRequest("directory", str(write_cobol_estate(tmp_path / "estate"))), service.store)
    run = service.register_result(result, kind="directory", label="estate")
    path = "src/cobol/PAYROLL.cbl"
    assert path in COBOL_ESTATE or True
    assert http.get(f"/discovery/runs/{run.run_id}/source", params={"path": path, "line": 1}).status_code == 200
    checkpoint = checkpoint_dir(service.store, result.checkpoint.checkpoint_id)
    release(checkpoint)
    (checkpoint / "source" / "src/cobol/PAYROLL.cbl").write_text("tampered\n", encoding="utf-8")
    response = http.get(f"/discovery/runs/{run.run_id}/source", params={"path": path, "line": 1})
    assert response.status_code == 409 and "tamper" in response.json()["detail"].lower()

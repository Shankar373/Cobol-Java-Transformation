"""B5: the application discovery view is bound to the blueprint and agrees with it on programs, copybooks and calls."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.discovery import test_readiness_gating as gating
from tests.discovery.test_readiness_gating import COMPLETE, ingest, new_app

api = gating.api  # the application fixture is shared with the gating tests


def test_discovery_response_names_the_checkpoint_and_blueprint_it_is_bound_to(api: TestClient) -> None:
    app_id = new_app(api, "parity-binding")
    ingest(api, app_id, COMPLETE)
    discovery = api.get(f"/applications/{app_id}/discovery").json()
    blueprint = api.get(f"/applications/{app_id}/blueprint").json()
    assert discovery["blueprint_id"] == blueprint["blueprint_id"] != ""
    assert discovery["checkpoint_id"] == blueprint["identity"]["checkpoint_id"].strip() != ""


def test_discovery_and_blueprint_agree_on_programs_copybooks_and_calls(api: TestClient) -> None:
    app_id = new_app(api, "parity-facts")
    ingest(api, app_id, COMPLETE)
    discovery = api.get(f"/applications/{app_id}/discovery").json()
    blueprint = api.get(f"/applications/{app_id}/blueprint").json()
    assert {p["program_id"] for p in discovery["cobol_programs"]} == {p["name"] for p in blueprint["programs"]}
    assert set(discovery["copybooks"]) == {c for p in blueprint["programs"] for c in p["copybooks"]}
    legacy_calls = {(c["caller"], c["target"]) for c in discovery["call_dependencies"]}
    blueprint_calls = {(p["name"], t) for p in blueprint["programs"] for t in p["calls"]}
    assert legacy_calls == blueprint_calls


def test_an_application_without_a_pin_reports_empty_bindings_not_a_guess(api: TestClient) -> None:
    from api.app import _svc

    app_id = new_app(api, "parity-unpinned")
    ingest(api, app_id, COMPLETE)
    service = _svc()
    with service._store._lock:
        service._store._conn.execute("DELETE FROM source_pins")
        service._store._conn.commit()
    discovery = api.get(f"/applications/{app_id}/discovery").json()
    assert discovery["blueprint_id"] == "" and discovery["checkpoint_id"] == ""

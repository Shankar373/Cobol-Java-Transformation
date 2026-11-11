"""The runtime a user selects is the runtime that is generated: no default, no substitution (hermetic)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.service import Service
from api.store import Store

client = TestClient(app)

COBOL = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       PROCEDURE DIVISION.
           DISPLAY "HELLO".
           STOP RUN.
"""
RUNTIMES = ["spring_boot", "plain_java", "quarkus", "micronaut"]


@pytest.fixture()
def service():
    import api.app as app_mod
    import api.service as svc_mod

    store = Store()
    svc = Service(store)
    app_mod._store = svc_mod._store = store
    app_mod._service = svc_mod._service = svc
    return svc


def _create(**extra):
    return client.post("/applications", json={"name": "sel", "workload_id": "wl-sel", **extra})


def test_a_request_without_a_runtime_is_rejected_not_defaulted(service):
    response = _create()
    assert response.status_code == 422, response.text
    assert "target_runtime" in response.text
    assert client.get("/applications").json() == []


@pytest.mark.parametrize("value", ["", "   ", "cobol_vm", "SPRING_BOOT", "jakarta_ee", "liberty"])
def test_an_empty_unknown_or_uncertified_runtime_is_rejected(service, value):
    response = _create(target_runtime=value)
    assert response.status_code in (400, 422), response.text
    assert client.get("/applications").json() == []


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_the_chosen_runtime_is_stored_and_returned_unchanged(service, runtime):
    created = _create(target_runtime=runtime)
    assert created.status_code == 201 and created.json()["target_runtime"] == runtime
    assert client.get(f"/applications/{created.json()['id']}").json()["target_runtime"] == runtime


def test_the_runtime_registry_lists_exactly_the_four_certified_choices(service):
    rows = client.get("/runtimes").json()
    assert sorted(r["key"] for r in rows if r["certified"]) == sorted(RUNTIMES)


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_generation_produces_the_selected_runtime_and_no_other(service, runtime, monkeypatch):
    # generation only: the capability plan must not depend on whether this host has a Docker daemon
    from engine import docker_cli

    monkeypatch.setattr(docker_cli, "docker_available_with_retry", lambda: True)
    app_id = _create(target_runtime=runtime).json()["id"]
    client.post(f"/applications/{app_id}/upload", files=[("files", ("HELLO.cob", io.BytesIO(COBOL), "text/plain"))])
    rec = service.get_application(app_id)
    from api.store import RunRecord

    run = service._store.add_run(RunRecord(id="run-sel", application_id=app_id, workload_id="wl-sel"))
    out, _entry = service._generate_application(rec, run)
    markers = {
        "spring_boot": "spring-boot",
        "quarkus": "quarkus",
        "micronaut": "micronaut",
    }
    pom = Path(out) / "pom.xml"
    text = pom.read_text(encoding="utf-8").lower() if pom.exists() else ""
    for name, marker in markers.items():
        assert (marker in text) is (name == runtime), (runtime, name)
    if runtime == "plain_java":
        assert not any(marker in text for marker in markers.values())

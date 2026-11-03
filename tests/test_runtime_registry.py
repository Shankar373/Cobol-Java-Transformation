"""Roadmap unit 1: one runtime-target registry drives engine, API and UI."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as app_mod
from api.service import Service
from api.store import Store
from engine.candidate.factory import candidate_adapter_for_target
from engine.transformation import runtime_adapters
from engine.transformation.runtime_registry import (
    CERTIFIED_RUNTIME_KEYS,
    RUNTIME_KEYS,
    RUNTIME_TARGETS,
    require_certified,
    runtime_target,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    store = Store()
    app_mod._store = store
    app_mod._service = Service(store)
    return TestClient(app_mod.app)


def test_the_certified_set_is_the_certification_matrix():
    """The registry's certified set must equal the corpus certification matrix."""
    workflow = (REPO / ".github/workflows/certification.yml").read_text(encoding="utf-8")
    matrix = re.search(r"runtime:\s*\[([^\]]*)\]", workflow)
    assert matrix, "certification matrix not found"
    assert set(re.findall(r"[a-z_]+", matrix.group(1))) == set(CERTIFIED_RUNTIME_KEYS)


def test_registry_is_the_source_of_the_engine_tables():
    assert runtime_adapters.SUPPORTED_TARGET_RUNTIMES == RUNTIME_KEYS
    assert runtime_adapters.PLAN_OUTPUT_TYPE_BY_TARGET == {
        t.key: t.plan_output_type for t in RUNTIME_TARGETS
    }
    # Every registered target has an assembly adapter and a candidate lane.
    assert set(runtime_adapters.implemented_target_runtimes()) == set(RUNTIME_KEYS)
    for key in RUNTIME_KEYS:
        assert candidate_adapter_for_target(key) is not None


def test_unknown_target_names_the_supported_set():
    with pytest.raises(ValueError, match="supported target_runtime values"):
        runtime_target("cobol_on_mars")
    with pytest.raises(ValueError, match="supported target_runtime values"):
        candidate_adapter_for_target("cobol_on_mars")


def test_jakarta_is_registered_but_not_certified():
    assert runtime_target("jakarta_ee").certified is False
    with pytest.raises(ValueError, match="not certified"):
        require_certified("jakarta_ee")
    assert require_certified("quarkus").key == "quarkus"


def test_runtimes_endpoint_lists_the_registry(client):
    body = client.get("/runtimes").json()
    assert [r["key"] for r in body] == list(RUNTIME_KEYS)
    assert {r["key"] for r in body if r["certified"]} == set(CERTIFIED_RUNTIME_KEYS)
    assert all(r["label"] and r["note"] for r in body)


@pytest.mark.parametrize("key", CERTIFIED_RUNTIME_KEYS)
def test_certified_runtimes_are_accepted_by_the_api(client, key):
    response = client.post("/applications", json={
        "name": f"rt-{key}-{uuid.uuid4().hex[:6]}", "workload_id": "wl", "target_runtime": key,
    })
    assert response.status_code == 201, response.text
    assert response.json()["target_runtime"] == key


def test_uncertified_runtime_is_rejected_by_the_api(client):
    response = client.post("/applications", json={
        "name": f"rt-jk-{uuid.uuid4().hex[:6]}", "workload_id": "wl", "target_runtime": "jakarta_ee",
    })
    assert response.status_code == 400
    assert "not certified" in response.json()["detail"]
    assert "quarkus" in response.json()["detail"]


def test_unknown_runtime_is_still_rejected_by_the_api(client):
    response = client.post("/applications", json={
        "name": f"rt-x-{uuid.uuid4().hex[:6]}", "workload_id": "wl", "target_runtime": "nope",
    })
    assert response.status_code == 400


def test_engine_can_still_generate_the_uncertified_profile():
    """Uncertified does not mean removed: the engine adapter remains."""
    adapter = runtime_adapters.get_runtime_adapter("jakarta_ee")
    assert adapter.target_runtime == "jakarta_ee"


def test_stale_pipeline_references_are_gone():
    for path in ("api/service.py", "api/models.py"):
        text = (REPO / path).read_text(encoding="utf-8")
        assert "engine.pipeline.UniversalModernizationPipeline" not in text, path
    assert Service._candidate_adapter.__doc__


def test_modernize_and_revalidate_share_the_adapter_selection():
    source = (REPO / "api/service.py").read_text(encoding="utf-8")
    assert source.count("candidate_adapter_for_target(") == 1
    assert source.count("self._candidate_adapter(") == 2


def test_node_scripts_are_pinned_to_lf():
    """A CRLF shebang breaks Node (`#!/usr/bin/env node\r`) on Windows checkouts."""
    attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "*.mjs text eol=lf" in attributes
    script = (REPO / "frontend/scripts/verify-bundle-secrets.mjs").read_bytes()
    assert script.startswith(b"#!")

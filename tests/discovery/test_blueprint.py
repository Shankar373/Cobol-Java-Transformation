"""Application Blueprint (ADR-0014): content, identity, determinism, artefact digests, scrubbing and the API."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import discovery_routes
from api.app import app
from enterprise.discovery.blueprint import BLUEPRINT_SCHEMA, blueprint_id_of, verify_blueprint
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService
from tests.discovery.helpers import COBOL_ESTATE, read_json, write_cobol_estate

SECTIONS = ("applications", "architecture", "artefacts", "build", "completeness", "entry_points", "estate", "identity", "integrations",
            "limitations", "programs", "readiness", "relationships", "resources", "unresolved")


@pytest.fixture()
def store(tmp_path: Path):
    path = tmp_path / "store"
    yield path
    rmtree_force(path)


@pytest.fixture()
def estate(tmp_path: Path) -> Path:
    return write_cobol_estate(tmp_path / "estate")


@pytest.fixture()
def result(estate: Path, store: Path):
    return discover(DiscoveryRequest("directory", str(estate)), store)


@pytest.fixture()
def blueprint(result) -> dict:
    return read_json(result.outdir / result.outputs["blueprint"])


def test_blueprint_is_published_with_every_section(result, blueprint: dict) -> None:
    assert result.outputs["blueprint"] == "application-blueprint.json"
    assert blueprint["schema_version"] == BLUEPRINT_SCHEMA
    for section in SECTIONS:
        assert section in blueprint, section


def test_identity_ties_the_blueprint_to_checkpoint_and_graph(result, blueprint: dict) -> None:
    identity = blueprint["identity"]
    graph = read_json(result.outdir / result.outputs["graph"])
    assert identity["checkpoint_id"] == result.checkpoint.checkpoint_id
    assert identity["source_digest"] == result.checkpoint.source_digest
    assert identity["graph_id"] == graph["header"]["graph_id"] == blueprint["architecture"]["graph_id"]
    assert identity["source"]["kind"] == "directory"


def test_blueprint_id_is_the_hash_of_the_rest_and_verifies(blueprint: dict) -> None:
    assert verify_blueprint(blueprint) is True
    body = {k: v for k, v in blueprint.items() if k != "blueprint_id"}
    assert blueprint["blueprint_id"] == blueprint_id_of(body)


def test_any_edit_breaks_verification(blueprint: dict) -> None:
    tampered = copy.deepcopy(blueprint)
    tampered["estate"]["files"] += 1
    assert verify_blueprint(tampered) is False
    tampered = copy.deepcopy(blueprint)
    del tampered["blueprint_id"]
    assert verify_blueprint(tampered) is False


def test_artefact_references_match_the_bytes_on_disk(result, blueprint: dict) -> None:
    assert set(blueprint["artefacts"]) == {"applications", "compatibility", "graph", "inventory", "readiness", "report", "summary",
                                           "unresolved"}
    for name, ref in blueprint["artefacts"].items():
        data = (result.outdir / ref["file"]).read_bytes()
        assert ref["file"] == result.outputs[name]
        assert ref["sha256"] == hashlib.sha256(data).hexdigest() and ref["bytes"] == len(data), name


def test_estate_inventory_matches_the_inventory_artefact(result, blueprint: dict) -> None:
    inventory = read_json(result.outdir / result.outputs["inventory"])
    assert blueprint["estate"]["files"] == len(inventory["files"]) == len(COBOL_ESTATE)
    assert blueprint["estate"]["bytes"] == sum(f["size"] for f in inventory["files"])
    assert sum(blueprint["estate"]["files_by_class"].values()) == len(inventory["files"])


def test_applications_programs_and_entry_points_come_from_the_report(result, blueprint: dict) -> None:
    report = read_json(result.outdir / result.outputs["report"])
    assert [a["id"] for a in blueprint["applications"]] == [a["id"] for a in report["applications"]["applications"]]
    assert [p["name"] for p in blueprint["programs"]] == [p["name"] for p in report["programs"]]
    assert blueprint["entry_points"] == report["applications"]["entry_points"]
    assert {"PAYROLL", "AUDITLOG"} <= {p["name"] for p in blueprint["programs"]}
    payroll = next(p for p in blueprint["programs"] if p["name"] == "PAYROLL")
    assert "AUDITLOG" in payroll["calls"] and "EMPREC" in payroll["copybooks"]
    assert all(p["profile_id"] for p in blueprint["programs"])


def test_each_application_carries_its_own_architecture_slice(blueprint: dict) -> None:
    assert blueprint["applications"]
    for app_row in blueprint["applications"]:
        arch = app_row["architecture"]
        assert arch["edges"] == sum(arch["relations"].values())
        assert app_row["files"] > 0 and set(arch) == {"dependency_kinds", "edges", "relations"}


def test_unresolved_section_agrees_with_the_unresolved_artefact(result, blueprint: dict) -> None:
    unresolved = read_json(result.outdir / result.outputs["unresolved"])
    section = blueprint["unresolved"]
    assert section["total"] == len(unresolved["unresolved"]) > 0
    assert section["ambiguous"] == len(unresolved["ambiguous"])
    assert sum(section["by_reason"].values()) == section["total"]
    assert section["blocking"] + section["non_blocking"] == section["total"]
    assert section["blocking_total"] == section["blocking"] and len(section["blocking_references"]) <= section["blocking"]
    assert any(r["to"].endswith("MISSING1") for r in section["blocking_references"])


def test_resources_and_integrations_are_summaries_with_reference_counts(blueprint: dict) -> None:
    resources, integrations = blueprint["resources"], blueprint["integrations"]
    assert set(resources) == {"datasets", "vsam", "db2"} and set(resources["db2"]) == {"plans", "stored_procedures", "tables"}
    assert set(integrations) == {"cics", "ims", "mq", "utilities"}
    for row in [*resources["datasets"], *resources["db2"]["tables"]]:
        assert {"id", "kind", "origin", "references"} <= set(row) and "referenced_by" not in row
    assert any(t["id"] == "table:HR.EMPLOYEE" or t["id"].endswith("EMPLOYEE") for t in resources["db2"]["tables"])


def test_architecture_reports_graph_statistics_and_export_formats(result, blueprint: dict) -> None:
    graph = read_json(result.outdir / result.outputs["graph"])
    arch = blueprint["architecture"]
    assert arch["stats"]["nodes"] == len(graph["nodes"]) and arch["stats"]["edges"] == len(graph["edges"])
    assert sum(arch["node_kinds"].values()) == len(graph["nodes"]) and sum(arch["relations"].values()) == len(graph["edges"])
    assert {"json", "dot", "graphml"} <= set(arch["export_formats"])


def test_readiness_and_completeness_are_the_reports(result, blueprint: dict) -> None:
    report = read_json(result.outdir / result.outputs["report"])
    assert blueprint["readiness"]["status"] == report["readiness"]["status"]
    assert blueprint["completeness"]["status"] == report["completeness"]["status"]
    assert blueprint["limitations"] == report["limitations"]


def test_blueprint_is_byte_identical_across_stores_and_reruns(tmp_path: Path, estate: Path) -> None:
    blobs = []
    for name in ("one", "two"):
        out = discover(DiscoveryRequest("directory", str(estate)), tmp_path / name)
        blobs.append((out.outdir / out.outputs["blueprint"]).read_bytes())
        rmtree_force(tmp_path / name)
    assert blobs[0] == blobs[1]


def test_blueprint_names_no_local_path(result, store: Path, estate: Path) -> None:
    text = (result.outdir / result.outputs["blueprint"]).read_text(encoding="utf-8")
    for local in (str(store), str(store.resolve()), str(estate), str(estate.resolve())):
        assert local not in text and local.replace("\\", "/") not in text


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    service = DiscoveryRunService(tmp_path / "discovery", workers=1)
    discovery_routes.reset_service_for_tests(service)
    yield TestClient(app), service
    service.shutdown()
    discovery_routes.reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


def test_blueprint_endpoint_serves_the_verified_document(client, estate: Path) -> None:
    http, service = client
    result = discover(DiscoveryRequest("directory", str(estate)), service.store)
    run = service.register_result(result, kind="directory", label="estate")
    response = http.get(f"/discovery/runs/{run.run_id}/blueprint")
    assert response.status_code == 200
    document = json.loads(response.content)
    assert verify_blueprint(document) and document["identity"]["checkpoint_id"] == result.checkpoint.checkpoint_id
    assert http.get("/discovery/runs/%s/blueprint" % ("0" * 32)).status_code == 404

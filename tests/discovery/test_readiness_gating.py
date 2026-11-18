"""Downstream gating: ingest, modernize and revalidate consult discovery readiness; ZIP/Git end to end with a compiler check."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import discovery_routes
from api.app import app
from api.service import Service
from enterprise.discovery.compilers import ToolchainConfig
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService
from tests.discovery.helpers import COBOL_ESTATE, _fixed, write_tree
from tests.discovery.test_compilers_applications import FakeCobc

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
FAKE_WHICH = lambda name: "/fake/cobc" if name == "cobc" else None  # noqa: E731
FAKE = ToolchainConfig(backend="local", runner=FakeCobc(), which=FAKE_WHICH)

COMPLETE = {
    "src/MAIN.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. MAIN.", "PROCEDURE DIVISION.", "    CALL 'SUB'.", "    COPY LAYOUT.", "    GOBACK."),
    "src/SUB.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. SUB.", "PROCEDURE DIVISION.", "    GOBACK."),
    "cpy/LAYOUT.cpy": _fixed("01 L PIC X."),
    "jcl/RUN.jcl": "//RUN JOB\n//S1 EXEC PGM=MAIN\n",
}


def zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buffer.getvalue()


@pytest.fixture()
def api(tmp_path: Path, monkeypatch, request):
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCOVERY_COMPILER_BACKEND", "none")
    if not getattr(request, "param", None) == "no-compiler":
        monkeypatch.setattr(ToolchainConfig, "from_environment", classmethod(lambda cls: FAKE))  # a compiler that verifies
    svc = DiscoveryRunService(tmp_path / "discovery")
    discovery_routes.reset_service_for_tests(svc)
    yield TestClient(app)
    svc.shutdown()
    discovery_routes.reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


def new_app(client: TestClient, name: str) -> str:
    response = client.post("/applications", json={"name": name, "workload_id": "wl-gating", "target_runtime": "spring_boot"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ingest(client: TestClient, app_id: str, files: dict[str, str]):
    return client.post(f"/applications/{app_id}/ingest", files={"file": ("estate.zip", zip_bytes(files), "application/zip")})


def modernize(client: TestClient, app_id: str):
    with patch.object(Service, "_modernize_background", lambda *a, **k: None):
        return client.post(f"/applications/{app_id}/modernize")


# --- the gate ---------------------------------------------------------------------------------------------------------------


def test_ingest_reports_readiness_and_modernize_is_refused_while_discovery_is_incomplete(api: TestClient) -> None:
    app_id = new_app(api, "gate-blocked")
    files = {**COMPLETE, "src/MAIN.cbl": COMPLETE["src/MAIN.cbl"].replace("COPY LAYOUT.", "COPY GONECPY.")}
    response = ingest(api, app_id, files)
    assert response.status_code == 201
    readiness = response.json()["readiness"]
    assert readiness["status"] == "BLOCKED" and readiness["allowed"] is False
    assert readiness["blockers"][0]["id"] == "no-blocking-unresolved-references"
    assert readiness["blocking_references"][0]["to"] == "copybook:GONECPY"

    refused = modernize(api, app_id)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "blocked until discovery is complete" in detail and "copybook:GONECPY" in detail
    assert api.get(f"/applications/{app_id}/runs").json() == [], "a refused request must not create a run"


def test_supplying_the_missing_artefact_opens_the_gate_and_the_run_carries_the_readiness(api: TestClient) -> None:
    app_id = new_app(api, "gate-open")
    broken = {**COMPLETE, "src/MAIN.cbl": COMPLETE["src/MAIN.cbl"].replace("COPY LAYOUT.", "COPY GONECPY.")}
    assert ingest(api, app_id, broken).json()["readiness"]["status"] == "BLOCKED"
    assert modernize(api, app_id).status_code == 409

    fixed = ingest(api, app_id, COMPLETE)
    assert fixed.json()["readiness"]["status"] == "READY"
    started = modernize(api, app_id)
    assert started.status_code == 202
    assert started.json()["readiness"]["status"] == "READY" and started.json()["readiness"]["allowed"] is True


def test_unsupported_constructs_are_listed_on_the_run_request_and_never_reported_as_handled(api: TestClient) -> None:
    app_id = new_app(api, "gate-unsupported")
    files = {**COMPLETE, "src/ONLINE.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. ONLINE.", "PROCEDURE DIVISION.",
                                                  "    EXEC CICS RETURN END-EXEC.")}
    readiness = ingest(api, app_id, files).json()["readiness"]
    assert readiness["status"] == "NOT_SUPPORTED" and readiness["allowed"] is True and readiness["unsupported_total"] == 1
    assert readiness["unsupported"][0]["feature"] == "exec-cics" and readiness["unsupported"][0]["file"] == "src/ONLINE.cbl"
    started = modernize(api, app_id)
    assert started.status_code == 202 and started.json()["readiness"]["status"] == "NOT_SUPPORTED"
    assert started.json()["readiness"]["unsupported"][0]["note"]


@pytest.mark.parametrize("api", ["no-compiler"], indirect=True)
def test_no_compiler_never_reads_as_ready_but_never_blocks_either(api: TestClient) -> None:
    app_id = new_app(api, "gate-nocompiler")
    readiness = ingest(api, app_id, COMPLETE).json()["readiness"]
    assert readiness["status"] == "NOT_SUPPORTED" and readiness["allowed"] is True
    assert readiness["unverified_total"] == 2 and {u["reason"] for u in readiness["unverified"]} == {"NOT_ATTEMPTED_NO_COMPILER"}
    started = modernize(api, app_id)
    assert started.status_code == 202 and started.json()["readiness"]["unverified_total"] == 2


def test_readiness_endpoint_returns_the_stored_record_and_refresh_reassesses(api: TestClient) -> None:
    app_id = new_app(api, "gate-endpoint")
    ingest(api, app_id, COMPLETE)
    first = api.get(f"/applications/{app_id}/readiness").json()
    assert first["status"] == "READY" and first["discovery_run_id"] and first["checkpoint_id"].startswith("CP-")
    report = api.get(f"/discovery/runs/{first['discovery_run_id']}/report").json()
    assert report["readiness"]["status"] == "READY" and report["completeness"]["status"] == "COMPLETE"
    assert api.post(f"/applications/{app_id}/readiness/refresh").json()["checkpoint_id"] == first["checkpoint_id"]


def test_a_changed_source_tree_is_reassessed_before_the_next_run(api: TestClient) -> None:
    app_id = new_app(api, "gate-change")
    ingest(api, app_id, COMPLETE)
    assert modernize(api, app_id).status_code == 202
    from api.app import _svc

    workspace = Path(_svc().get_application(app_id).cobol_source_path)
    time.sleep(0.02)
    (workspace / "src/MAIN.cbl").write_text(COMPLETE["src/MAIN.cbl"].replace("CALL 'SUB'.", "CALL 'VANISHED'."), encoding="utf-8")
    refused = modernize(api, app_id)
    assert refused.status_code == 409 and "program:VANISHED" in refused.json()["detail"]


def test_source_that_discovery_cannot_assess_is_blocked_not_waved_through(api: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CONTROL_PLANE_MAX_ZIP_ENTRIES", "1000")
    app_id = new_app(api, "gate-unassessable")
    placeholder = {"A.cob": "A"}  # a COBOL file that is not a program
    readiness = ingest(api, app_id, placeholder).json()["readiness"]
    assert readiness["status"] == "BLOCKED" and "no-scanner-errors" in [b["id"] for b in readiness["blockers"]]
    assert modernize(api, app_id).status_code == 409


def test_revalidation_passes_the_same_gate(api: TestClient, tmp_path: Path) -> None:
    from api.app import _svc
    from api.models import RunStage

    app_id = new_app(api, "gate-revalidate")
    ingest(api, app_id, COMPLETE)
    started = modernize(api, app_id)
    run_id = started.json()["run_id"]
    service = _svc()
    run = service._store.get_run(run_id)
    run.stage = RunStage.FAILED
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    service._persist_final(run)
    service._store.set_run_generated(run_id, str(bundle), "Main")
    workspace = Path(service.get_application(app_id).cobol_source_path)
    time.sleep(0.02)
    (workspace / "src/MAIN.cbl").write_text(COMPLETE["src/MAIN.cbl"].replace("COPY LAYOUT.", "COPY MISSING2."), encoding="utf-8")
    with patch.object(Service, "_revalidate_background", lambda *a, **k: None, create=True):
        refused = api.post(f"/runs/{run_id}/validate")
    assert refused.status_code == 409 and "copybook:MISSING2" in refused.json()["detail"], refused.text


# --- ZIP and Git end to end with compiler discovery ---------------------------------------------------------------------------


def estate_with_defect() -> dict[str, str]:
    return {**COMPLETE, "src/BAD.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. BAD.", "PROCEDURE DIVISION.", "    BADSYNTAX HERE.", "    GOBACK."),
            "src/ONLINE.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. ONLINE.", "PROCEDURE DIVISION.", "    EXEC CICS RETURN END-EXEC."),
            "build/Makefile": "all:\n\tcobc -x -free src/MAIN.cbl\n", "jcl/BAD.jcl": "//BAD JOB\n//S1 EXEC PGM=BAD\n"}


@pytest.fixture()
def store(tmp_path: Path):
    path = tmp_path / "store"
    yield path
    rmtree_force(path)


def git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = write_tree(tmp_path / "repo", files)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "estate"]):
        subprocess.run([*GIT, *args], cwd=repo, check=True, capture_output=True)
    return repo


def artefact(result, name: str) -> dict:
    return json.loads((result.outdir / name).read_text(encoding="utf-8"))


def test_zip_end_to_end_reports_compatibility_applications_and_readiness(tmp_path: Path, store: Path) -> None:
    archive = tmp_path / "e.zip"
    archive.write_bytes(zip_bytes(estate_with_defect()))
    result = discover(DiscoveryRequest("zip", str(archive)), store, toolchain=FAKE)
    compat = artefact(result, "compiler-compatibility.json")
    verdicts = {p["file"]: p["verdict"] for p in compat["programs"]}
    assert verdicts == {"src/BAD.cbl": "COMPILE_ERRORS", "src/MAIN.cbl": "COMPILES", "src/ONLINE.cbl": "NOT_ATTEMPTED_PROPRIETARY",
                        "src/SUB.cbl": "COMPILES"}
    bad = next(p for p in compat["programs"] if p["file"] == "src/BAD.cbl")
    assert bad["diagnostics"][0]["line"] == 4, "compiler diagnostics map to the original source line"
    assert compat["toolchain"]["required"][0]["family"] == "gnucobol"
    applications = artefact(result, "applications.json")
    assert {a["name"] for a in applications["applications"]} == {"BAD", "RUN", "ONLINE"}
    readiness = artefact(result, "transformation-readiness.json")
    assert readiness["status"] == "NOT_SUPPORTED" and readiness["allowed"] is True
    assert {c["file"] for c in readiness["compile_errors"]} == {"src/BAD.cbl"} and readiness["unsupported"][0]["feature"] == "exec-cics"
    assert result.report["completeness"]["status"] in ("COMPLETE", "COMPLETE_WITH_OPEN_ITEMS")


def test_git_end_to_end_gives_the_same_compiler_and_application_evidence_as_zip(tmp_path: Path) -> None:
    files = estate_with_defect()
    archive = tmp_path / "e.zip"
    archive.write_bytes(zip_bytes(files))
    repo = git_repo(tmp_path, files)
    zipped = discover(DiscoveryRequest("zip", str(archive)), tmp_path / "s1", toolchain=FAKE)
    gitted = discover(DiscoveryRequest("git", str(repo)), tmp_path / "s2", toolchain=FAKE)
    try:
        for name in ("compiler-compatibility.json", "applications.json", "transformation-readiness.json"):
            assert (zipped.outdir / name).read_bytes() == (gitted.outdir / name).read_bytes(), name
        assert gitted.report["provenance"]["commit"] and not zipped.report["provenance"]["commit"]
    finally:
        rmtree_force(tmp_path / "s1")
        rmtree_force(tmp_path / "s2")


def test_compiler_discovery_is_deterministic_across_runs_and_stores(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "e", estate_with_defect())
    outputs = []
    for index in range(2):
        result = discover(DiscoveryRequest("directory", str(root), label="e"), tmp_path / f"s{index}", toolchain=FAKE)
        outputs.append({n: (result.outdir / n).read_bytes() for n in ("compiler-compatibility.json", "applications.json",
                                                                       "transformation-readiness.json", "discovery-report.json")})
    assert outputs[0] == outputs[1]
    for index in range(2):
        rmtree_force(tmp_path / f"s{index}")


def test_no_compiler_still_completes_every_other_discovery_check(tmp_path: Path, store: Path) -> None:
    root = write_tree(tmp_path / "e", estate_with_defect())
    result = discover(DiscoveryRequest("directory", str(root)), store, toolchain=ToolchainConfig(backend="none"))
    compat = artefact(result, "compiler-compatibility.json")
    assert compat["backend"]["kind"] == "none"
    assert {p["verdict"] for p in compat["programs"]} == {"NOT_ATTEMPTED_NO_COMPILER", "NOT_ATTEMPTED_PROPRIETARY"}
    assert result.report["summary"]["files"] == len(estate_with_defect()) and result.report["programs"]
    assert artefact(result, "transformation-readiness.json")["status"] == "NOT_SUPPORTED"


def test_environment_selects_the_backend_and_an_unreadable_setting_never_enables_a_tool(monkeypatch) -> None:
    monkeypatch.setenv("DISCOVERY_COMPILER_BACKEND", "none")
    assert ToolchainConfig.from_environment().backend == "none"
    monkeypatch.setenv("DISCOVERY_COMPILER_BACKEND", "container")
    monkeypatch.setenv("DISCOVERY_COMPILE_BUDGET_SECONDS", "12")
    config = ToolchainConfig.from_environment()
    assert (config.backend, config.budget_seconds) == ("container", 12.0)
    monkeypatch.setenv("DISCOVERY_COMPILER_BACKEND", "rm -rf")
    monkeypatch.setenv("DISCOVERY_COMPILE_BUDGET_SECONDS", "soon")
    config = ToolchainConfig.from_environment()
    assert (config.backend, config.budget_seconds) == ("none", 240.0)


def test_source_viewer_reads_the_checkpoint_and_refuses_anything_not_inventoried(api: TestClient, tmp_path: Path) -> None:
    run = api.post("/discovery/runs/zip", files={"file": ("e.zip", zip_bytes(COBOL_ESTATE))}).json()
    for _ in range(600):
        state = api.get(f"/discovery/runs/{run['run_id']}").json()
        if state["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert state["state"] == "succeeded"
    ok = api.get(f"/discovery/runs/{run['run_id']}/source", params={"path": "src/cobol/PAYROLL.cbl", "line": 22, "context": 2})
    assert ok.status_code == 200
    body = ok.json()
    assert [line["number"] for line in body["lines"]] == [20, 21, 22, 23, 24] and "MISSING1" in body["lines"][2]["text"]
    assert body["sha256"] == hashlib.sha256(COBOL_ESTATE["src/cobol/PAYROLL.cbl"].encode()).hexdigest()
    for bad in ({"path": "../../etc/passwd", "line": 1}, {"path": "src/cobol/NOPE.cbl", "line": 1},
                {"path": "src/cobol/PAYROLL.cbl", "line": 9999}, {"path": "/etc/passwd", "line": 1}, {"path": "src\\cobol\\PAYROLL.cbl", "line": 1}):
        assert api.get(f"/discovery/runs/{run['run_id']}/source", params=bad).status_code == 404, bad


# --- the real open-source compiler (Docker lane) ---------------------------------------------------------------------------


def _gnucobol_image() -> str:
    if not shutil.which("docker"):
        pytest.skip("docker is not available")
    for image in ("gnucobol-ocesql:latest",):
        probe = subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False)
        if probe.returncode == 0:
            return image
    pytest.skip("the GnuCOBOL oracle image is not built")


@pytest.mark.docker
def test_real_gnucobol_container_checks_real_programs_and_maps_diagnostics_to_lines(tmp_path: Path, store: Path) -> None:
    image = _gnucobol_image()
    files = {
        "src/OK.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. OK.", "PROCEDURE DIVISION.", "    DISPLAY 'HELLO'.", "    STOP RUN."),
        "src/BAD.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. BAD.", "PROCEDURE DIVISION.", "    DISPLAY 'HELLO'", "    MOVE TO.", "    STOP RUN."),
        "src/CPY.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. CPYUSER.", "DATA DIVISION.", "WORKING-STORAGE SECTION.", "    COPY LAYOUT.",
                              "PROCEDURE DIVISION.", "    MOVE 'A' TO L-A.", "    STOP RUN."),
        "cpy/LAYOUT.cpy": _fixed("01 L-REC.", "    05 L-A PIC X."),
        "src/CICS.cbl": _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. CICSP.", "PROCEDURE DIVISION.", "    EXEC CICS RETURN END-EXEC."),
        "src/FREE.cbl": ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\nPROGRAM-ID. FREEP.\nPROCEDURE DIVISION.\nDISPLAY 'X'.\nSTOP RUN.\n",
    }
    root = write_tree(tmp_path / "e", files)
    result = discover(DiscoveryRequest("directory", str(root)), store, toolchain=ToolchainConfig(backend="container", image=image))
    compat = artefact(result, "compiler-compatibility.json")
    assert compat["backend"]["kind"] == "container" and compat["backend"]["version"]
    verdicts = {p["file"]: p["verdict"] for p in compat["programs"]}
    assert verdicts == {"src/BAD.cbl": "COMPILE_ERRORS", "src/CICS.cbl": "NOT_ATTEMPTED_PROPRIETARY", "src/CPY.cbl": "COMPILES",
                        "src/FREE.cbl": "COMPILES", "src/OK.cbl": "COMPILES"}
    bad = next(p for p in compat["programs"] if p["file"] == "src/BAD.cbl")
    assert bad["diagnostics"] and bad["diagnostics"][0]["file"] == "src/BAD.cbl" and bad["diagnostics"][0]["severity"] == "error"
    assert bad["diagnostics"][0]["line"] in (4, 5)
    assert {t["tool"]: t["available"] for t in compat["tools"]}["cobc"] is True
    assert artefact(result, "transformation-readiness.json")["compile_errors"][0]["file"] == "src/BAD.cbl"


def test_fingerprint_follows_content_not_size_or_mtime(tmp_path: Path) -> None:
    from api.readiness import fingerprint

    target = tmp_path / "P.cbl"
    target.write_bytes(b"       PROGRAM-ID. AAAA.\n")
    before, stamp = fingerprint(tmp_path), target.stat()
    target.write_bytes(b"       PROGRAM-ID. BBBB.\n")  # same size
    import os

    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))  # same mtime
    assert fingerprint(tmp_path) != before


def test_vsam_migration_passes_the_same_readiness_gate(api: TestClient) -> None:
    app_id = new_app(api, "gate-vsam")
    broken = {**COMPLETE, "src/MAIN.cbl": COMPLETE["src/MAIN.cbl"].replace("COPY LAYOUT.", "COPY GONECPY.")}
    assert ingest(api, app_id, broken).json()["readiness"]["status"] == "BLOCKED"
    refused = api.post(f"/applications/{app_id}/vsam/migrate", files={"dataset": ("d.dat", b"x")}, data={"options": "{}"})
    assert refused.status_code == 409 and "GONECPY" in refused.json()["detail"]

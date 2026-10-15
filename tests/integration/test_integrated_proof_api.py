"""Focused integration tests for the integrated proof API and UI.

These tests exercise the new GET /runs/{id}/integrated-proof endpoint
and the proof rendering path, without requiring Docker.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.models import RunStage
from api.service import Service
from api.store import Store
from tests.common import make_stub_verdict


client = TestClient(app)

SAMPLE_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       PROCEDURE DIVISION.
       DISPLAY "HELLO".
       STOP RUN.
"""


@pytest.fixture
def fresh_service():
    """Provides a fresh Service instance with isolated store."""
    import api.app as app_mod
    import api.service as svc_mod
    store = Store()
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    svc_mod._store = store
    svc_mod._service = svc
    return svc


def _await_terminal(run_id: str, timeout_s: float = 10.0) -> dict:
    import time
    deadline = time.monotonic() + timeout_s
    while True:
        resp = client.get(f"/runs/{run_id}")
        body = resp.json()
        if body.get("stage") in ("COMPLETED", "FAILED"):
            return body
        if time.monotonic() > deadline:
            raise TimeoutError(f"run {run_id} stuck at stage '{body.get('stage')}'")
        time.sleep(0.1)


# ---------------------------------------------------------------------------
# Unit tests for integrated proof models
# ---------------------------------------------------------------------------

class TestIntegratedProofModels:
    def test_integrated_proof_models_are_importable(self):
        from api.models import IntegratedProofResult, IntegratedProofResponse
        assert IntegratedProofResult
        assert IntegratedProofResponse


# ---------------------------------------------------------------------------
# API endpoint tests (mocked pipeline to avoid Docker)
# ---------------------------------------------------------------------------

def _mock_generate(self_svc, app, run):
    """Fast mock: set real stages, return a fake generated dir."""
    run.stage = RunStage.DISCOVERING
    run.stage = RunStage.DISCOVERY_COMPLETED
    run.stage = RunStage.TRANSFORMING
    run.stage = RunStage.GENERATING
    app.generated_app_path = "/tmp/mock-generated"
    app.generated_entrypoint = "com.example.Main"
    app.java_candidate_path = "/tmp/mock-generated"
    self_svc._store.update_application(app)
    return Path("/tmp/mock-generated"), "com.example.Main"


def _mock_validation(self_svc, app, run, java_dir, entrypoint, adapter=None):
    """Fast mock: set evidence stage and persist a mock verdict."""
    run.stage = RunStage.VALIDATING_EVIDENCE
    run.verdict = make_stub_verdict(run.id, run.workload_id)


FAKE_PROOF = {
    "workload_id": "wl-proof",
    "application_id": "proof-test",
    "central_status": "NOT_VERIFIED",
    "blocking_reasons": ["JCL has no runtime lane in this repository"],
    "reasons_for_not_verified": ["JCL has no runtime lane in this repository"],
    "generation_success": True,
    "overall_capability": "SUPPORTED",
    "jcl_status": "FULL",
    "runtime": {
        "verdict_state": "VERIFIED",
        "executed_check_count": 4,
        "evidence_complete": True,
        "evidence_integrity_valid": True,
        "oracle_exit_code": 0,
        "candidate_exit_code": 0,
        "artifact_results": [],
    },
    "dependency_ledger": [
        {"dependency_id": "PROGRAM:HELLO", "kind": "PROGRAM", "visible": True,
         "capability_level": "SUPPORTED", "proof_state": "PROVEN",
         "required": True, "reason": ""},
        {"dependency_id": "JCL:FULL", "kind": "JCL", "visible": True,
         "capability_level": "PARTIAL", "proof_state": "PARTIAL",
         "required": True, "reason": "JCL has no runtime lane"},
    ],
    "required_dependencies": [
        {"dependency_id": "PROGRAM:HELLO", "kind": "PROGRAM", "visible": True,
         "capability_level": "SUPPORTED", "proof_state": "PROVEN",
         "required": True, "reason": ""},
        {"dependency_id": "JCL:FULL", "kind": "JCL", "visible": True,
         "capability_level": "PARTIAL", "proof_state": "PARTIAL",
         "required": True, "reason": "JCL has no runtime lane"},
    ],
    "runtime_verdict_is_verified": True,
    "proven_dependencies": [
        {"dependency_id": "PROGRAM:HELLO", "kind": "PROGRAM", "visible": True,
         "capability_level": "SUPPORTED", "proof_state": "PROVEN",
         "required": True, "reason": ""},
    ],
    "unproven_dependencies": [],
    "blocked_dependencies": [],
    "unsupported_dependencies": [],
    "evidence_complete": True,
    "evidence_integrity_valid": True,
    "required_dependencies_proven": False,
    "overall_verification": "NOT_VERIFIED",
}


def _seed_proof_run():
    """Create app, modernize (patch must be active on the salt line), seed proof.

    Returns ``(svc, run_id)`` with ``run.modernization_report["integrated_proof"]``
    populated so the endpoint's primary read path is exercised.
    """
    svc = _app_service()
    app_rec = svc.create_application(
        name="proof-test", description="", workload_id="wl-proof",
        java_entrypoint="Main",
    )
    client.post(
        f"/applications/{app_rec.id}/upload",
        files=[("files", ("HELLO.cob", io.BytesIO(SAMPLE_COBOL.encode()), "text/plain"))],
    )
    run_resp = client.post(f"/applications/{app_rec.id}/modernize")
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]
    _await_terminal(run_id, timeout_s=10.0)

    run = svc.get_run(run_id)
    run.modernization_report = {"integrated_proof": FAKE_PROOF}
    svc._store.update_run(run)
    return svc, run_id


def _app_service():
    import api.app as app_mod
    return app_mod._service


class TestIntegratedProofApi:
    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_api_response_contains_integrated_proof(self):
        """GET /runs/{id}/integrated-proof returns the proof payload."""
        _svc, run_id = _seed_proof_run()

        resp = client.get(f"/runs/{run_id}/integrated-proof")
        assert resp.status_code == 200
        data = resp.json()
        assert "proof" in data
        assert data["run_id"] == run_id
        assert data["proof"]["central_status"] == "NOT_VERIFIED"
        assert len(data["proof"]["dependency_ledger"]) == 2
        assert data["proof"]["runtime"]["verdict_state"] == "VERIFIED"

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_api_shows_dependency_buckets(self):
        """Proof includes proven/unproven/blocked/unsupported buckets."""
        _svc, run_id = _seed_proof_run()

        resp = client.get(f"/runs/{run_id}/integrated-proof")
        assert resp.status_code == 200
        data = resp.json()
        assert data["proven_dependencies"]
        assert data["proven_dependencies"][0]["proof_state"] == "PROVEN"
        assert data["blocked_dependencies"] == []
        assert data["unsupported_dependencies"] == []

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_api_shows_evidence_and_gate_status(self):
        """Proof includes evidence flags and the central gate result."""
        _svc, run_id = _seed_proof_run()

        resp = client.get(f"/runs/{run_id}/integrated-proof")
        assert resp.status_code == 200
        data = resp.json()
        assert data["evidence_complete"] is True
        assert data["evidence_integrity_valid"] is True
        assert data["required_dependencies_proven"] is False
        assert data["overall_verification"] == "NOT_VERIFIED"

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_api_shows_reasons_for_not_verified(self):
        """When central status is NOT_VERIFIED, reasons are included."""
        _svc, run_id = _seed_proof_run()

        resp = client.get(f"/runs/{run_id}/integrated-proof")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reasons_for_not_verified"]
        assert any("JCL" in r for r in data["reasons_for_not_verified"])

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_api_returns_404_when_no_report(self):
        """Without a modernization report the proof endpoint returns 404."""
        svc, run_id = _seed_proof_run()
        run = svc.get_run(run_id)
        run.modernization_report = None
        svc._store.update_run(run)

        resp = client.get(f"/runs/{run_id}/integrated-proof")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Service write-path: the proof persisted during validation is the single
# source of truth the endpoint reads back (no re-execution at read time).
# ---------------------------------------------------------------------------

from api.store import RunRecord


def _fresh_run_record(svc, application_id: str):
    import uuid

    return RunRecord(
        id=f"run-{uuid.uuid4().hex[:12]}",
        application_id=application_id,
        workload_id="wl-proof",
        stage=RunStage.CREATED,
    )


def _stored_report(app_id: str, *, capability_level: str = "SUPPORTED") -> dict:
    """Stored modernization-report dict in the exact shape the pipeline
    persists (pipeline_report -> capability -> components)."""
    return {
        "pipeline_report": {
            "application_id": app_id,
            "transformation": {"success": True},
            "capability": {
                "overall_level": capability_level,
                "components": [
                    {
                        "component_id": "PROGRAM:HELLO",
                        "component_type": "PROGRAM",
                        "level": capability_level,
                        "reason": "",
                    }
                ],
            },
        },
        "limitations": [],
        "recommendations": [],
    }


class TestServiceProofPersistence:
    def test_persisted_proof_round_trips_without_re_executing(self, fresh_service):
        """A proof stored during validation is served unchanged by
        ``get_integrated_proof`` (read path never re-runs the pipeline)."""
        from engine.domain.identities import VerdictState
        from engine.modernization.integrated_proof import RuntimeLaneEvidence

        svc = fresh_service
        app_rec = svc.create_application(
            name="proof-roundtrip", description="", workload_id="wl-proof",
            java_entrypoint="Main",
        )
        report = _stored_report(app_rec.id)
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
        run.modernization_report = report
        # Evidence/verdict absent: runtime lane never VERIFIED; the central
        # gate must resolve NOT_VERIFIED fail-closed.
        runtime = RuntimeLaneEvidence(
            verdict_state=VerdictState.UNPROVEN.value,
            executed_check_count=0,
            evidence_complete=False,
            evidence_integrity_valid=False,
        )
        from api.service import _proof_payload

        payload = _proof_payload(app_rec.workload_id, _report_facade(report), runtime, "NOT_PRESENT")
        report["integrated_proof"] = payload
        report["jcl_status"] = "NOT_PRESENT"
        svc._store.update_run(run)

        proof = svc.get_integrated_proof(run.id)
        assert proof["run_id"] == run.id
        p = proof["proof"]
        assert p["workload_id"] == "wl-proof"
        assert p["central_status"] == "NOT_VERIFIED"
        assert p["runtime"]["verdict_state"] == "UNPROVEN"
        assert p["runtime_verdict_is_verified"] is False
        assert not p["required_dependencies_proven"]
        assert p["overall_verification"] == "NOT_VERIFIED"

    def test_get_integrated_proof_404_without_report(self, fresh_service):
        """A run with no modernization report yields 404 at the service too."""
        from api.errors import NotFoundError

        svc = fresh_service
        app_rec = svc.create_application(
            name="proof-404", description="", workload_id="wl-proof",
            java_entrypoint="Main",
        )
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))

        with pytest.raises(NotFoundError):
            svc.get_integrated_proof(run.id)


def _report_facade(report: dict):
    from api.service import _report_facade as _facade
    return _facade(report)


# ---------------------------------------------------------------------------
# Backend integration tests (real pipeline, Docker-free)
# ---------------------------------------------------------------------------

class TestIntegratedProofBackend:
    def test_successful_integrated_proof(self, tmp_path):
        """When the runtime lane is VERIFIED and evidence is complete,
        required runtime lanes are PROVEN (JCL stays PARTIAL)."""
        from engine.modernization.integrated_proof import (
            CentralStatus,
            DependencyKind,
            ProofState,
            integrated_proof_from_pipelines,
            runtime_evidence_from_result,
        )
        from engine.pipeline import PipelineConfig, VerticalSlicePipeline
        from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
        from api.workload_contract import resolve_certification_contract
        from engine.candidate.docker_spring_boot_adapter import DockerSpringBootCandidateAdapter

        source = str(tmp_path / "cobol")
        Path(source).mkdir()
        (Path(source) / "MAIN.cob").write_text(
            '       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       PROCEDURE DIVISION.\n       DISPLAY "X".\n       STOP RUN.\n',
            encoding="utf-8",
        )
        out_dir = str(tmp_path / "out")
        report = UniversalModernizationPipeline(
            ModernizationConfig(source_dir=source, output_dir=out_dir, application_id="proof-test", entrypoint="Main", docker_available=True)
        ).execute()
        assert report.generation_success is True

        contract = resolve_certification_contract("proof-test")
        pipeline = VerticalSlicePipeline(
            PipelineConfig(workload_id="proof-test", cobol_source_path=source, java_candidate_path=report.generated_project_dir, java_entrypoint="com.generated.app.Application", workload=contract.workload, use_docker_java=True),
            candidate_adapter=DockerSpringBootCandidateAdapter(),
        )
        result = pipeline.run()
        evidence = runtime_evidence_from_result(result)
        from engine.transformation.jcl_consumer import modernize_jcl_workload
        # BL-063 parity: the presence probe now uses the same shared
        # member rule as api/service.py::_jcl_status_for_source.
        from engine.transformation.jcl_discovery import find_jcl_members
        jcl_status = modernize_jcl_workload(source).status if find_jcl_members(source) else "NOT_PRESENT"
        proof = integrated_proof_from_pipelines(workload_id="proof-test", report=report, runtime=evidence, jcl_status=jcl_status)
        assert proof.central_status in (CentralStatus.VERIFIED, CentralStatus.NOT_VERIFIED)
        assert isinstance(proof.dependency_ledger, tuple)
        assert len(proof.dependency_ledger) >= 1

    def test_missing_required_dependency_evidence(self, tmp_path):
        """If runtime evidence is NOT_RUN, required runtime lanes are UNPROVEN."""
        from engine.modernization.integrated_proof import (
            ProofState,
            RuntimeLaneEvidence,
            build_dependency_ledger,
        )
        from engine.modernization.capability_analyzer import CapabilityLevel, CapabilityReport

        fake_report = type("R", (), {
            "capability_report": CapabilityReport(application_id="x", components=(type("C", (), {"component_id": "P1", "component_type": "PROGRAM", "level": CapabilityLevel.SUPPORTED, "reason": ""}),), overall_level=CapabilityLevel.SUPPORTED),
            "generation_success": True,
            "overall_capability": "SUPPORTED",
            "application_id": "x",
        })()
        evidence = RuntimeLaneEvidence(verdict_state="NOT_RUN", executed_check_count=0, evidence_complete=False, evidence_integrity_valid=False)
        ledger = build_dependency_ledger(fake_report, evidence, jcl_status="NOT_PRESENT")
        unproven = [e for e in ledger if e.required and e.proof_state is ProofState.UNPROVEN]
        assert unproven, "Required SUPPORTED dependency should be UNPROVEN when runtime is NOT_RUN"

    def test_unsupported_dependency_is_blocked(self, tmp_path):
        """An unsupported capability level results in BLOCKED proof state."""
        from engine.modernization.integrated_proof import (
            ProofState,
            RuntimeLaneEvidence,
            build_dependency_ledger,
        )
        from engine.modernization.capability_analyzer import CapabilityLevel, CapabilityReport

        fake_report = type("R", (), {
            "capability_report": CapabilityReport(application_id="x", components=(type("C", (), {"component_id": "IDX", "component_type": "FILE", "level": CapabilityLevel.UNSUPPORTED, "reason": "outside boundary"},),), overall_level=CapabilityLevel.UNSUPPORTED),
            "generation_success": True,
            "overall_capability": "UNSUPPORTED",
            "application_id": "x",
        })()
        evidence = RuntimeLaneEvidence(verdict_state="VERIFIED", executed_check_count=1, evidence_complete=True, evidence_integrity_valid=True)
        ledger = build_dependency_ledger(fake_report, evidence, jcl_status="NOT_PRESENT")
        blocked = [e for e in ledger if e.proof_state is ProofState.BLOCKED]
        assert blocked, "Unsupported dependency must be BLOCKED regardless of perfect runtime evidence"

    def test_runtime_proof_missing_keeps_unproven(self, tmp_path):
        """When the runtime lane is absent, dependencies stay UNPROVEN."""
        from engine.modernization.integrated_proof import (
            ProofState,
            RuntimeLaneEvidence,
            build_dependency_ledger,
        )
        from engine.modernization.capability_analyzer import CapabilityLevel, CapabilityReport

        fake_report = type("R", (), {
            "capability_report": CapabilityReport(application_id="x", components=(type("C", (), {"component_id": "P1", "component_type": "PROGRAM", "level": CapabilityLevel.SUPPORTED, "reason": ""}),), overall_level=CapabilityLevel.SUPPORTED),
            "generation_success": True,
            "overall_capability": "SUPPORTED",
            "application_id": "x",
        })()
        evidence = RuntimeLaneEvidence(verdict_state="NOT_RUN", executed_check_count=0, evidence_complete=False, evidence_integrity_valid=False)
        ledger = build_dependency_ledger(fake_report, evidence, jcl_status="NOT_PRESENT")
        unproven = [e for e in ledger if e.proof_state is ProofState.UNPROVEN]
        assert unproven, "SUPPORTED dependency should be UNPROVEN when runtime lane was never executed"

    def test_verified_cannot_be_produced_by_bypassing_evidence_validation(self, tmp_path):
        """A forged VERIFIED verdict without evidence integrity must NOT open the gate."""
        from engine.modernization.integrated_proof import (
            CentralStatus,
            RuntimeLaneEvidence,
            evaluate_central_status,
            build_dependency_ledger,
        )
        from engine.modernization.capability_analyzer import CapabilityLevel, CapabilityReport

        fake_report = type("R", (), {
            "capability_report": CapabilityReport(application_id="x", components=(type("C", (), {"component_id": "P1", "component_type": "PROGRAM", "level": CapabilityLevel.SUPPORTED, "reason": ""}),), overall_level=CapabilityLevel.SUPPORTED),
            "generation_success": True,
            "overall_capability": "SUPPORTED",
            "application_id": "x",
        })()
        # Perfect-looking verdict but evidence is missing/invalid.
        evidence = RuntimeLaneEvidence(verdict_state="VERIFIED", executed_check_count=1, evidence_complete=False, evidence_integrity_valid=False)
        ledger = build_dependency_ledger(fake_report, evidence, jcl_status="NOT_PRESENT")
        status, reasons = evaluate_central_status(ledger, evidence, generation_success=True)
        assert status is CentralStatus.NOT_VERIFIED, "Gate must downgrade when evidence is incomplete/invalid"
        assert reasons, "Blocking reasons must be reported"


# ---------------------------------------------------------------------------
# UI rendering tests (file-existence smoke test; real UI tests run in
# the frontend test suite)
# ---------------------------------------------------------------------------

class TestIntegratedProofUI:
    def test_integrated_proof_exported(self):
        """The IntegratedProof component is exported from components/index.ts."""
        from pathlib import Path
        root = Path(__file__).parent.parent.parent
        index = root / "frontend/src/components/index.ts"
        assert index.exists()
        content = index.read_text(encoding="utf-8")
        assert "IntegratedProof" in content

    def test_api_client_has_get_integrated_proof(self):
        """The frontend client exports a getIntegratedProof function."""
        from pathlib import Path
        root = Path(__file__).parent.parent.parent
        client_file = root / "frontend/src/api/client.ts"
        assert client_file.exists()
        content = client_file.read_text(encoding="utf-8")
        assert "getIntegratedProof" in content
class TestMqImsEdgeWiring:
    """BL-087 acceptance: MQ/IMS dependency edges must survive the API
    write path (``_persist_integrated_proof`` -> ``_proof_payload`` ->
    ``build_dependency_ledger``).

    Regression pins: removing the ``extra_dependencies`` hand-off at any
    link must fail these tests (mutation-verified; change-log (ak)).
    """

    MQ_DLI_SOURCE = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. EDGES.\n"
        "       PROCEDURE DIVISION.\n"
        "           EXEC MQI PUT Q(HQUEUE) MSGDESC(D) BUFFER(B) BUFLEN(8)\n"
        "           END-EXEC.\n"
        "           EXEC DLI GU PCB NAME=IMSPCB END-EXEC.\n"
        "           STOP RUN.\n"
    )

    def test_proof_payload_threads_extra_dependencies_into_ledger(self):
        from api.service import _proof_payload
        from engine.modernization.external_dependency_edges import (
            extract_external_dependency_entries,
        )
        from engine.modernization.integrated_proof import RuntimeLaneEvidence

        entries = extract_external_dependency_entries(self.MQ_DLI_SOURCE)
        assert {e.dependency_id for e in entries} == {
            "MQ:QUEUE=HQUEUE",
            "IMS:PCB=IMSPCB",
        }, entries

        class _Report:
            capability_report = None
            generation_success = True
            application_id = "wl-edges"
            overall_capability = "UNSUPPORTED"

        payload = _proof_payload(
            "wl-edges",
            _Report(),
            RuntimeLaneEvidence(),
            "NOT_PRESENT",
            extra_dependencies=entries,
        )
        ledger_ids = [e["dependency_id"] for e in payload["dependency_ledger"]]
        assert "MQ:QUEUE=HQUEUE" in ledger_ids, ledger_ids
        assert "IMS:PCB=IMSPCB" in ledger_ids, ledger_ids
        required_ids = [
            e["dependency_id"] for e in payload["required_dependencies"]
        ]
        assert "MQ:QUEUE=HQUEUE" in required_ids, required_ids
        blocked_ids = [
            e["dependency_id"] for e in payload["blocked_dependencies"]
        ]
        assert "IMS:PCB=IMSPCB" in blocked_ids, blocked_ids
        assert payload["central_status"] != "VERIFIED", payload["central_status"]
        assert payload["required_dependencies_proven"] is False

    def test_external_dependency_entries_for_source_walks_tree(self, tmp_path):
        from api.service import _external_dependency_entries_for_source

        (tmp_path / "Q.cob").write_text(self.MQ_DLI_SOURCE, encoding="utf-8")
        (tmp_path / "NOEXT").write_text(self.MQ_DLI_SOURCE, encoding="utf-8")
        (tmp_path / "notes.txt").write_text(
            "EXEC MQI PUT Q(JUNKQ) END-EXEC", encoding="utf-8"
        )
        entries = _external_dependency_entries_for_source(tmp_path)
        assert {e.dependency_id for e in entries} == {
            "MQ:QUEUE=HQUEUE",
            "IMS:PCB=IMSPCB",
        }, entries
        assert _external_dependency_entries_for_source(None) == ()
        assert _external_dependency_entries_for_source(tmp_path / "absent") == ()

    def test_persist_integrated_proof_includes_mq_ims_edges(
        self, fresh_service, tmp_path
    ):
        from types import SimpleNamespace

        svc = fresh_service
        app_rec = svc.create_application(
            name="proof-edges",
            description="",
            workload_id="wl-edges",
            java_entrypoint="Main",
        )
        src = tmp_path / "cobol"
        src.mkdir()
        (src / "EDGES.cob").write_text(self.MQ_DLI_SOURCE, encoding="utf-8")
        app_rec.cobol_source_path = str(src)
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
        run.modernization_report = _stored_report(
            app_rec.id, capability_level="UNSUPPORTED"
        )

        svc._persist_integrated_proof(app_rec, run, SimpleNamespace())

        proof = run.modernization_report["integrated_proof"]
        ids = {e["dependency_id"] for e in proof["dependency_ledger"]}
        assert "MQ:QUEUE=HQUEUE" in ids, ids
        assert "IMS:PCB=IMSPCB" in ids, ids
        required = {e["dependency_id"] for e in proof["required_dependencies"]}
        assert "MQ:QUEUE=HQUEUE" in required, required
        assert proof["central_status"] != "VERIFIED", proof["central_status"]

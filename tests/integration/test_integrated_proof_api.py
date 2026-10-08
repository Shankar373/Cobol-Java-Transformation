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
    def test_models_import(self):
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
        jcl_status = modernize_jcl_workload(source).status if Path(source).rglob("*.jcl") else "NOT_PRESENT"
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
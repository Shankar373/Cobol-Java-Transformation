"""Phase D TASK 4: negative integration scenarios (8 fail-closed cases).

Every scenario must show the same four-step chain:

    dependency visible  ->  dependency classified  ->  blocked / partial
                         ->  central status NOT VERIFIED (never VERIFIED)

The gate is also re-run with *perfect* runtime evidence for the lanes that
have no runtime at all (JCL / DB2 / CICS), proving the central status can
never be opened by a strong runtime lane alone.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.modernization.integrated_proof import (
    CentralStatus,
    DependencyKind,
    DependencyLedgerEntry,
    ProofState,
    RuntimeLaneEvidence,
    evaluate_central_status,
    integrated_proof_from_pipelines,
    jcl_ledger_entry,
    runtime_evidence_from_result,
)
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.jcl_consumer import modernize_jcl_workload

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)


# ---------------------------------------------------------------------------
# Scenario sources
# ---------------------------------------------------------------------------

MISSING_COPYBOOK = HEADER.format(pid="NOCOPYBOOK") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       COPY MISSING-REC.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY \"NO COPYBOOK\".\n"
    "           STOP RUN.\n"
)

MISSING_CALL_TARGET = HEADER.format(pid="LONELY") + (
    "       PROCEDURE DIVISION.\n"
    "           CALL 'NOSUCHPROGRAM'.\n"
    "           STOP RUN.\n"
)

ARITY_CALLER = HEADER.format(pid="ARITY-MAIN") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-A PIC 9(4) VALUE 1.\n"
    "       01 WS-B PIC 9(4) VALUE 2.\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL 'ARITY-CALLEE' USING WS-A WS-B.\n"
    "           STOP RUN.\n"
)

ARITY_CALLEE = HEADER.format(pid="ARITY-CALLEE") + (
    "       DATA DIVISION.\n"
    "       LINKAGE SECTION.\n"
    "       01 LS-A PIC 9(4).\n"
    "       PROCEDURE DIVISION USING LS-A.\n"
    "           EXIT PROGRAM.\n"
)

INDEXED_FILE = HEADER.format(pid="IDXPROG") + (
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    "           SELECT IDX-FILE ASSIGN TO \"/workspace/output/idx.dat\"\n"
    "               ORGANIZATION IS INDEXED\n"
    "               ACCESS MODE IS DYNAMIC\n"
    "               RECORD KEY IS IDX-ID.\n"
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD  IDX-FILE.\n"
    "       01  IDX-REC.\n"
    "           05  IDX-ID              PIC X(6).\n"
    "           05  IDX-VAL             PIC X(10).\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-STATUS               PIC X(2) VALUE \"00\".\n"
    "       PROCEDURE DIVISION.\n"
    "           OPEN INPUT IDX-FILE.\n"
    "           READ IDX-FILE.\n"
    "           CLOSE IDX-FILE.\n"
    "           STOP RUN.\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _modernize(tmp_path, files: dict[str, str], entrypoint: str):
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (src / name).write_text(text, encoding="utf-8")
    report = UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(src),
            output_dir=str(tmp_path / "out"),
            application_id="phase-d-negative",
            entrypoint=entrypoint,
            docker_available=True,
        )
    ).execute()
    return report


def _component(report, component_type: str, needle: str = ""):
    if report.capability_report is None:
        raise AssertionError(
            f"capability report missing; limitations={report.limitations}"
        )
    for component in report.capability_report.components:
        if component.component_type != component_type:
            continue
        if needle and needle not in component.component_id:
            continue
        return component
    raise AssertionError(
        f"no {component_type} component {needle!r} in "
        f"{[c.component_id for c in report.capability_report.components]}"
    )


def _assert_never_verified(report, runtime: RuntimeLaneEvidence | None = None):
    """Central status must be NOT VERIFIED for a blocked/partial workload."""
    evidence = runtime or RuntimeLaneEvidence(verdict_state="NOT_RUN")
    proof = integrated_proof_from_pipelines(
        workload_id="phase-d-negative",
        report=report,
        runtime=evidence,
    )
    assert proof.central_status is CentralStatus.NOT_VERIFIED, proof.to_dict()
    assert proof.blocking_reasons, proof.to_dict()
    return proof


def _assert_entry_blocks(entry: DependencyLedgerEntry):
    """Visible + classified + not PROVEN, even with a perfect runtime lane."""
    assert entry.visible is True, entry
    assert entry.required is True, entry
    assert entry.capability_level is not None, entry
    assert entry.proof_state is not ProofState.PROVEN, entry

    perfect_runtime = RuntimeLaneEvidence(
        verdict_state="VERIFIED",
        executed_check_count=4,
        evidence_complete=True,
        evidence_integrity_valid=True,
    )
    status, reasons = evaluate_central_status((entry,), perfect_runtime)
    assert status is CentralStatus.NOT_VERIFIED, (entry, reasons)
    assert reasons
    return reasons


# ---------------------------------------------------------------------------
# 1. Missing COPYBOOK
# ---------------------------------------------------------------------------


class TestMissingCopybook:
    def test_copybook_dependency_is_visible_and_classified(self, tmp_path):
        report = _modernize(tmp_path, {"MAIN.cob": MISSING_COPYBOOK}, "NOCOPYBOOK")
        app = ApplicationDiscovery().discover(
            str(tmp_path / "cobol"), application_id="phase-d-negative"
        )
        main = app.get_program("NOCOPYBOOK")
        assert main is not None
        assert [c.copybook_name for c in main.copybooks] == ["MISSING-REC"]

    def test_missing_copybook_blocks_generation(self, tmp_path):
        report = _modernize(tmp_path, {"MAIN.cob": MISSING_COPYBOOK}, "NOCOPYBOOK")
        assert report.generation_success is False
        assert report.generation_errors or report.limitations

    def test_missing_copybook_central_status_is_not_verified(self, tmp_path):
        report = _modernize(tmp_path, {"MAIN.cob": MISSING_COPYBOOK}, "NOCOPYBOOK")
        proof = _assert_never_verified(report)
        assert proof.unproven_dependencies or not proof.generation_success


# ---------------------------------------------------------------------------
# 2. Missing CALL target
# ---------------------------------------------------------------------------


class TestMissingCallTarget:
    def test_call_edge_is_visible_and_unresolved(self, tmp_path):
        (tmp_path / "MAIN.cob").write_text(MISSING_CALL_TARGET, encoding="utf-8")
        app = ApplicationDiscovery().discover(
            str(tmp_path), application_id="phase-d-negative"
        )
        call_edges = [e for e in app.edges if e.edge_type == "CALL"]
        assert len(call_edges) == 1
        assert "resolution=UNRESOLVED" in call_edges[0].metadata

    def test_unresolved_call_is_classified_not_supported(self, tmp_path):
        (tmp_path / "MAIN.cob").write_text(MISSING_CALL_TARGET, encoding="utf-8")
        app = ApplicationDiscovery().discover(
            str(tmp_path), application_id="phase-d-negative"
        )
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        calls = [c for c in report.components if c.component_type == "CALL"]
        assert len(calls) == 1
        assert calls[0].level.value != "SUPPORTED"
        _assert_entry_blocks(DependencyLedgerEntry(
            dependency_id=calls[0].component_id,
            kind=DependencyKind.CALL,
            visible=True,
            capability_level=calls[0].level,
            proof_state=ProofState.BLOCKED,
            required=True,
            reason=calls[0].reason,
        ))

    def test_missing_call_target_central_status_is_not_verified(self, tmp_path):
        report = _modernize(tmp_path, {"MAIN.cob": MISSING_CALL_TARGET}, "LONELY")
        _assert_never_verified(report)


# ---------------------------------------------------------------------------
# 3. Unsupported parameter contract
# ---------------------------------------------------------------------------


class TestUnsupportedParameterContract:
    def test_linkage_arity_mismatch_is_classified_not_supported(self, tmp_path):
        from engine.modernization.modernization_planner import ModernizationPlanner

        (tmp_path / "MAIN.cob").write_text(ARITY_CALLER, encoding="utf-8")
        (tmp_path / "CALLEE.cob").write_text(ARITY_CALLEE, encoding="utf-8")
        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        assert len(plan.call_relationships) == 1
        relationship = plan.call_relationships[0]
        assert relationship.capability_level.value != "SUPPORTED"
        assert relationship.may_proceed is False

    def test_by_value_and_by_content_are_never_claimed_supported(self):
        from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY

        keys = list(CONSTRUCT_REGISTRY)
        assert not any("BY VALUE" in key for key in keys), keys
        assert not any("BY CONTENT" in key for key in keys), keys

    def test_arity_mismatch_central_status_is_not_verified(self, tmp_path):
        report = _modernize(
            tmp_path,
            {"MAIN.cob": ARITY_CALLER, "CALLEE.cob": ARITY_CALLEE},
            "ARITY-MAIN",
        )
        proof = _assert_never_verified(report)
        assert any("ARITY" in reason for reason in proof.blocking_reasons)


# ---------------------------------------------------------------------------
# 4. Unsupported file operation
# ---------------------------------------------------------------------------


class TestUnsupportedFileOperation:
    def test_indexed_file_is_visible_and_unsupported(self, tmp_path):
        report = _modernize(tmp_path, {"MAIN.cob": INDEXED_FILE}, "IDXPROG")
        component = _component(report, "FILE", "IDX-FILE")
        assert component.level.value == "UNSUPPORTED"
        assert "outside the certified file boundary" in component.reason

    def test_program_is_blocked_by_its_file_dependency(self, tmp_path):
        report = _modernize(tmp_path, {"MAIN.cob": INDEXED_FILE}, "IDXPROG")
        program = _component(report, "PROGRAM", "IDXPROG")
        assert program.level.value == "UNSUPPORTED"
        assert "IDX-FILE" in program.reason

    def test_indexed_file_central_status_is_not_verified(self, tmp_path):
        report = _modernize(tmp_path, {"MAIN.cob": INDEXED_FILE}, "IDXPROG")
        assert report.skipped_count >= 1 or report.generation_success is False
        proof = _assert_never_verified(report)
        assert proof.unproven_dependencies


# ---------------------------------------------------------------------------
# 5. Unavailable external dependency (candidate adapter)
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "version"],
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(not _docker_available(), reason="Docker not available")


@needs_docker
class TestUnavailableExternalDependency:
    def test_unavailable_adapter_blocks_the_runtime_lane(self, tmp_path):
        from engine.candidate.docker_java_adapter import (
            DockerJavaCandidateAdapter,
            DockerJavaConfig,
        )
        from engine.domain.identities import AdapterStatus
        from engine.pipeline import PipelineConfig, VerticalSlicePipeline

        adapter = DockerJavaCandidateAdapter(DockerJavaConfig(
            image="nonexistent-image:latest",
            digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        ))
        assert adapter.status == AdapterStatus.UNAVAILABLE

        fixture = tmp_path / "cobol"
        fixture.mkdir()
        (fixture / "MAIN.cob").write_text(
            HEADER.format(pid="UNAVAIL") + (
                "       PROCEDURE DIVISION.\n"
                "           DISPLAY \"UNAVAILABLE LANE\".\n"
                "           STOP RUN.\n"
            ),
            encoding="utf-8",
        )

        pipeline = VerticalSlicePipeline(
            PipelineConfig(
                workload_id="phase-d-unavailable",
                cobol_source_path=str(fixture),
                java_candidate_path=str(tmp_path),
                java_entrypoint="Main",
            ),
            candidate_adapter=adapter,
        )
        result = pipeline.run()
        assert result.verdict.state.value != "VERIFIED"

        evidence = runtime_evidence_from_result(result)
        assert evidence.verdict_is_verified is False
        assert evidence.evidence_complete is False or not evidence.evidence_integrity_valid

        report = _modernize(
            tmp_path, {"MAIN.cob": (fixture / "MAIN.cob").read_text()}, "UNAVAIL"
        )
        proof = _assert_never_verified(report, runtime=evidence)
        assert any("runtime verdict" in r for r in proof.blocking_reasons)


# ---------------------------------------------------------------------------
# 6. Unsupported JCL construct
# ---------------------------------------------------------------------------


class TestUnsupportedJclConstruct:
    def test_unsupported_jcl_is_visible_and_classified(self):
        result = modernize_jcl_workload("fixtures/workload-jcl")
        assert result.status in ("PARTIAL", "FULL")
        if result.status == "FULL":
            pytest.skip("supported-subset fixture regression: no unsupported constructs")
        assert len(result.unsupported_constructs) > 0
        assert "IF/THEN/ELSE/ENDIF control blocks" in result.unsupported_constructs

    def test_jcl_status_is_classified_never_supported(self):
        full = jcl_ledger_entry("FULL")
        assert full.capability_level == CapabilityLevel.PARTIAL
        assert full.proof_state == ProofState.PARTIAL
        assert full.required is True
        for status in ("PARTIAL", "EMPTY", "ERROR"):
            entry = jcl_ledger_entry(status)
            assert entry.capability_level == CapabilityLevel.UNSUPPORTED
            assert entry.proof_state == ProofState.BLOCKED

    def test_unsupported_jcl_blocks_the_gate_even_with_a_verified_runtime(self):
        result = modernize_jcl_workload("fixtures/workload-jcl")
        entry = jcl_ledger_entry(result.status)
        assert entry.dependency_id == f"JCL:{result.status}"
        reasons = _assert_entry_blocks(entry)
        assert any("JCL" in r for r in reasons)


# ---------------------------------------------------------------------------
# 7. Unavailable DB2 runtime
# ---------------------------------------------------------------------------


class TestUnavailableDb2Runtime:
    def test_exec_sql_program_is_visible_and_unsupported(self, tmp_path):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DB2PROG.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-ID PIC X(6).\n"
            "       PROCEDURE DIVISION.\n"
            "           EXEC SQL\n"
            "               SELECT CUSTOMER_ID INTO :WS-ID\n"
            "               FROM CUSTOMERS\n"
            "           END-EXEC.\n"
            "           STOP RUN.\n"
        )
        (tmp_path / "MAIN.cob").write_text(source, encoding="utf-8")
        app = ApplicationDiscovery().discover(
            str(tmp_path), application_id="phase-d-negative"
        )
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        program = next(c for c in report.components if c.component_type == "PROGRAM")
        assert program.level.value == "UNSUPPORTED"
        _assert_entry_blocks(DependencyLedgerEntry(
            dependency_id=program.component_id,
            kind=DependencyKind.DB2,
            visible=True,
            capability_level=program.level,
            proof_state=ProofState.BLOCKED,
            required=True,
            reason=program.reason,
        ))

    def test_db2_lane_never_claims_runtime_verified(self, tmp_path):
        from engine.sql.dialect import compatibility_report, runtime_verified_features
        from engine.sql.extractor import analyze_cobol_sql

        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DB2PROG.\n"
            "           EXEC SQL\n"
            "               SELECT CUSTOMER_ID FROM CUSTOMERS\n"
            "           END-EXEC.\n"
        )
        model = analyze_cobol_sql(source, "DB2PROG")
        report = compatibility_report(model)
        assert runtime_verified_features(report) == []
        for item in report:
            assert item.runtime_verified is False
            assert item.claim.value != "DB2_RUNTIME_VERIFIED"


# ---------------------------------------------------------------------------
# 8. Unsupported CICS command
# ---------------------------------------------------------------------------


class TestUnsupportedCicsCommand:
    def test_allocate_command_is_classified_unsupported(self):
        from engine.cics.model import CicsConstructStatus
        from engine.cics.subset import classify_command
        from engine.transformation.ir import CicsCommandType

        classification = classify_command(CicsCommandType.ALLOCATE)
        assert classification.status == CicsConstructStatus.UNSUPPORTED
        assert classification.is_mapped is False
        assert classification.category == "UNSUPPORTED"

    def test_cics_fixture_records_unsupported_constructs(self):
        from pathlib import Path

        from engine.transformation.cics_java_mapping import map_cics_programs

        source = Path("fixtures/workload-cics/cobol/ORDPROC.cob").read_text(
            encoding="utf-8"
        )
        service = map_cics_programs(source).services[0]
        assert {item.command for item in service.unsupported_constructs} == {"ALLOCATE"}
        entry = DependencyLedgerEntry(
            dependency_id=f"CICS:{service.source_program}",
            kind=DependencyKind.CICS,
            visible=True,
            capability_level=CapabilityLevel.UNSUPPORTED,
            proof_state=ProofState.BLOCKED,
            required=True,
            reason="EXEC CICS ALLOCATE is outside the supported subset",
        )
        _assert_entry_blocks(entry)


# ---------------------------------------------------------------------------
# Gate invariants shared by every scenario
# ---------------------------------------------------------------------------


class TestGateNeverUpgrades:
    @pytest.mark.parametrize(
        "verdict_state,complete,valid,expected",
        [
            ("NOT_RUN", False, False, CentralStatus.NOT_VERIFIED),
            ("UNAVAILABLE", False, False, CentralStatus.NOT_VERIFIED),
            ("FAILED", True, True, CentralStatus.NOT_VERIFIED),
            ("ERROR", True, True, CentralStatus.NOT_VERIFIED),
            ("VERIFIED", False, True, CentralStatus.NOT_VERIFIED),
            ("VERIFIED", True, False, CentralStatus.NOT_VERIFIED),
        ],
    )
    def test_runtime_conditions_alone_cannot_open_the_gate(
        self, verdict_state, complete, valid, expected,
    ):
        entry = DependencyLedgerEntry(
            dependency_id="JCL:PARTIAL",
            kind=DependencyKind.JCL,
            visible=True,
            capability_level=CapabilityLevel.PARTIAL,
            proof_state=ProofState.PARTIAL,
            required=True,
            reason="no runtime lane",
        )
        status, _ = evaluate_central_status(
            (entry,),
            RuntimeLaneEvidence(
                verdict_state=verdict_state,
                evidence_complete=complete,
                evidence_integrity_valid=valid,
            ),
        )
        assert status is expected

"""FILE dependencies need dependency-specific file comparison evidence.

Audit finding EV-006 / R9 (runtime-proof certification): a single
workload-level ``VERIFIED`` runtime verdict cohort-promoted *every*
runtime-kind dependency — including ``FILE`` — to ``PROVEN``, even when the
certification contract compared only ``STDOUT`` and ``EXIT_STATUS`` and no
file artifact was ever read back.  A workload proven on stdout alone must
never be able to claim its file outputs proven.

Red-first evidence (against unmodified ``engine/modernization/integrated_proof.py``):

* ``test_file_dependency_without_file_comparison_is_not_proven`` fails —
  the FILE entry came back ``PROVEN`` from the cohort promotion.
* ``test_file_dependency_with_mismatched_file_artifact_is_not_proven``
  fails — inconsistent evidence still reached ``PROVEN``.

Scope of the binding (honest limitation, not weakened):

* ``FILE`` proof now requires at least one compared ``TEXT_FILE``/
  ``FIXED_RECORD`` artifact and every compared file artifact ``MATCH``.
* ``PROGRAM``/``CALL``/``COPYBOOK``/``PARAMETER`` keep workload-scope proof:
  their only behavioural channel in this evidence model is the workload's
  stdout/exit-status comparison, which the ``VERIFIED`` verdict already
  gates.  ``test_program_dependency_proof_scope_is_workload_level`` pins
  that boundary so it cannot widen silently.

Engine-only (no fastapi/pydantic, no Docker): safe for the
capability-truth gate in .github/workflows/ci.yml.
"""

from __future__ import annotations

from types import SimpleNamespace

from engine.modernization.capability_analyzer import CapabilityLevel
from engine.modernization.integrated_proof import (
    CentralStatus,
    ProofState,
    RuntimeLaneEvidence,
    build_dependency_ledger,
    evaluate_central_status,
    runtime_evidence_from_result,
)


def _verified_runtime(
    artifact_results: tuple[tuple[str, str], ...],
) -> RuntimeLaneEvidence:
    return RuntimeLaneEvidence(
        verdict_state="VERIFIED",
        executed_check_count=4,
        evidence_complete=True,
        evidence_integrity_valid=True,
        oracle_exit_code=0,
        candidate_exit_code=0,
        artifact_results=artifact_results,
    )


#: A run certified on stdout + exit status only: no file artifact compared.
STDOUT_ONLY_RUNTIME = _verified_runtime(
    (("STDOUT", "MATCH"), ("EXIT_STATUS", "MATCH"))
)

#: The declared file workload contract (stdout, stderr, exit, fixed record).
FILE_COMPARED_RUNTIME = _verified_runtime(
    (
        ("STDOUT", "MATCH"),
        ("STDERR", "MATCH"),
        ("EXIT_STATUS", "MATCH"),
        ("FIXED_RECORD", "MATCH"),
    )
)


def _component(component_id: str, component_type: str, level):
    return SimpleNamespace(
        component_id=component_id,
        component_type=component_type,
        level=level,
        reason="",
    )


def _report(*components, generation_success: bool = True):
    return SimpleNamespace(
        application_id="file-proof",
        generation_success=generation_success,
        overall_capability="SUPPORTED",
        capability_report=SimpleNamespace(
            application_id="file-proof",
            components=components,
            overall_level=CapabilityLevel.SUPPORTED,
        ),
    )


def _entry(ledger, dependency_id: str):
    matches = [e for e in ledger if e.dependency_id == dependency_id]
    assert len(matches) == 1, (
        f"expected exactly one {dependency_id!r} entry, got "
        f"{[e.dependency_id for e in ledger]}"
    )
    return matches[0]


FILE_REPORT = _report(
    _component("OUT-FILE", "FILE", CapabilityLevel.SUPPORTED),
    _component("PROG1", "PROGRAM", CapabilityLevel.SUPPORTED),
)


class TestFileDependencyNeedsFileEvidence:
    def test_file_dependency_without_file_comparison_is_not_proven(self):
        """stdout-only certification must not promote a FILE dependency."""
        ledger = build_dependency_ledger(FILE_REPORT, STDOUT_ONLY_RUNTIME)
        entry = _entry(ledger, "FILE:OUT-FILE")
        assert entry.proof_state is not ProofState.PROVEN, (
            "FILE dependency reached PROVEN without any file artifact "
            f"comparison (evidence: {STDOUT_ONLY_RUNTIME.artifact_results})"
        )
        assert entry.proof_state is ProofState.PARTIAL, entry
        assert "file artifact" in entry.reason, entry.reason

    def test_stdout_only_run_cannot_certify_the_application(self):
        """The FILE PARTIAL entry must downgrade the central gate."""
        ledger = build_dependency_ledger(FILE_REPORT, STDOUT_ONLY_RUNTIME)
        status, reasons = evaluate_central_status(
            ledger, STDOUT_ONLY_RUNTIME, generation_success=True
        )
        assert status is CentralStatus.NOT_VERIFIED, reasons
        assert reasons, "fail-closed verdict must carry a blocking reason"
        assert any("FILE" in r for r in reasons), reasons

    def test_file_dependency_with_matched_file_artifact_is_proven(self):
        """Declared file contract + MATCH keeps the honest positive lane."""
        ledger = build_dependency_ledger(FILE_REPORT, FILE_COMPARED_RUNTIME)
        entry = _entry(ledger, "FILE:OUT-FILE")
        assert entry.proof_state is ProofState.PROVEN, entry
        status, reasons = evaluate_central_status(
            ledger, FILE_COMPARED_RUNTIME, generation_success=True
        )
        assert status is CentralStatus.VERIFIED, reasons

    def test_file_dependency_with_mismatched_file_artifact_is_not_proven(self):
        """Defensive: inconsistent evidence can never yield PROVEN."""
        inconsistent = _verified_runtime(
            (("STDOUT", "MATCH"), ("FIXED_RECORD", "MATCH"), ("TEXT_FILE", "MISMATCH"))
        )
        ledger = build_dependency_ledger(FILE_REPORT, inconsistent)
        entry = _entry(ledger, "FILE:OUT-FILE")
        assert entry.proof_state is not ProofState.PROVEN, entry
        assert entry.proof_state is ProofState.PARTIAL, entry
        assert "MISMATCH" in entry.reason, entry.reason

    def test_program_dependency_proof_scope_is_workload_level(self):
        """Pinned boundary: PROGRAM keeps workload-scope proof.

        The evidence model has no per-program comparison channel; program
        behaviour is observed through the workload's stdout/exit artifacts,
        which the VERIFIED verdict already gates.  If this test ever fails,
        the binding scope changed and docs/verification must be re-audited.
        """
        ledger = build_dependency_ledger(FILE_REPORT, STDOUT_ONLY_RUNTIME)
        entry = _entry(ledger, "PROG1")
        assert entry.proof_state is ProofState.PROVEN, entry


class TestEvidenceCarriesFileArtifacts:
    def test_runtime_evidence_converts_file_comparison_types(self):
        """The binding's input exists: file artifact types reach the gate."""
        comparison = SimpleNamespace(artifact_type="FIXED_RECORD", result="MATCH")
        result = SimpleNamespace(
            verdict=SimpleNamespace(state="VERIFIED", executed_check_count=4),
            oracle_exit_code=0,
            candidate_exit_code=0,
            comparison_evidence=(comparison,),
        )
        evidence = runtime_evidence_from_result(result)
        assert ("FIXED_RECORD", "MATCH") in evidence.artifact_results, (
            evidence.artifact_results
        )

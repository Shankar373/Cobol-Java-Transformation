"""Phase 10 P0-c: the central gate must not verify an empty dependency ledger.

Master README §41 requires the central verdict to combine the trusted runtime
verdict with DEPENDENCY evidence and "every required dependency PROVEN".
Zero enumerated dependencies is a *missing input*, not proof: an empty ledger
must fail closed with an explicit blocking reason, and
``required_dependencies_proven`` (computed in ``api/service.py::_proof_payload``
— covered in tests/test_phase10_p0_proof_trust_api.py) must not be vacuously
true.

Red-first evidence: ``test_empty_ledger_cannot_open_the_gate`` fails against
unmodified code (``evaluate_central_status((), perfect_runtime)`` returned
``(VERIFIED, ())``).

Engine-only (no fastapi/pydantic): safe for the dependency-free
capability-truth gate in .github/workflows/ci.yml.
"""

from __future__ import annotations

from engine.modernization.capability_analyzer import CapabilityLevel
from engine.modernization.integrated_proof import (
    CentralStatus,
    DependencyKind,
    DependencyLedgerEntry,
    ProofState,
    RuntimeLaneEvidence,
    build_dependency_ledger,
    evaluate_central_status,
)

PERFECT_RUNTIME = RuntimeLaneEvidence(
    verdict_state="VERIFIED",
    executed_check_count=4,
    evidence_complete=True,
    evidence_integrity_valid=True,
    oracle_exit_code=0,
    candidate_exit_code=0,
)


def _proven_program_entry() -> DependencyLedgerEntry:
    return DependencyLedgerEntry(
        dependency_id="PROGRAM:P1",
        kind=DependencyKind.PROGRAM,
        visible=True,
        capability_level=CapabilityLevel.SUPPORTED,
        proof_state=ProofState.PROVEN,
        required=True,
        reason="",
    )


class _CapabilityLessReport:
    """Report without any capability analysis (probe F-2b shape)."""

    application_id = "app-empty-ledger"
    generation_success = True
    overall_capability = ""
    capability_report = None


class TestEmptyLedgerFailsClosed:
    """§41/§53.9: a ledger with zero dependency evidence can never verify."""

    def test_empty_ledger_cannot_open_the_gate(self):
        status, reasons = evaluate_central_status(
            (), PERFECT_RUNTIME, generation_success=True
        )
        assert status is CentralStatus.NOT_VERIFIED, (
            "P0-c: empty ledger + perfect runtime certified VERIFIED (fail-open)"
        )
        assert reasons, "the fail-closed verdict must carry a blocking reason"
        assert any(
            "ledger" in r.lower() or "dependenc" in r.lower() for r in reasons
        ), reasons

    def test_capability_less_report_yields_empty_ledger_and_fails_closed(self):
        ledger = build_dependency_ledger(_CapabilityLessReport(), PERFECT_RUNTIME)
        assert ledger == (), "test setup: no capability analysis => empty ledger"
        status, reasons = evaluate_central_status(
            ledger, PERFECT_RUNTIME, generation_success=True
        )
        assert status is CentralStatus.NOT_VERIFIED, (
            "P0-c: a capability-less report resolved to central VERIFIED"
        )
        assert reasons

    def test_proven_required_entry_still_verifies(self):
        """Regression: a real ledger with all required entries PROVEN verifies."""
        status, reasons = evaluate_central_status(
            (_proven_program_entry(),), PERFECT_RUNTIME, generation_success=True
        )
        assert status is CentralStatus.VERIFIED
        assert reasons == ()

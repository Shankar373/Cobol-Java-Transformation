"""Verdict derivation engine.

Implements the strict seven-state verdict model as defined by VERDICT_CONTRACT.md.
Verdict derivation MUST be driven by evidence.
Verdict derivation is deterministic and testable as a pure function over the evidence model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.domain.identities import VerdictState, WorkloadId
from engine.evidence.models import EvidenceManifest


class VerdictDerivationError(Exception):
    """Raised when verdict derivation fails."""


@dataclass(frozen=True)
class Verdict:
    """A derived verdict with complete scope."""
    state: VerdictState
    workload_id: WorkloadId
    run_id: str
    source_hash: str
    candidate_hash: str | None
    oracle_id: str
    oracle_digest: str
    executed_check_count: int
    skipped_count: int
    unavailable_count: int
    supported_scope_statement: str
    evidence_manifest_hash: str
    derivation_timestamp: str
    differences: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "state": self.state.value,
            "workload_id": self.workload_id.value,
            "run_id": self.run_id,
            "source_hash": self.source_hash,
            "candidate_hash": self.candidate_hash,
            "oracle_id": self.oracle_id,
            "oracle_digest": self.oracle_digest,
            "executed_check_count": self.executed_check_count,
            "skipped_count": self.skipped_count,
            "unavailable_count": self.unavailable_count,
            "supported_scope_statement": self.supported_scope_statement,
            "evidence_manifest_hash": self.evidence_manifest_hash,
            "derivation_timestamp": self.derivation_timestamp,
            "differences": list(self.differences),
        }


class VerdictDeriver:
    """Derives verdicts from evidence manifests. Pure function — no side effects."""

    def __init__(self) -> None:
        self._supported_scope = (
            "V1 validation scope: "
            "GnuCOBOL 3.1.2.0 oracle, plain Java candidate, "
            "artifacts: STDOUT, STDERR, EXIT_STATUS, TEXT_FILE, FIXED_RECORD; "
            "INDEXED/RELATIVE/SQL/DATABASE excluded (UNSUPPORTED); "
            "substring containment permanently forbidden."
        )

    def derive(self, manifest: EvidenceManifest) -> Verdict:
        """Derive a verdict from an evidence manifest. Pure function."""
        # Step 1: Check for platform/validator errors first
        error_state = self._check_for_errors(manifest)
        if error_state is not None:
            return self._create_verdict(
                state=error_state,
                manifest=manifest,
                differences=("Platform/validator error detected",),
            )

        # Step 2: Check for unavailable infrastructure
        unavailable_state = self._check_for_unavailable(manifest)
        if unavailable_state is not None:
            return self._create_verdict(
                state=unavailable_state,
                manifest=manifest,
                differences=("Required infrastructure unavailable",),
            )

        # Step 3: Check for unsupported artifacts
        unsupported_state = self._check_for_unsupported(manifest)
        if unsupported_state is not None:
            return self._create_verdict(
                state=unsupported_state,
                manifest=manifest,
                differences=("Unsupported artifact type encountered",),
            )

        # Step 4: Check for missing evidence
        if not manifest.is_complete():
            return self._create_verdict(
                state=VerdictState.UNPROVEN,
                manifest=manifest,
                differences=("Incomplete evidence manifest",),
            )

        # Step 5: Check for zero executed checks
        executed_checks = len(manifest.comparison_evidence)
        if executed_checks == 0:
            return self._create_verdict(
                state=VerdictState.UNPROVEN,
                manifest=manifest,
                differences=("Zero executed checks",),
            )

        # Step 6: Analyze comparison results
        differences = []
        has_mismatch = False
        has_inconclusive = False

        for comp in manifest.comparison_evidence:
            if comp.result == "MISMATCH":
                has_mismatch = True
                differences.extend(comp.differences)
            elif comp.result == "INCONCLUSIVE":
                has_inconclusive = True

        # Step 7: Derive final verdict
        if has_mismatch:
            state = VerdictState.FAILED
        elif has_inconclusive:
            state = VerdictState.PARTIAL
        else:
            state = VerdictState.VERIFIED

        return self._create_verdict(
            state=state,
            manifest=manifest,
            differences=tuple(differences),
        )

    def _check_for_errors(self, manifest: EvidenceManifest) -> VerdictState | None:
        """Check for platform/validator execution errors."""
        for execution in manifest.execution_evidence:
            if execution.termination_status == "error":
                return VerdictState.ERROR
            if execution.timeout_applied:
                return VerdictState.ERROR
        return None

    def _check_for_unavailable(self, manifest: EvidenceManifest) -> VerdictState | None:
        """Check for unavailable infrastructure.

        For the oracle: any non-"normal" status means the reference failed
        and cannot be used as ground truth. This includes nonzero_exit.

        For the candidate: only "error" and "timeout" indicate infrastructure
        unavailability. A nonzero_exit means the program ran but failed
        logically — output can still be compared to the oracle.
        """
        oracle_unavailable_statuses = {"error", "timeout", "nonzero_exit"}
        candidate_unavailable_statuses = {"error", "timeout"}

        # Check if oracle execution succeeded
        oracle_executions = [
            e for e in manifest.execution_evidence
            if e.runtime_id.startswith("oracle")
        ]
        if not oracle_executions:
            return VerdictState.UNAVAILABLE
        if all(e.termination_status in oracle_unavailable_statuses for e in oracle_executions):
            return VerdictState.UNAVAILABLE

        # Check if candidate execution succeeded
        candidate_executions = [
            e for e in manifest.execution_evidence
            if e.runtime_id.startswith("candidate")
        ]
        if not candidate_executions:
            return VerdictState.UNAVAILABLE
        if all(e.termination_status in candidate_unavailable_statuses for e in candidate_executions):
            return VerdictState.UNAVAILABLE

        return None

    def _check_for_unsupported(self, manifest: EvidenceManifest) -> VerdictState | None:
        """Check for unsupported artifact types."""
        supported_types = {"STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"}
        for artifact in manifest.artifact_evidence:
            if artifact.artifact.artifact_type not in supported_types:
                return VerdictState.UNSUPPORTED
        return None

    def _create_verdict(
        self,
        state: VerdictState,
        manifest: EvidenceManifest,
        differences: tuple[str, ...] = (),
    ) -> Verdict:
        """Create a verdict with complete scope."""
        from datetime import datetime, timezone

        executed_checks = len(manifest.comparison_evidence)
        skipped_count = 0  # V1: no skipping
        unavailable_count = sum(
            1 for e in manifest.execution_evidence
            if e.termination_status != "normal"
        )

        return Verdict(
            state=state,
            workload_id=manifest.workload_id,
            run_id=manifest.run_id.value,
            source_hash=str(manifest.source_identity.source_hash),
            candidate_hash=str(manifest.candidate_identity.candidate_hash) if manifest.candidate_identity else None,
            oracle_id=manifest.oracle_identity.oracle_id,
            oracle_digest=manifest.oracle_identity.image_digest,
            executed_check_count=executed_checks,
            skipped_count=skipped_count,
            unavailable_count=unavailable_count,
            supported_scope_statement=self._supported_scope,
            evidence_manifest_hash=str(manifest.manifest_hash),
            derivation_timestamp=datetime.now(timezone.utc).isoformat(),
            differences=differences,
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def derive_verdict(manifest: EvidenceManifest) -> Verdict:
    """Derive a verdict from an evidence manifest. Pure function."""
    deriver = VerdictDeriver()
    return deriver.derive(manifest)

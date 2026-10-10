"""Evidence integrity and binding validation.

This module implements the trust-boundary admission layer between
raw/untrusted evidence and the pure VerdictDeriver.

Architecture:

    raw/untrusted EvidenceManifest
            ↓
    EvidenceIntegrityValidator.validate()
            ↓
    ValidatedEvidenceManifest  (or IntegrityViolation)
            ↓
    VerdictDeriver.derive()

The VerdictDeriver remains pure. This module is responsible for
proving that the evidence is internally consistent before it
reaches the verdict derivation.

FINDINGS ADDRESSED:
- A: Forged but structurally valid evidence → validation layer rejects
- B: Cross-run artifact replay → run binding enforced
- C: Cross-workload artifact replay → workload binding enforced
- D: Oracle identity recording without verification → execution binding enforced
- E: Candidate/source binding → source_hash consistency enforced
- F: Candidate nonzero exit → EXIT_STATUS completeness enforced
- G: Manifest hash too weak → complete evidence graph hashing
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from engine.domain.identities import (
    ContentHash,
)
from engine.evidence.models import (
    EvidenceManifest,
)

# ---------------------------------------------------------------------------
# Violation types
# ---------------------------------------------------------------------------

class ViolationType(Enum):
    """Types of evidence integrity violations."""
    RUN_BINDING_MISMATCH = "run_binding_mismatch"
    WORKLOAD_BINDING_MISMATCH = "workload_binding_mismatch"
    SOURCE_CANDIDATE_MISMATCH = "source_candidate_mismatch"
    ORACLE_IDENTITY_MISMATCH = "oracle_identity_mismatch"
    IMAGE_IDENTITY_MISMATCH = "image_identity_mismatch"
    ARTIFACT_EXECUTION_MISMATCH = "artifact_execution_mismatch"
    COMPARISON_ARTIFACT_MISMATCH = "comparison_artifact_mismatch"
    COMPARATOR_BINDING_MISMATCH = "comparator_binding_mismatch"
    CONTENT_HASH_MISMATCH = "content_hash_mismatch"
    MANIFEST_HASH_MISMATCH = "manifest_hash_mismatch"
    SOURCE_MUTATION = "source_mutation"
    UNKNOWN_COMPARISON_RESULT = "unknown_comparison_result"
    MISSING_REQUIRED_EVIDENCE = "missing_required_evidence"
    MISSING_EXIT_STATUS = "missing_exit_status"
    CROSS_RUN_REPLAY = "cross_run_replay"
    CROSS_WORKLOAD_REPLAY = "cross_workload_replay"
    ORPHAN_ARTIFACT = "orphan_artifact"
    ORPHAN_COMPARISON = "orphan_comparison"
    MALFORMED_EVIDENCE = "malformed_evidence"


#: Comparison results the evidence model accepts. Anything else is
#: unrecognised evidence and must fail closed (never treated as MATCH).
KNOWN_COMPARISON_RESULTS = frozenset({"MATCH", "MISMATCH", "INCONCLUSIVE"})


@dataclass(frozen=True)
class IntegrityViolation:
    """A single evidence integrity violation."""
    violation_type: ViolationType
    description: str
    field_path: str
    expected: str
    actual: str


# ---------------------------------------------------------------------------
# Validated manifest wrapper
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidatedEvidenceManifest:
    """Evidence manifest that has passed integrity/binding validation.

    This type distinction ensures that VerdictDeriver can only receive
    evidence that has been validated through the trust-boundary layer.
    """
    manifest: EvidenceManifest
    integrity_hash: ContentHash
    validated_at: str
    validation_summary: str


# ---------------------------------------------------------------------------
# EvidenceIntegrityValidator
# ---------------------------------------------------------------------------

class EvidenceIntegrityValidator:
    """Validates evidence manifest integrity and bindings.

    This is the trust-boundary admission layer. Raw evidence must pass
    through this validator before reaching VerdictDeriver.

    The validator does NOT:
    - Execute any code from the evidence
    - Access the filesystem
    - Make network calls
    - Call Docker
    - Modify the manifest

    The validator IS a pure function over the manifest content,
    checking structural invariants and binding consistency.
    """

    def validate(self, manifest: EvidenceManifest) -> ValidatedEvidenceManifest | list[IntegrityViolation]:
        """Validate an evidence manifest. Returns ValidatedEvidenceManifest
        on success, or list of IntegrityViolation on failure.

        This is the single entry point for trust-boundary admission.
        """
        violations: list[IntegrityViolation] = []

        # 1. Run binding validation (FINDING B)
        violations.extend(self._validate_run_bindings(manifest))

        # 2. Workload binding validation (FINDING C)
        violations.extend(self._validate_workload_bindings(manifest))

        # 3. Source/candidate binding (FINDING E)
        violations.extend(self._validate_source_candidate_binding(manifest))

        # 4. Oracle identity binding (FINDING D)
        violations.extend(self._validate_oracle_binding(manifest))

        # 5. Artifact-execution binding
        violations.extend(self._validate_artifact_execution_binding(manifest))

        # 6. Comparison-artifact binding
        violations.extend(self._validate_comparison_artifact_binding(manifest))

        # 6b. Comparator binding: evidence must name the comparator that is
        # registered for the artifact type it claims to have compared
        violations.extend(self._validate_comparator_binding(manifest))

        # 6c. Comparison result domain: unknown results never count as MATCH
        violations.extend(self._validate_comparison_results(manifest))

        # 6d. Source mutation: execution must not modify the source tree
        violations.extend(self._validate_source_mutation(manifest))

        # 7. EXIT_STATUS completeness (FINDING F)
        violations.extend(self._validate_exit_status_completeness(manifest))

        # 8. Manifest hash integrity (FINDING G)
        violations.extend(self._validate_manifest_integrity(manifest))

        # 9. Required evidence presence
        violations.extend(self._validate_required_evidence(manifest))

        if violations:
            return violations

        # Compute integrity hash over the complete evidence graph
        integrity_hash = self._compute_integrity_hash(manifest)

        return ValidatedEvidenceManifest(
            manifest=manifest,
            integrity_hash=integrity_hash,
            validated_at=datetime.now(timezone.utc).isoformat(),
            validation_summary="All binding and integrity checks passed",
        )

    # ------------------------------------------------------------------
    # FINDING B: Cross-run binding
    # ------------------------------------------------------------------

    def _validate_run_bindings(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """All nested evidence must be bound to the manifest's run_id."""
        violations: list[IntegrityViolation] = []
        expected_run = manifest.run_id.value

        # Check execution evidence
        for i, exec_ev in enumerate(manifest.execution_evidence):
            if exec_ev.run_id.value != expected_run:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.CROSS_RUN_REPLAY,
                    description=f"Execution evidence [{i}] has run_id '{exec_ev.run_id.value}' "
                                f"but manifest declares '{expected_run}'",
                    field_path=f"execution_evidence[{i}].run_id",
                    expected=expected_run,
                    actual=exec_ev.run_id.value,
                ))

        # Check artifact evidence — artifacts are bound to execution_id,
        # which is bound to run_id through execution evidence
        valid_exec_ids = {
            e.execution_id.value for e in manifest.execution_evidence
            if e.run_id.value == expected_run
        }
        for i, art_ev in enumerate(manifest.artifact_evidence):
            if art_ev.execution_id.value not in valid_exec_ids:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.CROSS_RUN_REPLAY,
                    description=f"Artifact evidence [{i}] has execution_id "
                                f"'{art_ev.execution_id.value}' not found in "
                                f"manifest execution evidence for run '{expected_run}'",
                    field_path=f"artifact_evidence[{i}].execution_id",
                    expected=f"one of {valid_exec_ids}",
                    actual=art_ev.execution_id.value,
                ))

        # Check comparison evidence
        for i, comp_ev in enumerate(manifest.comparison_evidence):
            if comp_ev.run_id.value != expected_run:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.CROSS_RUN_REPLAY,
                    description=f"Comparison evidence [{i}] has run_id "
                                f"'{comp_ev.run_id.value}' but manifest declares '{expected_run}'",
                    field_path=f"comparison_evidence[{i}].run_id",
                    expected=expected_run,
                    actual=comp_ev.run_id.value,
                ))

        return violations

    # ------------------------------------------------------------------
    # FINDING C: Cross-workload binding
    # ------------------------------------------------------------------

    def _validate_workload_bindings(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Validate that evidence is bound to the manifest's workload.

        Evidence produced by the pipeline carries its workload id. Evidence
        whose workload id is present but different from the manifest's is
        cross-workload replay; evidence without a workload id is bound
        transitively through execution_id → run_id.
        """
        violations: list[IntegrityViolation] = []
        expected_workload = manifest.workload_id.value

        for i, exec_ev in enumerate(manifest.execution_evidence):
            if exec_ev.workload_id is None:
                continue
            if exec_ev.workload_id.value != expected_workload:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.WORKLOAD_BINDING_MISMATCH,
                    description=f"Execution evidence [{i}] is bound to workload "
                                f"'{exec_ev.workload_id.value}' but manifest declares "
                                f"'{expected_workload}'",
                    field_path=f"execution_evidence[{i}].workload_id",
                    expected=expected_workload,
                    actual=exec_ev.workload_id.value,
                ))

        for i, comp_ev in enumerate(manifest.comparison_evidence):
            if comp_ev.workload_id is None:
                continue
            if comp_ev.workload_id.value != expected_workload:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.WORKLOAD_BINDING_MISMATCH,
                    description=f"Comparison evidence [{i}] is bound to workload "
                                f"'{comp_ev.workload_id.value}' but manifest declares "
                                f"'{expected_workload}'",
                    field_path=f"comparison_evidence[{i}].workload_id",
                    expected=expected_workload,
                    actual=comp_ev.workload_id.value,
                ))

        # Artifacts replayed from another workload surface as executions or
        # comparisons from that workload; an artifact bound to an execution of
        # a different workload is caught through the execution chain above.
        return violations

    # ------------------------------------------------------------------
    # FINDING E: Source/candidate binding
    # ------------------------------------------------------------------

    def _validate_source_candidate_binding(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Candidate's source_hash must match the manifest's source hash."""
        violations: list[IntegrityViolation] = []

        if manifest.candidate_identity is not None:
            candidate = manifest.candidate_identity
            manifest_source_hash = str(manifest.source_identity.source_hash)
            candidate_source_hash = str(candidate.source_hash)

            if candidate_source_hash != manifest_source_hash:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.SOURCE_CANDIDATE_MISMATCH,
                    description=f"Candidate source_hash '{candidate_source_hash}' "
                                f"does not match manifest source_hash '{manifest_source_hash}'",
                    field_path="candidate_identity.source_hash",
                    expected=manifest_source_hash,
                    actual=candidate_source_hash,
                ))

        return violations

    # ------------------------------------------------------------------
    # FINDING D: Oracle identity binding
    # ------------------------------------------------------------------

    def _validate_oracle_binding(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Oracle execution evidence must be bound to the manifest's oracle identity."""
        violations: list[IntegrityViolation] = []

        # Check that oracle execution evidence exists and has valid runtime_id
        oracle_execs = [
            e for e in manifest.execution_evidence
            if e.runtime_id.startswith("oracle")
        ]

        if not oracle_execs and manifest.oracle_identity is not None:
            # No oracle execution evidence — this is caught by
            # _validate_required_evidence, but we also check identity binding
            pass

        # Verify that oracle identity is present
        if manifest.oracle_identity is None:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.ORACLE_IDENTITY_MISMATCH,
                description="Manifest has no oracle_identity",
                field_path="oracle_identity",
                expected="non-null OracleIdentity",
                actual="None",
            ))
            return violations

        # The image identity actually executed must equal the identity the
        # manifest claims. Evidence without a recorded image identity cannot
        # prove this binding and is left to the other checks; evidence with a
        # recorded identity must match exactly.
        expected_digest = manifest.oracle_identity.image_digest
        for i, exec_ev in enumerate(oracle_execs):
            if exec_ev.image_digest is None:
                continue
            if exec_ev.image_digest != expected_digest:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.IMAGE_IDENTITY_MISMATCH,
                    description=f"Oracle execution [{i}] ran image "
                                f"'{exec_ev.image_digest}' but manifest claims "
                                f"oracle identity '{expected_digest}'",
                    field_path=f"execution_evidence[{i}].image_digest",
                    expected=expected_digest,
                    actual=exec_ev.image_digest,
                ))

        return violations

    # ------------------------------------------------------------------
    # Artifact-execution binding
    # ------------------------------------------------------------------

    def _validate_artifact_execution_binding(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Each artifact's execution_id must reference a valid execution."""
        violations: list[IntegrityViolation] = []
        valid_exec_ids = {e.execution_id.value for e in manifest.execution_evidence}

        for i, art_ev in enumerate(manifest.artifact_evidence):
            if art_ev.execution_id.value not in valid_exec_ids:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.ARTIFACT_EXECUTION_MISMATCH,
                    description=f"Artifact [{i}] references execution_id "
                                f"'{art_ev.execution_id.value}' not in manifest execution evidence",
                    field_path=f"artifact_evidence[{i}].execution_id",
                    expected=f"one of {valid_exec_ids}",
                    actual=art_ev.execution_id.value,
                ))

        return violations

    # ------------------------------------------------------------------
    # Comparison-artifact binding
    # ------------------------------------------------------------------

    def _validate_comparison_artifact_binding(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Each comparison must reference artifacts present in the manifest."""
        violations: list[IntegrityViolation] = []
        valid_artifact_ids = {a.artifact.artifact_id for a in manifest.artifact_evidence}

        for i, comp_ev in enumerate(manifest.comparison_evidence):
            if comp_ev.oracle_artifact_id not in valid_artifact_ids:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.COMPARISON_ARTIFACT_MISMATCH,
                    description=f"Comparison [{i}] references oracle_artifact_id "
                                f"'{comp_ev.oracle_artifact_id}' not in manifest artifact evidence",
                    field_path=f"comparison_evidence[{i}].oracle_artifact_id",
                    expected=f"one of {valid_artifact_ids}",
                    actual=comp_ev.oracle_artifact_id,
                ))
            if comp_ev.candidate_artifact_id not in valid_artifact_ids:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.COMPARISON_ARTIFACT_MISMATCH,
                    description=f"Comparison [{i}] references candidate_artifact_id "
                                f"'{comp_ev.candidate_artifact_id}' not in manifest artifact evidence",
                    field_path=f"comparison_evidence[{i}].candidate_artifact_id",
                    expected=f"one of {valid_artifact_ids}",
                    actual=comp_ev.candidate_artifact_id,
                ))

        return violations

    # ------------------------------------------------------------------
    # Comparator binding: evidence must be attributed to the comparator
    # registered for the artifact type it claims to have compared
    # ------------------------------------------------------------------

    def _validate_comparator_binding(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Each comparison must be attributed to the registered comparator
        for its artifact type (canonical id or a declared legacy alias)."""
        from engine.comparators.framework import (
            CANONICAL_COMPARATOR_IDS,
            COMPARATOR_ID_ALIASES,
        )

        violations: list[IntegrityViolation] = []
        for i, comp_ev in enumerate(manifest.comparison_evidence):
            expected = CANONICAL_COMPARATOR_IDS.get(comp_ev.artifact_type)
            if expected is None:
                # Unknown artifact types are rejected by the deriver
                # (UNSUPPORTED); nothing to bind here.
                continue
            resolved = COMPARATOR_ID_ALIASES.get(
                comp_ev.comparator_id, comp_ev.comparator_id
            )
            if resolved != expected:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.COMPARATOR_BINDING_MISMATCH,
                    description=f"Comparison [{i}] for artifact_type="
                                f"{comp_ev.artifact_type!r} is attributed to "
                                f"comparator {comp_ev.comparator_id!r} but the "
                                f"registered comparator is {expected!r}",
                    field_path=f"comparison_evidence[{i}].comparator_id",
                    expected=expected,
                    actual=comp_ev.comparator_id,
                ))
        return violations

    # ------------------------------------------------------------------
    # Comparison result domain: unknown results fail closed
    # ------------------------------------------------------------------

    def _validate_comparison_results(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Comparison results outside MATCH/MISMATCH/INCONCLUSIVE are
        unrecognised evidence and must never be read as a match."""
        violations: list[IntegrityViolation] = []
        for i, comp_ev in enumerate(manifest.comparison_evidence):
            if comp_ev.result not in KNOWN_COMPARISON_RESULTS:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.UNKNOWN_COMPARISON_RESULT,
                    description=f"Comparison [{i}] has unknown result "
                                f"{comp_ev.result!r}; known results are "
                                f"{sorted(KNOWN_COMPARISON_RESULTS)}",
                    field_path=f"comparison_evidence[{i}].result",
                    expected=f"one of {sorted(KNOWN_COMPARISON_RESULTS)}",
                    actual=comp_ev.result,
                ))
        return violations

    # ------------------------------------------------------------------
    # Source mutation: an execution must not modify the source tree
    # ------------------------------------------------------------------

    def _validate_source_mutation(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Source-tree hashes recorded before and after an execution must be
        identical: execution stages sources read-only and never rewrites them."""
        violations: list[IntegrityViolation] = []
        for i, exec_ev in enumerate(manifest.execution_evidence):
            before = str(exec_ev.source_tree_hash_before)
            after = str(exec_ev.source_tree_hash_after)
            if before != after:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.SOURCE_MUTATION,
                    description=f"Execution [{i}] ({exec_ev.runtime_id}) modified "
                                f"the source tree during execution",
                    field_path=f"execution_evidence[{i}].source_tree_hash_after",
                    expected=before,
                    actual=after,
                ))
        return violations

    # ------------------------------------------------------------------
    # FINDING F: EXIT_STATUS completeness
    # ------------------------------------------------------------------

    def _validate_exit_status_completeness(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """If candidate has nonzero_exit, EXIT_STATUS must be present
        in both artifact and comparison evidence."""
        violations: list[IntegrityViolation] = []

        # Check if any candidate execution has nonzero_exit
        has_nonzero_candidate = any(
            e.runtime_id.startswith("candidate") and e.termination_status == "nonzero_exit"
            for e in manifest.execution_evidence
        )

        if has_nonzero_candidate:
            # EXIT_STATUS must be in artifact evidence for both roles
            artifact_types = {a.artifact.artifact_type for a in manifest.artifact_evidence}
            if "EXIT_STATUS" not in artifact_types:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.MISSING_EXIT_STATUS,
                    description="Candidate has nonzero_exit but EXIT_STATUS "
                                "is not in artifact evidence",
                    field_path="artifact_evidence",
                    expected="EXIT_STATUS present",
                    actual="EXIT_STATUS absent",
                ))

            # EXIT_STATUS must be in comparison evidence
            comparison_types = {c.artifact_type for c in manifest.comparison_evidence}
            if "EXIT_STATUS" not in comparison_types:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.MISSING_EXIT_STATUS,
                    description="Candidate has nonzero_exit but EXIT_STATUS "
                                "is not in comparison evidence",
                    field_path="comparison_evidence",
                    expected="EXIT_STATUS comparison present",
                    actual="EXIT_STATUS comparison absent",
                ))

        return violations

    # ------------------------------------------------------------------
    # FINDING G: Manifest integrity (strengthened)
    # ------------------------------------------------------------------

    def _validate_manifest_integrity(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Verify the manifest's construction-time seal still matches the
        current evidence graph.

        The seal is captured when the manifest is constructed. Recomputing
        the canonical graph and comparing it against the seal detects any
        in-place mutation of evidence after construction — including
        mutations that keep every individual field type-valid.
        """
        violations: list[IntegrityViolation] = []

        sealed = manifest.sealed_hash
        recomputed = manifest.manifest_hash

        if sealed is None:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MANIFEST_HASH_MISMATCH,
                description="Manifest carries no construction-time seal; "
                            "evidence integrity cannot be established",
                field_path="sealed_hash",
                expected="sha256 seal of the evidence graph",
                actual="None",
            ))
        elif sealed != recomputed:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MANIFEST_HASH_MISMATCH,
                description="Manifest evidence was mutated after construction: "
                            "the construction-time seal no longer matches the "
                            "current evidence graph",
                field_path="sealed_hash",
                expected=str(sealed),
                actual=str(recomputed),
            ))

        return violations

    # ------------------------------------------------------------------
    # Required evidence presence
    # ------------------------------------------------------------------

    def _validate_required_evidence(self, manifest: EvidenceManifest) -> list[IntegrityViolation]:
        """Validate the minimum evidence contract required for certification."""
        violations: list[IntegrityViolation] = []
        if not manifest.execution_evidence:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MISSING_REQUIRED_EVIDENCE,
                description="No execution evidence in manifest",
                field_path="execution_evidence",
                expected="oracle and candidate execution evidence",
                actual="0",
            ))
            return violations

        oracle_execs = [e for e in manifest.execution_evidence if e.runtime_id.startswith("oracle")]
        candidate_execs = [e for e in manifest.execution_evidence if e.runtime_id.startswith("candidate")]
        if not oracle_execs:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MISSING_REQUIRED_EVIDENCE,
                description="No oracle execution evidence",
                field_path="execution_evidence",
                expected="at least 1 oracle execution",
                actual="0 oracle executions",
            ))
        if not candidate_execs:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MISSING_REQUIRED_EVIDENCE,
                description="No candidate execution evidence",
                field_path="execution_evidence",
                expected="at least 1 candidate execution",
                actual="0 candidate executions",
            ))
        elif not any(e.execution_phase == "EXECUTE" for e in candidate_execs):
            phases = sorted({e.execution_phase for e in candidate_execs})
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MISSING_REQUIRED_EVIDENCE,
                description="Candidate evidence contains no executed run: "
                            "a build failure is not execution evidence",
                field_path="execution_evidence",
                expected="at least 1 candidate execution with phase EXECUTE",
                actual=f"phases present: {phases}",
            ))

        oracle_ids = {e.execution_id.value for e in oracle_execs}
        candidate_ids = {e.execution_id.value for e in candidate_execs}
        oracle_artifacts = [a for a in manifest.artifact_evidence if a.execution_id.value in oracle_ids]
        candidate_artifacts = [a for a in manifest.artifact_evidence if a.execution_id.value in candidate_ids]
        if not oracle_artifacts:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MISSING_REQUIRED_EVIDENCE,
                description="No oracle artifact evidence",
                field_path="artifact_evidence",
                expected="at least 1 oracle artifact",
                actual="0 oracle artifacts",
            ))
        if not candidate_artifacts:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MISSING_REQUIRED_EVIDENCE,
                description="No candidate artifact evidence",
                field_path="artifact_evidence",
                expected="at least 1 candidate artifact",
                actual="0 candidate artifacts",
            ))

        compared_ids = {
            artifact_id
            for comparison in manifest.comparison_evidence
            for artifact_id in (comparison.oracle_artifact_id, comparison.candidate_artifact_id)
        }
        for artifact in manifest.artifact_evidence:
            if artifact.artifact.artifact_id not in compared_ids:
                violations.append(IntegrityViolation(
                    violation_type=ViolationType.MISSING_REQUIRED_EVIDENCE,
                    description=f"Artifact '{artifact.artifact.artifact_id}' is not covered by any comparison",
                    field_path="comparison_evidence",
                    expected=f"comparison referencing {artifact.artifact.artifact_id}",
                    actual="artifact is unreferenced",
                ))
        if not manifest.comparison_evidence:
            violations.append(IntegrityViolation(
                violation_type=ViolationType.MISSING_REQUIRED_EVIDENCE,
                description="No comparison evidence in manifest",
                field_path="comparison_evidence",
                expected="at least 1 comparison",
                actual="0 comparisons",
            ))
        return violations

    # ------------------------------------------------------------------
    # FINDING G: Strengthened integrity hash
    # ------------------------------------------------------------------

    def _compute_integrity_hash(self, manifest: EvidenceManifest) -> ContentHash:
        """Compute a comprehensive integrity hash over the entire evidence graph.

        Delegates to the canonical evidence graph used for the manifest's
        construction-time seal, so the validated hash and the seal always
        cover the same fields: top-level identities, controlled inputs,
        environment identities, and every execution, artifact, and comparison
        evidence field.

        This is a deterministic, complete content-addressed representation
        of the evidence graph. Any modification to any covered field changes
        the hash.
        """
        return manifest.manifest_hash

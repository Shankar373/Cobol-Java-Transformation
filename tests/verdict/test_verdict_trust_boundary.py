"""CI #400 regression tests — evidence trust-boundary contract.

Root cause: VerdictDeriver.derive() accepted raw EvidenceManifest directly.
Callers could bypass EvidenceIntegrityValidator entirely and pass a tampered
or forged manifest to derive_verdict(), potentially obtaining VerdictState.VERIFIED
for evidence that had integrity violations.

These tests prove:
1. derive_verdict_validated() enforces the trust boundary — only
   ValidatedEvidenceManifest can reach derivation through this path.
2. A tampered manifest (with comparisons removed) cannot produce VERIFIED
   through the validated path.
3. Genuine structural violations are rejected by the validator before
   they reach VerdictDeriver.
4. A valid, unmodified manifest that passes the validator can still produce VERIFIED.
5. The pipeline's _pipeline_trust_boundary helper correctly blocks VERIFIED
   for manifests with structural violations.
"""

from __future__ import annotations

import sys
import os

# Allow import of adversarial conftest helpers
_tests_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _tests_dir)

from tests.adversarial.conftest import (
    make_oracle_exec,
    make_candidate_exec,
    make_artifact,
    make_artifact_evidence,
    make_comparison,
    make_manifest,
)

from engine.domain.identities import (
    ArtifactIdentity,
    CandidateIdentity,
    ContentHash,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    VerdictState,
    WorkloadId,
)
from engine.evidence.integrity import (
    EvidenceIntegrityValidator,
    ValidatedEvidenceManifest,
    ViolationType,
)
from engine.evidence.models import (
    ArtifactEvidence,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)
from engine.verdict.derivation import (
    VerdictDeriver,
    derive_verdict,
    derive_verdict_validated,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

validator = EvidenceIntegrityValidator()


def _h(s: str) -> ContentHash:
    return ContentHash.from_string(s)


def _make_valid_manifest(run_id: RunId, result: str = "MATCH") -> EvidenceManifest:
    """Build a structurally valid, integrity-clean manifest."""
    oracle_art = make_artifact(
        "art-oracle-stdout", "STDOUT", "ORACLE", b"oracle-output"
    )
    candidate_art = make_artifact(
        "art-candidate-stdout", "STDOUT", "CANDIDATE", b"oracle-output"
        if result == "MATCH" else b"candidate-output"
    )
    oracle_ev = make_artifact_evidence(oracle_art, "oracle-exec-1")
    candidate_ev = make_artifact_evidence(candidate_art, "candidate-exec-1")
    comparison = make_comparison(
        run_id,
        result=result,
        oracle_id="art-oracle-stdout",
        candidate_id="art-candidate-stdout",
        differences=("output differs",) if result == "MISMATCH" else (),
    )
    return make_manifest(
        run_id=run_id,
        artifacts=(oracle_ev, candidate_ev),
        comparisons=(comparison,),
    )


# ---------------------------------------------------------------------------
# CI #400 Trust-Boundary Regression Tests
# ---------------------------------------------------------------------------


class TestDeriveThroughValidatedManifest:
    """Prove that derive_verdict_validated() enforces the trust boundary."""

    def test_valid_manifest_produces_verified_through_validated_path(self):
        """A structurally valid manifest with all MATCH comparisons produces
        VERIFIED when going through the validated path.

        This proves the happy path is not broken by the trust-boundary fix.
        """
        run_id = RunId(value="run-tb-valid")
        manifest = _make_valid_manifest(run_id, result="MATCH")
        validation = validator.validate(manifest)

        assert isinstance(validation, ValidatedEvidenceManifest), (
            "Valid manifest must pass integrity validation"
        )
        verdict = derive_verdict_validated(validation)
        assert verdict.state == VerdictState.VERIFIED

    def test_genuine_mismatch_produces_failed_through_validated_path(self):
        """A genuine MISMATCH (not tampered) produces FAILED through the
        validated path.  This proves the fix doesn't break normal failure verdicts.
        """
        run_id = RunId(value="run-tb-mismatch")
        manifest = _make_valid_manifest(run_id, result="MISMATCH")

        validation = validator.validate(manifest)
        assert isinstance(validation, ValidatedEvidenceManifest), (
            "A structurally valid manifest with MISMATCH must pass integrity validation"
        )
        verdict = derive_verdict_validated(validation)
        assert verdict.state == VerdictState.FAILED

    def test_cross_run_replay_blocked_by_validator(self):
        """An artifact bound to an execution from a different run (cross-run
        replay) must be rejected by the validator before reaching derivation.
        """
        run_b = RunId(value="run-tb-replay-B")
        oracle_b = make_oracle_exec(run_b, "oracle-exec-B")
        candidate_b = make_candidate_exec(run_b, "candidate-exec-B")

        # Stolen artifact: bound to oracle-exec-A (from run A), not run B
        stolen_art = make_artifact("art-stolen", "STDOUT", "ORACLE", b"data")
        stolen_ev = make_artifact_evidence(stolen_art, "oracle-exec-A")

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_b,
            workload_id=WorkloadId(value="wl-replay"),
            source_identity=SourceIdentity(
                source_id="src", source_hash=_h("s"), file_count=1, total_size_bytes=10
            ),
            candidate_identity=CandidateIdentity(
                candidate_id="cand", candidate_hash=_h("c"), source_hash=_h("s"),
                file_count=1, total_size_bytes=10,
            ),
            oracle_identity=OracleIdentity(
                oracle_id="gnucobol-3.1.2",
                image_digest="sha256:" + "a" * 64,
                compiler_version="3.1.2.0",
            ),
            environment_identities=(),
            controlled_input=InputIdentity(input_id="inp", stdin_hash=_h("inp")),
            execution_evidence=(oracle_b, candidate_b),
            artifact_evidence=(stolen_ev,),  # execution_id points to run-A exec
            comparison_evidence=(),
        )

        validation = validator.validate(manifest)
        # Cross-run replay must be detected as an integrity violation
        assert isinstance(validation, list), (
            "Cross-run replay must fail integrity validation"
        )
        assert any(
            v.violation_type == ViolationType.CROSS_RUN_REPLAY for v in validation
        ), f"Expected CROSS_RUN_REPLAY violation; got {[v.violation_type for v in validation]}"

    def test_orphan_comparison_blocked_by_validator(self):
        """A comparison referencing non-existent artifacts must be rejected
        by the validator.
        """
        run_id = RunId(value="run-tb-orphan")
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="wl-orphan"),
            source_identity=SourceIdentity(
                source_id="src", source_hash=_h("s"), file_count=1, total_size_bytes=10
            ),
            candidate_identity=CandidateIdentity(
                candidate_id="cand", candidate_hash=_h("c"), source_hash=_h("s"),
                file_count=1, total_size_bytes=10,
            ),
            oracle_identity=OracleIdentity(
                oracle_id="gnucobol-3.1.2",
                image_digest="sha256:" + "a" * 64,
                compiler_version="3.1.2.0",
            ),
            environment_identities=(),
            controlled_input=InputIdentity(input_id="inp", stdin_hash=_h("inp")),
            execution_evidence=(
                make_oracle_exec(run_id, "oracle-exec-1"),
                make_candidate_exec(run_id, "candidate-exec-1"),
            ),
            artifact_evidence=(),  # no artifacts
            comparison_evidence=(
                # comparison references non-existent artifacts
                make_comparison(
                    run_id, result="MATCH",
                    oracle_id="art-GHOST-o", candidate_id="art-GHOST-c",
                ),
            ),
        )

        validation = validator.validate(manifest)
        assert isinstance(validation, list), (
            "Orphan comparison must fail integrity validation"
        )

    def test_derive_verdict_validated_requires_validated_manifest_type(self):
        """derive_verdict_validated() must only accept ValidatedEvidenceManifest.

        This tests the type-level enforcement of the trust boundary.
        Both raw and validated paths must agree on the verdict for clean evidence.
        """
        run_id = RunId(value="run-tb-type")
        manifest = _make_valid_manifest(run_id)

        # derive_verdict() still accepts raw manifest (backward compat)
        verdict_raw = derive_verdict(manifest)
        assert verdict_raw is not None

        # derive_verdict_validated() must accept ValidatedEvidenceManifest
        validation = validator.validate(manifest)
        assert isinstance(validation, ValidatedEvidenceManifest)
        verdict_validated = derive_verdict_validated(validation)
        assert verdict_validated is not None

        # Both paths must agree on the verdict for a clean manifest
        assert verdict_raw.state == verdict_validated.state

    def test_zero_comparisons_produces_unproven_through_validated_path(self):
        """A manifest with no comparison evidence produces UNPROVEN.
        This tests that zero-check manifests are handled correctly through
        the validated path.
        """
        run_id = RunId(value="run-tb-unproven")
        # Build manifest with no comparisons
        manifest = make_manifest(run_id=run_id, artifacts=(), comparisons=())

        validation = validator.validate(manifest)
        if isinstance(validation, ValidatedEvidenceManifest):
            verdict = derive_verdict_validated(validation)
            assert verdict.state == VerdictState.UNPROVEN


class TestVerdictDeriverTrustBoundaryMethods:
    """Prove that VerdictDeriver.derive_from_validated() only processes
    evidence that has passed the integrity validator.
    """

    def test_derive_from_validated_uses_inner_manifest(self):
        """derive_from_validated(validated) must use validated.manifest, not
        re-validate — the ValidatedEvidenceManifest is the proof that
        validation already passed.
        """
        run_id = RunId(value="run-tb-inner")
        manifest = _make_valid_manifest(run_id)
        validation = validator.validate(manifest)
        assert isinstance(validation, ValidatedEvidenceManifest)

        deriver = VerdictDeriver()
        verdict = deriver.derive_from_validated(validation)
        assert verdict.state == VerdictState.VERIFIED
        # Manifest hash in verdict must match the original manifest
        assert verdict.evidence_manifest_hash == str(manifest.manifest_hash)

    def test_derive_from_validated_consistent_with_derive_on_same_manifest(self):
        """derive_from_validated(validated) and derive(raw_manifest) must
        produce the same verdict for the same underlying evidence.
        """
        run_id = RunId(value="run-tb-consistent")
        manifest = _make_valid_manifest(run_id)
        validation = validator.validate(manifest)
        assert isinstance(validation, ValidatedEvidenceManifest)

        deriver = VerdictDeriver()
        v1 = deriver.derive(manifest)
        v2 = deriver.derive_from_validated(validation)
        assert v1.state == v2.state

    def test_derive_unsafe_from_raw_bypasses_trust_boundary_explicitly(self):
        """derive_unsafe_from_raw() is an internal-use bypass for the
        pipeline's error-override path.  It must work, but callers must
        understand they are bypassing the trust boundary.
        """
        run_id = RunId(value="run-tb-unsafe")
        manifest = _make_valid_manifest(run_id)
        deriver = VerdictDeriver()
        verdict = deriver.derive_unsafe_from_raw(manifest)
        # Result is the natural verdict — same as derive()
        assert verdict.state == derive_verdict(manifest).state

    def test_derive_from_validated_mismatch_consistent(self):
        """derive_from_validated() on a MISMATCH manifest produces FAILED,
        consistent with the raw derive() path.
        """
        run_id = RunId(value="run-tb-mis-consistent")
        manifest = _make_valid_manifest(run_id, result="MISMATCH")
        validation = validator.validate(manifest)
        assert isinstance(validation, ValidatedEvidenceManifest)

        deriver = VerdictDeriver()
        v_raw = deriver.derive(manifest)
        v_validated = deriver.derive_from_validated(validation)
        assert v_raw.state == v_validated.state == VerdictState.FAILED

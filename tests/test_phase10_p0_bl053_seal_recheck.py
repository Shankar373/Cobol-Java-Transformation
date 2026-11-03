"""Phase 10 P0-a (BL-053): post-validation mutation must fail derivation closed.

``derive_from_validated`` is the trust-boundary entry point: it promises that
calling code bypassing the validator cannot produce an incorrect verdict.
A manifest mutated *after* ``EvidenceIntegrityValidator.validate()`` was
currently trusted verbatim — flipping the only comparison MISMATCH -> MATCH
after validation certified VERIFIED (Master README §39 forbidden upgrade).

Red-first evidence: ``test_post_validation_mutation_fails_closed_verdict``
fails against unmodified code (verdict.state == VERIFIED) and passes once
``derive_from_validated`` re-binds ``validated.manifest.manifest_hash`` to
``validated.integrity_hash``.

Engine-only (no fastapi/pydantic): safe for the dependency-free
capability-truth gate in .github/workflows/ci.yml.
"""

from __future__ import annotations

from engine.domain.identities import RunId, VerdictState
from engine.evidence.integrity import (
    EvidenceIntegrityValidator,
    ValidatedEvidenceManifest,
)
from engine.verdict.derivation import derive_verdict_validated
from tests.adversarial.conftest import (
    make_artifact,
    make_artifact_evidence,
    make_comparison,
    make_manifest,
)


def _make_manifest(run_id: RunId, result: str):
    """One STDOUT pair whose single comparison has the given result."""
    oracle_art = make_artifact("art-oracle-stdout", "STDOUT", "ORACLE", b"out")
    candidate_art = make_artifact("art-candidate-stdout", "STDOUT", "CANDIDATE", b"out")
    comparison = make_comparison(
        run_id,
        result=result,
        oracle_id="art-oracle-stdout",
        candidate_id="art-candidate-stdout",
        differences=("output differs",) if result == "MISMATCH" else (),
    )
    return make_manifest(
        run_id=run_id,
        artifacts=(
            make_artifact_evidence(oracle_art, "oracle-exec-1"),
            make_artifact_evidence(candidate_art, "candidate-exec-1"),
        ),
        comparisons=(comparison,),
    )


def _validated(run_id: RunId, result: str) -> ValidatedEvidenceManifest:
    validated = EvidenceIntegrityValidator().validate(_make_manifest(run_id, result))
    assert isinstance(
        validated, ValidatedEvidenceManifest
    ), f"setup: manifest must validate, got {validated!r}"
    return validated


class TestPostValidationMutationFailsClosed:
    """BL-053: TOCTOU between validation and verdict derivation."""

    def test_post_validation_mutation_fails_closed_verdict(self):
        run_id = RunId(value="run-phase10-p0a-toctou")
        validated = _validated(run_id, "MISMATCH")

        # Sanity: the evidence really fails comparison before any mutation.
        natural = derive_verdict_validated(validated)
        assert natural.state is VerdictState.FAILED

        # TOCTOU: mutate the manifest AFTER validation — flip the only
        # comparison to MATCH (a "FAILED -> VERIFIED" forbidden upgrade).
        validated.manifest.comparison_evidence = (
            make_comparison(
                run_id,
                result="MATCH",
                oracle_id="art-oracle-stdout",
                candidate_id="art-candidate-stdout",
            ),
        )
        assert validated.manifest.manifest_hash != validated.integrity_hash, (
            "test setup: the mutation must change the recomputed manifest hash"
        )

        mutated = derive_verdict_validated(validated)
        assert mutated.state is not VerdictState.VERIFIED, (
            "BL-053: a manifest mutated after validation certified VERIFIED"
        )
        assert mutated.state is VerdictState.ERROR, (
            f"expected fail-closed ERROR, got {mutated.state.value}"
        )
        assert mutated.differences, "the verdict must explain the fail-closed"
        assert any(
            "validation" in d.lower() for d in mutated.differences
        ), mutated.differences

    def test_unmutated_failed_evidence_still_fails(self):
        """Regression: the seal re-check must not over-block natural FAILED."""
        validated = _validated(RunId(value="run-phase10-p0a-natural-failed"), "MISMATCH")
        verdict = derive_verdict_validated(validated)
        assert verdict.state is VerdictState.FAILED

    def test_clean_evidence_still_verifies_after_validation(self):
        """Regression: a genuinely matching, validated manifest still verifies."""
        validated = _validated(RunId(value="run-phase10-p0a-clean-match"), "MATCH")
        verdict = derive_verdict_validated(validated)
        assert verdict.state is VerdictState.VERIFIED
        assert verdict.evidence_manifest_hash == str(validated.manifest.manifest_hash)

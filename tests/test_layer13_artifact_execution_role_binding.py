"""Layer 13: an artifact's ``producer_role`` must agree with the execution that produced it.

``contracts/ARTIFACT_CONTRACT_SPEC.md`` §4: "each artifact is bound to exactly
one producing execution via ``producer_role`` + ``execution_id``. Cross-role
ambiguity is schema-invalid." §5 rule 3 requires producer/execution bindings to
be consistent, else ``identity_mismatch``.

``EvidenceIntegrityValidator`` bound every artifact to an execution that exists
in the same run (``_validate_artifact_execution_binding``) and required a
comparison's oracle side to carry ``producer_role == "ORACLE"`` and its candidate
side ``"CANDIDATE"`` (``_comparison_pairing_violations``), but never checked the
two claims against each other: an artifact could label itself ORACLE while
naming the *candidate* execution that produced it.

That leaves a self-certification path. In ``_self_certifying`` every comparison
is internally consistent and MATCHes, yet no comparison ever pits oracle output
against candidate output: one pair compares the candidate's bytes with the
candidate's bytes, the other compares the oracle's bytes with the oracle's
bytes. Required evidence is satisfied because it counts artifacts by *execution
id* (``_validate_required_evidence``) while pairing counts them by *role*, so the
two notions of "which side is this" disagree. The manifest validates and derives
VERIFIED for a program that never ran against the reference.

L13 closes it: a producing execution whose ``runtime_id`` identifies its role
must agree with the artifact's ``producer_role``; disagreement is refused by
name (``ARTIFACT_ROLE_MISMATCH``).
"""

from __future__ import annotations

from engine.domain.identities import RunId
from engine.evidence.integrity import (
    EvidenceIntegrityValidator,
    ValidatedEvidenceManifest,
    ViolationType,
)
from engine.verdict.derivation import VerdictDeriver, derive_verdict_untrusted
from tests.adversarial.test_evidence_trust_boundary import (
    _art_ev,
    _comp,
    _exec,
    _manifest,
)

validator = EvidenceIntegrityValidator()


def _run(tag: str) -> RunId:
    return RunId(value=f"run-l13-role-{tag}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _honest(run_id: RunId) -> object:
    """A correctly bound manifest: ORACLE artifacts from the oracle execution,
    CANDIDATE artifacts from the candidate execution."""
    artifacts = (
        _art_ev("art-stdout-oracle", "STDOUT", "ORACLE", "oracle-output", "oracle-exec-1"),
        _art_ev("art-stdout-candidate", "STDOUT", "CANDIDATE", "candidate-output", "candidate-exec-1"),
        _art_ev("art-exit-oracle", "EXIT_STATUS", "ORACLE", "oracle-exit", "oracle-exec-1"),
        _art_ev("art-exit-candidate", "EXIT_STATUS", "CANDIDATE", "candidate-exit", "candidate-exec-1"),
    )
    comparisons = (
        _comp(
            run_id, result="MATCH",
            oracle_id="art-stdout-oracle", candidate_id="art-stdout-candidate",
            artifact_type="STDOUT",
        ),
        _comp(
            run_id, result="MATCH",
            oracle_id="art-exit-oracle", candidate_id="art-exit-candidate",
            artifact_type="EXIT_STATUS",
        ),
    )
    return _manifest(
        run_id=run_id,
        artifacts=artifacts,
        comparisons=comparisons,
        oracle_execs=(_exec(run_id, "oracle-exec-1"),),
        candidate_execs=(_exec(run_id, "candidate-exec-1", runtime_id="candidate-java"),),
    )


def _cross_role(run_id: RunId) -> object:
    """Every artifact's ``producer_role`` disagrees with its producing
    execution: the STDOUT "oracle" side is the candidate's own bytes produced by
    the candidate execution, and the EXIT_STATUS "candidate" side is the
    oracle's own bytes produced by the oracle execution."""
    artifacts = (
        # Cross-role: labelled ORACLE, produced by the candidate execution.
        _art_ev("art-stdout-oracle", "STDOUT", "ORACLE", "candidate-output", "candidate-exec-1"),
        _art_ev("art-stdout-candidate", "STDOUT", "CANDIDATE", "candidate-output", "candidate-exec-1"),
        # Cross-role: labelled CANDIDATE, produced by the oracle execution.
        _art_ev("art-exit-oracle", "EXIT_STATUS", "ORACLE", "oracle-exit", "oracle-exec-1"),
        _art_ev("art-exit-candidate", "EXIT_STATUS", "CANDIDATE", "oracle-exit", "oracle-exec-1"),
    )
    comparisons = (
        _comp(
            run_id, result="MATCH",
            oracle_id="art-stdout-oracle", candidate_id="art-stdout-candidate",
            artifact_type="STDOUT",
        ),
        _comp(
            run_id, result="MATCH",
            oracle_id="art-exit-oracle", candidate_id="art-exit-candidate",
            artifact_type="EXIT_STATUS",
        ),
    )
    return _manifest(
        run_id=run_id,
        artifacts=artifacts,
        comparisons=comparisons,
        oracle_execs=(_exec(run_id, "oracle-exec-1"),),
        candidate_execs=(_exec(run_id, "candidate-exec-1", runtime_id="candidate-java"),),
    )


def _violation_types(outcome) -> set[ViolationType]:
    assert isinstance(outcome, list), (
        "expected the manifest to be refused, but the validator accepted it"
    )
    return {v.violation_type for v in outcome}


# ---------------------------------------------------------------------------
# Controls: correctly bound evidence must keep validating
# ---------------------------------------------------------------------------

def test_control_honest_manifest_still_validates():
    outcome = validator.validate(_honest(_run("control")))
    assert isinstance(outcome, ValidatedEvidenceManifest)


def test_control_honest_manifest_still_derives_verified():
    manifest = _honest(_run("control-verified"))
    verdict = VerdictDeriver().derive(manifest)
    assert verdict.state.value == "VERIFIED"


# ---------------------------------------------------------------------------
# Red: cross-role bindings must be refused by name
# ---------------------------------------------------------------------------

def test_oracle_artifact_naming_the_candidate_execution_is_refused():
    outcome = validator.validate(_cross_role(_run("oracle-on-candidate")))
    assert ViolationType.ARTIFACT_ROLE_MISMATCH in _violation_types(outcome), (
        "an ORACLE-role artifact bound to the candidate execution is"
        " cross-role ambiguity, which ARTIFACT_CONTRACT_SPEC.md §4 declares"
        " schema-invalid"
    )


def test_candidate_artifact_naming_the_oracle_execution_is_refused():
    manifest = _cross_role(_run("candidate-on-oracle"))
    outcome = validator.validate(manifest)
    types = _violation_types(outcome)
    assert ViolationType.ARTIFACT_ROLE_MISMATCH in types
    # Both directions must be caught, not only the oracle side.
    assert sum(
        v.violation_type == ViolationType.ARTIFACT_ROLE_MISMATCH for v in outcome
    ) == 2, [v.description for v in outcome]


def test_swapping_the_two_artifacts_producing_executions_is_refused():
    """Mutation: rebind each artifact to the other role's execution, leaving
    every other field (including both ``producer_role`` labels) untouched."""
    honest = _honest(_run("swap"))
    swapped = _manifest(
        run_id=honest.run_id,
        artifacts=(
            _art_ev("art-stdout-oracle", "STDOUT", "ORACLE", "oracle-output", "candidate-exec-1"),
            _art_ev("art-stdout-candidate", "STDOUT", "CANDIDATE", "candidate-output", "oracle-exec-1"),
            _art_ev("art-exit-oracle", "EXIT_STATUS", "ORACLE", "oracle-exit", "candidate-exec-1"),
            _art_ev("art-exit-candidate", "EXIT_STATUS", "CANDIDATE", "candidate-exit", "oracle-exec-1"),
        ),
        comparisons=honest.comparison_evidence,
        oracle_execs=honest.execution_evidence[:1],
        candidate_execs=honest.execution_evidence[1:],
    )
    outcome = validator.validate(swapped)
    assert ViolationType.ARTIFACT_ROLE_MISMATCH in _violation_types(outcome)


def test_self_certifying_manifest_never_reaches_verified():
    """The end-to-end property: a manifest whose comparisons never pit oracle
    output against candidate output must not certify equivalence."""
    manifest = _cross_role(_run("self-certify"))
    outcome = validator.validate(manifest)
    violations = _violation_types(outcome)
    assert ViolationType.ARTIFACT_ROLE_MISMATCH in violations

    verdict = derive_verdict_untrusted(manifest, outcome)
    assert verdict.state.value != "VERIFIED", (
        "cross-role evidence was allowed to certify equivalence"
    )
    assert verdict.state.value == "ERROR"


def test_self_certifying_manifest_naturally_derives_verified_before_the_clamp():
    """Documents why the clamp alone is not enough: the deriver sees only
    MATCH results and would certify this manifest if the validator let it
    through. The check belongs in the validator."""
    manifest = _cross_role(_run("natural"))
    verdict = VerdictDeriver().derive(manifest)
    assert verdict.state.value == "VERIFIED"

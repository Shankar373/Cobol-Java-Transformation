"""Layer 13: the artifact-contract loader must not silently substitute declared fields.

``engine/contracts/validator.py`` opens with the rule it exists to enforce:
"There must be NO 'best effort' contract interpretation." ``load_artifact_contract``
broke that rule for two declared fields:

* ``on_extra`` was never read — a comparator declaring ``on_extra: "FAILED"``
  loaded with the default ``"MISMATCH"``, so the loaded contract did not say
  what the contract said.
* ``permanently_forbidden`` was never passed to ``ArtifactContract`` — a
  contract declaring extra permanent prohibitions loaded with only the
  ``("substring_containment",)`` default.

Two related holes made the substitution invisible:

* ``FailurePolicy.__post_init__`` validated ``on_missing`` and ``on_malformed``
  but not ``on_extra``, so an arbitrary value — including a certifying one such
  as ``"MATCH"`` — was accepted silently.
* Reading ``permanently_forbidden`` naively would *weaken* the ADR-0002
  prohibition: the default currently protects ``substring_containment``
  whether or not the contract mentions it, and a declared empty list would
  disarm it. The declared value must therefore be honored only within the
  bounds of the prohibition that survives all contract versions.

Fail-closed by name: an unvalidatable ``on_extra`` and a contract that tries
to declare away (or claim beyond) the permanent prohibition are refused with
``ContractValidationError``.
"""

from __future__ import annotations

import pytest

from engine.contracts.models import FailurePolicy, NormalizationPolicy
from engine.contracts.validator import (
    ContractValidationError,
    load_artifact_contract,
)

VALID_ARTIFACT_CONTRACT_DATA = {
    "contract_id": "artifact-v1",
    "version": "1.0",
    "artifact_types": [
        {"name": "STDOUT", "compared_as": "Process stdout bytes"},
        {"name": "EXIT_STATUS", "compared_as": "Observed process exit code"},
    ],
    "comparators": [
        {"comparator_id": "STDOUT_COMPARATOR", "artifact_type": "STDOUT"},
        {"comparator_id": "EXIT_STATUS_COMPARATOR", "artifact_type": "EXIT_STATUS"},
    ],
}


def _with_comparator(**fields: object) -> dict:
    """VALID data with ``fields`` added to the first comparator declaration."""
    data = {**VALID_ARTIFACT_CONTRACT_DATA}
    comparators = [dict(c) for c in data["comparators"]]
    comparators[0].update(fields)
    data["comparators"] = comparators
    return data


def _loaded_failure_policy(data: dict) -> FailurePolicy:
    contract = load_artifact_contract(data)
    comparator = contract.get_comparator("STDOUT")
    assert comparator is not None
    return comparator.failure_policy


# ---------------------------------------------------------------------------
# Controls: a contract that declares neither field must keep loading exactly
# as it did before, with both defaults intact.
# ---------------------------------------------------------------------------

def test_control_default_contract_still_loads():
    contract = load_artifact_contract(VALID_ARTIFACT_CONTRACT_DATA)
    assert contract.get_comparator("STDOUT").failure_policy.on_extra == "MISMATCH"
    assert contract.permanently_forbidden == ("substring_containment",)


# ---------------------------------------------------------------------------
# Red: declared values must survive loading
# ---------------------------------------------------------------------------

def test_declared_on_extra_is_honored_not_dropped():
    """A comparator declaring ``on_extra: "FAILED"`` must load as ``"FAILED"``.

    Substituting the default is a best-effort interpretation of the contract:
    the loaded object asserts a failure behavior the contract never declared.
    """
    policy = _loaded_failure_policy(_with_comparator(on_extra="FAILED"))
    assert policy.on_extra == "FAILED", (
        f"declared on_extra was dropped; loader substituted {policy.on_extra!r}"
    )


def test_declared_permanently_forbidden_is_honored_not_dropped():
    """A contract declaring extra permanent prohibitions must load them all."""
    contract = load_artifact_contract({
        **VALID_ARTIFACT_CONTRACT_DATA,
        "permanently_forbidden": ["substring_containment", "case_folding"],
    })
    assert contract.permanently_forbidden == ("substring_containment", "case_folding"), (
        f"declared permanently_forbidden was dropped; loader substituted "
        f"{contract.permanently_forbidden!r}"
    )


# ---------------------------------------------------------------------------
# Red: an unvalidatable failure policy must be refused by name
# ---------------------------------------------------------------------------

def test_failure_policy_refuses_an_arbitrary_on_extra():
    """``on_extra`` must be validated like its two sibling fields.

    No engine code reads ``on_extra`` yet, so an arbitrary value is recorded
    as if it were legitimate — and ``"MATCH"`` would be a certifying state if
    anything ever consulted it.
    """
    with pytest.raises(ValueError, match="Invalid on_extra"):
        FailurePolicy(on_extra="MATCH")


def test_loader_refuses_an_arbitrary_on_extra_by_contract_error():
    """The loader's own error type, not a leaked ``ValueError``."""
    with pytest.raises(ContractValidationError, match="on_extra"):
        load_artifact_contract(_with_comparator(on_extra="MATCH"))


def test_loader_refuses_an_arbitrary_on_missing_by_contract_error():
    """Same wrapping rule for the already-validated sibling field: the loader
    reports contract problems as ``ContractValidationError``."""
    with pytest.raises(ContractValidationError, match="on_missing"):
        load_artifact_contract(_with_comparator(on_missing="SKIP"))


# ---------------------------------------------------------------------------
# Red: reading the declared prohibition must not weaken ADR-0002
# ---------------------------------------------------------------------------

def test_contract_cannot_declare_away_the_permanent_prohibition():
    """Mutation: empty ``permanently_forbidden`` must not disarm the rule that
    ARTIFACT_CONTRACT_SPEC.md §2 says survives all future versions. Before the
    field was read at all the default protected it; reading it makes this
    refusal mandatory, not optional."""
    with pytest.raises(ContractValidationError, match="substring_containment"):
        load_artifact_contract({
            **VALID_ARTIFACT_CONTRACT_DATA,
            "permanently_forbidden": [],
        })


def test_contract_cannot_narrow_the_permanent_prohibition():
    """Mutation: keeping a different prohibition while dropping
    ``substring_containment`` is the same weakening, spelled differently."""
    with pytest.raises(ContractValidationError, match="substring_containment"):
        load_artifact_contract({
            **VALID_ARTIFACT_CONTRACT_DATA,
            "permanently_forbidden": ["case_folding"],
        })


def test_contract_cannot_claim_a_prohibition_the_normalization_gate_does_not_enforce():
    """A declared permanent prohibition outside ``NormalizationPolicy.FORBIDDEN``
    is a gate the engine does not implement — loading it would record an
    unenforceable claim as if it were enforced."""
    with pytest.raises(ContractValidationError, match="bit_fiddling"):
        load_artifact_contract({
            **VALID_ARTIFACT_CONTRACT_DATA,
            "permanently_forbidden": ["substring_containment", "bit_fiddling"],
        })


def test_every_enforceable_prohibition_can_be_declared():
    """Control: the whole enforced set is declarable, so the subset rule above
    narrows declarations rather than outlawing them."""
    contract = load_artifact_contract({
        **VALID_ARTIFACT_CONTRACT_DATA,
        "permanently_forbidden": sorted(NormalizationPolicy.FORBIDDEN),
    })
    assert set(contract.permanently_forbidden) == set(NormalizationPolicy.FORBIDDEN)

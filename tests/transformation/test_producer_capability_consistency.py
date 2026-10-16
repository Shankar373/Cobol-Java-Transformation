"""Cross-producer capability guard (BL-011).

Master README Section 14 makes the semantic capability registry the single
source of capability truth for the deterministic COBOL -> Java lane.  BL-011
recorded that no generic guard forced every producer's declared
``supported_constructs`` / ``unsupported_constructs`` to agree with it.

This module locks the invariants that must hold for *every*
``TransformationProducer`` in the package:

1. A producer that implements the *deterministic* COBOL -> Java lane may never
   contradict the registry in either direction.
2. Every producer, in any lane, returns a non-empty declared-capability
   surface and never claims a construct both ways.
3. Producer list members that are not registry keys must be declared structural
   vocabulary (divisions / PIC clauses / file organizations) rather than
   behavioural constructs, so they cannot be mistaken for a verdict.

Scope note — the opensource4j adapter is deliberately excluded from the
registry-agreement check.  It is an *external* producer: its generated Java
requires the COBOL runtime ``libcobj.jar`` and is explicitly classified as an
alternative/benchmark lane, not the deterministic lane the registry describes.
It legitimately claims constructs (``GO TO``, ``SORT``) that the deterministic
mapper cannot express, because the upstream tool handles them.  Forcing it to
mirror the registry would falsify its real behaviour, so the registry-vs-external
divergence is asserted explicitly instead of being erased.

The internal native producer's own reconciliation lives in
``test_capability_registry_reconciliation.py``; this module generalises the
check so a future producer cannot reintroduce the contradiction.
"""

from __future__ import annotations

import pytest

from engine.transformation.contracts import TransformationProducer
from engine.transformation.producers.internal_native import (
    InternalNativeJavaProducer,
)
from engine.transformation.producers.opensource4j import (
    OpenSourceCOBOL4JProducerAdapter,
)
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    CapabilityLevel,
    SUPPORTED_CONSTRUCTS,
    UNSUPPORTED_CONSTRUCTS,
)

ALL_PRODUCERS = [
    pytest.param(InternalNativeJavaProducer(), id="internal-native"),
    pytest.param(OpenSourceCOBOL4JProducerAdapter(), id="opensource4j"),
]

# The registry governs the *deterministic* COBOL -> Java lane only.  Producers
# that implement that lane must agree with it unconditionally.
_DETERMINISTIC_LANE_PRODUCERS = [
    pytest.param(InternalNativeJavaProducer(), id="internal-native"),
]

# Declared list members that are intentionally outside the construct registry:
# structural vocabulary, not capability verdicts.
_STRUCTURAL_VOCABULARY = frozenset({
    "IDENTIFICATION DIVISION",
    "ENVIRONMENT DIVISION",
    "DATA DIVISION",
    "FILE-CONTROL",
    "FILE SECTION",
    "WORKING-STORAGE",
    "PIC X(n)",
    "PIC 9(n)",
    "INDEXED files",
    "RELATIVE files",
})


def _declared(producer: TransformationProducer):
    """Get the declared capability lists without invoking external tooling.

    Both producers expose their declared lists as module-level constants (the
    opensource4j adapter does so precisely so its claims are inspectable without
    shelling out to an external compiler).
    """
    if isinstance(producer, InternalNativeJavaProducer):
        from engine.transformation.producers.internal_native import (
            _PRODUCER_SUPPORTED_CONSTRUCTS,
            _PRODUCER_UNSUPPORTED_CONSTRUCTS,
        )

        return (
            set(_PRODUCER_SUPPORTED_CONSTRUCTS),
            set(_PRODUCER_UNSUPPORTED_CONSTRUCTS),
        )
    from engine.transformation.producers.opensource4j import (
        _PRODUCER_SUPPORTED_CONSTRUCTS,
        _PRODUCER_UNSUPPORTED_CONSTRUCTS,
    )

    return (
        set(_PRODUCER_SUPPORTED_CONSTRUCTS),
        set(_PRODUCER_UNSUPPORTED_CONSTRUCTS),
    )


@pytest.mark.parametrize("producer", _DETERMINISTIC_LANE_PRODUCERS)
class TestDeterministicProducerRegistryAgreement:
    """A deterministic-lane producer may never contradict the registry."""

    def test_no_supported_claim_contradicts_registry(
        self, producer: TransformationProducer
    ) -> None:
        supported, _ = _declared(producer)
        offenders = sorted(supported & UNSUPPORTED_CONSTRUCTS)
        assert not offenders, (
            f"{producer.get_identity()} claims SUPPORTED for "
            f"registry-UNSUPPORTED constructs: {offenders}"
        )

    def test_no_unsupported_claim_contradicts_registry(
        self, producer: TransformationProducer
    ) -> None:
        _, unsupported = _declared(producer)
        offenders = sorted(unsupported & SUPPORTED_CONSTRUCTS)
        assert not offenders, (
            f"{producer.get_identity()} claims UNSUPPORTED for "
            f"registry-SUPPORTED constructs: {offenders}"
        )


@pytest.mark.parametrize("producer", ALL_PRODUCERS)
class TestEveryProducerDeclaredSurface:
    """Invariants that hold for every producer, in any lane."""

    def test_no_construct_is_claimed_both_ways(
        self, producer: TransformationProducer
    ) -> None:
        supported, unsupported = _declared(producer)
        both = sorted(supported & unsupported)
        assert not both, f"Constructs claimed both supported and unsupported: {both}"

    def test_producer_declares_capabilities(
        self, producer: TransformationProducer
    ) -> None:
        supported, unsupported = _declared(producer)
        assert supported or unsupported, (
            f"{producer.get_identity()} ships with an empty declared "
            "capability surface"
        )

    def test_declared_members_are_registry_keys_or_structural(
        self, producer: TransformationProducer
    ) -> None:
        """No silent vocabulary: every declared member must be accounted for.

        A member outside the registry is only acceptable when it is declared
        structural vocabulary; anything else would be an unverifiable verdict.
        """
        supported, unsupported = _declared(producer)
        unknown = sorted(
            (supported | unsupported)
            - set(CONSTRUCT_REGISTRY)
            - _STRUCTURAL_VOCABULARY
        )
        assert not unknown, (
            "Declared constructs that are neither registry keys nor declared "
            f"structural vocabulary: {unknown}"
        )

    def test_producer_identity_is_unique(
        self, producer: TransformationProducer
    ) -> None:
        identity, version = producer.get_identity()
        assert identity, "Producer must expose a non-empty identity"
        assert version, "Producer must expose a non-empty version"


class TestExternalProducerDivergenceIsExplicit:
    """The external lane's divergence must be documented, not accidental.

    The opensource4j adapter claims ``GO TO`` / ``SORT`` as supported while the
    deterministic registry marks them UNSUPPORTED.  That divergence is correct
    and expected (an external COBOL runtime handles what our mapper cannot), but
    it must be asserted so nobody "fixes" it by editing the registry.
    """

    def test_external_producer_scope_is_documented(self) -> None:
        assert "alternative/benchmark producer" in (
            OpenSourceCOBOL4JProducerAdapter.__doc__ or ""
        )
        assert "libcobj.jar" in (
            OpenSourceCOBOL4JProducerAdapter.__doc__ or ""
        )

    def test_external_producer_runtime_requirement_is_declared(self) -> None:
        requirements = OpenSourceCOBOL4JProducerAdapter().get_runtime_requirements()
        assert any("libcobj" in r for r in requirements), requirements

    def test_external_producer_divergence_is_known_and_bounded(self) -> None:
        supported, _ = _declared(OpenSourceCOBOL4JProducerAdapter())
        divergence = sorted(supported & UNSUPPORTED_CONSTRUCTS)
        # The deterministic mapper cannot express these; the external runtime can.
        assert divergence == ["GO TO", "SORT"], (
            "The external producer's divergence from the deterministic registry "
            f"changed to {divergence}. If this is intentional, update this test "
            "and the lane documentation together; if not, remove the claims."
        )


class TestRegistryItself:
    def test_every_key_has_evidence(self) -> None:
        for key, entry in CONSTRUCT_REGISTRY.items():
            assert entry.evidence.strip(), f"{key} has no evidence text"

    def test_no_key_is_partial_and_supported(self) -> None:
        for key, entry in CONSTRUCT_REGISTRY.items():
            if entry.level is CapabilityLevel.PARTIAL:
                assert entry.effective_source_level is CapabilityLevel.PARTIAL, key

    def test_partial_constructs_are_not_in_supported(self) -> None:
        """A PARTIAL verdict must never be flattened into SUPPORTED."""
        partial = {
            key for key, e in CONSTRUCT_REGISTRY.items()
            if e.level is CapabilityLevel.PARTIAL
        }
        supported, unsupported = _declared(InternalNativeJavaProducer())
        assert not (supported & partial), sorted(supported & partial)
        assert not (unsupported & partial), sorted(unsupported & partial)

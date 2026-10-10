"""Capability-truth reconciliation between the producer and the registry.

Master README Section 14 makes the semantic capability registry
(``engine/transformation/semantic_capability.py``) the single source of
capability truth.  COBOL Universality Roadmap finding P0-1 recorded that the
internal native producer declared a hand-maintained capability list that
contradicted the registry (it claimed ``GO TO`` supported and ``COMPUTE`` /
``SUBTRACT`` / ``MULTIPLY`` / ``CALL`` / ``EVALUATE`` unsupported while the
registry marks them the other way round).

The producer now derives its declared lists from the registry, and these tests
lock that reconciliation so the contradiction cannot silently return.
"""

from __future__ import annotations

from engine.transformation.producers.internal_native import (
    InternalNativeJavaProducer,
)
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    CapabilityLevel,
    PARTIAL_CONSTRUCTS,
    SUPPORTED_CONSTRUCTS,
    UNSUPPORTED_CONSTRUCTS,
)


def _minimal_program() -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. RECON.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-COUNT PIC 9(4) VALUE 0.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        "           MOVE 42 TO WS-COUNT\n"
        "           DISPLAY WS-COUNT\n"
        "           STOP RUN.\n"
    )


def _declared() -> tuple[set[str], set[str]]:
    result = InternalNativeJavaProducer().transform(
        _minimal_program(), program_id="RECON"
    )
    return set(result.supported_constructs), set(result.unsupported_constructs)


class TestProducerRegistryReconciliation:
    def test_no_supported_claim_is_unsupported_by_registry(self) -> None:
        supported, _ = _declared()
        offenders = sorted(supported & UNSUPPORTED_CONSTRUCTS)
        assert not offenders, (
            "Producer claims SUPPORTED for registry-UNSUPPORTED constructs: "
            f"{offenders}"
        )

    def test_no_unsupported_claim_is_supported_by_registry(self) -> None:
        _, unsupported = _declared()
        offenders = sorted(unsupported & SUPPORTED_CONSTRUCTS)
        assert not offenders, (
            "Producer claims UNSUPPORTED for registry-SUPPORTED constructs: "
            f"{offenders}"
        )

    def test_partial_constructs_are_not_overclaimed(self) -> None:
        """PARTIAL constructs must appear in neither producer list."""
        supported, unsupported = _declared()
        assert not (supported & PARTIAL_CONSTRUCTS), sorted(
            supported & PARTIAL_CONSTRUCTS
        )
        assert not (unsupported & PARTIAL_CONSTRUCTS), sorted(
            unsupported & PARTIAL_CONSTRUCTS
        )

    def test_every_registry_supported_construct_is_declared_supported(self) -> None:
        supported, _ = _declared()
        missing = sorted(SUPPORTED_CONSTRUCTS - supported)
        assert not missing, f"Registry-supported constructs not declared: {missing}"

    def test_every_registry_unsupported_construct_is_declared_unsupported(self) -> None:
        _, unsupported = _declared()
        missing = sorted(UNSUPPORTED_CONSTRUCTS - unsupported)
        assert not missing, (
            f"Registry-unsupported constructs not declared: {missing}"
        )

    def test_each_registry_key_is_documented_as_supported_or_unsupported(self) -> None:
        """Registry keys under SUPPORTED/UNSUPPORTED classify deterministically."""
        for key, entry in CONSTRUCT_REGISTRY.items():
            if entry.level is CapabilityLevel.SUPPORTED:
                assert key in SUPPORTED_CONSTRUCTS
            elif entry.level is CapabilityLevel.UNSUPPORTED:
                assert key in UNSUPPORTED_CONSTRUCTS
            elif entry.level is CapabilityLevel.PARTIAL:
                assert key in PARTIAL_CONSTRUCTS


class TestP0_1RegressionCases:
    """The exact contradictions recorded by roadmap finding P0-1."""

    def test_go_to_is_not_claimed_supported(self) -> None:
        supported, unsupported = _declared()
        assert "GO TO" not in supported
        assert "GO TO" in unsupported

    def test_now_supported_verbs_are_not_claimed_unsupported(self) -> None:
        _, unsupported = _declared()
        for construct in ("COMPUTE", "SUBTRACT", "MULTIPLY", "CALL", "EVALUATE"):
            assert construct not in unsupported, construct

    def test_now_supported_verbs_are_claimed_supported(self) -> None:
        supported, _ = _declared()
        for construct in ("COMPUTE", "SUBTRACT", "MULTIPLY", "CALL", "EVALUATE"):
            assert construct in supported, construct

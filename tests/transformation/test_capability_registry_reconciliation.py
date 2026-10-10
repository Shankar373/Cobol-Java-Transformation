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


class TestAllRegistryKeysAppearInSomeVerdict:
    """Every registry key must be classified by the producer somehow.

    BL-002..BL-005 added COMP/COMP-3, REDEFINES/OCCURS/88-LEVEL,
    BY CONTENT/BY VALUE and ROUNDED keys.  The producer derives its supported /
    unsupported lists from the registry by level, so a newly added key must show
    up in exactly one of them (or in neither, if it is PARTIAL) without any
    hand-editing of the producer.
    """

    def test_new_registry_keys_are_classified_without_hand_editing(self) -> None:
        """Every registry key must resolve to a producer verdict automatically.

        SUPPORTED / UNSUPPORTED keys must appear in the matching list.  PARTIAL
        and UNKNOWN keys are deliberately claimed by neither list: they are not
        a positive or negative claim, and asserting them into a list would
        overstate what the producer does.
        """
        supported, unsupported = _declared()
        classified = supported | unsupported
        unclassified = sorted(
            key
            for key, entry in CONSTRUCT_REGISTRY.items()
            if entry.level
            in (CapabilityLevel.SUPPORTED, CapabilityLevel.UNSUPPORTED)
            and key not in classified
        )
        assert not unclassified, (
            "Registry keys neither declared supported nor unsupported: "
            f"{unclassified}"
        )

    def test_partial_and_unknown_keys_are_claimed_by_neither_list(self) -> None:
        """A partial/unknown verdict must never be presented as a hard claim."""
        supported, unsupported = _declared()
        for key, entry in CONSTRUCT_REGISTRY.items():
            if entry.level in (CapabilityLevel.PARTIAL, CapabilityLevel.UNKNOWN):
                assert key not in supported, f"{key} overclaimed as supported"
                assert key not in unsupported, f"{key} overclaimed as unsupported"

    def test_newly_registered_keys_have_expected_verdicts(self) -> None:
        """Spot-check the keys added by BL-002..BL-005."""
        supported, unsupported = _declared()
        # COMP family is PARTIAL -> claimed by neither list.
        for key in ("COMP", "COMP-3", "COMP-5"):
            assert key not in supported and key not in unsupported, key
        # REDEFINES / OCCURS / 88-LEVEL are UNKNOWN -> also in neither list.
        for key in ("REDEFINES", "OCCURS", "88-LEVEL"):
            assert key not in supported and key not in unsupported, key
        # BY CONTENT / BY VALUE are PARTIAL -> neither list.
        for key in ("BY CONTENT", "BY VALUE"):
            assert key not in supported and key not in unsupported, key
        # ROUNDED is SUPPORTED -> must be declared supported.
        assert "ROUNDED" in supported, "ROUNDED was added as SUPPORTED"

"""Phase 12 P3 — BL-066: structured blocking-reason mapping.

`ModernizationPlanner._map_blocking_reasons` classified by raw substring:

* any reason containing "parse" (e.g. the word "parsed") became
  PARSE_FAILURE whenever the level was UNSUPPORTED — a misclassification;
* a GO TO reason appended UNSUPPORTED_CONSTRUCT a *second* time on top of
  the level-derived append, so the returned tuple carried duplicates.

Red-first: the two defects are exercised directly (RED on unmodified
code), then the fix (precise parse-failure phrasing + dedup guard) is
pinned, with guard tests that a genuine parse failure still maps to
PARSE_FAILURE and that GO TO alone still maps to UNSUPPORTED_CONSTRUCT.
"""

from __future__ import annotations

from engine.modernization.capability_analyzer import CapabilityLevel
from engine.modernization.modernization_planner import (
    BlockingReason,
    ModernizationPlanner,
)


_planner = ModernizationPlanner()


class TestBL066StructuredReasonMapping:
    def test_goto_reason_yields_single_unsupported_construct(self):
        """BL-066 duplicate: 'unsupported' + 'go to' both appended
        UNSUPPORTED_CONSTRUCT (defect 1: duplicated reasons tuple)."""
        reasons = _planner._map_blocking_reasons(
            CapabilityLevel.UNSUPPORTED,
            "UNSUPPORTED_CONSTRUCT: GO TO LOOP-DECK is not supported",
        )
        assert reasons.count(BlockingReason.UNSUPPORTED_CONSTRUCT) == 1, reasons
        assert BlockingReason.UNKNOWN_CONSTRUCT not in reasons, reasons

    def test_go_to_only_reason_still_maps_to_unsupported(self):
        """Behavior-preservation guard: GO TO alone (no 'unsupported'
        substring) still classifies via the level-derived clause."""
        reasons = _planner._map_blocking_reasons(
            CapabilityLevel.UNSUPPORTED,
            "GO TO target cannot be mapped",
        )
        assert BlockingReason.UNSUPPORTED_CONSTRUCT in reasons, reasons

    def test_parsed_wording_is_not_a_parse_failure(self):
        """BL-066 misclassification (defect 2): a reason that merely
        mentions being *parsed* must not become PARSE_FAILURE. With no
        other matching phrase the planner's documented fall-through is
        UNKNOWN_CONSTRUCT (the mapping never consults the capability
        level for UNSUPPORTED-class reasons)."""
        reasons = _planner._map_blocking_reasons(
            CapabilityLevel.UNSUPPORTED,
            "construct was PARSED during discovery but has no lowering",
        )
        assert BlockingReason.PARSE_FAILURE not in reasons, reasons
        assert reasons == (BlockingReason.UNKNOWN_CONSTRUCT,), reasons

    def test_genuine_parse_failure_still_maps(self):
        """Guard against over-fixing: real parse-failure phrasing keeps
        its PARSE_FAILURE classification."""
        reasons = _planner._map_blocking_reasons(
            CapabilityLevel.UNSUPPORTED,
            "failed to parse program text",
        )
        assert BlockingReason.PARSE_FAILURE in reasons, reasons

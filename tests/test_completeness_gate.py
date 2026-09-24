from __future__ import annotations

from engine.modernization.capability_analyzer import (
    CapabilityLevel,
    CapabilityReport,
    ComponentCapability,
)
from engine.modernization.completeness_gate import (
    Readiness,
    evaluate_verification_readiness,
)


def _report(*levels: CapabilityLevel) -> CapabilityReport:
    components = tuple(
        ComponentCapability(
            component_id=f"component-{i}",
            component_type="PROGRAM",
            level=level,
        )
        for i, level in enumerate(levels)
    )
    overall = (
        CapabilityLevel.UNSUPPORTED
        if CapabilityLevel.UNSUPPORTED in levels
        else CapabilityLevel.UNAVAILABLE
        if CapabilityLevel.UNAVAILABLE in levels
        else CapabilityLevel.PARTIAL
        if CapabilityLevel.PARTIAL in levels
        else CapabilityLevel.SUPPORTED
    )
    return CapabilityReport("gate-test", components, overall)


def test_supported_is_ready() -> None:
    decision = evaluate_verification_readiness(
        _report(CapabilityLevel.SUPPORTED)
    )
    assert decision.readiness is Readiness.READY
    assert decision.ready


def test_partial_is_blocked_by_default() -> None:
    decision = evaluate_verification_readiness(
        _report(CapabilityLevel.SUPPORTED, CapabilityLevel.PARTIAL)
    )
    assert decision.readiness is Readiness.BLOCKED
    assert any("PARTIAL" in reason for reason in decision.reasons)


def test_partial_can_be_explicitly_exploratory() -> None:
    decision = evaluate_verification_readiness(
        _report(CapabilityLevel.PARTIAL),
        allow_partial=True,
    )
    assert decision.readiness is Readiness.READY


def test_unsupported_always_blocks() -> None:
    decision = evaluate_verification_readiness(
        _report(CapabilityLevel.UNSUPPORTED),
        allow_partial=True,
    )
    assert decision.readiness is Readiness.BLOCKED


def test_unavailable_always_blocks() -> None:
    decision = evaluate_verification_readiness(
        _report(CapabilityLevel.UNAVAILABLE),
        allow_partial=True,
    )
    assert decision.readiness is Readiness.BLOCKED

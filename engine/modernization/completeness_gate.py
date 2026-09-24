"""Fail-closed readiness gate for modernization verification.

The gate is a policy boundary: unsupported, unavailable, or (by default)
partial capabilities cannot silently proceed as if they were production-ready.
It does not claim business equivalence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.modernization.capability_analyzer import CapabilityReport


class Readiness(Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ReadinessDecision:
    readiness: Readiness
    reasons: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.readiness is Readiness.READY

    def to_dict(self) -> dict[str, object]:
        return {
            "readiness": self.readiness.value,
            "ready": self.ready,
            "reasons": list(self.reasons),
        }


def evaluate_verification_readiness(
    report: CapabilityReport,
    *,
    allow_partial: bool = False,
) -> ReadinessDecision:
    """Evaluate whether an application may enter verification."""
    reasons: list[str] = []

    if report.unsupported_count:
        reasons.append(f"{report.unsupported_count} component(s) are UNSUPPORTED")
    if report.unavailable_count:
        reasons.append(f"{report.unavailable_count} component(s) are UNAVAILABLE")
    if report.partial_count and not allow_partial:
        reasons.append(
            f"{report.partial_count} component(s) are PARTIAL "
            "(exploratory mode is required to continue)"
        )

    if reasons:
        return ReadinessDecision(Readiness.BLOCKED, tuple(reasons))
    return ReadinessDecision(Readiness.READY)

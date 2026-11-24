"""Layer 8: reconcile the Layer 7 capability report with the application before a plan is drawn from it.

``TransformationPlanGenerator`` used to read the report as a bare ``{component_id: component}`` map.  That map was fail-open:

* a later component overwrote an earlier one with the same id, so ``UNSUPPORTED`` then ``SUPPORTED`` planned ``TRANSFORM``;
* a copybook and a program with one name shared one entry, so a copybook was planned from a program's evidence;
* a report for another application, a report whose ``overall_level`` disagrees with its own components, and components
  naming programs or copybooks the application does not have, were all accepted silently;
* a level that was not a ``CapabilityLevel`` crashed the planner instead of blocking.

Here the evidence is reconciled once, deterministically, into two things: the *effective* capability of each
``(component_type, component_id)`` (the worst of every statement made about it, never the last one) and the
*conflicts* that make the whole report untrustworthy.  Any conflict blocks every program and copybook of the plan with the
conflict named; a component-level contradiction lowers that component to its worst level.  Nothing here ever raises a level.

Pure and deterministic: no clock, no randomness, no I/O, no LLM.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from engine.modernization.capability_analyzer import CapabilityReport, ComponentCapability
from engine.transformation.ir import CobolApplication
from engine.transformation.semantic_capability import CapabilityLevel, worst_level

#: Component types whose ids must name something the application has.
_ANCHORED_TYPES = ("PROGRAM", "COPYBOOK")


@dataclass(frozen=True)
class ReconciledEvidence:
    """The capability evidence a plan may rely on."""

    by_key: dict[tuple[str, str], ComponentCapability]
    conflicts: tuple[str, ...]
    notes: tuple[str, ...] = ()     # component-level disagreements already resolved to the worst level

    def capability(self, component_type: str, component_id: str) -> ComponentCapability | None:
        return self.by_key.get((component_type, component_id))


def _level_of(component: ComponentCapability) -> CapabilityLevel:
    """The component's level, or ``UNKNOWN`` when it is not a ``CapabilityLevel`` (a value nobody defined is not support)."""
    return component.level if isinstance(component.level, CapabilityLevel) else CapabilityLevel.UNKNOWN


def _merge(key: tuple[str, str], group: list[ComponentCapability]) -> tuple[ComponentCapability, str]:
    """One effective component from every statement made about one key, and a note when they disagreed.

    The worst level wins.  Among the statements at that level the *last* one supplies the reason (it is the one the former
    last-wins lookup used, so a refusal's wording does not change); the disagreement is stated in the returned note, never in
    the reason.
    """
    levels = [_level_of(c) for c in group]
    worst = worst_level(levels)
    assert worst is not None
    chosen = [c for c, level in zip(group, levels) if level is worst][-1]
    reason = chosen.reason
    if not isinstance(chosen.level, CapabilityLevel):
        reason = f"capability level {chosen.level!r} is not a known level: {reason}".rstrip(": ")
    note = ""
    if len(set(levels)) > 1:
        seen = ", ".join(sorted({level.value for level in levels}))
        note = f"capability evidence for {key[0].lower()} {key[1]!r} disagreed ({seen}); the worst level applies"
    return dataclasses.replace(chosen, level=worst, reason=reason, details=dict(chosen.details)), note


def _conflicts(application: CobolApplication, report: CapabilityReport, effective: list[ComponentCapability]) -> list[str]:
    problems: list[str] = []
    if report.application_id != application.application_id:
        problems.append(f"capability report is for application {report.application_id!r}, "
                        f"the plan is for {application.application_id!r}")
    if report.components:
        components = [_level_of(c) for c in report.components]
        derived = worst_level(components)
        stated = report.overall_level if isinstance(report.overall_level, CapabilityLevel) else None
        if stated is not derived:
            problems.append(f"capability report states overall level {getattr(stated, 'value', report.overall_level)!r} "
                            f"but its components give {getattr(derived, 'value', derived)!r}")
    programs = [u.program_id for u in application.programs]
    known = {"PROGRAM": set(programs), "COPYBOOK": set(application.copybooks)}
    for component in effective:
        if component.component_type in _ANCHORED_TYPES and component.component_id not in known[component.component_type]:
            problems.append(f"capability evidence names {component.component_type.lower()} "
                            f"{component.component_id!r}, which the application does not have")
    return problems


def reconcile(application: CobolApplication, report: CapabilityReport) -> ReconciledEvidence:
    """The effective capability per ``(type, id)`` and every conflict that invalidates the report."""
    groups: dict[tuple[str, str], list[ComponentCapability]] = {}
    for component in report.components:
        groups.setdefault((component.component_type, component.component_id), []).append(component)
    merged: dict[tuple[str, str], ComponentCapability] = {}
    notes: list[str] = []
    for key, group in sorted(groups.items()):
        merged[key], note = _merge(key, group)
        if note:
            notes.append(note)
    return ReconciledEvidence(by_key=merged, conflicts=tuple(_conflicts(application, report, list(merged.values()))),
                              notes=tuple(notes))

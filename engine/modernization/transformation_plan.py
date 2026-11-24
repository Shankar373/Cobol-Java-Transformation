"""Transformation plan generator — produces a TransformationPlan from a
CapabilityReport and discovered application.

The plan:
    1. Routes each program to the appropriate transformer
    2. Orders programs callees-first (``priority``, ``execution_order``); the component list keeps discovery order
    3. Marks unsupported/unavailable components, and the callers of blocked programs, for skip
    4. Specifies assembly requirements
    5. Defines oracle execution parameters

The plan is a data structure consumed by the pipeline; it does NOT
perform any transformation itself.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from engine.transformation.entrypoint import resolve_entrypoint
from engine.modernization.capability_analyzer import (
    CapabilityLevel,
    CapabilityReport,
    ComponentCapability,
)
from engine.modernization.plan_evidence import reconcile
from engine.modernization.plan_graph import blocked_by_dependency, dependency_ranks, oracle_parameters
from engine.transformation.ir import CobolApplication
from engine.transformation.runtime_adapters import VALID_PLAN_OUTPUT_TYPES


def _require_valid_plan_output_type(value: str) -> None:
    """Fail closed when the plan would record an unknown assembly target."""
    if value not in VALID_PLAN_OUTPUT_TYPES:
        raise ValueError(
            f"invalid assembly_output_type: {value!r} — supported plan "
            f"output types: "
            f"{', '.join(repr(v) for v in VALID_PLAN_OUTPUT_TYPES)}"
        )


class TransformerType(Enum):
    """Which transformer handles a component."""
    INTERNAL_NATIVE = "INTERNAL_NATIVE"
    OPEN_SOURCE_4J = "OPEN_SOURCE_4J"
    SKIP = "SKIP"


class TransformationAction(Enum):
    """What to do with a component."""
    TRANSFORM = "TRANSFORM"
    SKIP = "SKIP"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class ComponentPlan:
    """Transformation plan for a single component."""
    component_id: str
    component_type: str
    action: TransformationAction
    transformer: TransformerType
    reason: str = ""
    priority: int = 0  # lower = earlier in execution order (programs: callees first; 0 = not ordered)
    #: The capability level the decision rests on ("MISSING" when the report said nothing) and the Layer 5 ids that
    #: justify it, carried from the capability component; neither is part of the plan identity (``plan_id``).
    capability_level: str = ""
    provenance: str = ""
    #: The callee that blocks this program (a RESOLVED CALL to a program that is not transformed); "" otherwise.
    blocked_by: str = ""


@dataclass(frozen=True)
class AssemblyPlan:
    """Plan for assembling the final application."""
    output_type: str  # "SPRING_BOOT", "NATIVE_JAVA"
    base_package: str
    application_name: str
    include_service_registry: bool


@dataclass(frozen=True)
class OraclePlan:
    """Plan for GnuCOBOL oracle execution."""
    source_format: str  # "free" or "fixed"
    entry_program: str  # "" unless entry_resolution is "RESOLVED"
    link_modules: tuple[str, ...] = ()
    input_files: tuple[str, ...] = ()
    # RESOLVED: the entry was requested and matched exactly, or the CALL graph proves a
    # single root.  UNRESOLVED: no entry could be established (entry_program is "" and
    # entry_diagnostic says why); an unresolved plan must not be run on an oracle.
    entry_resolution: str = "RESOLVED"
    entry_diagnostic: str = ""


@dataclass(frozen=True)
class TransformationPlan:
    """Complete transformation plan for an application."""
    application_id: str
    components: tuple[ComponentPlan, ...]
    assembly: AssemblyPlan
    oracle: OraclePlan
    total_programs: int
    transformable_programs: int
    skipped_programs: int
    #: Why the capability report could not be trusted at all (empty when it could); every program and copybook is then SKIP.
    evidence_conflicts: tuple[str, ...] = ()
    #: Component-level disagreements in the report that were resolved to the worst level (informational, not blocking).
    evidence_notes: tuple[str, ...] = ()

    @property
    def entrypoint_resolved(self) -> bool:
        return self.oracle.entry_resolution == "RESOLVED" and bool(self.oracle.entry_program)

    @property
    def entry_transformable(self) -> bool:
        """The entry was established *and* its program is planned for transformation (an entry nobody emits runs nothing)."""
        if not self.entrypoint_resolved:
            return False
        entry = [c for c in self.components
                 if c.component_type == "PROGRAM" and c.component_id == self.oracle.entry_program]
        return bool(entry) and all(c.action == TransformationAction.TRANSFORM for c in entry)

    @property
    def execution_order(self) -> tuple[str, ...]:
        """Program ids in the order they are to be built: callees before callers."""
        programs = [c for c in self.components if c.component_type == "PROGRAM"]
        return tuple(c.component_id for c in sorted(programs, key=lambda c: c.priority))

    @property
    def has_transformations(self) -> bool:
        return any(c.action == TransformationAction.TRANSFORM for c in self.components)

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "oracle": {
                "entry_program": self.oracle.entry_program,
                "entry_resolution": self.oracle.entry_resolution,
                "entry_diagnostic": self.oracle.entry_diagnostic,
                "source_format": self.oracle.source_format,
                "link_modules": list(self.oracle.link_modules),
            },
            "evidence_conflicts": list(self.evidence_conflicts),
            "evidence_notes": list(self.evidence_notes),
            "total_programs": self.total_programs,
            "transformable_programs": self.transformable_programs,
            "skipped_programs": self.skipped_programs,
            "components": [
                {
                    "component_id": c.component_id,
                    "action": c.action.value,
                    "transformer": c.transformer.value,
                    "reason": c.reason,
                    "priority": c.priority,
                    "capability_level": c.capability_level,
                    "provenance": c.provenance,
                    "blocked_by": c.blocked_by,
                }
                for c in self.components
            ],
            "assembly": {
                "output_type": self.assembly.output_type,
                "base_package": self.assembly.base_package,
                "application_name": self.assembly.application_name,
            },
        }


class TransformationPlanGenerator:
    """Generates transformation plans from capability reports and application graphs.

    Usage:
        generator = TransformationPlanGenerator()
        plan = generator.generate(application, capability_report)
    """

    def generate(
        self,
        application: CobolApplication,
        report: CapabilityReport,
        entrypoint: str = "",
        assembly_output_type: str = "SPRING_BOOT",
    ) -> TransformationPlan:
        """Generate a transformation plan from a capability report.

        ``assembly_output_type`` records which runtime target this
        plan assembles for; it is validated fail-closed against the plan
        vocabulary so the plan can never claim a target the pipeline is
        not configured to emit.
        """
        _require_valid_plan_output_type(assembly_output_type)
        components: list[ComponentPlan] = []

        # Reconcile the report with the application: the worst statement per (type, id), and every conflict that
        # makes the report untrustworthy (which blocks every program and copybook).
        evidence = reconcile(application, report)
        ranks = dependency_ranks(application)

        # Plan each program (discovery order; ``priority`` carries the callees-first order)
        for position, unit in enumerate(self._topological_sort(application)):
            cap = evidence.capability("PROGRAM", unit.program_id)
            plan = self._plan_program(unit.program_id, cap, evidence.conflicts)
            components.append(self._stamp(plan, cap, ranks[position]))

        # A FILE the capability analysis did not support blocks the program that owns it (its id is "PROGRAM:FILE").
        for (kind, component_id), file_cap in evidence.by_key.items():
            owner = component_id.split(":", 1)[0]
            if kind == "FILE" and file_cap.level != CapabilityLevel.SUPPORTED:
                components = [
                    dataclasses.replace(
                        c, action=TransformationAction.SKIP, transformer=TransformerType.SKIP,
                        reason=f"{file_cap.level.value}: file {component_id.partition(':')[2]}: {file_cap.reason}")
                    if c.component_type == "PROGRAM" and c.component_id == owner
                    and c.action == TransformationAction.TRANSFORM else c
                    for c in components]

        # Plan copybooks
        for cb_name in application.copybooks:
            cap = evidence.capability("COPYBOOK", cb_name)
            if evidence.conflicts:
                components.append(self._blocked_by_conflict(cb_name, "COPYBOOK", evidence.conflicts))
            elif cap is None:
                components.append(ComponentPlan(
                    component_id=cb_name,
                    component_type="COPYBOOK",
                    action=TransformationAction.SKIP,
                    transformer=TransformerType.SKIP,
                    reason="No capability analysis result — copybook transformation blocked",
                    capability_level="MISSING",
                ))
            elif cap.level == CapabilityLevel.SUPPORTED:
                components.append(self._stamp(ComponentPlan(
                    component_id=cb_name,
                    component_type="COPYBOOK",
                    action=TransformationAction.TRANSFORM,
                    transformer=TransformerType.INTERNAL_NATIVE,
                    reason=cap.reason,
                ), cap, 0))
            else:
                components.append(self._stamp(ComponentPlan(
                    component_id=cb_name,
                    component_type="COPYBOOK",
                    action=TransformationAction.SKIP,
                    transformer=TransformerType.SKIP,
                    reason=f"{cap.level.value}: {cap.reason}",
                ), cap, 0))

        # A program that CALLs (resolved) a program the plan does not transform, or that COPYs a copybook the plan does not
        # transform, cannot be transformed either.  ``blocked_by`` keeps such a caller out of the refusal's program list: the
        # refusal names the root cause (the callee's or the copybook's own reason), as it always did.
        transformable_ids = [c.component_id for c in components
                             if c.component_type == "PROGRAM" and c.action == TransformationAction.TRANSFORM]
        skipped_copybooks = {c.component_id for c in components
                             if c.component_type == "COPYBOOK" and c.action == TransformationAction.SKIP}
        for blocked, dependency in blocked_by_dependency(application, transformable_ids, skipped_copybooks).items():
            components = [
                dataclasses.replace(
                    c, action=TransformationAction.SKIP, transformer=TransformerType.SKIP, blocked_by=dependency,
                    reason=f"Dependency blocked: {dependency}, which is not transformable")
                if c.component_type == "PROGRAM" and c.component_id == blocked else c
                for c in components]

        # Plan every CALL that is not RESOLVED (UNRESOLVED, AMBIGUOUS or no resolution at all): fail closed
        for edge in application.edges:
            if edge.edge_type == "CALL" and edge.resolution != "RESOLVED":
                components.append(ComponentPlan(
                    component_id=f"{edge.source}->{edge.target}",
                    component_type="CALL",
                    action=TransformationAction.SKIP,
                    transformer=TransformerType.SKIP,
                    reason=(f"Unresolved call target: {edge.target}" if edge.resolution == "UNRESOLVED"
                            else f"Call target {edge.target} is {edge.resolution or 'not resolved'}, not RESOLVED"),
                    capability_level=CapabilityLevel.UNSUPPORTED.value,
                ))

        # Every CALL the capability analysis did not classify SUPPORTED -
        # arity mismatch, cycle, dynamic target, unproven callee - is a plan
        # entry too. Only UNRESOLVED edges used to reach the plan, so an
        # arity mismatch or an A->B->A cycle went on to javac or the oracle
        # instead of being refused here (audit A8).
        planned_calls = {c.component_id for c in components if c.component_type == "CALL"}
        for (kind, component_id), cap in evidence.by_key.items():
            if kind == "CALL" and cap.level != CapabilityLevel.SUPPORTED and component_id not in planned_calls:
                planned_calls.add(component_id)
                components.append(self._stamp(ComponentPlan(
                    component_id=component_id,
                    component_type="CALL",
                    action=TransformationAction.SKIP,
                    transformer=TransformerType.SKIP,
                    reason=f"{cap.level.value}: {cap.reason}",
                ), cap, 0))

        # Resolve entrypoint
        resolved_entry, entry_diagnostic = self._resolve_entrypoint(application, components, entrypoint)

        # Count stats
        programs = [c for c in components if c.component_type == "PROGRAM"]
        total = len(programs)
        transformable = sum(1 for c in programs if c.action == TransformationAction.TRANSFORM)
        skipped = total - transformable

        # Build assembly plan
        assembly = AssemblyPlan(
            output_type=assembly_output_type,
            base_package="com.modernized.app",
            application_name=application.application_id,
            include_service_registry=len(programs) > 1,
        )

        # Build oracle plan
        source_format, link_modules = oracle_parameters(application, resolved_entry)
        oracle = OraclePlan(
            source_format=source_format,
            entry_program=resolved_entry,
            link_modules=link_modules,
            entry_resolution="RESOLVED" if resolved_entry else "UNRESOLVED",
            entry_diagnostic=entry_diagnostic,
        )

        return TransformationPlan(
            application_id=application.application_id,
            components=tuple(components),
            assembly=assembly,
            oracle=oracle,
            total_programs=total,
            transformable_programs=transformable,
            skipped_programs=skipped,
            evidence_conflicts=evidence.conflicts,
            evidence_notes=evidence.notes,
        )

    @staticmethod
    def _stamp(plan: ComponentPlan, capability: ComponentCapability | None, priority: int) -> ComponentPlan:
        """``plan`` with its dependency priority and the capability level and Layer 5 provenance it rests on."""
        if plan.capability_level == "CONFLICT":
            return dataclasses.replace(plan, priority=priority)
        if capability is None:
            return dataclasses.replace(plan, priority=priority, capability_level="MISSING")
        return dataclasses.replace(
            plan, priority=priority, capability_level=capability.level.value,
            provenance=capability.details.get("ir_provenance", ""))

    @staticmethod
    def _blocked_by_conflict(component_id: str, component_type: str, conflicts: tuple[str, ...]) -> ComponentPlan:
        return ComponentPlan(
            component_id=component_id,
            component_type=component_type,
            action=TransformationAction.SKIP,
            transformer=TransformerType.SKIP,
            reason="Capability evidence conflict — transformation blocked: " + "; ".join(conflicts),
            capability_level="CONFLICT",
        )

    def _plan_program(
        self,
        program_id: str,
        capability: ComponentCapability | None,
        conflicts: tuple[str, ...] = (),
    ) -> ComponentPlan:
        """Plan a single program's transformation.

        Fail-closed contract:
            SUPPORTED   → TRANSFORM (the only path to transformation)
            PARTIAL     → SKIP  (partial support must not silently proceed)
            UNSUPPORTED → SKIP
            UNAVAILABLE → SKIP
            None/unknown → SKIP (missing capability is not a green light)
        """
        if conflicts:
            return self._blocked_by_conflict(program_id, "PROGRAM", conflicts)
        if capability is None:
            return ComponentPlan(
                component_id=program_id,
                component_type="PROGRAM",
                action=TransformationAction.SKIP,
                transformer=TransformerType.SKIP,
                reason="No capability analysis result — transformation blocked (unknown capability)",
            )

        if capability.level == CapabilityLevel.SUPPORTED:
            return ComponentPlan(
                component_id=program_id,
                component_type="PROGRAM",
                action=TransformationAction.TRANSFORM,
                transformer=TransformerType.INTERNAL_NATIVE,
                reason="All constructs supported",
            )
        if capability.level == CapabilityLevel.PARTIAL:
            # PARTIAL support must not silently proceed as if fully supported.
            # The generated candidate would be incomplete; transformation is blocked.
            return ComponentPlan(
                component_id=program_id,
                component_type="PROGRAM",
                action=TransformationAction.SKIP,
                transformer=TransformerType.SKIP,
                reason=f"Partial support — transformation blocked: {capability.reason}",
            )
        if capability.level == CapabilityLevel.UNSUPPORTED:
            return ComponentPlan(
                component_id=program_id,
                component_type="PROGRAM",
                action=TransformationAction.SKIP,
                transformer=TransformerType.SKIP,
                reason=f"Unsupported: {capability.reason}",
            )
        if capability.level == CapabilityLevel.UNAVAILABLE:
            return ComponentPlan(
                component_id=program_id,
                component_type="PROGRAM",
                action=TransformationAction.SKIP,
                transformer=TransformerType.SKIP,
                reason=f"Unavailable: {capability.reason}",
            )
        # Unknown/unexpected capability level — fail closed.
        return ComponentPlan(
            component_id=program_id,
            component_type="PROGRAM",
            action=TransformationAction.SKIP,
            transformer=TransformerType.SKIP,
            reason=f"Unknown capability level '{capability.level}' — transformation blocked",
        )

    def _topological_sort(self, application: CobolApplication) -> list:
        """Program units in discovery order; the callees-first order is each component's ``priority`` (plan_graph)."""
        return list(application.programs)

    def _resolve_entrypoint(
        self,
        application: CobolApplication,
        components: list[ComponentPlan],
        requested: str,
    ) -> tuple[str, str]:
        """Resolve the entrypoint program: ``(program_id, "")`` or ``("", reason)``.

        The same fail-closed rule as the generator (``engine.transformation.entrypoint``):
        a requested entry must match exactly one program; with none requested the CALL graph
        must prove a single root.  There is no fallback to the first (transformable) program:
        a plan whose entry cannot be established carries no entry and says why.  Copybooks
        and CALL components are never candidates.
        """
        programs = [c.component_id for c in components if c.component_type == "PROGRAM"]
        edges = tuple(
            (e.source, e.target) for e in application.edges if e.edge_type == "CALL"
        )
        return resolve_entrypoint(programs, requested, edges)

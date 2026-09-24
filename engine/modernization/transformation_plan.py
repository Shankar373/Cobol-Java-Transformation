"""Transformation plan generator — produces a TransformationPlan from a
CapabilityReport and discovered application.

The plan:
    1. Routes each program to the appropriate transformer
    2. Determines transformation order (topological sort by CALL graph)
    3. Marks unsupported/unavailable components for skip
    4. Specifies assembly requirements
    5. Defines oracle execution parameters

The plan is a data structure consumed by the pipeline; it does NOT
perform any transformation itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityLevel, CapabilityReport
from engine.transformation.ir import CobolApplication


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
    priority: int = 0  # lower = earlier in execution order


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
    entry_program: str
    link_modules: tuple[str, ...] = ()
    input_files: tuple[str, ...] = ()


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

    @property
    def has_transformations(self) -> bool:
        return any(c.action == TransformationAction.TRANSFORM for c in self.components)

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "total_programs": self.total_programs,
            "transformable_programs": self.transformable_programs,
            "skipped_programs": self.skipped_programs,
            "components": [
                {
                    "component_id": c.component_id,
                    "action": c.action.value,
                    "transformer": c.transformer.value,
                    "reason": c.reason,
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
    ) -> TransformationPlan:
        """Generate a transformation plan from a capability report."""
        components: list[ComponentPlan] = []

        # Build capability lookup
        capability_lookup = {c.component_id: c for c in report.components}

        # Topological order by CALL dependencies
        ordered_units = self._topological_sort(application)

        # Plan each program
        for unit in ordered_units:
            cap = capability_lookup.get(unit.program_id)
            plan = self._plan_program(unit.program_id, cap)
            components.append(plan)

        # Plan copybooks
        for cb_name in application.copybooks:
            cap = capability_lookup.get(cb_name)
            components.append(ComponentPlan(
                component_id=cb_name,
                component_type="COPYBOOK",
                action=TransformationAction.TRANSFORM,
                transformer=TransformerType.INTERNAL_NATIVE,
                reason="Copybook resolution",
            ))

        # Plan unresolved calls
        for edge in application.edges:
            if edge.edge_type == "CALL" and edge.metadata and "UNRESOLVED" in edge.metadata:
                components.append(ComponentPlan(
                    component_id=f"{edge.source}->{edge.target}",
                    component_type="CALL",
                    action=TransformationAction.SKIP,
                    transformer=TransformerType.SKIP,
                    reason=f"Unresolved call target: {edge.target}",
                ))

        # Resolve entrypoint
        resolved_entry = self._resolve_entrypoint(application, components, entrypoint)

        # Count stats
        programs = [c for c in components if c.component_type == "PROGRAM"]
        total = len(programs)
        transformable = sum(1 for c in programs if c.action == TransformationAction.TRANSFORM)
        skipped = total - transformable

        # Build assembly plan
        assembly = AssemblyPlan(
            output_type="SPRING_BOOT",
            base_package="com.modernized.app",
            application_name=application.application_id,
            include_service_registry=len(programs) > 1,
        )

        # Build oracle plan
        oracle = OraclePlan(
            source_format="free",
            entry_program=resolved_entry,
        )

        return TransformationPlan(
            application_id=application.application_id,
            components=tuple(components),
            assembly=assembly,
            oracle=oracle,
            total_programs=total,
            transformable_programs=transformable,
            skipped_programs=skipped,
        )

    def _plan_program(
        self,
        program_id: str,
        capability: 'ComponentCapability | None',
    ) -> ComponentPlan:
        """Plan a single program's transformation."""
        if capability is None:
            return ComponentPlan(
                component_id=program_id,
                component_type="PROGRAM",
                action=TransformationAction.TRANSFORM,
                transformer=TransformerType.INTERNAL_NATIVE,
                reason="No capability analysis — default transformable",
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
            return ComponentPlan(
                component_id=program_id,
                component_type="PROGRAM",
                action=TransformationAction.TRANSFORM,
                transformer=TransformerType.INTERNAL_NATIVE,
                reason=f"Partial support: {capability.reason}",
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
        return ComponentPlan(
            component_id=program_id,
            component_type="PROGRAM",
            action=TransformationAction.TRANSFORM,
            transformer=TransformerType.INTERNAL_NATIVE,
        )

    def _topological_sort(self, application: CobolApplication) -> list:
        """Sort program units topologically by CALL dependencies."""
        units = list(application.programs)
        # Simple stable sort — preserve discovery order for determinism
        return units

    def _resolve_entrypoint(
        self,
        application: CobolApplication,
        components: list[ComponentPlan],
        requested: str,
    ) -> str:
        """Resolve the entrypoint program.

        First tries transformable programs; falls back to any program
        in the graph so the oracle plan always has an entry point.
        """
        all_programs = [
            c for c in components if c.component_type == "PROGRAM"
        ]
        transformable = [
            c for c in all_programs
            if c.action == TransformationAction.TRANSFORM
        ]

        # Prefer explicit request
        if requested:
            for c in all_programs:
                if c.component_id.upper() == requested.upper():
                    return c.component_id

        # Prefer transformable
        if transformable:
            return transformable[0].component_id

        # Fall back to any program (for oracle plan even when SKIP)
        if all_programs:
            return all_programs[0].component_id

        return ""

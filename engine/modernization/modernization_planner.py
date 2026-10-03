"""Modernization Planner — Single entry point for Phase 1 modernization planning.

Architecture:
    Universal Ingestion
        ↓
    Application Discovery
        ↓
    Capability Graph
        ↓
    Modernization Plan

The planner exposes:
- programs
- entry programs
- CALL relationships
- copybook relationships
- file dependencies
- capability levels
- blocking reasons
- transformation strategy
- validation strategy

Fail-closed semantics:
    SUPPORTED     → may proceed
    PARTIAL       → explicitly marked (degraded capability)
    UNSUPPORTED   → blocked
    UNAVAILABLE   → blocked
    UNKNOWN       → blocked/unproven

This module does NOT implement transformation producers.
It only produces a deterministic, verifiable plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
    CapabilityReport,
    ComponentCapability,
)
from engine.modernization.transformation_plan import (
    TransformationAction,
    TransformationPlan,
    TransformationPlanGenerator,
    TransformerType,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.ir import (
    CobolApplication,
    CobolProgramUnit,
    DependencyEdge,
    FileDependency,
    ProgramCall,
)


class ModernizationStatus(Enum):
    """Overall modernization readiness status."""
    READY = "READY"                    # All programs SUPPORTED
    PARTIAL = "PARTIAL"                # Some programs PARTIAL, rest SUPPORTED
    BLOCKED = "BLOCKED"                # Has UNSUPPORTED or UNAVAILABLE
    UNKNOWN = "UNKNOWN"                # Cannot determine (should not happen)


class BlockingReason(Enum):
    """Reasons a component is blocked from modernization."""
    UNSUPPORTED_CONSTRUCT = "UNSUPPORTED_CONSTRUCT"
    DYNAMIC_CALL = "DYNAMIC_CALL"
    RECURSIVE_CALL = "RECURSIVE_CALL"
    UNRESOLVED_CALL = "UNRESOLVED_CALL"
    CALL_CYCLE = "CALL_CYCLE"
    MISSING_COPYBOOK = "MISSING_COPYBOOK"
    MISSING_PROGRAM = "MISSING_PROGRAM"
    DOCKER_UNAVAILABLE = "DOCKER_UNAVAILABLE"
    PARSE_FAILURE = "PARSE_FAILURE"
    UNKNOWN_CONSTRUCT = "UNKNOWN_CONSTRUCT"


class TransformationStrategy(Enum):
    """Strategy for transforming a component."""
    INTERNAL_NATIVE = "INTERNAL_NATIVE"
    OPEN_SOURCE_4J = "OPEN_SOURCE_4J"
    EXTERNAL = "EXTERNAL"
    MANUAL = "MANUAL"
    SKIP = "SKIP"


class ValidationStrategy(Enum):
    """Strategy for validating a transformed component."""
    DOCKER_ORACLE = "DOCKER_ORACLE"
    SEMANTIC_COMPARISON = "SEMANTIC_COMPARISON"
    UNIT_TEST = "UNIT_TEST"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    SKIP = "SKIP"


@dataclass(frozen=True)
class ProgramPlan:
    """Plan for a single COBOL program."""
    program_id: str
    source_path: str
    entry_points: tuple[str, ...]
    calls: tuple[ProgramCall, ...]
    copybooks: tuple[str, ...]
    file_dependencies: tuple[FileDependency, ...]
    capability_level: CapabilityLevel
    capability_reason: str
    blocking_reasons: tuple[BlockingReason, ...]
    transformation_strategy: TransformationStrategy
    validation_strategy: ValidationStrategy
    paragraphs: int
    data_items: int
    file_count: int

    @property
    def is_supported(self) -> bool:
        return self.capability_level == CapabilityLevel.SUPPORTED

    @property
    def is_partial(self) -> bool:
        return self.capability_level == CapabilityLevel.PARTIAL

    @property
    def is_blocked(self) -> bool:
        return self.capability_level in (
            CapabilityLevel.UNSUPPORTED,
            CapabilityLevel.UNAVAILABLE,
        )

    @property
    def may_proceed(self) -> bool:
        """Fail-closed: only SUPPORTED may proceed."""
        return self.capability_level == CapabilityLevel.SUPPORTED


@dataclass(frozen=True)
class CopybookPlan:
    """Plan for a copybook."""
    copybook_name: str
    source_program: str
    capability_level: CapabilityLevel
    capability_reason: str
    blocking_reasons: tuple[BlockingReason, ...]
    transformation_strategy: TransformationStrategy
    validation_strategy: ValidationStrategy

    @property
    def may_proceed(self) -> bool:
        return self.capability_level == CapabilityLevel.SUPPORTED


@dataclass(frozen=True)
class CallRelationship:
    """A CALL relationship between programs."""
    caller: str
    target: str
    arguments: tuple[str, ...]
    call_type: str  # STATIC, DYNAMIC
    resolution: str  # RESOLVED, UNRESOLVED, EXTERNAL
    capability_level: CapabilityLevel
    capability_reason: str
    blocking_reasons: tuple[BlockingReason, ...]
    transformation_strategy: TransformationStrategy
    validation_strategy: ValidationStrategy

    @property
    def may_proceed(self) -> bool:
        return self.capability_level == CapabilityLevel.SUPPORTED


@dataclass(frozen=True)
class FileDependencyPlan:
    """File dependency plan."""
    program_id: str
    file_name: str
    operation: str  # READ, WRITE, OPEN, CLOSE
    mode: str
    capability_level: CapabilityLevel
    capability_reason: str
    blocking_reasons: tuple[BlockingReason, ...]
    transformation_strategy: TransformationStrategy
    validation_strategy: ValidationStrategy

    @property
    def may_proceed(self) -> bool:
        return self.capability_level == CapabilityLevel.SUPPORTED


@dataclass(frozen=True)
class EntryProgram:
    """An entry program (has STOP RUN or is JCL entry point)."""
    program_id: str
    source_path: str
    entry_points: tuple[str, ...]
    has_stop_run: bool
    is_jcl_entry: bool = False


@dataclass(frozen=True)
class ModernizationPlan:
    """Complete modernization plan for a COBOL application."""
    application_id: str
    source_directory: str

    # Programs
    programs: tuple[ProgramPlan, ...]
    entry_programs: tuple[EntryProgram, ...]

    # Relationships
    call_relationships: tuple[CallRelationship, ...]
    copybook_relationships: tuple[CopybookPlan, ...]
    file_dependencies: tuple[FileDependencyPlan, ...]

    # Capability summary
    capability_report: CapabilityReport
    overall_status: ModernizationStatus

    # Statistics
    total_programs: int
    supported_programs: int
    partial_programs: int
    unsupported_programs: int
    unavailable_programs: int
    unknown_programs: int

    # Transformation plan
    transformation_plan: TransformationPlan

    # Blocking summary
    blocking_summary: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "source_directory": self.source_directory,
            "overall_status": self.overall_status.value,
            "statistics": {
                "total_programs": self.total_programs,
                "supported": self.supported_programs,
                "partial": self.partial_programs,
                "unsupported": self.unsupported_programs,
                "unavailable": self.unavailable_programs,
                "unknown": self.unknown_programs,
            },
            "programs": [
                {
                    "program_id": p.program_id,
                    "source_path": p.source_path,
                    "entry_points": list(p.entry_points),
                    "calls": [c.target for c in p.calls],
                    "copybooks": list(p.copybooks),
                    "file_dependencies": [f"{fd.operation}:{fd.file_name}" for fd in p.file_dependencies],
                    "capability_level": p.capability_level.value,
                    "capability_reason": p.capability_reason,
                    "blocking_reasons": [br.value for br in p.blocking_reasons],
                    "transformation_strategy": p.transformation_strategy.value,
                    "validation_strategy": p.validation_strategy.value,
                    "may_proceed": p.may_proceed,
                    "paragraphs": p.paragraphs,
                    "data_items": p.data_items,
                    "file_count": p.file_count,
                }
                for p in self.programs
            ],
            "entry_programs": [
                {
                    "program_id": ep.program_id,
                    "source_path": ep.source_path,
                    "entry_points": list(ep.entry_points),
                    "has_stop_run": ep.has_stop_run,
                    "is_jcl_entry": ep.is_jcl_entry,
                }
                for ep in self.entry_programs
            ],
            "call_relationships": [
                {
                    "caller": cr.caller,
                    "target": cr.target,
                    "arguments": list(cr.arguments),
                    "call_type": cr.call_type,
                    "resolution": cr.resolution,
                    "capability_level": cr.capability_level.value,
                    "capability_reason": cr.capability_reason,
                    "blocking_reasons": [br.value for br in cr.blocking_reasons],
                    "transformation_strategy": cr.transformation_strategy.value,
                    "validation_strategy": cr.validation_strategy.value,
                    "may_proceed": cr.may_proceed,
                }
                for cr in self.call_relationships
            ],
            "copybook_relationships": [
                {
                    "copybook_name": cb.copybook_name,
                    "source_program": cb.source_program,
                    "capability_level": cb.capability_level.value,
                    "capability_reason": cb.capability_reason,
                    "blocking_reasons": [br.value for br in cb.blocking_reasons],
                    "transformation_strategy": cb.transformation_strategy.value,
                    "validation_strategy": cb.validation_strategy.value,
                    "may_proceed": cb.may_proceed,
                }
                for cb in self.copybook_relationships
            ],
            "file_dependencies": [
                {
                    "program_id": fd.program_id,
                    "file_name": fd.file_name,
                    "operation": fd.operation,
                    "mode": fd.mode,
                    "capability_level": fd.capability_level.value,
                    "capability_reason": fd.capability_reason,
                    "blocking_reasons": [br.value for br in fd.blocking_reasons],
                    "transformation_strategy": fd.transformation_strategy.value,
                    "validation_strategy": fd.validation_strategy.value,
                    "may_proceed": fd.may_proceed,
                }
                for fd in self.file_dependencies
            ],
            "blocking_summary": list(self.blocking_summary),
            "transformation_plan": self.transformation_plan.to_dict(),
        }


class ModernizationPlanner:
    """Single entry point for Phase 1 modernization planning.

    Usage:
        planner = ModernizationPlanner(docker_available=False)
        plan = planner.plan(source_directory, application_id="my-app")

    The planner:
    1. Discovers the COBOL application structure
    2. Analyzes capabilities against available transformers
    3. Produces a deterministic, complete modernization plan
    4. Exposes all relationships, capabilities, and strategies
    """

    def __init__(
        self,
        docker_available: bool = False,
        parser: Any | None = None,
    ) -> None:
        self._discovery = ApplicationDiscovery(parser=parser)
        self._capability_analyzer = CapabilityAnalyzer(
            docker_available=docker_available,
            cobol_parser=parser,
        )
        self._plan_generator = TransformationPlanGenerator()
        self._docker_available = docker_available

    def plan(
        self,
        source_dir: str | Path,
        application_id: str | None = None,
        entrypoint: str = "",
    ) -> ModernizationPlan:
        """Generate a complete modernization plan from a source directory.

        Args:
            source_dir: Directory containing COBOL source files.
            application_id: Explicit application ID (default: directory name).
            entrypoint: Requested entrypoint program ID.

        Returns:
            ModernizationPlan with all Phase 1 information.
        """
        source_path = Path(source_dir)
        if not source_path.exists():
            raise ValueError(f"Source directory does not exist: {source_dir}")

        # Phase 1: Universal Ingestion + Application Discovery
        application = self._discovery.discover(
            source_path,
            application_id=application_id or source_path.name,
        )

        # Phase 2: Capability Graph
        capability_report = self._capability_analyzer.analyze(application)

        # Phase 3: Modernization Plan (deterministic)
        transformation_plan = self._plan_generator.generate(
            application, capability_report, entrypoint
        )

        # Build detailed plan with all required exposures
        return self._build_plan(
            application,
            capability_report,
            transformation_plan,
            str(source_path),
        )

    def _build_plan(
        self,
        application: CobolApplication,
        capability_report: CapabilityReport,
        transformation_plan: TransformationPlan,
        source_dir: str,
    ) -> ModernizationPlan:
        """Build the detailed modernization plan."""
        # Lookup tables
        cap_by_id = {c.component_id: c for c in capability_report.components}
        unit_by_id = {u.program_id: u for u in application.programs}

        # Build program plans
        program_plans: list[ProgramPlan] = []
        entry_programs: list[EntryProgram] = []

        for unit in application.programs:
            cap = cap_by_id.get(unit.program_id)
            plan = self._build_program_plan(unit, cap)
            program_plans.append(plan)

            # Check if entry program
            if self._is_entry_program(unit):
                entry_programs.append(EntryProgram(
                    program_id=unit.program_id,
                    source_path=unit.source_path,
                    entry_points=unit.entry_points,
                    has_stop_run=self._has_stop_run(unit),
                ))

        # Build call relationships
        call_relationships: list[CallRelationship] = []
        for edge in application.edges:
            if edge.edge_type == "CALL":
                call_relationships.append(self._build_call_relationship(edge, cap_by_id))

        # Build copybook relationships
        copybook_relationships: list[CopybookPlan] = []
        for unit in application.programs:
            for cb in unit.copybooks:
                cap = cap_by_id.get(cb.copybook_name)
                copybook_relationships.append(self._build_copybook_plan(cb, cap))

        # Build file dependencies
        file_dependencies: list[FileDependencyPlan] = []
        for unit in application.programs:
            for fd in unit.file_dependencies:
                cap = cap_by_id.get(f"{unit.program_id}:{fd.file_name}")
                file_dependencies.append(self._build_file_plan(fd, cap))

        # Statistics
        total = len(program_plans)
        supported = sum(1 for p in program_plans if p.capability_level == CapabilityLevel.SUPPORTED)
        partial = sum(1 for p in program_plans if p.capability_level == CapabilityLevel.PARTIAL)
        unsupported = sum(1 for p in program_plans if p.capability_level == CapabilityLevel.UNSUPPORTED)
        unavailable = sum(1 for p in program_plans if p.capability_level == CapabilityLevel.UNAVAILABLE)

        # Overall status
        overall = self._derive_overall_status(capability_report)

        # Blocking summary
        blocking = self._build_blocking_summary(
            program_plans, call_relationships, copybook_relationships, file_dependencies, capability_report
        )

        return ModernizationPlan(
            application_id=application.application_id,
            source_directory=source_dir,
            programs=tuple(program_plans),
            entry_programs=tuple(entry_programs),
            call_relationships=tuple(call_relationships),
            copybook_relationships=tuple(copybook_relationships),
            file_dependencies=tuple(file_dependencies),
            capability_report=capability_report,
            overall_status=overall,
            total_programs=total,
            supported_programs=supported,
            partial_programs=partial,
            unsupported_programs=unsupported,
            unavailable_programs=unavailable,
            unknown_programs=0,  # Not used; UNKNOWN maps to UNSUPPORTED
            transformation_plan=transformation_plan,
            blocking_summary=tuple(blocking),
        )

    def _build_program_plan(
        self,
        unit: CobolProgramUnit,
        cap: ComponentCapability | None,
    ) -> ProgramPlan:
        """Build plan for a single program."""
        if cap is None:
            level = CapabilityLevel.UNKNOWN
            reason = "No capability analysis available"
            blocking = (BlockingReason.UNKNOWN_CONSTRUCT,)
        else:
            level = cap.level
            reason = cap.reason
            blocking = self._map_blocking_reasons(cap.level, cap.reason)

        # Determine transformation strategy
        if level == CapabilityLevel.SUPPORTED:
            strategy = TransformationStrategy.INTERNAL_NATIVE
        elif level == CapabilityLevel.PARTIAL:
            strategy = TransformationStrategy.INTERNAL_NATIVE
        elif level == CapabilityLevel.UNSUPPORTED:
            strategy = TransformationStrategy.MANUAL
        elif level == CapabilityLevel.UNAVAILABLE:
            strategy = TransformationStrategy.SKIP
        else:
            strategy = TransformationStrategy.SKIP

        # Validation strategy
        if level in (CapabilityLevel.SUPPORTED, CapabilityLevel.PARTIAL):
            validation = ValidationStrategy.DOCKER_ORACLE
        elif level == CapabilityLevel.UNSUPPORTED:
            validation = ValidationStrategy.MANUAL_REVIEW
        else:
            validation = ValidationStrategy.SKIP

        return ProgramPlan(
            program_id=unit.program_id,
            source_path=unit.source_path,
            entry_points=unit.entry_points,
            calls=unit.calls,
            copybooks=tuple(cb.copybook_name for cb in unit.copybooks),
            file_dependencies=unit.file_dependencies,
            capability_level=level,
            capability_reason=reason,
            blocking_reasons=blocking,
            transformation_strategy=strategy,
            validation_strategy=validation,
            paragraphs=len(unit.program.paragraphs) if unit.program else 0,
            data_items=len(unit.program.working_storage) if unit.program else 0,
            file_count=len(unit.program.file_definitions) if unit.program else 0,
        )

    def _build_call_relationship(
        self,
        edge: DependencyEdge,
        cap_by_id: dict[str, ComponentCapability],
    ) -> CallRelationship:
        """Build call relationship plan."""
        cap = cap_by_id.get(f"{edge.source}->{edge.target}")
        if cap:
            level = cap.level
            reason = cap.reason
            blocking = self._map_blocking_reasons(cap.level, cap.reason)
        else:
            # Derive from edge metadata
            metadata = edge.metadata or ""
            if "call_type=DYNAMIC" in metadata:
                level = CapabilityLevel.UNSUPPORTED
                reason = "Dynamic CALL (data-item target) has no static dispatch"
                blocking = (BlockingReason.DYNAMIC_CALL,)
            elif "resolution=UNRESOLVED" in metadata:
                level = CapabilityLevel.PARTIAL
                reason = "Unresolved static call target"
                blocking = (BlockingReason.UNRESOLVED_CALL,)
            elif edge.source == edge.target:
                level = CapabilityLevel.UNSUPPORTED
                reason = "Recursive/self CALL is out of scope"
                blocking = (BlockingReason.RECURSIVE_CALL,)
            else:
                level = CapabilityLevel.SUPPORTED
                reason = "Resolved"
                blocking = ()

        if level == CapabilityLevel.SUPPORTED:
            strategy = TransformationStrategy.INTERNAL_NATIVE
            validation = ValidationStrategy.DOCKER_ORACLE
        elif level == CapabilityLevel.PARTIAL:
            strategy = TransformationStrategy.INTERNAL_NATIVE
            validation = ValidationStrategy.DOCKER_ORACLE
        elif level == CapabilityLevel.UNSUPPORTED:
            strategy = TransformationStrategy.MANUAL
            validation = ValidationStrategy.MANUAL_REVIEW
        else:
            strategy = TransformationStrategy.SKIP
            validation = ValidationStrategy.SKIP

        return CallRelationship(
            caller=edge.source,
            target=edge.target,
            arguments=(),  # Would need deeper parsing
            call_type="DYNAMIC" if "call_type=DYNAMIC" in (edge.metadata or "") else "STATIC",
            resolution="UNRESOLVED" if "resolution=UNRESOLVED" in (edge.metadata or "") else "RESOLVED",
            capability_level=level,
            capability_reason=reason,
            blocking_reasons=blocking,
            transformation_strategy=strategy,
            validation_strategy=validation,
        )

    def _build_copybook_plan(
        self,
        cb_ref,
        cap: ComponentCapability | None,
    ) -> CopybookPlan:
        """Build copybook relationship plan."""
        if cap:
            level = cap.level
            reason = cap.reason
            blocking = self._map_blocking_reasons(cap.level, cap.reason)
        else:
            level = CapabilityLevel.SUPPORTED
            reason = "Copybook resolution supported"
            blocking = ()

        if level == CapabilityLevel.SUPPORTED:
            strategy = TransformationStrategy.INTERNAL_NATIVE
            validation = ValidationStrategy.DOCKER_ORACLE
        else:
            strategy = TransformationStrategy.SKIP
            validation = ValidationStrategy.SKIP

        return CopybookPlan(
            copybook_name=cb_ref.copybook_name,
            source_program=cb_ref.source_program,
            capability_level=level,
            capability_reason=reason,
            blocking_reasons=blocking,
            transformation_strategy=strategy,
            validation_strategy=validation,
        )

    def _build_file_plan(
        self,
        fd: FileDependency,
        cap: ComponentCapability | None,
    ) -> FileDependencyPlan:
        """Build file dependency plan."""
        if cap:
            level = cap.level
            reason = cap.reason
            blocking = self._map_blocking_reasons(cap.level, cap.reason)
        else:
            level = CapabilityLevel.SUPPORTED
            reason = f"Sequential file {fd.operation} supported"
            blocking = ()

        if level == CapabilityLevel.SUPPORTED:
            strategy = TransformationStrategy.INTERNAL_NATIVE
            validation = ValidationStrategy.DOCKER_ORACLE
        else:
            strategy = TransformationStrategy.SKIP
            validation = ValidationStrategy.SKIP

        return FileDependencyPlan(
            program_id=fd.program_id,
            file_name=fd.file_name,
            operation=fd.operation,
            mode=fd.mode,
            capability_level=level,
            capability_reason=reason,
            blocking_reasons=blocking,
            transformation_strategy=strategy,
            validation_strategy=validation,
        )

    def _is_entry_program(self, unit: CobolProgramUnit) -> bool:
        """Determine if a program is an entry point."""
        if unit.entry_points:
            return True
        if unit.program:
            for para in unit.program.paragraphs:
                for stmt in para.statements:
                    if type(stmt).__name__ == "StopRunStatement":
                        return True
        return False

    def _has_stop_run(self, unit: CobolProgramUnit) -> bool:
        """Check if program has STOP RUN."""
        if not unit.program:
            return False
        for para in unit.program.paragraphs:
            for stmt in para.statements:
                if type(stmt).__name__ == "StopRunStatement":
                    return True
        return False

    def _map_blocking_reasons(
        self,
        level: CapabilityLevel,
        reason: str,
    ) -> tuple[BlockingReason, ...]:
        """Map capability level and reason to blocking reasons."""
        if level == CapabilityLevel.SUPPORTED:
            return ()

        reasons: list[BlockingReason] = []
        reason_lower = reason.lower()

        if level == CapabilityLevel.UNAVAILABLE:
            reasons.append(BlockingReason.DOCKER_UNAVAILABLE)

        if "dynamic call" in reason_lower:
            reasons.append(BlockingReason.DYNAMIC_CALL)
        if "recursive" in reason_lower or "self call" in reason_lower:
            reasons.append(BlockingReason.RECURSIVE_CALL)
        if "unresolved" in reason_lower and "call" in reason_lower:
            reasons.append(BlockingReason.UNRESOLVED_CALL)
        if "cyclic" in reason_lower or "cycle" in reason_lower:
            reasons.append(BlockingReason.CALL_CYCLE)
        if "copybook" in reason_lower and "missing" in reason_lower:
            reasons.append(BlockingReason.MISSING_COPYBOOK)
        if "program" in reason_lower and ("missing" in reason_lower or "not found" in reason_lower):
            reasons.append(BlockingReason.MISSING_PROGRAM)
        if "parse" in reason_lower or "failed to parse" in reason_lower:
            reasons.append(BlockingReason.PARSE_FAILURE)
        if "unsupported" in reason_lower:
            reasons.append(BlockingReason.UNSUPPORTED_CONSTRUCT)
        if "go to" in reason_lower:
            reasons.append(BlockingReason.UNSUPPORTED_CONSTRUCT)

        if not reasons:
            reasons.append(BlockingReason.UNKNOWN_CONSTRUCT)

        return tuple(reasons)

    def _derive_overall_status(self, report: CapabilityReport) -> ModernizationStatus:
        """Derive overall modernization status from capability report."""
        if report.unavailable_count > 0:
            return ModernizationStatus.BLOCKED
        if report.unsupported_count > 0:
            return ModernizationStatus.BLOCKED
        if report.partial_count > 0:
            return ModernizationStatus.PARTIAL
        if report.supported_count > 0:
            return ModernizationStatus.READY
        return ModernizationStatus.UNKNOWN

    def _build_blocking_summary(
        self,
        programs: list[ProgramPlan],
        calls: list[CallRelationship],
        copybooks: list[CopybookPlan],
        files: list[FileDependencyPlan],
        capability_report: CapabilityReport,
    ) -> list[str]:
        """Build human-readable blocking summary."""
        summary: list[str] = []

        for p in programs:
            if p.is_blocked:
                for br in p.blocking_reasons:
                    summary.append(f"Program {p.program_id}: {br.value} — {p.capability_reason}")

        for cr in calls:
            if not cr.may_proceed:
                for br in cr.blocking_reasons:
                    summary.append(f"CALL {cr.caller}->{cr.target}: {br.value} — {cr.capability_reason}")

        for cb in copybooks:
            if not cb.may_proceed:
                for br in cb.blocking_reasons:
                    summary.append(f"COPYBOOK {cb.copybook_name}: {br.value} — {cb.capability_reason}")

        for fd in files:
            if not fd.may_proceed:
                for br in fd.blocking_reasons:
                    summary.append(f"FILE {fd.program_id}:{fd.file_name}: {br.value} — {fd.capability_reason}")

        # Check for cyclic CALL dependencies from capability report
        for comp in capability_report.components:
            if comp.component_type == "CALL" and "->" in comp.component_id and comp.component_id.count("->") >= 2:
                # This is a cycle component (e.g., "A->B->A")
                if comp.level in (CapabilityLevel.UNSUPPORTED, CapabilityLevel.UNAVAILABLE):
                    for br in self._map_blocking_reasons(comp.level, comp.reason):
                        summary.append(f"CALL CYCLE {comp.component_id}: {br.value} — {comp.reason}")

        if not summary:
            summary.append("No blocking issues identified")

        return summary
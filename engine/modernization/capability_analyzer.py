"""Capability analyzer — inspects the Application Semantic Graph and produces
a CapabilityReport classifying every component and construct.

Classification levels:
    SUPPORTED   — transformer can handle this construct fully
    PARTIAL     — transformer handles a subset; remainder is degraded
    UNSUPPORTED — transformer cannot handle this construct at all
    UNAVAILABLE — infrastructure (Docker, oracle) is not present

The analyzer is a pure function over the discovered application graph and the
available infrastructure. It does NOT transform anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.transformation.ir import (
    CobolApplication,
    CobolProgramUnit,
    CopybookReference,
    DependencyEdge,
    FileDependency,
    ProgramCall,
)
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.contracts import TransformationProducer


class CapabilityLevel(Enum):
    """Classification of a capability."""
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ComponentCapability:
    """Capability status for a single component or construct."""
    component_id: str
    component_type: str  # "PROGRAM", "COPYBOOK", "CALL", "FILE", "SQL", "CICS", "JCL"
    level: CapabilityLevel
    reason: str = ""
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityReport:
    """Complete capability analysis of a discovered application."""
    application_id: str
    components: tuple[ComponentCapability, ...]
    overall_level: CapabilityLevel

    @property
    def supported_count(self) -> int:
        return sum(1 for c in self.components if c.level == CapabilityLevel.SUPPORTED)

    @property
    def partial_count(self) -> int:
        return sum(1 for c in self.components if c.level == CapabilityLevel.PARTIAL)

    @property
    def unsupported_count(self) -> int:
        return sum(1 for c in self.components if c.level == CapabilityLevel.UNSUPPORTED)

    @property
    def unavailable_count(self) -> int:
        return sum(1 for c in self.components if c.level == CapabilityLevel.UNAVAILABLE)

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "overall_level": self.overall_level.value,
            "supported": self.supported_count,
            "partial": self.partial_count,
            "unsupported": self.unsupported_count,
            "unavailable": self.unavailable_count,
            "components": [
                {
                    "component_id": c.component_id,
                    "component_type": c.component_type,
                    "level": c.level.value,
                    "reason": c.reason,
                }
                for c in self.components
            ],
        }


class CapabilityAnalyzer:
    """Analyzes a discovered COBOL application against available capabilities.

    Usage:
        analyzer = CapabilityAnalyzer(producer_capabilities, docker_available)
        report = analyzer.analyze(application)
    """

    # These sets describe the capability vocabulary. Actual classification is
    # performed from semantic IR and downstream mapping evidence below.
    SUPPORTED_STATEMENTS = frozenset({
        "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
        "DISPLAY", "IF", "PERFORM", "READ", "WRITE", "OPEN", "CLOSE",
        "START", "REWRITE", "DELETE", "STRING", "STOP RUN", "CALL",
    })
    PARTIAL_STATEMENTS = frozenset({"UNSTRING", "PERFORM VARYING"})
    UNSUPPORTED_STATEMENTS = frozenset({"GO TO", "PERFORM TIMES", "UNKNOWN"})

    def __init__(
        self,
        producer_capabilities: tuple[object, ...] = (),
        docker_available: bool = False,
        cobol_parser: CobolParser | None = None,
    ) -> None:
        self._capabilities = set(producer_capabilities)
        self._docker_available = docker_available
        self._parser = cobol_parser or CobolParser()

    def analyze(self, application: CobolApplication) -> CapabilityReport:
        """Analyze a discovered application and produce a capability report."""
        components: list[ComponentCapability] = []

        # Check infrastructure first
        infra_level = self._check_infrastructure()

        # Analyze each program unit from semantic IR. Parser recognition alone
        # never grants capability.
        for unit in application.programs:
            components.extend(self._analyze_program_unit(unit))

        # COPYBOOK is a dependency relationship, not an independently generated
        # program. Discovery/resolution of the dependency is supported; the
        # copybook itself must not be emitted as a Java program. The consuming
        # program remains governed by the semantic IR produced for that program.
        for cb_name in application.copybooks:
            components.append(ComponentCapability(
                component_id=cb_name,
                component_type="COPYBOOK",
                level=CapabilityLevel.SUPPORTED,
                reason="Copybook dependency discovered; declarations are consumed as program source context and no standalone Java class is generated",
            ))

        # Analyze CALL edges using exact metadata tokens. Dynamic, unresolved
        # and cyclic dispatch are never transformable. Static calls to programs
        # present in the same application are resolved even if the discovery
        # object preserves the original call record as UNRESOLVED.
        for edge in application.edges:
            if edge.edge_type == "CALL":
                metadata = edge.metadata or ""
                target_known = edge.target.upper() in {p.program_id.upper() for p in application.programs}
                is_resolved = "resolution=RESOLVED" in metadata or target_known
                is_dynamic = "call_type=DYNAMIC" in metadata
                is_self_call = edge.source == edge.target
                if is_dynamic:
                    level = CapabilityLevel.UNSUPPORTED
                    reason = "Dynamic CALL (data-item target) has no static dispatch"
                elif is_self_call:
                    level = CapabilityLevel.UNSUPPORTED
                    reason = "Recursive/self CALL is out of scope"
                elif not is_resolved:
                    level = CapabilityLevel.PARTIAL
                    reason = "Unresolved static call target"
                else:
                    level = CapabilityLevel.SUPPORTED
                    reason = "Resolved static CALL dependency"
                components.append(ComponentCapability(
                    component_id=f"{edge.source}->{edge.target}",
                    component_type="CALL",
                    level=level,
                    reason=reason,
                ))

        for cycle in application.detect_cycles():
            components.append(ComponentCapability(
                component_id="->".join(cycle),
                component_type="CALL",
                level=CapabilityLevel.UNSUPPORTED,
                reason="Cyclic CALL dependency is out of scope",
            ))

        # Override with infrastructure unavailability (only for programs and calls)
        if infra_level == CapabilityLevel.UNAVAILABLE:
            for i, comp in enumerate(components):
                if comp.level == CapabilityLevel.SUPPORTED and comp.component_type in ("PROGRAM", "CALL"):
                    components[i] = ComponentCapability(
                        component_id=comp.component_id,
                        component_type=comp.component_type,
                        level=CapabilityLevel.UNAVAILABLE,
                        reason="Docker infrastructure not available",
                    )

        # Derive overall level
        overall = self._derive_overall_level(components)

        return CapabilityReport(
            application_id=application.application_id,
            components=tuple(components),
            overall_level=overall,
        )

    def _check_infrastructure(self) -> CapabilityLevel:
        """Check if Docker infrastructure is available."""
        if not self._docker_available:
            return CapabilityLevel.UNAVAILABLE
        return CapabilityLevel.SUPPORTED

    def _analyze_program_unit(self, unit: CobolProgramUnit) -> list[ComponentCapability]:
        """Classify a program from semantic IR and fail closed on gaps."""
        from engine.transformation.ir import FileOrganization, FileAccessMode

        components: list[ComponentCapability] = []
        if unit.program is None:
            return [ComponentCapability(
                component_id=unit.program_id,
                component_type="PROGRAM",
                level=CapabilityLevel.UNSUPPORTED,
                reason="Failed to parse program",
            )]

        program = unit.program
        unsupported: list[str] = []
        partial: list[str] = []
        known = {
            "MoveStatement", "AddStatement", "SubtractStatement", "MultiplyStatement",
            "DivideStatement", "ComputeStatement", "DisplayStatement", "IfStatement",
            "ReadStatement", "WriteStatement", "OpenStatement", "CloseStatement",
            "StartStatement", "RewriteStatement", "DeleteStatement", "StringStatement",
            "StopRunStatement", "CallStatement", "PerformStatement",
        }

        def walk(stmt) -> None:
            name = type(stmt).__name__
            if name not in known:
                if name == "UnstringStatement":
                    partial.append("UNSTRING mapping is not semantically generated")
                elif name == "GoToStatement":
                    unsupported.append("GO TO has no semantic Java control-flow mapping")
                elif name == "PerformTimesStatement":
                    unsupported.append("PERFORM TIMES has no direct mapper IR path")
                else:
                    unsupported.append(f"Unrecognized/unmapped IR statement {name}")
            elif name == "CallStatement" and stmt.is_dynamic:
                unsupported.append("Dynamic CALL has no static dispatch")

            fields = getattr(stmt, "__dataclass_fields__", {})
            for field_name in fields:
                child = getattr(stmt, field_name)
                if isinstance(child, tuple):
                    for item in child:
                        if hasattr(item, "__dataclass_fields__") and type(item).__name__.endswith("Statement"):
                            walk(item)
                elif hasattr(child, "__dataclass_fields__") and type(child).__name__.endswith("Statement"):
                    walk(child)

        for paragraph in program.paragraphs:
            for stmt in paragraph.statements:
                walk(stmt)

        known_program_ids = {p.program_id.upper() for p in application.programs}
        for call in unit.calls:
            if call.call_type.upper() == "DYNAMIC":
                unsupported.append(f"Dynamic CALL target {call.target}")
            elif call.target.upper() not in known_program_ids:
                partial.append(f"Unresolved CALL target {call.target}")

        # A COPY reference is already part of the parsed program's source
        # context. It is not itself a generated program, so it does not block
        # the consuming program. Missing/failed COPY resolution is handled by
        # discovery/parsing before this capability stage.

        file_defs = {fd.name: fd for fd in program.file_definitions}
        for fd in unit.file_dependencies:
            definition = file_defs.get(fd.file_name)
            if definition is None:
                unsupported.append(f"File dependency {fd.file_name} has no FILE definition")
                continue
            if definition.organization != FileOrganization.SEQUENTIAL:
                unsupported.append(
                    f"{definition.organization.value} file {fd.file_name} is outside the certified file boundary"
                )
            if definition.access_mode == FileAccessMode.DYNAMIC:
                unsupported.append(
                    f"Dynamic access mode for {fd.file_name} is outside the certified file boundary"
                )
            if fd.operation.upper() == "REWRITE" and definition.organization == FileOrganization.SEQUENTIAL:
                unsupported.append(f"Sequential REWRITE for {fd.file_name} is explicitly unsupported by the file runtime")

        if unsupported:
            level = CapabilityLevel.UNSUPPORTED
            reason = "Contains unsupported capabilities: " + "; ".join(unsupported)
        elif partial:
            level = CapabilityLevel.PARTIAL
            reason = "Contains partially certified capabilities: " + "; ".join(partial)
        else:
            level = CapabilityLevel.SUPPORTED
            reason = "All parsed constructs are within the currently certified deterministic subset"

        components.append(ComponentCapability(
            component_id=unit.program_id,
            component_type="PROGRAM",
            level=level,
            reason=reason,
            details={
                "paragraph_count": str(len(program.paragraphs)),
                "data_item_count": str(len(program.working_storage)),
                "file_count": str(len(program.file_definitions)),
                "call_count": str(len(unit.calls)),
                "copybook_count": str(len(unit.copybooks)),
            },
        ))

        for fd in unit.file_dependencies:
            definition = file_defs.get(fd.file_name)
            if definition is None:
                level = CapabilityLevel.UNSUPPORTED
                reason = "No FILE definition found for dependency"
            elif definition.organization != FileOrganization.SEQUENTIAL or definition.access_mode == FileAccessMode.DYNAMIC:
                level = CapabilityLevel.UNSUPPORTED
                reason = "Indexed/relative/dynamic file semantics are outside the certified boundary"
            elif fd.operation.upper() == "REWRITE":
                level = CapabilityLevel.UNSUPPORTED
                reason = "Sequential REWRITE is unsupported by the deterministic file runtime"
            else:
                level = CapabilityLevel.SUPPORTED
                reason = "Sequential file operation within certified boundary"
            components.append(ComponentCapability(
                component_id=f"{unit.program_id}:{fd.file_name}",
                component_type="FILE",
                level=level,
                reason=reason,
            ))

        return components

    def _derive_overall_level(self, components: list[ComponentCapability]) -> CapabilityLevel:
        """Derive overall application capability level."""
        if not components:
            return CapabilityLevel.UNKNOWN

        has_unsupported = any(c.level == CapabilityLevel.UNSUPPORTED for c in components)
        has_unavailable = any(c.level == CapabilityLevel.UNAVAILABLE for c in components)
        has_partial = any(c.level == CapabilityLevel.PARTIAL for c in components)

        if has_unavailable:
            return CapabilityLevel.UNAVAILABLE
        if has_unsupported:
            return CapabilityLevel.UNSUPPORTED
        if has_partial:
            return CapabilityLevel.PARTIAL
        return CapabilityLevel.SUPPORTED

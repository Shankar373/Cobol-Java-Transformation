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
from pathlib import Path

from engine.transformation.contracts import ProducerCapability
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

    # COBOL constructs the parser/transformer supports
    SUPPORTED_STATEMENTS = frozenset({
        "DISPLAY", "STOP RUN", "MOVE", "ADD", "SUBTRACT", "MULTIPLY",
        "DIVIDE", "COMPUTE", "IF", "ELSE", "PERFORM", "GO TO",
        "READ", "WRITE", "OPEN", "CLOSE", "REWRITE", "DELETE",
        "UNSTRING", "STRING", "EVALUATE", "WHEN", "CALL",
    })

    # Constructs that produce PARTIAL results
    PARTIAL_STATEMENTS = frozenset({
        "PERFORM VARYING", "SEARCH", "STRING", "UNSTRING",
        "SORT", "MERGE", "GENERATE", "SUPPRESS",
    })

    # Constructs that are UNSUPPORTED
    UNSUPPORTED_STATEMENTS = frozenset({
        "EXEC CICS", "EXEC SQL", "EXEC DLI",
        "RENDEZVOUS", "EXCEPTION", "RAISE",
    })

    def __init__(
        self,
        producer_capabilities: tuple[ProducerCapability, ...] = (),
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

        # Analyze each program unit
        for unit in application.programs:
            components.extend(self._analyze_program_unit(unit))

        # Analyze copybook references
        for cb_name in application.copybooks:
            components.append(ComponentCapability(
                component_id=cb_name,
                component_type="COPYBOOK",
                level=CapabilityLevel.SUPPORTED,
                reason="Copybook resolution supported",
            ))

        # Analyze dependency edges (exact resolution match — note that
        # "UNRESOLVED" contains "RESOLVED" as a substring, so a substring
        # test here would misclassify every unresolved call as supported).
        for edge in application.edges:
            if edge.edge_type == "CALL":
                metadata = edge.metadata or ""
                is_resolved = "resolution=RESOLVED" in metadata
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
                    reason = "Resolved"
                components.append(ComponentCapability(
                    component_id=f"{edge.source}->{edge.target}",
                    component_type="CALL",
                    level=level,
                    reason=reason,
                ))

        # Multi-program CALL cycles (A→B→A) cannot be reproduced with static
        # Java dispatch faithfully; flag them explicitly.
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
        """Analyze a single program unit for capabilities.

        Walks every statement recursively (including IF branches, inline
        PERFORM bodies and READ handlers) so nested control flow is never
        silently treated as supported.
        """
        from engine.transformation.ir import (
            GoToStatement,
            IfStatement,
            PerformStatement,
            ReadStatement,
            StopRunStatement,
        )

        components: list[ComponentCapability] = []

        if unit.program is None:
            components.append(ComponentCapability(
                component_id=unit.program_id,
                component_type="PROGRAM",
                level=CapabilityLevel.UNSUPPORTED,
                reason="Failed to parse program",
            ))
            return components

        # Check each statement type in the program
        program = unit.program
        has_unsupported = False
        has_partial = False
        unsupported_reasons: list[str] = []
        partial_reasons: list[str] = []

        def _walk(stmt) -> None:
            nonlocal has_unsupported, has_partial
            stmt_type = type(stmt).__name__
            if "CICS" in stmt_type or "Sql" in stmt_type:
                has_unsupported = True
                unsupported_reasons.append(stmt_type)
            elif "PerformVarying" in stmt_type or "Search" in stmt_type:
                has_partial = True
                partial_reasons.append(stmt_type)
            if isinstance(stmt, GoToStatement):
                # GO TO is rendered as a comment; arbitrary jumps have no
                # Java equivalent in the generated structure.
                has_unsupported = True
                unsupported_reasons.append(f"GO TO {stmt.target}")
            if isinstance(stmt, PerformStatement):
                if stmt.thru_target:
                    known = {para.name for para in program.paragraphs}
                    if stmt.paragraph_name not in known or stmt.thru_target not in known:
                        has_unsupported = True
                        unsupported_reasons.append(
                            f"PERFORM THRU unresolved range "
                            f"{stmt.paragraph_name} THRU {stmt.thru_target}"
                        )
            if isinstance(stmt, IfStatement):
                for s in stmt.then_body:
                    _walk(s)
                for s in stmt.else_body:
                    _walk(s)
            if isinstance(stmt, PerformStatement):
                for s in stmt.body:
                    _walk(s)
            if isinstance(stmt, ReadStatement):
                for s in stmt.not_at_end_body:
                    _walk(s)
                for s in stmt.at_end_body:
                    _walk(s)

        for paragraph in program.paragraphs:
            for stmt in paragraph.statements:
                _walk(stmt)

        # Implicit fall-through reliance: the generator executes the driver
        # (first) paragraph; a multi-paragraph program whose driver does not
        # terminate (no top-level STOP RUN) relies on fall-through into the
        # next paragraph, which is not reproduced.
        if len(program.paragraphs) > 1:
            driver_stmts = program.paragraphs[0].statements
            if not any(isinstance(s, StopRunStatement) for s in driver_stmts):
                has_partial = True
                partial_reasons.append("implicit paragraph fall-through")

        # Determine program capability level
        if has_unsupported:
            level = CapabilityLevel.UNSUPPORTED
            reason = f"Contains unsupported constructs: {', '.join(unsupported_reasons)}"
        elif has_partial:
            level = CapabilityLevel.PARTIAL
            reason = f"Contains partially supported constructs: {', '.join(partial_reasons)}"
        else:
            level = CapabilityLevel.SUPPORTED
            reason = "All constructs supported"

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

        # Check file dependencies
        for fd in unit.file_dependencies:
            file_level = CapabilityLevel.SUPPORTED
            file_reason = f"Sequential file {fd.operation} supported"
            components.append(ComponentCapability(
                component_id=f"{unit.program_id}:{fd.file_name}",
                component_type="FILE",
                level=file_level,
                reason=file_reason,
            ))

        return components

    def _derive_overall_level(self, components: list[ComponentCapability]) -> CapabilityLevel:
        """Derive overall application capability level."""
        if not components:
            return CapabilityLevel.SUPPORTED

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

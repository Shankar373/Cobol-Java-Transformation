"""Capability analyzer — inspects the Application Semantic Graph and produces
a CapabilityReport classifying every component and construct.

Classification levels (defined by ``engine.transformation.semantic_capability``):
    SUPPORTED   — transformer can handle this construct fully
    PARTIAL     — transformer handles a subset; remainder is degraded
    UNSUPPORTED — transformer cannot handle this construct at all
    UNAVAILABLE — infrastructure (Docker, oracle) is not present
    UNKNOWN     — support cannot be determined; fail closed

Construct levels are not hard-coded here.  They come from the authoritative
registry in ``engine.transformation.semantic_capability``, which is also the
source used by the transformation producers.  The analyzer combines three
independent evidence channels per program:

    1. IR walk      — what the parser actually produced (including nested
                      IF branches, inline PERFORM bodies and file handlers)
    2. Source scan  — what the COBOL source actually contains, which is what
                      catches constructs CobolParser silently drops
    3. Structure    — unresolved PERFORM THRU, implicit paragraph
                      fall-through, uncaptured OPEN targets, unmapped IR
                      statement classes

The analyzer is a pure function over the discovered application graph and the
available infrastructure. It does NOT transform anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from engine.transformation.contracts import ProducerCapability
from engine.transformation.ir import (
    CobolApplication,
    CobolProgramUnit,
    CopybookReference,
    DependencyEdge,
    FileDependency,
    FileOrganization,
    FileAccessMode,
    ProgramCall,
)
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.contracts import TransformationProducer
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    IR_TYPE_TO_CONSTRUCT,
    PARTIAL_CONSTRUCTS,
    SUPPORTED_CONSTRUCTS,
    UNSUPPORTED_CONSTRUCTS,
    CapabilityLevel,
    ir_covers,
    scan_constructs,
    worst_level,
)

__all__ = [
    "CapabilityLevel",
    "ComponentCapability",
    "CapabilityReport",
    "CapabilityAnalyzer",
]


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

    @property
    def unknown_count(self) -> int:
        """Components whose support could not be determined (fail closed)."""
        return sum(1 for c in self.components if c.level == CapabilityLevel.UNKNOWN)

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "overall_level": self.overall_level.value,
            "supported": self.supported_count,
            "partial": self.partial_count,
            "unsupported": self.unsupported_count,
            "unavailable": self.unavailable_count,
            "unknown": self.unknown_count,
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

    # Registry projections — mutually exclusive, derived from the single
    # authoritative construct registry (reachable/source level).
    SUPPORTED_STATEMENTS = SUPPORTED_CONSTRUCTS
    PARTIAL_STATEMENTS = PARTIAL_CONSTRUCTS
    UNSUPPORTED_STATEMENTS = UNSUPPORTED_CONSTRUCTS

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
        program_levels: dict[str, CapabilityLevel] = {}
        for unit in application.programs:
            unit_components = self._analyze_program_unit(unit)
            components.extend(unit_components)
            for comp in unit_components:
                if comp.component_type == "PROGRAM":
                    program_levels[comp.component_id] = comp.level

        # Analyze copybook references (resolution is recorded at discovery)
        for cb_name in application.copybooks:
            components.append(self._analyze_copybook(application, cb_name))

        # Analyze dependency edges (exact resolution match — note that
        # "UNRESOLVED" contains "RESOLVED" as a substring, so a substring
        # test here would misclassify every unresolved call as supported).
        for edge in application.edges:
            if edge.edge_type == "CALL":
                components.append(
                    self._analyze_call(edge, program_levels)
                )

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

    # ------------------------------------------------------------------
    # Program classification
    # ------------------------------------------------------------------

    def _analyze_program_unit(self, unit: CobolProgramUnit) -> list[ComponentCapability]:
        """Analyze a single program unit for capabilities.

        Combines the IR walk, the source scan and the structural rules, then
        aggregates with worst-case severity so a nested or source-only
        construct can never be hidden by an outer supported statement.
        """
        from engine.transformation.ir import (
            DeleteStatement,
            IfStatement,
            OpenStatement,
            PerformStatement,
            ReadStatement,
            RewriteStatement,
            StartStatement,
            StopRunStatement,
            WriteStatement,
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

        program = unit.program
        findings: list[tuple[str, CapabilityLevel, str]] = []
        ir_types_seen: set[str] = set()

        # If discovery produced only a stub IR (parse_error is set), seed the
        # findings with the error so the program is correctly classified as
        # UNSUPPORTED even if the source scan does not catch the exact construct
        # that caused the CobolParseError.
        if unit.parse_error:
            findings.append((
                "parse_error",
                CapabilityLevel.UNSUPPORTED,
                f"Parser raised CobolParseError: {unit.parse_error}",
            ))

        # Diagnostics emitted while parsing individual statements.  They mark
        # constructs the parser recognised but could not turn into IR; without
        # them an empty-but-present node still maps to a SUPPORTED registry key
        # and the loss is invisible to every later gate.
        for message in unit.parse_diagnostics:
            findings.append((
                "unparsed_statement",
                CapabilityLevel.UNSUPPORTED,
                message,
            ))

        def _note_ir(name: str) -> None:
            ir_types_seen.add(name)
            key = IR_TYPE_TO_CONSTRUCT.get(name)
            if key is None:
                # No registry mapping means the deterministic mapper has no
                # path for this statement class (classify_statement_capability
                # falls back to UNSUPPORTED) — fail closed as UNSUPPORTED.
                findings.append((
                    name,
                    CapabilityLevel.UNSUPPORTED,
                    f"Unrecognized/unmapped IR statement {name}",
                ))
                return
            entry = CONSTRUCT_REGISTRY[key]
            findings.append((key, entry.level, entry.evidence))

        def _walk(stmt) -> None:
            name = type(stmt).__name__
            _note_ir(name)

            for attr in ("invalid_key_body", "not_invalid_key_body"):
                if getattr(stmt, attr, None):
                    ir_types_seen.add("InvalidKeyScope")
                    break

            if isinstance(stmt, PerformStatement):
                if stmt.thru_target:
                    known = {para.name for para in program.paragraphs}
                    if stmt.paragraph_name not in known or stmt.thru_target not in known:
                        findings.append((
                            "PERFORM THRU",
                            CapabilityLevel.UNSUPPORTED,
                            "PERFORM THRU unresolved range "
                            f"{stmt.paragraph_name} THRU {stmt.thru_target}",
                        ))
                for nested in stmt.body:
                    _walk(nested)
            elif isinstance(stmt, IfStatement):
                for nested in stmt.then_body:
                    _walk(nested)
                for nested in stmt.else_body:
                    _walk(nested)
            elif isinstance(stmt, ReadStatement):
                for attr in ("at_end_body", "not_at_end_body",
                             "invalid_key_body", "not_invalid_key_body"):
                    for nested in getattr(stmt, attr, ()) or ():
                        _walk(nested)
            elif isinstance(stmt, (WriteStatement, StartStatement,
                                   RewriteStatement, DeleteStatement)):
                for attr in ("invalid_key_body", "not_invalid_key_body"):
                    for nested in getattr(stmt, attr, ()) or ():
                        _walk(nested)

            if isinstance(stmt, OpenStatement) and not stmt.file_name:
                findings.append((
                    "OPEN",
                    CapabilityLevel.PARTIAL,
                    "OPEN statement target was not captured by CobolParser "
                    f"(mode={stmt.mode})",
                ))

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
                findings.append((
                    "paragraph fall-through",
                    CapabilityLevel.PARTIAL,
                    "implicit paragraph fall-through",
                ))

        # Source evidence: constructs present in COBOL that produced no IR.
        ir_construct_keys = {
            IR_TYPE_TO_CONSTRUCT[name]
            for name in ir_types_seen
            if name in IR_TYPE_TO_CONSTRUCT
        }
        if unit.source_text:
            for key in sorted(scan_constructs(unit.source_text)):
                entry = CONSTRUCT_REGISTRY.get(key)
                if entry is None:
                    continue
                if key in ir_construct_keys:
                    # The parser produced IR for this construct; the registry
                    # IR level is the authoritative verdict.
                    continue
                if ir_covers(key, ir_construct_keys | ir_types_seen):
                    # The construct is legitimately realised by a different
                    # IR node (e.g. EVALUATE -> IfStatement, PERFORM ... TIMES
                    # -> PerformStatement); the IR walk already classified it.
                    continue
                if entry.effective_source_level is CapabilityLevel.UNSUPPORTED:
                    # The construct appears in source but the deterministic
                    # parser never turns it into IR (it has no real mapping),
                    # so the mapper can never see it.  Do not repeat the
                    # registry's IR-level evidence here — it would read as
                    # support for something the output can never contain.
                    findings.append((
                        key,
                        CapabilityLevel.UNSUPPORTED,
                        f"{key} is used in source but the deterministic "
                        "parser has no IR for it; it cannot be transformed",
                    ))
                    continue
                findings.append((key, entry.effective_source_level, entry.evidence))

        # A COPY reference is part of the parsed program's source context; it
        # is not itself a generated program, so an unresolved resolution
        # status does not block the consuming program here.  Resolution
        # failures are recorded by discovery and reported on the COPYBOOK
        # component.

        # Blocking file semantics propagate into the program findings BEFORE
        # aggregation, so a program can never be claimed transformable while
        # one of its file operations is outside the certified boundary.  The
        # per-file verdict is additionally emitted as its own FILE component.
        file_verdicts: list[tuple[FileDependency, CapabilityLevel, str]] = []
        for fd in unit.file_dependencies:
            file_level, file_reason = self._file_capability(unit, fd)
            file_verdicts.append((fd, file_level, file_reason))
            if file_level in (
                CapabilityLevel.UNSUPPORTED,
                CapabilityLevel.PARTIAL,
                CapabilityLevel.UNKNOWN,
            ):
                findings.append((f"file {fd.file_name}", file_level, file_reason))

        level, reason = self._aggregate(findings)
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
                "constructs": ", ".join(sorted({key for key, _, _ in findings})),
            },
        ))

        for fd, file_level, file_reason in file_verdicts:
            components.append(ComponentCapability(
                component_id=f"{unit.program_id}:{fd.file_name}",
                component_type="FILE",
                level=file_level,
                reason=file_reason,
            ))

        return components

    @staticmethod
    def _aggregate(
        findings: list[tuple[str, CapabilityLevel, str]],
    ) -> tuple[CapabilityLevel, str]:
        """Combine findings into one program level and an honest reason."""
        if not findings:
            return CapabilityLevel.SUPPORTED, "All constructs supported"

        worst = worst_level([level for _, level, _ in findings])
        assert worst is not None

        def _named(level: CapabilityLevel) -> list[str]:
            return sorted({
                f"{key} ({evidence})"
                for key, found, evidence in findings
                if found is level
            })

        if worst is CapabilityLevel.UNKNOWN:
            return (
                CapabilityLevel.UNKNOWN,
                "Support cannot be determined for: "
                + ", ".join(sorted({key for key, lv, _ in findings if lv is worst})),
            )
        if worst is CapabilityLevel.UNSUPPORTED:
            return (
                CapabilityLevel.UNSUPPORTED,
                "Contains unsupported constructs: " + "; ".join(_named(worst)),
            )
        if worst is CapabilityLevel.PARTIAL:
            return (
                CapabilityLevel.PARTIAL,
                "Contains partially supported constructs: " + "; ".join(_named(worst)),
            )
        if worst is CapabilityLevel.UNAVAILABLE:
            return (
                CapabilityLevel.UNAVAILABLE,
                "; ".join(_named(worst)),
            )
        return CapabilityLevel.SUPPORTED, "All constructs supported"

    def _file_capability(
        self,
        unit: CobolProgramUnit,
        fd: FileDependency,
    ) -> tuple[CapabilityLevel, str]:
        """Classify one discovered file dependency by real file semantics.

        Anything outside the certified sequential boundary fails closed as
        UNSUPPORTED; only benign sequential operations are SUPPORTED.
        """
        program = unit.program
        file_defs = {f.name: f for f in program.file_definitions}
        definition = file_defs.get(fd.file_name)

        if definition is None:
            return (
                CapabilityLevel.UNSUPPORTED,
                f"File dependency {fd.file_name} has no FILE definition",
            )

        if definition.organization != FileOrganization.SEQUENTIAL:
            return (
                CapabilityLevel.UNSUPPORTED,
                f"{definition.organization.value} file {fd.file_name} is "
                "outside the certified file boundary",
            )

        if definition.access_mode == FileAccessMode.DYNAMIC:
            return (
                CapabilityLevel.UNSUPPORTED,
                f"Dynamic access mode for {fd.file_name} is outside the "
                "certified file boundary",
            )

        if fd.operation.upper() == "REWRITE":
            return (
                CapabilityLevel.UNSUPPORTED,
                f"Sequential REWRITE for {fd.file_name} is explicitly "
                "unsupported by the file runtime",
            )

        if fd.operation == "OPEN" and fd.mode in ("I-O", "EXTEND"):
            return (
                CapabilityLevel.PARTIAL,
                f"OPEN {fd.mode} on {fd.file_name} is not reproduced by the "
                "sequential file runtime",
            )

        return (
            CapabilityLevel.SUPPORTED,
            f"Sequential file {fd.operation} within certified boundary",
        )

    # ------------------------------------------------------------------
    # Copybook classification
    # ------------------------------------------------------------------

    def _analyze_copybook(
        self,
        application: CobolApplication,
        cb_name: str,
    ) -> ComponentCapability:
        refs: list[CopybookReference] = [
            cb
            for unit in application.programs
            for cb in unit.copybooks
            if cb.copybook_name == cb_name
        ]
        resolved_paths = [
            cb.resolved_path for cb in refs
            if cb.resolution == "RESOLVED" and cb.resolved_path
        ]

        if not resolved_paths:
            # A COPY reference is a dependency relationship, not a generated
            # program: the relationship is tracked and no standalone Java class
            # is emitted from the copybook.  Resolution status stays visible
            # here (resolution=...) and on the consuming program's reference;
            # it does not turn the consuming program's own parsed constructs
            # into unsupported ones.
            resolutions = {cb.resolution for cb in refs}
            resolution = "AMBIGUOUS" if "AMBIGUOUS" in resolutions else "UNRESOLVED"
            return ComponentCapability(
                component_id=cb_name,
                component_type="COPYBOOK",
                level=CapabilityLevel.SUPPORTED,
                reason=(
                    "Copybook dependency discovered; declarations are consumed "
                    "as program source context and no standalone Java class is "
                    f"generated (resolution={resolution})"
                ),
                details={"resolution": resolution},
            )

        content = ""
        read_error = ""
        for path in resolved_paths:
            try:
                content = Path(path).read_text(encoding="utf-8", errors="replace")
                break
            except OSError as exc:
                read_error = str(exc)

        if not content and read_error:
            return ComponentCapability(
                component_id=cb_name,
                component_type="COPYBOOK",
                level=CapabilityLevel.UNSUPPORTED,
                reason=(
                    f"Unsupported: copybook {cb_name} could not be read "
                    f"({read_error})"
                ),
                details={"resolution": "RESOLVED", "path": resolved_paths[0]},
            )

        detected = sorted(scan_constructs(content, restrict_to_procedure=False))
        levels = [
            CONSTRUCT_REGISTRY[key].effective_source_level
            for key in detected
            if key in CONSTRUCT_REGISTRY
        ]
        worst = worst_level(levels)

        if worst is None:
            return ComponentCapability(
                component_id=cb_name,
                component_type="COPYBOOK",
                level=CapabilityLevel.SUPPORTED,
                reason="Copybook resolved and contains no unsupported constructs",
                details={
                    "resolution": "RESOLVED",
                    "path": resolved_paths[0],
                },
            )

        entry_keys = sorted({
            key for key in detected
            if key in CONSTRUCT_REGISTRY
            and CONSTRUCT_REGISTRY[key].effective_source_level is worst
        })
        if worst is CapabilityLevel.UNKNOWN:
            reason = "Support cannot be determined for: " + ", ".join(entry_keys)
        elif worst is CapabilityLevel.UNSUPPORTED:
            reason = "Copybook contains unsupported constructs: " + ", ".join(entry_keys)
        elif worst is CapabilityLevel.PARTIAL:
            reason = "Copybook contains partially supported constructs: " + ", ".join(entry_keys)
        else:
            reason = f"Copybook contents classify as {worst.value}"

        return ComponentCapability(
            component_id=cb_name,
            component_type="COPYBOOK",
            level=worst,
            reason=reason,
            details={
                "resolution": "RESOLVED",
                "path": resolved_paths[0],
                "constructs": ", ".join(detected),
            },
        )

    # ------------------------------------------------------------------
    # CALL classification
    # ------------------------------------------------------------------

    def _analyze_call(
        self,
        edge: DependencyEdge,
        program_levels: dict[str, CapabilityLevel],
    ) -> ComponentCapability:
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
            # A resolved call is only as transformable as its callee.
            callee = program_levels.get(edge.target)
            if callee is None or callee is CapabilityLevel.SUPPORTED:
                level = CapabilityLevel.SUPPORTED
                reason = "Resolved"
            elif callee in (CapabilityLevel.PARTIAL, CapabilityLevel.UNAVAILABLE):
                level = CapabilityLevel.PARTIAL
                reason = (
                    f"Callee {edge.target} is not fully supported "
                    f"({callee.value})"
                )
            else:
                level = callee
                reason = (
                    f"Callee {edge.target} cannot be transformed "
                    f"({callee.value})"
                )

        return ComponentCapability(
            component_id=f"{edge.source}->{edge.target}",
            component_type="CALL",
            level=level,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _derive_overall_level(self, components: list[ComponentCapability]) -> CapabilityLevel:
        """Derive overall application capability level.

        Most severe component wins; UNKNOWN outranks everything because an
        undetermined construct must never be presented as safe.
        """
        if not components:
            return CapabilityLevel.SUPPORTED

        return worst_level([c.level for c in components]) or CapabilityLevel.SUPPORTED

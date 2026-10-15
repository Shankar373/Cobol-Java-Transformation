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

import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.transformation.contracts import ProducerCapability
from engine.transformation.ir import (
    CallStatement,
    CobolApplication,
    CobolProgramUnit,
    CopybookReference,
    DependencyEdge,
    FileDependency,
    FileOrganization,
    FileAccessMode,
    ProgramCall,
    normalize_cobol_name,
)
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.contracts import TransformationProducer
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    IR_TYPE_TO_CONSTRUCT,
    PARTIAL_CONSTRUCTS,
    SUPPORTED_CONSTRUCTS,
    UNSUPPORTED_CONSTRUCTS,
    USAGE_TO_CONSTRUCT,
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
    # Emitted values: "PROGRAM", "COPYBOOK", "CALL", "FILE".
    # JCL is deliberately absent: it is tracked by the JCL ledger
    # (integrated_proof.jcl_ledger_entry), never as a capability
    # component (Phase 5 audit, BL-077).
    component_type: str
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


_LINKAGE_WALK_ATTRS = (
    "body", "then_body", "else_body",
    "at_end_body", "not_at_end_body", "invalid_key_body",
    "not_invalid_key_body",
)

# CALL passing mode -> registry key.  Only the write-losing modes are tracked;
# BY REFERENCE stays covered by the CALL SUPPORTED verdict.



def _iter_call_statements(program) -> "list[CallStatement]":
    """Collect every CallStatement in a program, recursing into known bodies."""
    found: list[CallStatement] = []

    def _walk(stmt) -> None:
        if isinstance(stmt, CallStatement):
            found.append(stmt)
        for attr in _LINKAGE_WALK_ATTRS:
            nested = getattr(stmt, attr, None)
            if nested:
                for child in nested:
                    _walk(child)
        # Evaluate/Perform-style collections
        for attr in ("cases", "when_branches", "when_others_body"):
            coll = getattr(stmt, attr, None)
            if coll:
                for item in coll:
                    if isinstance(item, tuple):
                        for sub in item:
                            if hasattr(sub, "__class__"):
                                try:
                                    _walk(sub)
                                except (AttributeError, TypeError):
                                    pass
                    elif hasattr(item, "statements"):
                        for sub in item.statements:
                            _walk(sub)
                    elif isinstance(item, (list, tuple)):
                        for sub in item:
                            if hasattr(sub, "__class__"):
                                try:
                                    _walk(sub)
                                except (AttributeError, TypeError):
                                    pass

    for paragraph in getattr(program, "paragraphs", ()):
        for stmt in getattr(paragraph, "statements", ()):
            _walk(stmt)
    return found


def _iter_data_item_tree(item):
    """Yield a ``DataItem`` and every descendant (group hierarchy)."""
    yield item
    for child in getattr(item, "children", ()) or ():
        yield from _iter_data_item_tree(child)


def _iter_program_data_items(program) -> list:
    """Every DataItem declared by a program (working-storage + file records)."""
    found: list = []
    for item in getattr(program, "working_storage", ()) or ():
        found.extend(_iter_data_item_tree(item))
    for fd in getattr(program, "file_definitions", ()) or ():
        for item in getattr(fd, "record_items", ()) or ():
            found.extend(_iter_data_item_tree(item))
    return found


def _scan_copy_replacing(source_text: str) -> "list[tuple[str, CapabilityLevel, str]]":
    """Classify COPY ... REPLACING clauses the materialization lane cannot apply.

    BL-032: a clause whose operand form the lane does not implement (or
    that does not parse) fails generation with an explicit diagnostic, so
    the program cannot be transformed as-is — the verdict must say so
    instead of reporting SUPPORTED over a clause that is never applied.
    The grammar check reuses the materialization lane's parser
    (``_parse_replacing_clause``) so capability truth can never drift from
    what generation actually does.  Applied (well-formed) clauses classify
    nothing: their semantics are preserved by substitution.
    """
    from engine.transformation.copybook_model import (
        _find_copy_statements,
        _mask_comments,
        _parse_replacing_clause,
    )

    if not source_text:
        return []
    findings: "list[tuple[str, CapabilityLevel, str]]" = []
    masked = _mask_comments(source_text)
    seen: set[str] = set()
    for start, end, target in _find_copy_statements(source_text):
        _, error = _parse_replacing_clause(masked[start:end])
        if error is None:
            continue
        code, message = error
        key = f"COPY REPLACING {target.upper()}"
        if key in seen:
            continue
        seen.add(key)
        findings.append((
            key,
            CapabilityLevel.UNSUPPORTED,
            f"{message}; the clause is never applied and generation fails "
            f"closed ({code})",
        ))
    return findings


def _analyze_call_linkage_arity(
    application: CobolApplication,
) -> "list[ComponentCapability]":
    """Deterministically flag caller/callee LINKAGE arity mismatches.

    Only statically resolved CALLs are diagnosed. Dynamic calls, unresolved
    calls, self-calls and cycles retain their existing classifications.
    A mode (BY REFERENCE/BY CONTENT/BY VALUE) that cannot be proven
    compatible is never guessed - it is simply not used to derive support.
    """
    by_id = {}
    for unit in application.programs:
        if unit.program is not None:
            # BL-044: one shared uppercase normalization for every
            # program-id join (discovery stamps resolution the same way).
            by_id[normalize_cobol_name(unit.program.program_id)] = unit.program

    findings: list[ComponentCapability] = []
    for unit in application.programs:
        if unit.program is None:
            continue
        for stmt in _iter_call_statements(unit.program):
            if stmt.is_dynamic:
                continue
            target = normalize_cobol_name(stmt.program_name.rstrip("."))
            callee = by_id.get(target)
            if callee is None:
                continue  # existing unresolved-target path governs
            declared = sum(
                1 for item in callee.linkage_section
                if getattr(item, "level", None) == 1
            )
            passed = len(stmt.arguments)
            if passed != declared:
                findings.append(ComponentCapability(
                    component_id=f"{unit.program_id}->{target}",
                    component_type="CALL",
                    level=CapabilityLevel.UNSUPPORTED,
                    reason=(
                        f"CALL linkage arity mismatch: caller passes "
                        f"{passed} argument(s) but callee {target} declares "
                        f"{declared} top-level LINKAGE item(s)"
                    ),
                ))
    return findings


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

    def analyze(
        self,
        application: CobolApplication,
        source_root: "str | Path | None" = None,
    ) -> CapabilityReport:
        """Analyze a discovered application and produce a capability report.

        ``source_root`` (the ingested source tree) lets the copybook scan be
        transitive over the exact search directories generation uses
        (BL-039); when omitted the copybook's own directory keeps the legacy
        flat behavior.
        """
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
                    # BL-044: normalized keys so a resolved edge whose
                    # target spelling differs only in case still finds
                    # its callee's level.
                    program_levels[normalize_cobol_name(comp.component_id)] = comp.level

        # Analyze copybook references (resolution is recorded at discovery)
        for cb_name in application.copybooks:
            components.append(
                self._analyze_copybook(application, cb_name, source_root)
            )

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

        # Static CALL linkage arity: every STATIC, resolved CALL whose
        # caller USING argument count disagrees with the callee's declared
        # LINKAGE SECTION top-level items is a deterministic mismatch and
        # must NOT be treated as supported. Dynamic and unresolved calls
        # keep their existing classifications.
        components.extend(_analyze_call_linkage_arity(application))

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
        # Constructs proven by an IR flag carried on a statement rather than by
        # a statement class (currently ROUNDED).
        ir_flag_keys: set[str] = set()

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

        def _note_figurative(value) -> None:
            """Classify a FigurativeConstant appearing anywhere in the IR.

            Figurative constants are expressions, not statements, so they are
            not reached by the statement-class walk.  Reading them from the
            IR keeps the verdict backed by what the parser actually produced
            (the source scan alone cannot prove the mapper saw them).

            The walk is generic over the IR dataclass graph rather than a
            fixed field list, because a constant can sit at any depth:
            ``COMPUTE A = 0 + ZERO`` nests it inside a ``BinaryExpression``,
            which a named-field walk would never reach.
            """
            from engine.transformation.ir import (
                Expression as _Expression,
                FigurativeConstant as _FigurativeConstant,
            )
            stack = [value]
            seen: set[int] = set()
            while stack:
                current = stack.pop()
                if current is None or isinstance(current, str):
                    continue
                if id(current) in seen:
                    continue
                seen.add(id(current))
                if isinstance(current, _FigurativeConstant):
                    ir_flag_keys.add("FIGURATIVE CONSTANT")
                    continue
                if isinstance(current, _Expression):
                    for f in current.__dataclass_fields__:
                        stack.append(getattr(current, f, None))
                    continue
                if isinstance(current, (tuple, list, set, frozenset)):
                    stack.extend(current)

        def _walk_expression(stmt) -> None:
            _note_figurative(getattr(stmt, "source_expr", None))
            _note_figurative(getattr(stmt, "expression_expr", None))
            _note_figurative(getattr(stmt, "structured_condition", None))
            _note_figurative(getattr(stmt, "parts", None))
            _note_figurative(getattr(stmt, "condition", None))
            # STRING DELIMITED BY SPACE carries its figurative constant in
            # the IR (BL-027); without this the source scan would re-report
            # the bare SPACE word as source-only evidence.
            _note_figurative(getattr(stmt, "delimiter_exprs", None))

        def _walk(stmt) -> None:
            name = type(stmt).__name__
            _note_ir(name)

            # ROUNDED is a flag carried on the arithmetic statement itself, not
            # a statement class.  Read it from IR so the verdict is backed by
            # the parsed flag (the mapper selects RoundingMode.HALF_UP) rather
            # than by a bare source match, and so the source scan below does
            # not re-report it as source-only.
            if getattr(stmt, "rounded", False):
                ir_flag_keys.add("ROUNDED")
                entry = CONSTRUCT_REGISTRY["ROUNDED"]
                findings.append(("ROUNDED", entry.level, entry.evidence))

            _walk_expression(stmt)

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

            # NOTE — BY CONTENT / BY VALUE are intentionally not classified
            # here.  They have no registry key by design (see the note in
            # semantic_capability.py and the negative contract test
            # test_by_value_and_by_content_are_never_claimed_supported): an
            # unproven passing mode must never be used to derive a support
            # verdict, matching the rule on _analyze_call_linkage_arity.

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
                if key in ir_flag_keys:
                    # Proven by an IR flag the walk already classified (ROUNDED).
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

        # USAGE clause evidence (BL-002).  The parser records a declared
        # USAGE on DataItem; a non-DISPLAY usage means the numeric *value*
        # path is mapped but the record-area *byte encoding* is not certified.
        # Before this the clause was silently ignored, which the capability
        # rule forbids.  The source scan above is procedure-restricted, so
        # data-division usages are only visible here.
        usage_items: dict[str, list[str]] = {}
        for item in _iter_program_data_items(program):
            if not item.usage:
                continue
            usage_key = USAGE_TO_CONSTRUCT.get(item.usage, "USAGE")
            usage_items.setdefault(usage_key, []).append(f"{item.name} ({item.usage})")
        for usage_key in sorted(usage_items):
            items_text = ", ".join(sorted(usage_items[usage_key]))
            if usage_key in CONSTRUCT_REGISTRY:
                entry = CONSTRUCT_REGISTRY[usage_key]
                findings.append((
                    usage_key,
                    entry.level,
                    f"{entry.evidence}; items: {items_text}",
                ))
            else:
                findings.append((
                    "USAGE",
                    CapabilityLevel.PARTIAL,
                    "no certified value or encoding mapping; items: " + items_text,
                ))

        # REDEFINES / OCCURS / 88-level (BL-003) and the VSAM FILE-CONTROL
        # phrases (BL-086, roadmap P3-5).  These are pre-PROCEDURE-DIVISION
        # constructs the procedure-restricted source scan above cannot see,
        # so scan the source-before-PROCEDURE slice explicitly.  Classified
        # UNSUPPORTED (fail-closed) until a full-ladder runtime proof exists.
        data_text = unit.source_text or ""
        proc_match = re.search(r"\bPROCEDURE\s+DIVISION\b", data_text, re.IGNORECASE)
        if proc_match:
            data_text = data_text[:proc_match.start()]
        if data_text:
            data_detected = scan_constructs(data_text, restrict_to_procedure=False)
            for key in (
                "REDEFINES",
                "OCCURS",
                "88-LEVEL",
                "ORGANIZATION INDEXED",
                "ORGANIZATION RELATIVE",
                "ACCESS DYNAMIC",
                "RECORD KEY",
            ):
                if key in data_detected:
                    entry = CONSTRUCT_REGISTRY[key]
                    findings.append((key, entry.level, entry.evidence))

        # COPY ... REPLACING clauses the lane cannot apply (BL-032).  The
        # clause sits in the program source, so it is visible here even
        # though the copybook file itself contains no REPLACING text.  A
        # clause the materialization lane fails closed on must never leave
        # this program classified SUPPORTED.
        findings.extend(_scan_copy_replacing(unit.source_text or ""))

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
        source_root: "str | Path | None" = None,
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

        # BL-033 (capability truth): generation deterministically fails for an
        # unresolvable COPY reference ("Missing COPY target: <name>"), so the
        # dependency must not classify SUPPORTED — the capability graph and the
        # plan would assert the opposite of the same run's generation.
        # UNRESOLVED (no target on the search path, including quoted forms),
        # AMBIGUOUS (multiple equal-precedence candidates), a mixed set where
        # any consumer cannot resolve, and a name with no reference at all all
        # take this fail-closed branch.  The verdict applies to the copybook
        # dependency only: the consuming program keeps its own verdict (its
        # parsed constructs are unchanged), and no standalone Java class is
        # emitted from a copybook in any case.
        unresolved = [
            cb for cb in refs
            if cb.resolution != "RESOLVED" or not cb.resolved_path
        ]
        if unresolved or not resolved_paths:
            resolutions = {cb.resolution for cb in unresolved} or {"UNRESOLVED"}
            resolution = "AMBIGUOUS" if "AMBIGUOUS" in resolutions else "UNRESOLVED"
            if resolution == "AMBIGUOUS":
                reason = (
                    f"Copybook {cb_name} is ambiguous: multiple equal-precedence "
                    "candidates and no single target (resolution=AMBIGUOUS); "
                    "generation deterministically fails with 'Missing COPY target'"
                )
            else:
                reason = (
                    f"Copybook {cb_name} is unresolved: at least one COPY "
                    "reference has no target on the copybook search path "
                    "(resolution=UNRESOLVED); generation deterministically fails "
                    "with 'Missing COPY target'"
                )
            return ComponentCapability(
                component_id=cb_name,
                component_type="COPYBOOK",
                level=CapabilityLevel.UNSUPPORTED,
                reason=reason,
                details={"resolution": resolution},
            )

        content = ""
        read_error = ""
        for path in resolved_paths:
            try:
                # Strict UTF-8 (BL-056): a decode failure must take this
                # exact read-failure path — the lenient errors="replace"
                # reader let the analyzer classify bytes generation rejects
                # as (falsely) clean.  Valid UTF-8 reads are unchanged.
                content = Path(path).read_text(encoding="utf-8")
                break
            except (OSError, UnicodeError) as exc:
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

        # BL-039 (capability truth is transitive): scan every file the
        # generation lane merges — the top-level copybook plus each nested
        # COPY target — so constructs inside nested copybooks cannot escape
        # the verdict.  Search directories are the shared deterministic
        # authority when the caller knows the source root (parity with
        # generation); otherwise the top-level file's own directory keeps
        # the legacy flat behavior.  A nested target generation cannot
        # materialize (missing/ambiguous/cyclic/unreadable) is an ERROR
        # diagnostic naming it and fails the component closed — the
        # expanded-scan result can never contradict generation.
        from engine.transformation.copybook_model import collect_copybook_texts
        from engine.transformation.copybook_resolver import copybook_search_dirs

        top_path = Path(resolved_paths[0])
        search_dirs = (
            copybook_search_dirs(source_root)
            if source_root is not None
            else (top_path.parent,)
        )
        files, nested_diagnostics = collect_copybook_texts(top_path, search_dirs)
        nested_errors = [
            d.message for d in nested_diagnostics if d.level == "ERROR"
        ]
        if nested_errors:
            return ComponentCapability(
                component_id=cb_name,
                component_type="COPYBOOK",
                level=CapabilityLevel.UNSUPPORTED,
                reason=(
                    f"Copybook {cb_name} has nested COPY problems: "
                    + "; ".join(nested_errors)
                ),
                details={
                    "resolution": "RESOLVED",
                    "path": resolved_paths[0],
                    "nested_errors": "; ".join(nested_errors),
                },
            )

        top_stem = top_path.stem.upper()
        detected_by_file: list[tuple[str, set[str]]] = [
            (
                fpath.stem.upper(),
                set(scan_constructs(ftext, restrict_to_procedure=False)),
            )
            for fpath, ftext in files
        ]
        detected = sorted({key for _, keys in detected_by_file for key in keys})
        levels = [
            CONSTRUCT_REGISTRY[key].effective_source_level
            for key in detected
            if key in CONSTRUCT_REGISTRY
        ]
        worst = worst_level(levels)
        file_stems = ", ".join(fstem for fstem, _ in detected_by_file)

        if worst is None:
            nested_note = (
                f" (including {len(detected_by_file) - 1} nested copybook(s))"
                if len(detected_by_file) > 1
                else ""
            )
            return ComponentCapability(
                component_id=cb_name,
                component_type="COPYBOOK",
                level=CapabilityLevel.SUPPORTED,
                reason=(
                    "Copybook resolved and contains no unsupported constructs"
                    + nested_note
                ),
                details={
                    "resolution": "RESOLVED",
                    "path": resolved_paths[0],
                    "files": file_stems,
                },
            )

        entry_keys = sorted({
            key for key in detected
            if key in CONSTRUCT_REGISTRY
            and CONSTRUCT_REGISTRY[key].effective_source_level is worst
        })
        # Attribution: name the nested files that carry the worst-level keys
        # so the reason points at the file generation actually merges.
        nested_offenders = sorted({
            fstem for fstem, keys in detected_by_file
            if fstem != top_stem
            and any(
                key in CONSTRUCT_REGISTRY
                and CONSTRUCT_REGISTRY[key].effective_source_level is worst
                for key in keys
            )
        })
        nested_note = (
            " (via nested copybook " + ", ".join(nested_offenders) + ")"
            if nested_offenders
            else ""
        )
        if worst is CapabilityLevel.UNKNOWN:
            reason = "Support cannot be determined for: " + ", ".join(entry_keys) + nested_note
        elif worst is CapabilityLevel.UNSUPPORTED:
            reason = "Copybook contains unsupported constructs: " + ", ".join(entry_keys) + nested_note
        elif worst is CapabilityLevel.PARTIAL:
            reason = "Copybook contains partially supported constructs: " + ", ".join(entry_keys) + nested_note
        else:
            reason = f"Copybook contents classify as {worst.value}" + nested_note

        return ComponentCapability(
            component_id=cb_name,
            component_type="COPYBOOK",
            level=worst,
            reason=reason,
            details={
                "resolution": "RESOLVED",
                "path": resolved_paths[0],
                "files": file_stems,
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
        # BL-044: names join case-insensitively — a case-variant self CALL
        # must stay classified as recursive, not "resolved".
        is_self_call = (
            normalize_cobol_name(edge.source) == normalize_cobol_name(edge.target)
        )

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
            callee = program_levels.get(normalize_cobol_name(edge.target))
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

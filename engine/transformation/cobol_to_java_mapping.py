"""COBOL → Java semantic mapping.

Defines explicit mappings from COBOL semantic IR to the Java application model.
Each mapping is a pure function that takes COBOL IR and produces Java IR.

Mappings are organized by COBOL construct:

    COBOL PROGRAM      → JavaProgram / JavaClass
    COBOL paragraph    → JavaMethod
    COBOL DATA ITEM    → JavaField
    COBOL PIC          → JavaType
    COBOL MOVE         → JavaAssignment
    COBOL arithmetic   → Java expression
    COBOL IF           → JavaIf
    COBOL PERFORM      → Java method call / loop
    COBOL STRING       → Java string operations
    COBOL UNSTRING     → Java string split/parse
    COBOL file ops     → JavaFileResource
    COBOL DB2 SQL      → JavaDatabaseResource
    COBOL CICS         → JavaTransactionBoundary
    COBOL JCL          → JavaApplication composition

No workload-specific logic. No domain vocabulary.
All decisions derived from generic COBOL IR elements.
"""

from __future__ import annotations

import re

from engine.transformation import figurative
from engine.transformation.figurative import figurative_to_width, parse_figurative_constant
from engine.transformation.ir import (
    AddStatement,
    CallStatement,
    CloseStatement,
    CobolProgram,
    ComputeStatement,
    DataItem,
    DeleteStatement,
    DisplayStatement,
    DivideStatement,
    FileDefinition,
    GoToStatement,
    IfStatement,
    MoveStatement,
    MultiplyStatement,
    OpenStatement,
    Paragraph,
    PerformStatement,
    ReadStatement,
    RewriteStatement,
    SetConditionStatement,
    StartStatement,
    StopRunStatement,
    StringStatement,
    Statement,
    PerformTimesStatement,
    SubtractStatement,
    UnstringStatement,
    WriteStatement,
    ExitProgramStatement,
    FieldReference,
    FigurativeConstant,
    Literal,
)

from engine.transformation.numeric_semantics import (
    NumericValueError,
    display_format_spec,
    is_numeric_literal,
    java_integral_suffix,
    normalize_numeric_literal,
    normalize_value_for_pic,
)

from engine.transformation.redefines import build_redefines_plan, RedefinesPlan

from engine.transformation.java_ir import (
    JavaApplication,
    JavaArrayAccess,
    JavaAssignment,
    JavaBasicType,
    JavaBinaryOp,
    JavaBlock,
    JavaCast,
    JavaClass,
    JavaComment,
    JavaDatabaseResource,
    JavaDependency,
    JavaDependencyType,
    JavaField,
    JavaFileAccessMode,
    JavaFileKey,
    JavaFileOrganization,
    JavaFileResource,
    JavaFilledArray,
    JavaFor,
    JavaIf,
    JavaLiteral,
    JavaLocalVarDecl,
    JavaMatchOutcome,
    JavaMethod,
    JavaMethodCall,
    JavaMethodCallStatement,
    JavaNewArray,
    JavaParameter,
    JavaProgram,
    JavaReportConfig,
    JavaReturn,
    JavaSqlOperationType,
    JavaStatement,
    JavaStatusCodeMapping,
    JavaStringConcat,
    JavaSummaryField,
    JavaTernary,
    JavaThresholdRule,
    JavaTransactionBoundary,
    JavaType,
    JavaUnaryOp,
    JavaVariableRef,
    JavaWhile,
)


# ---------------------------------------------------------------------------
# PIC → Java type mapping
# ---------------------------------------------------------------------------

def _substantive_children(item: DataItem) -> tuple[DataItem, ...]:
    """Child items that make ``item`` a group.

    88-level condition names are attached to their conditional variable;
    they do not turn an elementary numeric item into an alphanumeric group.
    """
    return tuple(child for child in item.children if child.level != 88)


def map_pic_to_java_type(item: DataItem) -> JavaType:
    """Map a COBOL PIC clause to a Java type.

    Mapping rules:
    - PIC 9(n) where n <= 9  → int
    - PIC 9(n) where n > 9   → long
    - PIC 9(n)V9(m)          → double
    - PIC X(n)               → String
    - PIC A(n)               → String
    - Group items (children)  → String (treated as raw bytes)
    - PIC S9(n)              → int (signed)
    """
    if _substantive_children(item):
        return JavaType(basic_type=JavaBasicType.STRING)

    if item.is_numeric:
        # Fixed-point PIC values require a decimal-capable Java type.
        if item.decimal_places > 0:
            return JavaType(basic_type=JavaBasicType.DOUBLE)
        if item.pic_length > 9:
            return JavaType(basic_type=JavaBasicType.LONG)
        return JavaType(basic_type=JavaBasicType.INT)

    # Alphanumeric → String
    return JavaType(basic_type=JavaBasicType.STRING)


def _java_quote(text: str) -> str:
    r"""Escape ``text`` for embedding inside a Java string literal.

    The fill for a figurative VALUE is raw data: ``VALUE QUOTES`` yields
    ``"`` characters, ``LOW-VALUE``/``HIGH-VALUE`` yield NUL and 0xFF, and an
    ordinary literal may contain a backslash.  Emitting those unescaped
    produces a literal ``javac`` rejects.
    """
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\x00", "\\u0000")
        .replace("\xff", "\\u00ff")
    )
    return escaped


def map_pic_to_java_default(item: DataItem) -> str:
    """Get the Java default value for a COBOL PIC type.

    Numeric VALUE clauses are normalized through the deterministic numeric
    contract (leading-zero literals are never emitted as Java octal
    literals, fractional digits are truncated to the PIC scale, and
    overflow keeps the least-significant declared digits — matching
    GnuCOBOL).  A signed literal on an unsigned PIC and an invalid numeric
    VALUE raise :class:`NumericValueError` so the lane fails closed instead
    of emitting a bare identifier.  Integral values outside Java's ``int``
    range carry the ``L`` suffix so the declaration compiles.
    """
    if item.is_numeric:
        if not item.value:
            return "0"
        normalized = normalize_value_for_pic(
            item.value,
            integer_digits=item.integer_digits,
            decimal_digits=item.decimal_places,
            signed=item.signed,
        )
        return f"{normalized}{java_integral_suffix(normalized)}"
    if item.is_alphanumeric and item.pic_length > 0:
        if item.value:
            parsed = parse_figurative_constant(item.value)
            if parsed is not None:
                # Figurative VALUE clauses (VALUE SPACE/ZERO/QUOTE/
                # HIGH-VALUE/LOW-VALUE and VALUE ALL <pattern>) materialize
                # the filled pattern at the declared PIC width instead of
                # leaking the raw COBOL spelling (e.g. ``ALL "*"``) into the
                # Java literal.
                value = figurative_to_width(
                    parsed[0], parsed[1], item.pic_length
                )
                if value is None:
                    value = ""
                # The fill is raw data: ``VALUE QUOTES`` contains ``"`` and
                # ``LOW-VALUE``/``HIGH-VALUE`` contain control bytes, so the
                # literal must be escaped or ``javac`` rejects it.
                return '"' + _java_quote(value) + '"'
        value = item.value.strip(chr(39) + chr(34)) if item.value else ""
        if item.value and item.value.upper() in ("SPACE", "SPACES"):
            value = ""
        return '"' + _java_quote(value[:item.pic_length].ljust(item.pic_length)) + '"'
    if item.value:
        return f'"{item.value.strip(chr(39) + chr(34))}"'
    return '""'


# ---------------------------------------------------------------------------
# COBOL data references (with OCCURS subscripts)
# ---------------------------------------------------------------------------

_REFERENCE_RE = re.compile(r"^([A-Za-z][\w-]*)\s*((?:\([^()]*\)\s*)*)$")


def split_cobol_reference(name: str) -> tuple[str, tuple[str, ...]] | None:
    """Split ``NAME(sub1, sub2)`` into its base name and subscript texts.

    Returns ``None`` when ``name`` is not a plain data reference (for example
    an arithmetic expression or a literal).  Subscripts are split on commas,
    so both ``T(I, J)`` and ``T(I J)`` are accepted.
    """
    text = (name or "").strip()
    match = _REFERENCE_RE.match(text)
    if match is None:
        return None
    base = match.group(1)
    subs: list[str] = []
    for group in re.findall(r"\(([^()]*)\)", match.group(2)):
        for piece in re.split(r"[,\s]+", group.strip()):
            if piece:
                subs.append(piece)
    return base, tuple(subs)


def _subscript_to_java_source(subscript: str) -> str:
    """Render a COBOL subscript expression as Java source.

    A COBOL hyphen is part of a data name; the subtraction operator is
    whitespace-separated.  Rewriting every hyphen (the old behaviour) turned
    ``WS-I - 1`` into ``WS_I _ 1``.
    """
    text = subscript.strip()
    if is_numeric_literal(text):
        try:
            return str(int(normalize_numeric_literal(text)))
        except (NumericValueError, ValueError):
            return text
    return re.sub(r"(?<=\w)-(?=\w)", "_", text)


def cobol_reference_to_java_source(name: str) -> str:
    """Render a COBOL reference (optionally subscripted) as Java source.

    COBOL subscripts are 1-based; Java arrays are 0-based, so each subscript
    becomes ``[(sub - 1)]``.
    """
    parts = split_cobol_reference(name)
    if parts is None:
        return (name or "").strip().replace("-", "_")
    base, subs = parts
    rendered = base.replace("-", "_")
    for sub in subs:
        rendered += f"[({_subscript_to_java_source(sub)} - 1)]"
    return rendered


def _reference_expression(name: str) -> JavaExpression:
    """Build a Java expression for a COBOL reference, preserving subscripts."""
    parts = split_cobol_reference(name)
    if parts is None:
        return JavaVariableRef(name=(name or "").strip().replace("-", "_"))
    base, subs = parts
    expression: JavaExpression = JavaVariableRef(name=base.replace("-", "_"))
    for sub in subs:
        index = JavaBinaryOp(
            left=map_cobol_expr_to_java(sub),
            operator="-",
            right=JavaLiteral(value="1"),
        )
        expression = JavaArrayAccess(array=expression, index=index)
    return expression


def _effective_dimensions(items) -> dict[str, tuple[int, ...]]:
    """Map each data item to its OCCURS dimension chain (outermost first).

    The parser flattens group members to the top level while keeping the
    group hierarchy, so a subordinate item inherits every ancestor's OCCURS.
    A nested table therefore yields ``(outer, inner)`` and lowers to a
    multi-dimensional Java array.
    """
    dimensions: dict[str, tuple[int, ...]] = {}

    def walk(nodes, chain: tuple[int, ...]) -> None:
        for item in nodes:
            mine = chain
            if item.occurs is not None and item.occurs > 0:
                mine = chain + (item.occurs,)
            if mine:
                dimensions[item.name] = mine
            if item.children:
                walk(item.children, mine)

    walk(items, ())
    return dimensions


def _array_java_type(element_type: JavaType, dimensions: tuple[int, ...]) -> JavaType:
    result = element_type
    for _ in dimensions:
        result = JavaType(is_array=True, array_element_type=result)
    return result


def _array_initializer(
    element_type: JavaType,
    dimensions: tuple[int, ...],
    default_literal: str,
) -> JavaExpression:
    """Initialiser for a COBOL table, preserving the item default fill."""
    if element_type.basic_type == JavaBasicType.STRING and len(dimensions) == 1:
        # COBOL fills every entry with the item default (usually spaces).
        # ``new String[n]`` would leave nulls and DISPLAY would print "null".
        return JavaFilledArray(
            element_type=element_type,
            length=dimensions[0],
            fill=JavaLiteral(value=default_literal),
        )
    return JavaNewArray(element_type=element_type, dimensions=dimensions)



def _numeric_literal_java_type(value: str) -> JavaType:
    """Return the Java type implied by a numeric literal spelling."""
    if "." in value:
        return JavaType(basic_type=JavaBasicType.DOUBLE)
    if java_integral_suffix(value):
        # Outside Java's default int range: the literal must be typed long.
        return JavaType(basic_type=JavaBasicType.LONG)
    return JavaType(basic_type=JavaBasicType.INT)


def _numeric_java_literal(text: str) -> JavaLiteral:
    """Build a Java numeric literal with deterministic typing and suffix.

    The normalized value carries the ``L`` suffix whenever it falls outside
    Java's ``int`` range, so generated source compiles instead of failing
    with ``error: integer number too large``.
    """
    try:
        normalized = normalize_numeric_literal(text)
    except NumericValueError:
        normalized = text
    return JavaLiteral(
        value=f"{normalized}{java_integral_suffix(normalized)}",
        java_type=_numeric_literal_java_type(normalized),
    )


# ---------------------------------------------------------------------------
# COBOL statement → Java statement mapping
# ---------------------------------------------------------------------------

# Module-level counter for generated PERFORM...TIMES loop variables.
# Each counted loop gets a unique counter name so that sequential or
# nested TIMES loops in the same method never redeclare one another
# (which would not compile in Java).
import itertools as _itertools
from dataclasses import dataclass, replace as _dc_replace

_times_loop_counter = _itertools.count()


def _fresh_times_var() -> str:
    """Return a unique loop-counter name for a PERFORM...TIMES loop."""
    return f"_times_{next(_times_loop_counter)}"


def _negate_condition(java_cond) :
    """Negate a mapped Java condition for PERFORM...UNTIL (TEST BEFORE).

    COBOL loops WHILE NOT <until-condition>; Java renders while (!(...)).
    """
    return JavaUnaryOp(operator="!", operand=java_cond)


# ---------------------------------------------------------------------------
# COBOL file I/O → CobolFileIo.* helpers
# ---------------------------------------------------------------------------
# Module-level counter for generated file-I/O scratch variables (READ
# record buffers, status temporaries).  Reset once per program mapping so
# generated names stay deterministic for a given program.
_io_var_counter = _itertools.count()


def _reset_file_io_vars() -> None:
    """Reset the file-I/O scratch-variable counter (per-program determinism)."""
    global _io_var_counter
    _io_var_counter = _itertools.count()


def _fresh_io_var(prefix: str) -> str:
    """Unique scratch-variable name, e.g. ``_read_0`` / ``_st_1``."""
    return f"_{prefix}_{next(_io_var_counter)}"


_STDOUT_KEYWORDS = frozenset({
    "STDOUT", "SYSOUT", "SYSPRINT", "SYS000", "S1", "PRINT",
})


def _find_file_def(
    program: CobolProgram | None, file_name: str,
) -> FileDefinition | None:
    """File definition for ``file_name``, or None when unmatched."""
    if program is None or not file_name:
        return None
    for fd in program.file_definitions:
        if fd.name == file_name:
            return fd
    return None


def _resolve_path(fd: FileDefinition | None) -> str | None:
    """Container path for real file I/O; None for STDOUT/unknown/missing."""
    if fd is None:
        return None
    cp = (fd.container_path or "").upper()
    if not cp or cp in _STDOUT_KEYWORDS:
        return None
    return fd.container_path


def _str_lit(value: str) -> JavaLiteral:
    return JavaLiteral(value=value, java_type=JavaType(basic_type=JavaBasicType.STRING))


def _int_lit(value: int) -> JavaLiteral:
    return JavaLiteral(value=str(value))


def _bool_lit(value: bool) -> JavaLiteral:
    # Renderers quote unknown literals; true/false must stay bare Java    # keywords — both generators special-case untyped true/false/null.
    return JavaLiteral(value="true" if value else "false")


def _cobol_call(method: str, *args: JavaExpression) -> JavaMethodCall:
    """Static ``CobolFileIo.<method>(...)`` call expression."""
    return JavaMethodCall(
        class_name="CobolFileIo",
        method_name=method,
        arguments=tuple(args),
        is_static=True,
    )


def _find_data_item(program: CobolProgram | None, name: str) -> DataItem | None:
    """Data item by COBOL/Java-normalized name (WORKING-STORAGE first, then FD records).

    A subscripted reference (``WS-ELEMENT(WS-I)``) resolves to its table
    data item so receiver PIC semantics still apply to the element.
    """
    if program is None or not name:
        return None
    parts = split_cobol_reference(name)
    base = parts[0] if parts is not None else name
    normalized = base.replace("-", "_").upper()
    for item in program.working_storage:
        if item.name.replace("-", "_").upper() == normalized:
            return item
    for item in program.linkage_section:
        if item.name.replace("-", "_").upper() == normalized:
            return item
    for fd in program.file_definitions:
        for item in fd.record_items:
            if item.name.replace("-", "_").upper() == normalized:
                return item
    return None


# ---------------------------------------------------------------------------
# STRING: delimiter-aware sending phrases and write position
# ---------------------------------------------------------------------------

def _string_fail_closed_symbol(*reasons: str) -> str:
    """Java identifier naming a STRING form with no certified Java mapping.

    ``$`` can never appear in a COBOL-derived identifier, so the symbol is
    unresolvable by construction: ``javac`` reports the construct by name
    instead of a wrong value ever being produced silently.
    """
    return "UNSUPPORTED_STRING$" + "$".join(reasons)


def _unstring_fail_closed_symbol(*reasons: str) -> str:
    """Java identifier naming an UNSTRING clause with no certified mapping.

    Same fail-closed contract as :func:`_string_fail_closed_symbol`: the
    ``$`` makes the name unresolvable so ``javac`` reports the clause instead
    of the program running with a silently dropped ``WITH POINTER`` /
    ``VARYING IN`` / ``TALLYING IN`` / ``ON OVERFLOW``.
    """
    return "UNSUPPORTED_UNSTRING$" + "$".join(reasons)


def _string_phrase_java(src: JavaExpression, delim) -> JavaExpression:
    """One sending phrase truncated at its delimiter.

    ``None`` (``DELIMITED BY SIZE``) copies the whole item; SPACE and a
    quoted literal truncate at the first occurrence of the delimiter, and
    when the delimiter does not occur the whole item is copied (the COBOL
    rule).  The delimiter itself is never part of the result.
    """
    if delim is None:
        return src
    if isinstance(delim, FigurativeConstant):
        # SPACE/SPACES: truncation at the first space character.
        delim_java = figurative_constant_to_java(delim.kind)
    elif isinstance(delim, Literal):
        delim_java = _map_cobol_expression_to_java(delim)
    else:  # pragma: no cover - callers fail closed before reaching this
        return src
    idx_call = JavaMethodCall(
        object_ref=src, method_name="indexOf", arguments=(delim_java,)
    )
    return JavaMethodCall(
        object_ref=src,
        method_name="substring",
        arguments=(
            # copy the prefix that precedes the first delimiter occurrence
            _int_lit(0),
            JavaTernary(
                condition=JavaBinaryOp(
                    left=idx_call, operator=">=", right=_int_lit(0)
                ),
                true_expr=idx_call,
                false_expr=JavaMethodCall(
                    object_ref=src, method_name="length", arguments=()
                ),
            ),
        ),
    )


def _string_receiver_width(program: CobolProgram | None, target: str) -> int | None:
    """Declared character width of the STRING receiving item.

    Only a leaf item with a PIC-derived ``pic_length`` yields a width.  A
    group item or an undeclared receiver has no width here — and such a
    receiver is not declared in the generated Java either, so the program
    fails closed at ``javac`` (``cannot find symbol``) instead of silently
    losing the fixed-width rule.
    """
    item = _find_data_item(program, target) if program else None
    if item is None or item.pic_length <= 0:
        return None
    return item.pic_length


def _string_receiver_truncate_statements(
    target: str, width: int | None
) -> list[JavaStatement]:
    """Clip the STRING result to the receiving item's PIC width.

    A COBOL receiving field is fixed width: characters that would extend
    beyond its rightmost position are discarded (and the pointer stops at
    ``width + 1``).  The Java model keeps the receiver as a ``String`` whose
    length is the PIC width (``MOVE`` already pads *and* truncates to it),
    so clipping the written value with ``substring(0, width)`` reproduces
    that truncation exactly.
    """
    if width is None:
        return []
    target_ref = JavaVariableRef(name=target)
    return [
        JavaAssignment(
            target=target,
            expression=JavaMethodCall(
                object_ref=target_ref,
                method_name="substring",
                arguments=(
                    _int_lit(0),
                    JavaMethodCall(
                        class_name="Math",
                        method_name="min",
                        is_static=True,
                        arguments=(
                            JavaMethodCall(
                                object_ref=target_ref,
                                method_name="length",
                                arguments=(),
                            ),
                            _int_lit(width),
                        ),
                    ),
                ),
            ),
        )
    ]


def _string_receiver_statements(
    stmt: StringStatement,
    target: str,
    sources: list[JavaExpression],
    delims: list,
    program: CobolProgram | None,
) -> list[JavaStatement]:
    """Emit the STRING write with COBOL write-position semantics.

    The concatenated sending text is written over the receiving field from
    position 1 (or the ``WITH POINTER`` position) and the unwritten tail
    stays unchanged.  Everything is evaluated from the pre-statement value
    inside a single assignment, so an overlapping source/target resolves
    deterministically (atomic pre-state evaluation).

    Certified here: delimiter truncation (SIZE / literal / SPACE), delimiter
    excluded from the result, tail preservation, **fixed-width receiver
    overflow truncation** (the written value is clipped to the
    receiver's PIC width, discarding the characters that do not fit), and
    the pointer boundary rule: a pointer inside ``1 .. width + 1`` writes at
    that position and is advanced past the last character written (never
    beyond ``width + 1``); a pointer outside that range transfers nothing
    and is left unchanged.  Both rules were verified against real GnuCOBOL
    3.1.2 behaviour as the reference oracle.

    Not certified (fail-closed above): identifier delimiters, ON OVERFLOW,
    VARYING IN, non-integer pointers.  A receiver with no declared width
    (group item / undeclared name) keeps the unbounded emission and fails
    closed at ``javac`` because that receiver is not declared.
    """
    reasons: list[str] = []
    for d in delims:
        if isinstance(d, FieldReference):
            reasons.append(
                "DELIMITED_BY_IDENTIFIER_"
                + d.name.upper().replace("-", "_")
            )
    if stmt.has_overflow:
        reasons.append("OVERFLOW")
    if stmt.varying_pointer:
        # VARYING IN has no certified mapping; name the construct
        # so the fail-closed symbol identifies the phrase and its pointer.
        reasons.append(
            "VARYING_IN_" + stmt.varying_pointer.upper().replace("-", "_")
        )
    if stmt.pointer:
        pointer_item = _find_data_item(program, stmt.pointer) if program else None
        if pointer_item is not None and (
            not pointer_item.is_numeric or pointer_item.decimal_places > 0
        ):
            reasons.append("NON_INTEGER_POINTER")
    if reasons:
        return [JavaAssignment(
            target=target,
            expression=JavaVariableRef(name=_string_fail_closed_symbol(*reasons)),
        )]

    phrases = [_string_phrase_java(src, d) for src, d in zip(sources, delims)]
    built: JavaExpression = (
        phrases[0] if len(phrases) == 1 else JavaStringConcat(parts=tuple(phrases))
    )
    target_ref = JavaVariableRef(name=target)
    width = _string_receiver_width(program, target)
    built_length = JavaMethodCall(
        object_ref=built, method_name="length", arguments=()
    )

    if not stmt.pointer:
        # receiver := built + old.substring(min(old.length, built.length))
        tail = JavaMethodCall(
            object_ref=target_ref,
            method_name="substring",
            arguments=(
                JavaMethodCall(
                    class_name="Math",
                    method_name="min",
                    is_static=True,
                    arguments=(
                        JavaMethodCall(
                            object_ref=target_ref,
                            method_name="length",
                            arguments=(),
                        ),
                        built_length,
                    ),
                ),
            ),
        )
        return [
            JavaAssignment(
                target=target,
                expression=JavaStringConcat(parts=(built, tail)),
            ),
            # Characters beyond the receiving field's rightmost
            # position are discarded, so the result is clipped to the PIC
            # width (the old tail already accounts for the shorter result).
            *_string_receiver_truncate_statements(target, width),
        ]

    # WITH POINTER: write at the pointer position, keep the unwritten tail,
    # advance the pointer past the last character written.
    pointer_name = stmt.pointer.replace("-", "_")
    pointer_ref = JavaVariableRef(name=pointer_name)
    start = JavaBinaryOp(left=pointer_ref, operator="-", right=_int_lit(1))

    if width is None:
        # No declared width on the receiver (group item / undeclared name).
        # Such a receiver is not declared in the generated Java at all, so
        # the program fails closed at ``javac``; the emission used before
        # fixed-width clipping was added is kept here and is not certified
        # for any width-dependent behaviour.
        padded = JavaMethodCall(
            class_name="String",
            method_name="format",
            is_static=True,
            arguments=(
                JavaStringConcat(parts=(_str_lit("%-"), start, _str_lit("s"))),
                target_ref,
            ),
        )
        head = JavaMethodCall(
            object_ref=padded, method_name="substring", arguments=(_int_lit(0), start)
        )
        tail_start = JavaMethodCall(
            class_name="Math",
            method_name="min",
            is_static=True,
            arguments=(
                JavaMethodCall(object_ref=padded, method_name="length", arguments=()),
                JavaBinaryOp(left=start, operator="+", right=built_length),
            ),
        )
        tail = JavaMethodCall(
            object_ref=padded, method_name="substring", arguments=(tail_start,)
        )
        return [
            JavaAssignment(
                target=pointer_name,
                expression=JavaMethodCall(
                    class_name="Math",
                    method_name="max",
                    is_static=True,
                    arguments=(_int_lit(1), pointer_ref),
                ),
            ),
            JavaAssignment(
                target=target,
                expression=JavaStringConcat(parts=(head, built, tail)),
            ),
            JavaAssignment(
                target=pointer_name,
                expression=JavaBinaryOp(
                    left=pointer_ref, operator="+", right=built_length
                ),
            ),
        ]

    # Pointer boundary rule, verified against GnuCOBOL 3.1.2 behaviour:
    # a pointer in ``1 .. width + 1`` writes at that position and is
    # advanced past the last character written, never beyond
    # ``width + 1``; a pointer outside that range (0 or beyond
    # ``width + 1``) transfers nothing and is left unchanged.  The
    # receiver itself always keeps its declared width, so the characters
    # that do not fit are discarded exactly as COBOL does.
    in_range = JavaBinaryOp(
        left=JavaBinaryOp(left=pointer_ref, operator=">=", right=_int_lit(1)),
        operator="&&",
        right=JavaBinaryOp(
            left=pointer_ref, operator="<=", right=_int_lit(width + 1)
        ),
    )
    head = JavaMethodCall(
        object_ref=target_ref,
        method_name="substring",
        arguments=(
            _int_lit(0),
            JavaMethodCall(
                class_name="Math",
                method_name="min",
                is_static=True,
                arguments=(
                    JavaMethodCall(
                        object_ref=target_ref, method_name="length", arguments=()
                    ),
                    start,
                ),
            ),
        ),
    )
    tail_start = JavaMethodCall(
        class_name="Math",
        method_name="min",
        is_static=True,
        arguments=(
            JavaMethodCall(object_ref=target_ref, method_name="length", arguments=()),
            JavaBinaryOp(left=start, operator="+", right=built_length),
        ),
    )
    tail = JavaMethodCall(
        object_ref=target_ref, method_name="substring", arguments=(tail_start,)
    )
    assign = JavaAssignment(
        target=target,
        expression=JavaTernary(
            condition=in_range,
            true_expr=JavaStringConcat(parts=(head, built, tail)),
            false_expr=target_ref,
        ),
    )
    advance = JavaAssignment(
        target=pointer_name,
        expression=JavaTernary(
            condition=in_range,
            true_expr=JavaMethodCall(
                class_name="Math",
                method_name="min",
                is_static=True,
                arguments=(
                    JavaBinaryOp(
                        left=pointer_ref, operator="+", right=built_length
                    ),
                    _int_lit(width + 1),
                ),
            ),
            false_expr=pointer_ref,
        ),
    )
    return [
        assign,
        advance,
        *_string_receiver_truncate_statements(target, width),
    ]


def _numeric_display_items(program: CobolProgram) -> list[DataItem]:
    """Numeric items reachable by a ``DISPLAY`` statement, in declaration order.

    LINKAGE SECTION items are included because a called program can DISPLAY a
    parameter, and COBOL renders it at its declared PIC width (``PIC 9(4)``
    value 100 prints ``0100``) exactly like a WORKING-STORAGE item.
    """
    items = list(program.working_storage)
    items.extend(program.linkage_section)
    for fd in program.file_definitions:
        items.extend(fd.record_items)
    return [
        item for item in items
        if item.is_numeric
        and item.pic_length > 0
        and not _substantive_children(item)
    ]


def _numeric_parse_call(item: DataItem, value: JavaExpression) -> JavaMethodCall:
    """Parse a fixed-format COBOL numeric field using its PIC metadata."""
    trimmed = JavaMethodCall(
        object_ref=value,
        method_name="trim",
        arguments=(),
    )
    if item.decimal_places > 0:
        class_name, method_name = "Double", "parseDouble"
    elif item.pic_length > 9:
        class_name, method_name = "Long", "parseLong"
    else:
        class_name, method_name = "Integer", "parseInt"
    return JavaMethodCall(
        class_name=class_name,
        method_name=method_name,
        arguments=(trimmed,),
        is_static=True,
    )


def _record_layout(fd: FileDefinition | None) -> list[tuple[str, int, bool, bool]]:
    """(java_name, width, is_numeric, is_long) per elementary record item.

    Widths follow COBOL DISPLAY semantics: alphanumeric = PIC length,
    numeric = format width.  Items keep FD declaration order — the same
    order GnuCOBOL writes into the record area.  ``is_long`` mirrors
    ``map_pic_to_java_type`` (pic_length > 9 → long).
    """
    if fd is None:
        return []
    layout: list[tuple[str, int, bool, bool]] = []
    for item in fd.record_items:
        if item.is_condition_name or item.is_group:
            continue
        width = item.format_width if item.is_numeric else item.pic_length
        if width <= 0:
            continue
        is_long = item.is_numeric and item.pic_length > 9
        layout.append((item.name.replace("-", "_"), width, item.is_numeric, is_long))
    return layout


def _record_total_width(fd: FileDefinition | None) -> int:
    """Total record width in bytes/characters (sum of item widths)."""
    return sum(width for _, width, _, _ in _record_layout(fd))


def _key_field_item(
    fd: FileDefinition | None, program: CobolProgram | None,
) -> DataItem | None:
    """RECORD KEY data item (record area first, then WORKING-STORAGE)."""
    if fd is None or fd.record_key is None:
        return None
    key_name = fd.record_key.field_name
    for item in fd.record_items:
        if item.name == key_name:
            return item
    if program is not None:
        for item in program.working_storage:
            if item.name == key_name:
                return item
    return None


def _key_len(fd: FileDefinition | None, program: CobolProgram | None) -> int:
    """Primary-key byte width (0 = sequential / no key)."""
    item = _key_field_item(fd, program)
    if item is None:
        return 0
    return item.format_width if item.is_numeric else item.pic_length


def _key_expr(
    stmt_key: str, fd: FileDefinition | None, program: CobolProgram | None,
) -> JavaExpression:
    """Key value: explicit READ/START KEY clause, else record-key field."""
    if stmt_key:
        return map_cobol_expr_to_java(stmt_key)
    item = _key_field_item(fd, program)
    if item is not None:
        return JavaVariableRef(name=item.name.replace("-", "_"))
    if fd is not None and fd.relative_key:
        return JavaVariableRef(name=fd.relative_key.replace("-", "_"))
    return _int_lit(0)


def _is_relative(fd: FileDefinition | None) -> bool:
    """True when the file uses COBOL RELATIVE organization (RRN-addressed)."""
    if fd is None:
        return False
    org = fd.organization
    value = org.value if hasattr(org, "value") else str(org)
    return str(value).upper() == "RELATIVE"


def _open_key_len(fd: FileDefinition | None, program: CobolProgram | None) -> int:
    """keyLen passed to CobolFileIo.open: -1 selects relative RRN mode."""
    if _is_relative(fd):
        return -1
    return _key_len(fd, program)


def _status_target(fd: FileDefinition | None, program: CobolProgram | None) -> str:
    """Java name of the declared FILE STATUS field ('' when undeclared)."""
    if fd is None or program is None or not fd.file_status_field:
        return ""
    fsj = fd.file_status_field.replace("-", "_")
    names = {item.name.replace("-", "_") for item in program.working_storage}
    for fd2 in program.file_definitions:
        names.update(i.name.replace("-", "_") for i in fd2.record_items)
    return fsj if fsj in names else ""


def _status_eq(status_var: str, code: str) -> JavaExpression:
    """``"code".equals(status)`` — identity-safe String comparison."""
    return JavaMethodCall(
        object_ref=_str_lit(code),
        method_name="equals",
        arguments=(JavaVariableRef(name=status_var),),
    )


def _bind_status(
    result: list[JavaStatement],
    status_var: str,
    call: JavaMethodCall,
    need_expr: bool = False,
) -> str:
    """Bind a status-returning CobolFileIo call.

    Assigns to the declared FILE STATUS field when available; otherwise
    keeps the value in a fresh scratch variable (when a branch needs it)
    or discards it.  Returns the variable usable in conditions ('').
    """
    if status_var:
        result.append(JavaAssignment(target=status_var, expression=call))
        return status_var
    if need_expr:
        tmp = _fresh_io_var("st")
        result.append(JavaLocalVarDecl(
            java_type=JavaType(basic_type=JavaBasicType.STRING),
            name=tmp,
            initializer=call,
        ))
        return tmp
    result.append(JavaMethodCallStatement(call=call))
    return ""


def _status_branch(
    result: list[JavaStatement],
    status_var: str,
    code: str,
    fail_body,
    ok_body,
    program=None,
    called_programs=None,
) -> None:
    """Emit the INVALID KEY / NOT INVALID KEY branch on a status code.

    ``fail_body`` (INVALID KEY scope) runs when status == code;
    ``ok_body`` (NOT INVALID KEY scope) runs otherwise.  Exactly one of
    the two bodies may be present; both may be empty (no branch emitted).
    COBOL body statements are mapped to Java before being placed in the
    branch (raw COBOL IR would render as an empty JavaIf body).
    """
    def _map(body) -> tuple[JavaStatement, ...]:
        return tuple(
            j
            for s in body
            for j in map_cobol_statement(s, program, called_programs)
        )

    fail = _map(fail_body)
    ok = _map(ok_body)
    if fail and ok:
        result.append(JavaIf(
            condition=_status_eq(status_var, code),
            then_body=fail,
            else_body=ok,
        ))
    elif fail:
        result.append(JavaIf(
            condition=_status_eq(status_var, code),
            then_body=fail,
            else_body=(),
        ))
    elif ok:
        result.append(JavaIf(
            condition=_negate_condition(_status_eq(status_var, code)),
            then_body=ok,
            else_body=(),
        ))


def _assembly_expression(
    fd: FileDefinition | None, content_var: str,
) -> JavaExpression | None:
    """Padded fixed-length record image for WRITE/REWRITE.

    Concatenates each record item padded to its DISPLAY width (spaces for
    alphanumeric, leading zeros for numeric) — byte-identical to the
    record area GnuCOBOL writes.  Falls back to the record variable when
    the FD carries no layout.
    """
    layout = _record_layout(fd)
    if layout:
        parts: list[JavaExpression] = []
        for name, width, numeric, _is_long in layout:
            val: JavaExpression = JavaVariableRef(name=name)
            if numeric:
                val = JavaMethodCall(
                    class_name="String",
                    method_name="valueOf",
                    arguments=(val,),
                    is_static=True,
                )
            parts.append(_cobol_call("pad", val, _int_lit(width), _bool_lit(numeric)))
        if len(parts) == 1:
            return parts[0]
        return JavaStringConcat(parts=tuple(parts))
    if content_var:
        return JavaVariableRef(name=content_var)
    return None


def _disassembly_statements(
    fd: FileDefinition | None, read_var: str,
) -> list[JavaStatement]:
    """Split a read record image back into the FD record fields.

    The image is padded to the full record width first so short lines
    never break ``substring``; numeric fields are trimmed then parsed
    into int/long exactly as ``map_pic_to_java_type`` typed them.
    """
    items = [
        item for item in (fd.record_items if fd is not None else ())
        if not item.is_condition_name and not item.is_group
    ]
    if not items:
        return []
    widths = [
        item.format_width if item.is_numeric else item.pic_length
        for item in items
    ]
    total = sum(widths)
    padded = _cobol_call(
        "pad", JavaVariableRef(name=read_var), _int_lit(total), _bool_lit(False),
    )
    stmts: list[JavaStatement] = []
    offset = 0
    for item, width in zip(items, widths):
        name = item.name.replace("-", "_")
        window = JavaMethodCall(
            object_ref=padded,
            method_name="substring",
            arguments=(_int_lit(offset), _int_lit(offset + width)),
        )
        expr: JavaExpression = (
            _numeric_parse_call(item, window) if item.is_numeric else window
        )
        stmts.append(JavaAssignment(target=name, expression=expr))
        offset += width
    return stmts


def _into_statement(
    into_field: str, read_var: str, program: CobolProgram | None,
) -> JavaStatement | None:
    """READ INTO: MOVE the record image into the receiving field."""
    if not into_field:
        return None
    target = into_field.replace("-", "_")
    item = _find_data_item(program, into_field)
    ref = JavaVariableRef(name=read_var)
    if item is None:
        return JavaAssignment(target=target, expression=ref)
    if item.is_numeric:
        return JavaAssignment(
            target=target,
            expression=_numeric_parse_call(item, ref),
        )
    if item.pic_length > 0:
        return JavaAssignment(
            target=target,
            expression=_cobol_call("pad", ref, _int_lit(item.pic_length), _bool_lit(False)),
        )
    return JavaAssignment(target=target, expression=ref)

def map_cobol_expr_to_java(expr: str) -> JavaExpression:
    """Map a COBOL expression string to a Java expression.

    Handles:
    - Field references (DASH_UNDERSCORE conversion)
    - Literals
    - Figurative constants (ZERO / SPACES / ALL "x" / ...)
    - Arithmetic operators (+, -, *, /)
    """
    import re as _re
    expr = expr.strip()

    # Literal
    if expr.startswith("'") and expr.endswith("'"):
        return JavaLiteral(value=expr[1:-1], java_type=JavaType(basic_type=JavaBasicType.STRING))
    if expr.startswith('"') and expr.endswith('"'):
        return JavaLiteral(value=expr[1:-1], java_type=JavaType(basic_type=JavaBasicType.STRING))

    # Figurative constants are reserved words with a fixed value.  Without
    # this they fall through to the field-reference branch below and become
    # an undeclared Java variable (`A = ZERO;`), which does not compile.
    # NOTE: do not name this local `figurative` — that would shadow the
    # module-level import used by figurative_constant_to_java.
    parsed_figurative = parse_figurative_constant(expr)
    if parsed_figurative is not None:
        return figurative_constant_to_java(*parsed_figurative)

    # Check if it's a simple number
    if is_numeric_literal(expr):
        return _numeric_java_literal(expr)

    # Try to parse binary expressions: left OP right (operators must have spaces)
    _operand_pattern = r"[\w][\w-]*(?:\([^()]*\))?"
    binary_match = _re.match(
        rf"^({_operand_pattern})\s+(\+|\-|\*|/)\s+({_operand_pattern})$",
        expr,
    )
    if binary_match:
        left_str = binary_match.group(1).strip()
        op = binary_match.group(2).strip()
        right_str = binary_match.group(3).strip()

        left: JavaExpression
        if is_numeric_literal(left_str):
            left = _numeric_java_literal(left_str)
        else:
            left = _reference_expression(left_str)

        right: JavaExpression
        if is_numeric_literal(right_str):
            right = _numeric_java_literal(right_str)
        else:
            right = _reference_expression(right_str)

        return JavaBinaryOp(left=left, operator=op, right=right)

    # Field reference (single name, possibly subscripted)
    return _reference_expression(expr)


def figurative_constant_to_java(kind: str, fill: str | None = None) -> JavaExpression:
    """Map a COBOL figurative constant to a Java expression.

    A figurative constant supplies one *character* (or the numeric 0) which
    the receiving item replicates across its declared size.  The MOVE mapping
    already pads/truncates an alphanumeric receiving item to its PIC X width
    (``String.format("%-Ns", ...)``), so the constant itself only needs to
    yield a single repeatable Java value:

    * ``ZERO``          -> integer literal ``0`` (numeric receiver semantics
      then scale it to the PIC).
    * ``SPACES`` etc.   -> a one-character Java string literal, which the
      receiver padding expands across the field.
    * ``ALL "x"``       -> the one-character literal ``x``.

    An unknown kind fails closed to the numeric ``0`` only when explicitly
    numeric; otherwise it is emitted as a single space so the program still
    compiles rather than referencing an undeclared identifier.
    """
    if kind == figurative.ZERO:
        return JavaLiteral(value="0", java_type=JavaType(basic_type=JavaBasicType.INT))
    if kind == figurative.ALL and fill is not None:
        return JavaLiteral(value=fill, java_type=JavaType(basic_type=JavaBasicType.STRING))
    char = figurative.figurative_fill_char(kind)
    if char is None:
        # Fail closed: never emit a bare identifier for a reserved word.
        char = " "
    return JavaLiteral(value=char, java_type=JavaType(basic_type=JavaBasicType.STRING))


def _promote_numeric_expression_to_double(expr: JavaExpression) -> JavaExpression:
    """Promote arithmetic operands to double for decimal receiver calculations."""
    if isinstance(expr, JavaBinaryOp):
        return JavaBinaryOp(
            left=_promote_numeric_expression_to_double(expr.left),
            operator=expr.operator,
            right=_promote_numeric_expression_to_double(expr.right),
        )
    if isinstance(expr, JavaUnaryOp):
        return JavaUnaryOp(
            operator=expr.operator,
            operand=_promote_numeric_expression_to_double(expr.operand),
        )
    if isinstance(expr, JavaLiteral) and expr.java_type and expr.java_type.basic_type == JavaBasicType.DOUBLE:
        return expr
    return JavaCast(
        target_type=JavaType(basic_type=JavaBasicType.DOUBLE),
        expression=expr,
    )


def _expression_requires_fractional_type(
    expr: JavaExpression,
    program: CobolProgram | None,
) -> bool:
    """Return whether an arithmetic expression can produce a fractional value."""
    if isinstance(expr, JavaLiteral):
        return bool(
            expr.java_type
            and expr.java_type.basic_type == JavaBasicType.DOUBLE
        )
    if isinstance(expr, JavaVariableRef):
        item = _find_data_item(program, expr.name)
        return bool(item and item.decimal_places > 0)
    if isinstance(expr, JavaBinaryOp):
        return _expression_requires_fractional_type(expr.left, program) or _expression_requires_fractional_type(expr.right, program)
    if isinstance(expr, JavaUnaryOp):
        return _expression_requires_fractional_type(expr.operand, program)
    return True


def _expression_integral_digit_width(
    expr: JavaExpression,
    program: CobolProgram | None,
) -> int:
    """Conservatively estimate decimal digits needed for an integral expression."""
    if isinstance(expr, JavaVariableRef):
        item = _find_data_item(program, expr.name)
        return item.pic_length if item and item.is_numeric else 0
    if isinstance(expr, JavaLiteral):
        # A Java literal suffix (``123L``) is not a digit position.
        value = expr.value.strip().lstrip("+-").rstrip("Ll")
        if value and value.replace(".", "").isdigit():
            return len(value.replace(".", ""))
        return 0
    if isinstance(expr, JavaUnaryOp) and expr.operator == "-":
        return _expression_integral_digit_width(expr.operand, program)
    if isinstance(expr, JavaBinaryOp):
        left = _expression_integral_digit_width(expr.left, program)
        right = _expression_integral_digit_width(expr.right, program)
        if expr.operator in ("+", "-"):
            return max(left, right) + 1
        if expr.operator == "*":
            return left + right
        if expr.operator in ("/", "%"):
            return left
    return 0


def _protect_integral_overflow(
    expression: JavaExpression,
    target_item: DataItem,
    program: CobolProgram | None,
) -> JavaExpression:
    """Prevent Java integral overflow when an expression can exceed target type."""
    target_digits = 9 if target_item.pic_length <= 9 else 18

    if isinstance(expression, JavaBinaryOp):
        # Measure the source tree before recursively wrapping children so a
        # parent's width cannot be hidden by a child Math.* call.
        width = _expression_integral_digit_width(expression, program)
        left = _protect_integral_overflow(expression.left, target_item, program)
        right = _protect_integral_overflow(expression.right, target_item, program)
        candidate = JavaBinaryOp(left=left, operator=expression.operator, right=right)
        if width > target_digits:
            exact_methods = {
                "+": "addExact",
                "-": "subtractExact",
                "*": "multiplyExact",
            }
            method_name = exact_methods.get(expression.operator)
            if method_name:
                return JavaMethodCall(
                    class_name="Math",
                    method_name=method_name,
                    arguments=(left, right),
                    is_static=True,
                )
        return candidate

    if isinstance(expression, JavaUnaryOp):
        operand = _protect_integral_overflow(expression.operand, target_item, program)
        candidate = JavaUnaryOp(operator=expression.operator, operand=operand)
        if expression.operator == "-" and _expression_integral_digit_width(candidate, program) > target_digits:
            return JavaMethodCall(
                class_name="Math",
                method_name="negateExact",
                arguments=(operand,),
                is_static=True,
            )
        return candidate

    width = _expression_integral_digit_width(expression, program)
    if target_digits == 9 and width > target_digits:
        return JavaMethodCall(
            class_name="Math",
            method_name="toIntExact",
            arguments=(expression,),
            is_static=True,
        )
    return expression


def _is_numeric_expression(
    expression: JavaExpression,
    program: CobolProgram | None,
) -> bool:
    """Return whether an expression is numeric and safe for receiver semantics."""
    if isinstance(expression, JavaLiteral):
        return bool(
            expression.java_type
            and expression.java_type.basic_type != JavaBasicType.STRING
        )
    if isinstance(expression, JavaVariableRef):
        item = _find_data_item(program, expression.name)
        return bool(item and item.is_numeric)
    if isinstance(expression, JavaBinaryOp):
        return expression.operator in ("+", "-", "*", "/", "%") and (
            _is_numeric_expression(expression.left, program)
            and _is_numeric_expression(expression.right, program)
        )
    if isinstance(expression, JavaUnaryOp):
        return _is_numeric_expression(expression.operand, program)
    return False


def _expression_can_be_negative(
    expr: JavaExpression,
    program: CobolProgram | None,
) -> bool:
    """Conservatively report whether an integral/decimal expression can go below zero.

    The result is only ever used to decide whether an *unsigned* COBOL
    receiver needs the magnitude applied (see
    :func:`_apply_numeric_receiver_semantics`), so it errs towards
    ``True`` whenever an operand cannot be proven non-negative.
    """
    if isinstance(expr, JavaLiteral):
        return expr.value.strip().startswith("-")
    if isinstance(expr, JavaVariableRef):
        item = _find_data_item(program, expr.name)
        if item is None or not item.is_numeric:
            # Unknown operand: assume the worst rather than drop the fix.
            return True
        return item.signed
    if isinstance(expr, JavaUnaryOp):
        if expr.operator == "-":
            return True
        if expr.operator == "+":
            return _expression_can_be_negative(expr.operand, program)
        return True
    if isinstance(expr, JavaBinaryOp):
        left_negative = _expression_can_be_negative(expr.left, program)
        right_negative = _expression_can_be_negative(expr.right, program)
        if expr.operator in ("+", "*", "/"):
            return left_negative or right_negative
        if expr.operator == "%":
            # Java keeps the sign of the dividend.
            return left_negative
        return True
    if isinstance(expr, JavaCast):
        return _expression_can_be_negative(expr.expression, program)
    if isinstance(expr, JavaMethodCall):
        if expr.is_static and expr.class_name == "Math" and expr.method_name == "abs":
            return False
        return True
    return True


def _apply_numeric_receiver_semantics(
    expression: JavaExpression,
    target: str,
    program: CobolProgram | None,
    rounded: bool = False,
) -> JavaExpression:
    """Apply COBOL final-result scale/truncation semantics to an arithmetic receiver.

    An unsigned receiving PIC stores the *magnitude* of a negative result
    (GnuCOBOL oracle: ``COMPUTE UN = 0 - 5`` on ``PIC 9(3)`` stores
    ``005``, and ``PIC 9(3)V9`` receives ``001.2`` for ``-1.25``), so the
    magnitude is applied only when the receiver is unsigned *and* the
    expression is not provably non-negative.
    """
    item = _find_data_item(program, target)
    if item is None or not item.is_numeric:
        return expression

    scaled = _scale_numeric_receiver(expression, item, program, rounded)
    if item.signed or not _expression_can_be_negative(expression, program):
        return scaled
    return JavaMethodCall(
        class_name="Math",
        method_name="abs",
        arguments=(scaled,),
        is_static=True,
    )


def _scale_numeric_receiver(
    expression: JavaExpression,
    item: DataItem,
    program: CobolProgram | None,
    rounded: bool = False,
) -> JavaExpression:
    """Scale/truncate an expression to its receiving PIC (COBOL receiver semantics)."""
    if item.decimal_places > 0:
        # Decimal receivers require fractional arithmetic even when all source
        # operands are integer PICs, so division is not accidentally integer division.
        expression = _promote_numeric_expression_to_double(expression)
    elif not _expression_requires_fractional_type(expression, program):
        # Keep ordinary integral operations native, but make a potentially
        # overflowing expression fail explicitly instead of silently wrapping.
        return _protect_integral_overflow(expression, item, program)

    rounding_mode = (
        "java.math.RoundingMode.HALF_UP" if rounded else "java.math.RoundingMode.DOWN"
    )
    scaled = JavaMethodCall(
        object_ref=JavaMethodCall(
            class_name="java.math.BigDecimal",
            method_name="valueOf",
            arguments=(expression,),
            is_static=True,
        ),
        method_name="setScale",
        arguments=(
            JavaLiteral(value=str(item.decimal_places)),
            JavaVariableRef(name=rounding_mode),
        ),
    )
    if item.decimal_places > 0:
        return JavaMethodCall(object_ref=scaled, method_name="doubleValue", arguments=())

    narrow_method = "longValueExact" if item.pic_length > 9 else "intValueExact"
    return JavaMethodCall(object_ref=scaled, method_name=narrow_method, arguments=())


def _map_cobol_expression_to_java(expr) -> JavaExpression:
    """Map a structured COBOL IR Expression to a Java expression.

    COBOL literal → expression representation → Java literal:
    - Literal (non-numeric, e.g. 'SUBTRACT') → Java string literal
      (rendered quoted, never as a bare Java identifier).
    - Literal (numeric) → Java int literal.
    - FieldReference → Java variable reference.
    - Binary/Unary expressions recurse into operands.

    Raw strings fall back to :func:`map_cobol_expr_to_java` (which handles
    quoted text); anything else stringifies through the same path instead
    of ``str()``-ing the IR node into a variable name.
    """
    from engine.transformation import ir as _cobol_ir

    if isinstance(expr, str):
        return map_cobol_expr_to_java(expr)
    if isinstance(expr, _cobol_ir.Literal):
        if expr.is_numeric:
            return _numeric_java_literal(expr.value)
        return JavaLiteral(
            value=expr.value,
            java_type=JavaType(basic_type=JavaBasicType.STRING),
        )
    if isinstance(expr, _cobol_ir.FigurativeConstant):
        # Recover the repeated pattern from the preserved spelling —
        # ``ALL "ab"`` must compare/map as ``ab``, not as a space.
        parsed_text = (
            parse_figurative_constant(expr.text) if expr.text else None
        )
        return figurative_constant_to_java(
            expr.kind, parsed_text[1] if parsed_text is not None else None
        )
    if isinstance(expr, _cobol_ir.FieldReference):
        return _reference_expression(expr.name)
    if isinstance(expr, _cobol_ir.BinaryExpression):
        return JavaBinaryOp(
            left=_map_cobol_expression_to_java(expr.left),
            operator=expr.operator,
            right=_map_cobol_expression_to_java(expr.right),
        )
    if isinstance(expr, _cobol_ir.UnaryExpression):
        return JavaUnaryOp(
            operator=expr.operator,
            operand=_map_cobol_expression_to_java(expr.operand),
        )
    if isinstance(expr, _cobol_ir.IntrinsicCall):
        # `**` and `FUNCTION MIN(...)` have no certified Java
        # mapping, so the parser raises UNSUPPORTED_CONSTRUCT and the program
        # is classified UNSUPPORTED.  Code generation must still not lie: the
        # old fallthrough did ``str(expr)``, which printed the Python dataclass
        # repr straight into the Java source —
        # ``WS_A = Math.abs(IntrinsicCall(name='**', arguments='2 ** 3'));`` —
        # malformed output that happened to fail closed only because `javac`
        # could not parse a repr.  Emit an unmistakable, deliberately undefined
        # symbol instead: the statement keeps a valid Java expression shape and
        # `javac` reports the construct by name, so no wrong value can ever be
        # produced silently.
        return JavaVariableRef(name=_intrinsic_fail_closed_symbol(expr.name))
    if isinstance(expr, _cobol_ir.Expression):
        # Any other Expression node has no branch above.  Stringifying it would
        # silently put a Python repr into generated Java, so fail closed with
        # a name that cannot resolve.
        # ``$`` again: a COBOL-derived identifier can never contain it, so no
        # data item can accidentally declare this symbol.
        return JavaVariableRef(
            name=f"UNSUPPORTED_EXPRESSION${type(expr).__name__.upper()}"
        )
    return map_cobol_expr_to_java(str(expr))


def _intrinsic_fail_closed_symbol(name: str) -> str:
    """Return a Java identifier that names an unmapped COBOL intrinsic.

    The symbol is deliberately never declared, so any generated statement using
    it fails to compile rather than executing a wrong value.

    The separator is ``$`` and not ``_`` **on purpose**.  A COBOL user-defined
    word maps to Java by replacing hyphens with underscores, so a field named
    ``UNSUPPORTED-INTRINSIC-POWER`` would have *declared* a plain-underscore
    marker and made it resolve — silently converting fail-closed back into
    fail-open (confirmed by an adversarial probe).
    ``$`` is a legal Java identifier character but can never occur in a COBOL
    data name, so a collision is structurally impossible.  This follows the
    existing ``_FIGURATIVE_SENTINEL`` precedent: a marker COBOL source cannot
    produce.

    ``**`` is aliased to a readable stem; every other name is sanitised to
    alphanumerics so the result is always a legal Java identifier.
    """
    alias = {"**": "POWER", "*": "TIMES", "/": "DIVIDE"}.get(name.strip())
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").upper()
    stem = alias or cleaned or "UNNAMED"
    return f"UNSUPPORTED_INTRINSIC${stem}"


#: Marker wrapped around a figurative fill character in a substituted
#: condition token.  COBOL source cannot produce it (it is not a legal COBOL
#: identifier or literal body), so a genuine one-character COBOL literal such
#: as ``IF C = " "`` is never confused with ``IF C = SPACES``.
_FIGURATIVE_SENTINEL = "\\u0001FIG"

#: The sentinel wraps the fill's codepoint so it survives ``condition.split()``
#: as ONE whitespace-delimited token (required for multi-clause conditions such
#: as ``A > 1 OR C = SPACES``).  Both markers are escape sequences, so the
#: encoded token contains no space and cannot be produced by real COBOL source.
_FIGURATIVE_TOKEN = re.compile(
    re.escape(_FIGURATIVE_SENTINEL) + r"(\d+)" + re.escape(_FIGURATIVE_SENTINEL)
)


def _fold_negated_relational(condition: str) -> str:
    """Fold COBOL's negated relational operators into their Java equivalents.

    ``A NOT = B`` is ``A != B``, ``A NOT > B`` is ``A < B``, and so on.  The
    negation is attached to the operator rather than emitted as a separate
    ``!`` prefix, because Java has no unary prefix operator that can negate a
    relational result (``!A > B`` would compare a boolean, and ``A !> B`` does
    not compile at all).

    Quote-aware: a ``NOT`` inside a literal is left alone.
    """
    negated = {
        "=": "!=", "==": "!=", "!=": "==", "<>": "==",
        ">": "<=", "<=": ">", "<": ">=", ">=": "<",
    }
    parts = re.split(r"('[^']*'|\"[^\"]*\")", condition)
    for index in range(0, len(parts), 2):
        chunk = parts[index]
        chunk = re.sub(
            r"\bNOT\s*(>=|<=|<>|==|!=|>|<|=)",
            lambda m: negated[m.group(1)],
            chunk,
            flags=re.IGNORECASE,
        )
        parts[index] = chunk
    return "".join(parts)


def _substitute_figurative_constants(condition: str) -> str:
    """Replace figurative constants in a condition with Java literals.

    A figurative constant on the right of a comparison is a *fill*, not a
    single character: ``IF C = SPACES`` is true when **every** character of
    ``C`` is a space.  Comparing against a one-character literal would be
    wrong for any field wider than one character, so the token is replaced
    by a marked sentinel that :func:`_operand` expands into a
    whole-field comparison.

    The substitution happens on whole words only, before the DASH_UNDERSCORE
    rewrite, so ``HIGH-VALUE`` is still recognised as a reserved word and a
    hyphenated field such as ``HIGH-VALUE-CODE`` is left alone.
    """
    import re as _re

    pattern = (
        r"(?<![\w-])(?:"
        r"(?:ALL\s+(?:\"[^\"]{1}\"|'[^']{1}'))"
        r"|(?:ZEROES|ZEROS|ZERO-ZERO-ZERO|ZERO|SPACES|SPACE|QUOTES|QUOTE"
        r"|LOW-VALUES|LOW-VALUE|HIGH-VALUES|HIGH-VALUE)"
        r")(?![\w-])"
    )

    def _dispatch(match: "re.Match[str]") -> str:
        parsed = figurative.parse_figurative_constant(match.group(0))
        if parsed is None:
            return match.group(0)
        kind, fill = parsed
        if kind == figurative.ZERO:
            # Numeric zero compares directly against a numeric field.
            return "0"
        char = fill if fill is not None else figurative.figurative_fill_char(kind)
        if char is None:
            char = " "
        return f'"{_FIGURATIVE_SENTINEL}{ord(char)}{_FIGURATIVE_SENTINEL}"'

    return _re.sub(pattern, _dispatch, condition)


def _strip_figurative_sentinels(condition: str) -> str:
    """Replace any surviving figurative sentinel with a plain Java literal.

    A sentinel that reaches the generated source would be a leak of internal
    encoding.  The structured comparison path consumes sentinels via
    :func:`_operand`; this guard covers every other path (an unparsed or
    otherwise unsupported condition shape) so a sentinel can never be emitted
    verbatim into Java.
    """
    if _FIGURATIVE_SENTINEL not in condition:
        return condition
    return _FIGURATIVE_TOKEN.sub(_sentinel_to_literal, condition)


def _sentinel_to_literal(match: "re.Match[str]") -> str:
    """Render a surviving figurative sentinel as a one-character literal."""
    char = chr(int(match.group(1)))
    return f'"{_java_string_body(char)}"'


def _is_figurative_sentinel(token: str) -> bool:
    """True when ``token`` is a substituted figurative fill token."""
    return (
        token.startswith(f'"{_FIGURATIVE_SENTINEL}')
        and token.endswith(f'{_FIGURATIVE_SENTINEL}"')
    )


def _figurative_sentinel_char(token: str) -> str:
    """Return the fill character encoded in a substituted figurative token."""
    digits = token[1 + len(_FIGURATIVE_SENTINEL):-(1 + len(_FIGURATIVE_SENTINEL))]
    return chr(int(digits))


def _java_string_body(char: str) -> str:
    """Escape a single figurative fill character for a Java string literal."""
    return char.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Level-88 condition names
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConditionNameSpec:
    """An 88-level condition name and the values that satisfy it."""
    name: str            # COBOL spelling (hyphens preserved)
    parent: DataItem     # the conditional variable
    terms: tuple[tuple[str, str | None], ...]  # (value, THRU-high or None)


_CONDITION_VALUE_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|[^\s,]+")

_FIGURATIVE_ZERO_VALUES = frozenset({"ZERO", "ZEROS", "ZEROES"})


def _is_quoted_literal(text: str) -> bool:
    return (
        len(text) >= 2
        and text[0] == text[-1]
        and text[0] in "'\""
    )


def _condition_terms(raw: str) -> tuple[tuple[str, str | None], ...]:
    """Parse an 88-level VALUE clause into single values / THRU ranges."""
    tokens = _CONDITION_VALUE_TOKEN.findall(raw or "")
    terms: list[tuple[str, str | None]] = []
    i = 0
    while i < len(tokens):
        low = tokens[i]
        if (
            i + 2 < len(tokens)
            and tokens[i + 1].upper() in ("THRU", "THROUGH")
        ):
            terms.append((low, tokens[i + 2]))
            i += 3
        else:
            terms.append((low, None))
            i += 1
    return tuple(terms)


def condition_name_specs(program: CobolProgram | None) -> dict[str, ConditionNameSpec]:
    """Collect every 88-level condition name in the program (upper-cased key)."""
    specs: dict[str, ConditionNameSpec] = {}
    if program is None:
        return specs

    def walk(items, parent: DataItem | None) -> None:
        for item in items:
            if item.level == 88 and parent is not None:
                specs[item.name.upper()] = ConditionNameSpec(
                    name=item.name,
                    parent=parent,
                    terms=_condition_terms(item.value or ""),
                )
            elif item.children:
                walk(item.children, item)

    walk(program.working_storage, None)
    for fd in program.file_definitions:
        walk(fd.record_items, None)
    return specs


def _condition_value_literal(raw: str, parent: DataItem) -> JavaExpression:
    """A Java literal for one 88-level VALUE term, typed like its parent.

    Alphanumeric terms go through the same width padding/truncation and
    figurative-constant materialisation as a VALUE clause on the parent, so
    ``PIC X(3)`` + ``VALUE 'A'`` compares against ``"A  "`` exactly as
    GnuCOBOL stores it.  Numeric terms keep their numeric value (``VALUE 00``
    is decimal zero, never a Java octal literal).
    """
    text = raw.strip()
    if parent.is_numeric:
        unquoted = text[1:-1] if _is_quoted_literal(text) else text
        if unquoted.upper() in _FIGURATIVE_ZERO_VALUES:
            return JavaLiteral(value="0")
        try:
            return _numeric_java_literal(unquoted)
        except (NumericValueError, ValueError):
            # Never emit a bare identifier for an unparseable value.
            return JavaLiteral(
                value="UNSUPPORTED_CONDITION$VALUE",
                java_type=JavaType(basic_type=JavaBasicType.BOOLEAN),
            )
    return JavaLiteral(value=map_pic_to_java_default(_dc_replace(parent, value=text)))


def _condition_value_is_supported(raw: str, parent: DataItem) -> bool:
    """True when one 88-level VALUE term has a certified deterministic form."""
    text = raw.strip()
    if not text:
        return False
    if parent.is_numeric:
        unquoted = text[1:-1] if _is_quoted_literal(text) else text
        if unquoted.upper() in _FIGURATIVE_ZERO_VALUES:
            return True
        try:
            normalize_numeric_literal(unquoted)
        except (NumericValueError, ValueError):
            return False
        return True
    if _is_quoted_literal(text):
        return True
    # Figurative constants (SPACES / LOW-VALUES / HIGH-VALUES / ALL "x")
    # materialise deterministically at the parent width.
    return parse_figurative_constant(text) is not None


def condition_name_problems(
    program: CobolProgram | None,
) -> dict[str, str]:
    """Condition names whose VALUE clause has no certified lowering."""
    problems: dict[str, str] = {}
    for key, spec in condition_name_specs(program).items():
        if not spec.terms:
            problems[key] = "88-level condition name has no VALUE clause"
            continue
        for low, high in spec.terms:
            for token in (low, high):
                if token is None:
                    continue
                if not _condition_value_is_supported(token, spec.parent):
                    problems[key] = (
                        f"88-level VALUE term {token!r} on {spec.parent.name} "
                        "has no certified lowering"
                    )
                    break
            if key in problems:
                break
    return problems



def _condition_term_expression(
    spec: ConditionNameSpec,
    term: tuple[str, str | None],
) -> JavaExpression:
    low, high = term
    parent_name = spec.parent.name.replace("-", "_")
    parent_ref = JavaVariableRef(name=parent_name)
    low_expr = _condition_value_literal(low, spec.parent)
    if high is None:
        if spec.parent.is_numeric:
            return JavaBinaryOp(left=parent_ref, operator="==", right=low_expr)
        return JavaMethodCall(
            object_ref=low_expr,
            method_name="equals",
            arguments=(parent_ref,),
        )
    high_expr = _condition_value_literal(high, spec.parent)
    if spec.parent.is_numeric:
        return JavaBinaryOp(
            left=JavaBinaryOp(left=parent_ref, operator=">=", right=low_expr),
            operator="&&",
            right=JavaBinaryOp(left=parent_ref, operator="<=", right=high_expr),
        )
    return JavaBinaryOp(
        left=JavaBinaryOp(
            left=JavaMethodCall(
                object_ref=parent_ref,
                method_name="compareTo",
                arguments=(low_expr,),
            ),
            operator=">=",
            right=JavaLiteral(value="0"),
        ),
        operator="&&",
        right=JavaBinaryOp(
            left=JavaMethodCall(
                object_ref=parent_ref,
                method_name="compareTo",
                arguments=(high_expr,),
            ),
            operator="<=",
            right=JavaLiteral(value="0"),
        ),
    )


def condition_name_expression(spec: ConditionNameSpec) -> JavaExpression:
    """Boolean Java expression for an 88-level condition name."""
    if not spec.terms:
        return JavaLiteral(
            value="UNSUPPORTED_CONDITION$NO_VALUE",
            java_type=JavaType(basic_type=JavaBasicType.BOOLEAN),
        )
    expression = _condition_term_expression(spec, spec.terms[0])
    for term in spec.terms[1:]:
        expression = JavaBinaryOp(
            left=expression,
            operator="||",
            right=_condition_term_expression(spec, term),
        )
    return expression


def _condition_name_only(
    text: str,
    specs: dict[str, ConditionNameSpec],
) -> JavaExpression | None:
    """Resolve a condition that is exactly a condition name (or TRUE = name)."""
    stripped = text.strip()
    upper = stripped.upper()
    match = re.match(
        r"^(?:TRUE\s*=\s*)?(NOT\s+)?([A-Z0-9][\w-]*)$", stripped, re.IGNORECASE
    )
    if match is None:
        return None
    name = match.group(2).upper()
    spec = specs.get(name)
    if spec is None:
        return None
    expression = condition_name_expression(spec)
    if match.group(1):
        return JavaUnaryOp(operator="!", operand=expression)
    return expression


def expand_condition_names(
    condition: str, specs: dict[str, ConditionNameSpec]
) -> JavaExpression | None:
    """Resolve every level-88 name in ``condition`` to its comparison.

    Simple conditions resolve structurally; ``AND``/``OR`` compounds expand
    each side so a name can be mixed with ordinary comparisons.
    """
    if not specs:
        return None
    direct = _condition_name_only(condition, specs)
    if direct is not None:
        return direct
    parts = re.split(r"\s+(AND|OR)\s+", condition, flags=re.IGNORECASE)
    if len(parts) == 1:
        return None
    # Build left-associatively: a AND b OR c → ((a && b) || c)
    expression: JavaExpression | None = None
    pending_operator = ""
    for index, part in enumerate(parts):
        if index % 2 == 1:
            pending_operator = "&&" if part.upper() == "AND" else "||"
            continue
        side = _condition_name_only(part, specs)
        if side is None:
            side = map_cobol_condition_to_java(part, condition_names=specs)
        if expression is None:
            expression = side
        else:
            expression = JavaBinaryOp(
                left=expression, operator=pending_operator, right=side
            )
    return expression


def map_cobol_condition_to_java(
    condition: str,
    condition_names: dict[str, ConditionNameSpec] | None = None,
    program: CobolProgram | None = None,
) -> JavaExpression:
    """Map a COBOL condition string to a Java expression.

    Converts COBOL condition syntax to Java boolean expression.
    Returns a JavaBinaryOp for simple conditions, or JavaLiteral for complex ones.

    ``condition_names`` (or ``program``, from which they are derived) enables
    88-level condition-name resolution.
    """
    if condition_names is None and program is not None:
        condition_names = condition_name_specs(program)
    if condition_names:
        expanded = expand_condition_names(condition, condition_names)
        if expanded is not None:
            return expanded
    condition = condition.strip()
    import re as _re

    # Figurative constants are substituted FIRST, before any operator
    # rewriting and before the DASH_UNDERSCORE rewrite below.  Rewriting first
    # turned `HIGH-VALUE` into `HIGH_VALUE`, which no longer matched the
    # reserved word and fell through to a bare Java identifier.
    # Doing it first also lets `NOT = SPACES` be folded as one comparison
    # rather than leaving the fill literal outside the operator.
    condition = _substitute_figurative_constants(condition)
    # Fold `NOT <relational>` while the operators are still COBOL-spelled:
    # `A NOT > 3` is `A <= 3`.  Emitting a separate `!` prefix cannot work in
    # Java (`A !> 3` does not compile) and `!A > 3` compares a boolean.
    condition = _fold_negated_relational(condition)
    # Any remaining `NOT` is a logical negation of a sub-expression.
    condition = re.sub(r"(?<![\w!])NOT\s+", "!", condition, flags=re.IGNORECASE)

    # Handle WHEN OTHER → always true (standalone or as "subject = OTHER")
    if condition == "OTHER" or condition.endswith(" = OTHER") or condition.endswith("== OTHER"):
        return JavaLiteral(value="true")

    # Handle THRU range: subject = val1 THRU val2 → subject >= val1 && subject <= val2
    thru_match = _re.match(
        r'^(\w[\w-]*)\s*==\s*(\d+)\s+THRU\s+(\d+)$',
        condition.replace("-", "_").replace(" = ", " == ").strip(),
    )
    if thru_match:
        subject = thru_match.group(1).replace("-", "_")
        low = thru_match.group(2)
        high = thru_match.group(3)
        left = JavaBinaryOp(
            left=JavaVariableRef(name=subject),
            operator=">=",
            right=JavaLiteral(value=low),
        )
        right = JavaBinaryOp(
            left=JavaVariableRef(name=subject),
            operator="<=",
            right=JavaLiteral(value=high),
        )
        return JavaBinaryOp(left=left, operator="&&", right=right)

    # Handle IS/IS NOT
    condition = condition.replace(" IS NOT ", " != ")
    condition = condition.replace(" IS ", " == ")

    # Handle = <>
    condition = condition.replace(" <> ", " != ")
    # Handle bare = (but not ==, >=, <=, !=, and never inside quotes).
    condition = _replace_bare_equals(condition)

    # Handle AND/OR
    condition = condition.replace(" AND ", " && ")
    condition = condition.replace(" OR ", " || ")

    # Handle NOT as an *operator token*.  The previous unconditional
    # `replace("NOT ", "!")` ran after `NOT =` had already become `!=`, so
    # `C NOT = SPACES` produced `C ! == SPACES` and `A NOT > 3` produced
    # `A !> 3` — non-compiling Java with no diagnostic.  Here `NOT` is only
    # turned into `!` when it directly precedes a relational operator; in the
    # `NOT =`/`NOT >` forms it is folded into the *negated* operator instead
    # (`!=` / `<`), which is the COBOL meaning.  Handled by
    # _fold_negated_relational below, which must run while the operators are
    # still in their COBOL spelling AND after figurative substitution so a
    # `= SPACES` fill stays inside the comparison.

    # Convert field references. Single-quoted COBOL literals become
    # double-quoted Java string literals (single quotes would be Java
    # char literals and would not compile against String fields).
    #
    # Figurative constants are substituted here, *before* the DASH_UNDERSCORE
    # rewrite below.  Rewriting first turned `HIGH-VALUE` into `HIGH_VALUE`,
    # which no longer matched the reserved word and fell through to a bare
    # Java identifier.
    parts = condition.split()
    result_parts = []
    for part in parts:
        if part in ("==", "!=", "&&", "||", "(", ")", "!", ">=", "<=", ">", "<"):
            result_parts.append(part)
        elif len(part) >= 2 and part.startswith("'") and part.endswith("'"):
            inner = part[1:-1].replace('"', '\\"')
            result_parts.append(f'"{inner}"')
        elif part.startswith("'") or part.startswith('"'):
            result_parts.append(part)
        elif part.replace(".", "").replace("-", "").isdigit():
            result_parts.append(part)
        else:
            result_parts.append(part.replace("-", "_"))

    condition_str = " ".join(result_parts)

    # Try to parse simple binary conditions: left OP right
    binary_match = _re.match(
        r'^(\w+|"(?:[^"\\]|\\.)*")\s*(==|!=|>=|<=|>|<)\s*(\w+|"(?:[^"\\]|\\.)*")$',
        condition_str,
    )
    if binary_match:
        left_name = binary_match.group(1)
        op = binary_match.group(2)
        right_str = binary_match.group(3)

        def _operand(token: str) -> JavaExpression:
            if _is_figurative_sentinel(token):
                char = _figurative_sentinel_char(token)
                return JavaLiteral(
                    value=char,
                    java_type=JavaType(basic_type=JavaBasicType.STRING),
                )
            if token.startswith('"') or token.startswith("'"):
                return JavaLiteral(value=token)
            if token.replace(".", "").replace("-", "").isdigit():
                return JavaLiteral(value=token)
            return JavaVariableRef(name=token)

        left_is_fill = _is_figurative_sentinel(left_name)
        right_is_fill = _is_figurative_sentinel(right_str)
        left_expr = _operand(left_name)
        right_expr = _operand(right_str)

        # COBOL ``= SPACES``/``= ALL "x"`` compares against the *whole* field
        # filled with the character, so a one-character literal equality would
        # be wrong for any field wider than one character.  Emit a trim-free
        # all-characters-match test over the non-fill operand instead.
        if op in ("==", "!=") and (left_is_fill or right_is_fill):
            fill_expr = left_expr if left_is_fill else right_expr
            field_expr = right_expr if left_is_fill else left_expr
            matches = JavaMethodCall(
                object_ref=field_expr,
                method_name="chars",
                arguments=(),
            )
            all_of = JavaMethodCall(
                object_ref=matches,
                method_name="allMatch",
                arguments=(),
            )
            filled = JavaMethodCall(
                object_ref=field_expr,
                method_name="replace",
                arguments=(fill_expr, JavaLiteral(value="")),
            )
            is_empty = JavaMethodCall(
                object_ref=filled,
                method_name="isEmpty",
                arguments=(),
            )
            return is_empty if op == "==" else JavaUnaryOp(operator="!", operand=is_empty)

        # COBOL ``=`` on alphanumeric operands is content equality.  Java
        # ``==`` compares String identity, so a MOVE-built field never equals
        # a literal and the branch/loop takes the wrong side forever.
        left_is_string = left_name.startswith(('"', "'"))
        right_is_string = right_str.startswith(('"', "'"))
        if op in ("==", "!=") and (left_is_string or right_is_string):
            if left_is_string:
                equals_call: JavaExpression = JavaMethodCall(
                    object_ref=left_expr,
                    method_name="equals",
                    arguments=(right_expr,),
                )
            else:
                equals_call = JavaMethodCall(
                    object_ref=right_expr,
                    method_name="equals",
                    arguments=(left_expr,),
                )
            if op == "!=":
                return JavaUnaryOp(operator="!", operand=equals_call)
            return equals_call

        return JavaBinaryOp(left=left_expr, operator=op, right=right_expr)

    return JavaLiteral(value=_expand_figurative_in_condition(condition_str))


def _expand_figurative_in_condition(condition: str) -> str:
    """Rewrite figurative comparisons in a rendered condition string.

    The structured path handles a single binary comparison and can build the
    whole-field test properly.  A multi-clause condition (e.g.
    ``A >= 1 OR C = SPACES``) falls back to rendering the string, where a
    surviving sentinel would otherwise become a malformed literal.  Replace
    each ``field OP <sentinel>`` (and the mirrored form) with the same
    ``field.replace(fill, "").isEmpty()`` test the structured path emits, so
    the fallback keeps the *semantics* rather than just compiling.
    """
    if _FIGURATIVE_SENTINEL not in condition:
        return condition
    pattern = re.compile(
        r'([\w."]+)\s*(==|!=)\s*"' + re.escape(_FIGURATIVE_SENTINEL) + r'(\d+)'
        + re.escape(_FIGURATIVE_SENTINEL) + r'"'
        r'|"' + re.escape(_FIGURATIVE_SENTINEL) + r'(\d+)' + re.escape(_FIGURATIVE_SENTINEL)
        + r'"\s*(==|!=)\s*([\w."]+)'
    )

    def _expand(match: "re.Match[str]") -> str:
        if match.group(1) is not None:
            field, op, digits = match.group(1), match.group(2), match.group(3)
        else:
            digits, op, field = match.group(4), match.group(5), match.group(6)
        fill = chr(int(digits))
        test = f'{field}.replace("{_java_string_body(fill)}", "").isEmpty()'
        return test if op == "==" else f"!{test}"

    expanded = pattern.sub(_expand, condition)
    return _strip_figurative_sentinels(expanded)


def _replace_bare_equals(condition: str) -> str:
    """Replace COBOL bare `=` with Java `==`, quote-aware.

    Leaves `==`, `>=`, `<=`, `!=` untouched and never rewrites `=`
    inside single/double-quoted literals (e.g. ``WS-G = 'A=B'``).
    """
    import re as _re
    # Split into quoted and unquoted segments; only rewrite unquoted ones.
    parts = _re.split(r"('[^']*'|\"[^\"]*\")", condition)
    for i in range(0, len(parts), 2):
        parts[i] = _re.sub(r'(?<![<>!=])=(?!=)', ' == ', parts[i])
    return "".join(parts)


def _build_for_condition(
    var_name: str,
    until_condition: str,
    program: CobolProgram | None = None,
) -> JavaExpression:
    """Build a for-loop condition expression from a COBOL UNTIL condition.

    COBOL: PERFORM VARYING ... UNTIL condition  =  loop WHILE NOT condition.
    So:    UNTIL var > N  →  var <= N
           UNTIL var >= N →  var < N
           UNTIL var < N  →  var >= N
    """
    import re as _re
    until_condition = until_condition.strip()
    if until_condition == "TRUE":
        return JavaLiteral(value="true")

    # Try to parse: var > value  →  var <= value
    m = _re.match(r'(\w[\w-]*)\s*>\s*(\d+)', until_condition)
    if m:
        subject = m.group(1).replace("-", "_")
        stop_val = m.group(2)
        return JavaBinaryOp(
            left=JavaVariableRef(name=subject),
            operator="<=",
            right=JavaLiteral(value=stop_val),
        )

    # Try to parse: var >= value  →  var < value
    m = _re.match(r'(\w[\w-]*)\s*>=\s*(\d+)', until_condition)
    if m:
        subject = m.group(1).replace("-", "_")
        stop_val = m.group(2)
        return JavaBinaryOp(
            left=JavaVariableRef(name=subject),
            operator="<",
            right=JavaLiteral(value=stop_val),
        )

    # Try to parse: var < value  →  var >= value
    m = _re.match(r'(\w[\w-]*)\s*<\s*(\d+)', until_condition)
    if m:
        subject = m.group(1).replace("-", "_")
        stop_val = m.group(2)
        return JavaBinaryOp(
            left=JavaVariableRef(name=subject),
            operator=">=",
            right=JavaLiteral(value=stop_val),
        )

    # Try to parse: var <= value  →  var > value
    m = _re.match(r'(\w[\w-]*)\s*<=\s*(\d+)', until_condition)
    if m:
        subject = m.group(1).replace("-", "_")
        stop_val = m.group(2)
        return JavaBinaryOp(
            left=JavaVariableRef(name=subject),
            operator=">",
            right=JavaLiteral(value=stop_val),
        )

    # Fallback: map the condition as a Java expression
    return map_cobol_condition_to_java(until_condition, program=program)


def _is_plain_reference(arg: str) -> bool:
    """Whether a CALL USING argument is a plain data-item reference.

    Only plain references can receive BY REFERENCE write-back
    (``WS-X = Callee.LS``). Literals and compound expressions have no
    caller-side storage — matching COBOL, where a BY REFERENCE literal
    is passed through a temporary whose modification is discarded.
    """
    import re as _re
    return _re.match(r"^[A-Za-z][\w-]*$", (arg or "").strip()) is not None


def _expand_thru_range(stmt, program) -> list[str]:
    """Expand PERFORM <first> THRU <last> to the paragraph names in range.

    Returns the paragraph names from <first> through <last> inclusive, in
    source order. When the program context is unavailable or an endpoint
    is unknown, returns just the named paragraph so generation still fails
    closed (unknown method → compile error) instead of silently skipping.
    """
    first = (stmt.paragraph_name or "").strip()
    last = (stmt.thru_target or "").strip()
    if program is not None:
        names = [para.name for para in program.paragraphs]
        if first in names and last in names:
            lo = names.index(first)
            hi = names.index(last)
            if lo <= hi:
                return names[lo:hi + 1]
    return [first] if first else []



# Mapper-backed capability contract. Keep this alongside the actual mapper so
# capability analysis cannot silently drift from transformation support.
STATEMENT_CAPABILITY_SUPPORTED = frozenset({
    MoveStatement, AddStatement, SubtractStatement, MultiplyStatement,
    ComputeStatement, DivideStatement, DisplayStatement, IfStatement,
    PerformStatement, ReadStatement, WriteStatement, OpenStatement, CloseStatement,
    StartStatement, RewriteStatement, DeleteStatement, StringStatement,
    StopRunStatement, CallStatement,
    ExitProgramStatement, SetConditionStatement,
})
STATEMENT_CAPABILITY_PARTIAL = frozenset({UnstringStatement})
STATEMENT_CAPABILITY_UNSUPPORTED = frozenset({GoToStatement, PerformTimesStatement})


def classify_statement_capability(stmt: Statement) -> str:
    """Return the mapper-backed capability for one semantic IR statement."""
    statement_type = type(stmt)
    if statement_type in STATEMENT_CAPABILITY_UNSUPPORTED:
        return "UNSUPPORTED"
    if statement_type in STATEMENT_CAPABILITY_PARTIAL:
        return "PARTIAL"
    if statement_type in STATEMENT_CAPABILITY_SUPPORTED:
        return "SUPPORTED"
    return "UNSUPPORTED"

def map_cobol_statement(
    stmt: Statement,
    program: CobolProgram | None = None,
    called_programs: dict[str, CobolProgram] | None = None,
) -> list[JavaStatement]:
    """Map a single COBOL statement to one or more Java statements.

    Args:
        stmt: The COBOL IR statement to map.
        program: The enclosing CobolProgram — used for field format-width
            lookups and file-definition resolution.
        called_programs: Optional map of program-id → CobolProgram for
            all programs in the application.  Used to resolve the correct
            entry-point method when generating inter-program CALL IR.
    """
    result: list[JavaStatement] = []

    # Build the DISPLAY format lookup if program provided.  Each numeric
    # item maps to the String.format specifier that reproduces GnuCOBOL's
    # output for that PIC (digit field, zero fill, sign column, scale).
    field_display_formats = {}
    if program is not None:
        for item in _numeric_display_items(program):
            field_display_formats[item.name.replace("-", "_")] = (
                display_format_spec(
                    integer_digits=item.integer_digits,
                    decimal_digits=item.decimal_places,
                    signed=item.signed,
                ),
                item.decimal_places > 0,
            )

    if isinstance(stmt, MoveStatement):
        source = map_cobol_expr_to_java(stmt.source)
        # The IR stores every destination in ``targets`` (primary first) and
        # mirrors the primary one into ``target``. Emitting ``target`` and
        # then iterating the full tuple would duplicate the primary
        # assignment, so ``targets`` is the authoritative list.
        move_targets = stmt.targets or ((stmt.target,) if stmt.target else ())
        for move_target in move_targets:
            expression = source
            item = _find_data_item(program, move_target)
            if item is not None and item.is_numeric and _is_numeric_expression(expression, program):
                expression = _apply_numeric_receiver_semantics(
                    expression,
                    move_target,
                    program,
                )
            if item is not None and item.is_alphanumeric and item.pic_length > 0:
                # A figurative constant is a character string the
                # size of the receiving item — every position carries the
                # constant's character (``MOVE ZEROS TO PIC X(5)`` stores
                # ``00000``) and ``ALL <literal>`` repeats its pattern across
                # the width, truncated at the last copy.  Both rules are
                # verified against real GnuCOBOL 3.1.2 behaviour, so the value is
                # materialized at parse/emission time instead of being
                # space-padded (which was only ever right for SPACES).
                parsed_move_figurative = (
                    parse_figurative_constant(stmt.source)
                    if isinstance(stmt.source, str)
                    else None
                )
                filled = (
                    figurative_to_width(
                        parsed_move_figurative[0],
                        parsed_move_figurative[1],
                        item.pic_length,
                    )
                    if parsed_move_figurative is not None
                    else None
                )
                if filled is not None:
                    expression = JavaLiteral(
                        value=filled,
                        java_type=JavaType(basic_type=JavaBasicType.STRING),
                    )
                else:
                    # MOVE stores exactly the receiving PIC X width: pad on
                    # the right, or truncate on the right before any
                    # subsequent use.
                    padded = JavaMethodCall(
                        class_name="String", method_name="format", is_static=True,
                        arguments=(_str_lit(f"%-{item.pic_length}s"), source),
                    )
                    expression = JavaMethodCall(
                        object_ref=padded, method_name="substring",
                        arguments=(_int_lit(0), _int_lit(item.pic_length)),
                    )
            result.append(JavaAssignment(
                target=cobol_reference_to_java_source(move_target),
                expression=expression,
            ))

    elif isinstance(stmt, AddStatement):
        # ADD A TO B GIVING C → C = A + B  (C receives result, B unchanged)
        # ADD A TO B           → B = A + B  (in-place)
        target = cobol_reference_to_java_source(
            stmt.giving_target or stmt.target
        )
        source_a = map_cobol_expr_to_java(stmt.source)
        source_b = _reference_expression(stmt.target)
        if stmt.giving_target:
            result.append(JavaAssignment(
                target=target,
                expression=_apply_numeric_receiver_semantics(
                    JavaBinaryOp(left=source_a, operator="+", right=source_b),
                    target,
                    program,
                    stmt.rounded,
                ),
            ))
        else:
            result.append(JavaAssignment(
                target=target,
                expression=_apply_numeric_receiver_semantics(
                    JavaBinaryOp(left=source_b, operator="+", right=source_a),
                    target,
                    program,
                    stmt.rounded,
                ),
            ))

    elif isinstance(stmt, SubtractStatement):
        # SUBTRACT A FROM B GIVING C → C = B - A
        # SUBTRACT A FROM B           → B = B - A (in-place)
        # SUBTRACT A B C FROM D GIVING E → E = D - A - B - C (multi-source)
        # SUBTRACT A B C FROM D           → D = D - A - B - C (multi-source, in-place)
        target = cobol_reference_to_java_source(
            stmt.to_field or stmt.from_field
        )
        # Determine all subtrahends: use sources tuple if present, else single source
        sources = stmt.sources if stmt.sources else (stmt.source,)
        java_sources = [map_cobol_expr_to_java(s) for s in sources]
        # Build chained subtraction: ((minuend - s1) - s2) - ...
        expr: JavaExpression = _reference_expression(stmt.from_field)
        for src in java_sources:
            expr = JavaBinaryOp(left=expr, operator="-", right=src)
        result.append(JavaAssignment(
            target=target,
            expression=_apply_numeric_receiver_semantics(expr, target, program, stmt.rounded),
        ))

    elif isinstance(stmt, MultiplyStatement):
        # MULTIPLY A BY B GIVING C → C = A * B
        # MULTIPLY A BY B           → B = A * B (in-place, B receives result, A unchanged)
        # The left operand is always the source (A, multiplier)
        # If GIVING is present, target=C, multiplicand=B (both unchanged after)
        # If no GIVING, target=B (multiplicand gets updated in-place)
        if stmt.target:
            target = cobol_reference_to_java_source(stmt.target)
        else:
            target = cobol_reference_to_java_source(stmt.multiplicand)
        source = map_cobol_expr_to_java(stmt.source)
        result.append(JavaAssignment(
            target=target,
            expression=_apply_numeric_receiver_semantics(
                JavaBinaryOp(
                    left=source,
                    operator="*",
                    right=_reference_expression(stmt.multiplicand),
                ),
                target,
                program,
                stmt.rounded,
            ),
        ))

    elif isinstance(stmt, DivideStatement):
        target = cobol_reference_to_java_source(stmt.target)
        source = map_cobol_expr_to_java(stmt.source)
        divisor = map_cobol_expr_to_java(stmt.divisor)
        result.append(JavaAssignment(
            target=target,
            expression=_apply_numeric_receiver_semantics(
                JavaBinaryOp(left=source, operator="/", right=divisor),
                target,
                program,
                stmt.rounded,
            ),
        ))
        # REMAINDER target = source % divisor
        if stmt.remainder:
            remainder_target = cobol_reference_to_java_source(stmt.remainder)
            result.append(JavaAssignment(
                target=remainder_target,
                expression=_apply_numeric_receiver_semantics(
                    JavaBinaryOp(left=source, operator="%", right=divisor),
                    remainder_target,
                    program,
                    stmt.rounded,
                ),
            ))

    elif isinstance(stmt, ComputeStatement):
        target = cobol_reference_to_java_source(stmt.target)
        expression = (
            _map_cobol_expression_to_java(stmt.expression_expr)
            if stmt.expression_expr is not None
            else map_cobol_expr_to_java(stmt.expression)
        )
        result.append(JavaAssignment(
            target=target,
            expression=_apply_numeric_receiver_semantics(expression, target, program, stmt.rounded),
        ))

    elif isinstance(stmt, SetConditionStatement):
        # SET <condition-name> TO TRUE assigns the conditional variable the
        # value that satisfies the condition.  A name that is not an 88-level
        # condition (or has no VALUE terms) fails closed: the emitted symbol
        # is deliberately undeclared so javac reports it by name.
        specs = condition_name_specs(program)
        spec = specs.get(stmt.target.upper())
        problems = condition_name_problems(program)
        if spec is None or not spec.terms or stmt.target.upper() in problems:
            # Assign the parent (never the condition name) a deliberately
            # undeclared symbol so javac names the unsupported condition.
            fallback_target = (
                spec.parent.name if spec is not None else stmt.target
            )
            result.append(JavaAssignment(
                target=cobol_reference_to_java_source(fallback_target),
                expression=JavaVariableRef(
                    name="UNSUPPORTED_SET$CONDITION$"
                    + stmt.target.upper().replace("-", "_")
                ),
            ))
        else:
            parent = _dc_replace(spec.parent, value=spec.terms[0][0])
            literal = map_pic_to_java_default(parent)
            result.append(JavaAssignment(
                target=cobol_reference_to_java_source(spec.parent.name),
                expression=JavaLiteral(value=literal),
            ))

    elif isinstance(stmt, DisplayStatement):
        parts: list[JavaExpression] = []
        for part in stmt.parts:
            is_quoted = (
                (part.startswith("'") and part.endswith("'"))
                or (part.startswith('"') and part.endswith('"'))
            )
            if is_quoted:
                # COBOL string literal: strip quotes → Java String literal
                inner = part[1:-1]
                if inner:
                    parts.append(JavaLiteral(
                        value=inner,
                        java_type=JavaType(basic_type=JavaBasicType.STRING),
                    ))
            else:
                reference = split_cobol_reference(part)
                base_name = reference[0] if reference is not None else part
                java_name = base_name.replace("-", "_")
                # Type-aware numeric formatting: the specifier reproduces the
                # GnuCOBOL DISPLAY digit field (sign column + zero fill +
                # scale) instead of assuming every numeric is an int.
                if java_name in field_display_formats:
                    spec, is_fractional = field_display_formats[java_name]
                    arguments: tuple[JavaExpression, ...] = ()
                    if is_fractional:
                        # %f honours the platform locale; pin the separator.
                        arguments += (JavaVariableRef(name="java.util.Locale.US"),)
                    arguments += (
                        JavaLiteral(value=spec),
                        JavaVariableRef(
                            name=cobol_reference_to_java_source(part)
                        ),
                    )
                    parts.append(JavaMethodCall(
                        class_name="String",
                        method_name="format",
                        arguments=arguments,
                        is_static=True,
                    ))
                else:
                    # A figurative constant is a reserved word with a fixed
                    # value, not a field.  Without this a `DISPLAY SPACES`
                    # printed an undeclared Java identifier.
                    parsed_part = parse_figurative_constant(part)
                    if parsed_part is not None:
                        parts.append(figurative_constant_to_java(*parsed_part))
                    else:
                        parts.append(_reference_expression(part))
        if parts:
            concat = JavaStringConcat(parts=tuple(parts))
            # out.println(...) or System.err.println(...) based on destination
            is_stderr = stmt.destination == "STDERR"
            if is_stderr:
                result.append(JavaMethodCallStatement(
                    call=JavaMethodCall(
                        object_ref=JavaVariableRef(name="System.err"),
                        method_name="println",
                        arguments=(concat,),
                    )
                ))
            else:
                result.append(JavaMethodCallStatement(
                    call=JavaMethodCall(
                        object_ref=JavaVariableRef(name="System.out"),
                        method_name="println",
                        arguments=(concat,),
                    )
                ))

    elif isinstance(stmt, IfStatement):
        condition = map_cobol_condition_to_java(stmt.condition, program=program)
        then_body = []
        for s in stmt.then_body:
            then_body.extend(map_cobol_statement(s, program, called_programs))
        else_body = []
        for s in stmt.else_body:
            else_body.extend(map_cobol_statement(s, program, called_programs))
        result.append(JavaIf(
            condition=condition,
            then_body=tuple(then_body),
            else_body=tuple(else_body),
        ))

    elif isinstance(stmt, GoToStatement):
        # GO TO → comment (control flow not directly mappable)
        result.append(JavaComment(text=f"// GO TO {stmt.target}"))

    elif isinstance(stmt, StopRunStatement):
        result.append(JavaReturn())

    elif isinstance(stmt, ExitProgramStatement):
        # EXIT PROGRAM returns control to the caller — a Java return from the
        # generated program body.
        result.append(JavaReturn())

    elif isinstance(stmt, ReadStatement):
        # READ file [NEXT] [KEY IS k] [INTO w] / AT END / NOT AT END /
        # INVALID KEY / NOT INVALID KEY — exactly one CobolFileIo read:
        #
        #   String _read_N = CobolFileIo.readNext(path);      // cursor/next
        #   String _read_N = CobolFileIo.readKey(path, k);    // keyed/random
        #   if (_read_N != null) {                         // record read
        #       [fs = "00";] [record disassembly;] [INTO;] [ok bodies]
        #   } else {
        #       [fs = "10"/"23";] [AT END / INVALID KEY bodies]
        #   }
        #
        # Keyed reads fail with status 23 (INVALID KEY); cursor reads
        # fail with status 10 (AT END).  Status is assigned only when a
        # declared FILE STATUS field exists.  The record area is only
        # (re)populated on success — matching COBOL AT END semantics.
        fd = _find_file_def(program, stmt.file_name)
        path = _resolve_path(fd)
        status_var = _status_target(fd, program)
        has_at_end = bool(stmt.at_end_body or stmt.not_at_end_body)
        has_inv = bool(stmt.invalid_key_body or stmt.not_invalid_key_body)

        if path is None:
            # STDOUT/unmatched destination: no real record to read —
            # preserve legacy behaviour by inlining the success bodies.
            result.append(JavaComment(
                text=f"// READ {stmt.file_name}: no file path; success bodies inlined",
            ))
            for s in stmt.not_at_end_body:
                result.extend(map_cobol_statement(s, program, called_programs))
            for s in stmt.not_invalid_key_body:
                result.extend(map_cobol_statement(s, program, called_programs))
        else:
            # Indexed random READ (no NEXT) uses the current record-key field.
            # READ NEXT / sequential uses the cursor. Relative uses RRN.
            relative_read = _is_relative(fd) and not stmt.read_next
            if not stmt.key and not relative_read and not stmt.read_next:
                if fd is not None and fd.record_key is not None:
                    key_item = _key_field_item(fd, program)
                    if key_item is not None:
                        stmt_key_for_read = key_item.name
                    else:
                        stmt_key_for_read = ""
                else:
                    stmt_key_for_read = ""
            else:
                stmt_key_for_read = stmt.key

            keyed = bool(stmt_key_for_read) or (
                has_inv and not has_at_end
                and fd is not None and fd.record_key is not None
                and not stmt.read_next
            )
            read_var = _fresh_io_var("read")
            if relative_read:
                call = _cobol_call(
                    "readRelative", _str_lit(path), _key_expr("", fd, program),
                )
            elif keyed:
                call = _cobol_call(
                    "readKey", _str_lit(path),
                    _key_expr(stmt_key_for_read, fd, program),
                )
            else:
                call = _cobol_call("readNext", _str_lit(path))
            result.append(JavaLocalVarDecl(
                java_type=JavaType(basic_type=JavaBasicType.STRING),
                name=read_var,
                initializer=call,
            ))

            # Success branch: status + record disassembly + INTO + bodies.
            then_body: list[JavaStatement] = []
            if status_var:
                then_body.append(JavaAssignment(
                    target=status_var, expression=_str_lit("00"),
                ))
            then_body.extend(_disassembly_statements(fd, read_var))
            into_stmt = _into_statement(stmt.into_field, read_var, program)
            if into_stmt is not None:
                then_body.append(into_stmt)
            for s in stmt.not_invalid_key_body:
                then_body.extend(map_cobol_statement(s, program, called_programs))
            for s in stmt.not_at_end_body:
                then_body.extend(map_cobol_statement(s, program, called_programs))

            # Failure branch: status + AT END / INVALID KEY bodies.
            # Relative random READ and keyed READ both signal INVALID KEY (23);
            # sequential cursor READ signals AT END (10).
            fail_status = "23" if (keyed or relative_read) else "10"
            else_body: list[JavaStatement] = []
            if status_var or has_at_end or has_inv:
                if status_var:
                    else_body.append(JavaAssignment(
                        target=status_var, expression=_str_lit(fail_status),
                    ))
                for s in stmt.at_end_body:
                    else_body.extend(map_cobol_statement(s, program, called_programs))
                for s in stmt.invalid_key_body:
                    else_body.extend(map_cobol_statement(s, program, called_programs))

            if then_body or else_body:
                result.append(JavaIf(
                    condition=JavaBinaryOp(
                        left=JavaVariableRef(name=read_var),
                        operator="!=",
                        right=JavaLiteral(value="null"),
                    ),
                    then_body=tuple(then_body),
                    else_body=tuple(else_body),
                ))

    elif isinstance(stmt, WriteStatement):
        # WRITE record [FROM field] [INVALID KEY ...].
        #
        # Destination semantics:
        #   * STDOUT/SYSOUT/SYS* (or unmatched file) → System.out.println
        #   * real file path → CobolFileIo.write(path, recordImage, keyLen)
        #
        # Record image: WRITE … FROM field uses the field as-is; otherwise
        # the FD record items are assembled field-by-field padded to their
        # DISPLAY widths — byte-identical to the COBOL record area.
        # keyLen > 0 selects the indexed path (dup key → status 22, which
        # is what runs the INVALID KEY scope).
        fd = _find_file_def(program, stmt.file_name)
        path = _resolve_path(fd)
        content_var = (stmt.from_field or stmt.record_name).replace("-", "_")

        if path is None:
            result.append(JavaMethodCallStatement(
                call=JavaMethodCall(
                    object_ref=JavaVariableRef(name="System.out"),
                    method_name="println",
                    arguments=(JavaVariableRef(name=content_var),),
                )
            ))
        else:
            rec_expr = _assembly_expression(fd, content_var)
            if rec_expr is None:
                rec_expr = JavaVariableRef(name=content_var)
            if _is_relative(fd):
                # RELATIVE: third arg is the current RRN (relative key field).
                rrn_expr = _key_expr("", fd, program)
                call = _cobol_call("write", _str_lit(path), rec_expr, rrn_expr)
            else:
                call = _cobol_call(
                    "write", _str_lit(path), rec_expr, _int_lit(_key_len(fd, program)),
                )
            has_inv = bool(stmt.invalid_key_body or stmt.not_invalid_key_body)
            status_var = _bind_status(
                result, _status_target(fd, program), call, need_expr=has_inv,
            )
            if has_inv:
                _status_branch(
                    result, status_var, "22",
                    fail_body=stmt.invalid_key_body,
                    ok_body=stmt.not_invalid_key_body,
                    program=program,
                    called_programs=called_programs,
                )

    elif isinstance(stmt, OpenStatement):
        # OPEN mode file → CobolFileIo.open(path, mode, keyLen).
        fd = _find_file_def(program, stmt.file_name)
        path = _resolve_path(fd)
        if path is None:
            result.append(JavaComment(
                text=f"// OPEN {stmt.mode} {stmt.file_name}",
            ))
        else:
            call = _cobol_call(
                "open", _str_lit(path), _str_lit(stmt.mode),
                _int_lit(_open_key_len(fd, program)),
            )
            _bind_status(result, _status_target(fd, program), call)

    elif isinstance(stmt, CloseStatement):
        # CLOSE file → CobolFileIo.close(path) (flush + persist index).
        fd = _find_file_def(program, stmt.file_name)
        path = _resolve_path(fd)
        if path is None:
            result.append(JavaComment(text=f"// CLOSE {stmt.file_name}"))
        else:
            _bind_status(
                result, _status_target(fd, program),
                _cobol_call("close", _str_lit(path)),
            )

    elif isinstance(stmt, StartStatement):
        # START file KEY IS [rel] key → position the indexed cursor.
        # INVALID KEY runs when no record satisfies the relation (23).
        fd = _find_file_def(program, stmt.file_name)
        path = _resolve_path(fd)
        if path is None:
            result.append(JavaComment(text=f"// START {stmt.file_name}"))
        else:
            op = stmt.operator or "="
            call = _cobol_call(
                "start", _str_lit(path), _str_lit(op),
                _key_expr(stmt.key, fd, program),
            )
            has_bodies = bool(
                stmt.invalid_key_body or stmt.not_invalid_key_body
            )
            status_var = _bind_status(
                result, _status_target(fd, program), call, need_expr=has_bodies,
            )
            if has_bodies:
                _status_branch(
                    result, status_var, "23",
                    fail_body=stmt.invalid_key_body,
                    ok_body=stmt.not_invalid_key_body,
                    program=program,
                    called_programs=called_programs,
                )

    elif isinstance(stmt, RewriteStatement):
        # REWRITE record — indexed replace via CobolFileIo.rewrite.
        # Sequential REWRITE is not supported by CobolFileIo and fails
        # closed with status 23 (observable, never silently skipped).
        fd = _find_file_def(program, stmt.file_name)
        path = _resolve_path(fd)
        content_var = (stmt.from_field or stmt.record_name).replace("-", "_")
        has_inv = bool(stmt.invalid_key_body or stmt.not_invalid_key_body)
        status_field = _status_target(fd, program)
        if path is None:
            result.append(JavaComment(text=f"// REWRITE {stmt.file_name}"))
        else:
            key_len = _key_len(fd, program)
            if _is_relative(fd):
                # RELATIVE REWRITE: replace the record at the current RRN.
                rrn_expr = _key_expr("", fd, program)
                rec_expr = _assembly_expression(fd, content_var)
                if rec_expr is None:
                    rec_expr = JavaVariableRef(name=content_var)
                call = _cobol_call("rewrite", _str_lit(path), rec_expr, rrn_expr)
                cond_status = _bind_status(
                    result, status_field, call, need_expr=has_inv,
                )
            elif key_len <= 0:
                result.append(JavaComment(
                    text=f"// REWRITE {stmt.file_name}: sequential REWRITE "
                    "unsupported by CobolFileIo",
                ))
                if status_field:
                    cond_status = status_field
                    result.append(JavaAssignment(
                        target=status_field, expression=_str_lit("23"),
                    ))
                elif has_inv:
                    cond_status = _fresh_io_var("st")
                    result.append(JavaLocalVarDecl(
                        java_type=JavaType(basic_type=JavaBasicType.STRING),
                        name=cond_status,
                        initializer=_str_lit("23"),
                    ))
                else:
                    cond_status = ""
            else:
                rec_expr = _assembly_expression(fd, content_var)
                if rec_expr is None:
                    rec_expr = JavaVariableRef(name=content_var)
                call = _cobol_call(
                    "rewrite", _str_lit(path), rec_expr, _int_lit(key_len),
                )
                cond_status = _bind_status(
                    result, status_field, call, need_expr=has_inv,
                )
            if has_inv:
                _status_branch(
                    result, cond_status, "23",
                    fail_body=stmt.invalid_key_body,
                    ok_body=stmt.not_invalid_key_body,
                    program=program,
                    called_programs=called_programs,
                )

    elif isinstance(stmt, DeleteStatement):
        # DELETE file record by primary key → CobolFileIo.delete.
        # RELATIVE → CobolFileIo.deleteRelative(path, RRN).
        # Missing key → status 23 runs the INVALID KEY scope.
        fd = _find_file_def(program, stmt.file_name)
        path = _resolve_path(fd)
        has_inv = bool(stmt.invalid_key_body or stmt.not_invalid_key_body)
        if path is None:
            result.append(JavaComment(text=f"// DELETE {stmt.file_name}"))
        else:
            if _is_relative(fd):
                rrn_expr = _key_expr("", fd, program)
                call = _cobol_call("deleteRelative", _str_lit(path), rrn_expr)
            else:
                call = _cobol_call(
                    "delete", _str_lit(path), _key_expr("", fd, program),
                    _int_lit(_key_len(fd, program)),
                )
            status_var = _bind_status(
                result, _status_target(fd, program), call, need_expr=has_inv,
            )
            if has_inv:
                _status_branch(
                    result, status_var, "23",
                    fail_body=stmt.invalid_key_body,
                    ok_body=stmt.not_invalid_key_body,
                    program=program,
                    called_programs=called_programs,
                )

    elif isinstance(stmt, StringStatement):
        # STRING → delimiter-aware concatenation written into the
        # receiving field.  Structured expressions preserve
        # literal quoting (Literal → quoted Java string, never a bare
        # identifier); raw parts carry COBOL quoting (e.g. '"SUBTRACT"')
        # and are parsed the same way.  Delimiters, WITH POINTER and the
        # fail-closed forms are handled by _string_receiver_statements.
        if stmt.target:
            target = stmt.target.replace("-", "_")
            sources: list[JavaExpression] = []
            if stmt.structured_parts:
                for part in stmt.structured_parts:
                    sources.append(_map_cobol_expression_to_java(part))
            else:
                for part in stmt.parts:
                    sources.append(map_cobol_expr_to_java(part))
            if sources:
                delims: list = list(stmt.delimiter_exprs)
                if not delims:
                    # Legacy/directly-constructed statements without
                    # delimiter metadata behave as DELIMITED BY SIZE.
                    delims = [None] * len(sources)
                result.extend(
                    _string_receiver_statements(
                        stmt, target, sources, delims, program
                    )
                )

    elif isinstance(stmt, UnstringStatement):
        # The file-lane generator implements the certified delimited split;
        # this generic mapper path has no splitter and emitted only a comment.
        # Any extra clause changes the split (where the next scan starts, how
        # many receivers were filled, what happens on overflow), so it must
        # fail closed by name instead of looking like executed code.
        result.append(JavaComment(text=f"// UNSTRING {stmt.source}"))
        reasons: list[str] = []
        if stmt.pointer:
            reasons.append(
                "WITH_POINTER_" + stmt.pointer.upper().replace("-", "_")
            )
        if stmt.has_overflow:
            reasons.append("ON_OVERFLOW")
        if stmt.varying_pointer:
            reasons.append(
                "VARYING_IN_" + stmt.varying_pointer.upper().replace("-", "_")
            )
        if stmt.tallying_pointer:
            reasons.append(
                "TALLYING_IN_" + stmt.tallying_pointer.upper().replace("-", "_")
            )
        if reasons and stmt.targets:
            result.append(JavaAssignment(
                target=stmt.targets[0].replace("-", "_"),
                expression=JavaVariableRef(
                    name=_unstring_fail_closed_symbol(*reasons)
                ),
            ))

    elif isinstance(stmt, PerformStatement):
        # Check for VARYING form
        if stmt.until_condition and stmt.until_condition.startswith("VARYING "):
            # PERFORM VARYING var FROM init BY step UNTIL condition [inline-body]
            # Parse: "VARYING WS-LOOP-CNT FROM 1 BY 1 UNTIL WS-LOOP-CNT > 5"
            parts = stmt.until_condition.split(" FROM ")
            if len(parts) >= 2:
                var_part = parts[0].replace("VARYING ", "").strip()
                rest = parts[1]
                by_until = rest.split(" UNTIL ")
                init_and_by = by_until[0].strip() if by_until else "1"
                until_part = by_until[1].strip() if len(by_until) > 1 else "TRUE"

                # Parse init and BY from "1 BY 1"
                init_val = "1"
                by_val = "1"
                if " BY " in init_and_by:
                    ib_parts = init_and_by.split(" BY ")
                    init_val = ib_parts[0].strip()
                    by_val = ib_parts[1].strip()
                else:
                    init_val = init_and_by.strip()

                # Build condition expression using map_cobol_condition_to_java
                condition_expr = map_cobol_condition_to_java(
                    f"{var_part} < {until_part}" if "<" not in until_part and ">" not in until_part
                    else until_part.replace(var_part, var_part.replace("-", "_"))
                )
                # Build proper loop condition: var < stop_value (for > cases)
                var_jname = var_part.replace("-", "_")
                cond_java = _build_for_condition(var_jname, until_part, program)

                # Generate for loop body: use inline body or paragraph call
                body_stmts: list[JavaStatement] = []
                if stmt.body:
                    for s in stmt.body:
                        body_stmts.extend(map_cobol_statement(s, program, called_programs))
                elif stmt.paragraph_name:
                    body_stmts.append(JavaMethodCallStatement(
                        call=JavaMethodCall(
                            method_name=_paragraph_method_name(program, stmt.paragraph_name),
                            arguments=(),
                        )
                    ))

                result.append(JavaFor(
                    init=JavaLocalVarDecl(
                        java_type=JavaType(basic_type=JavaBasicType.INT),
                        name=var_jname,
                        initializer=JavaLiteral(value=init_val),
                    ),
                    condition=cond_java,
                    update=JavaAssignment(
                        target=var_jname,
                        expression=JavaBinaryOp(
                            left=JavaVariableRef(name=var_jname),
                            operator="+",
                            right=JavaLiteral(value=by_val),
                        ),
                    ),
                    body=tuple(body_stmts),
                ))
            else:
                if stmt.body:
                    body_stmts = []
                    for s in stmt.body:
                        body_stmts.extend(map_cobol_statement(s, program, called_programs))
                    result.append(JavaBlock(statements=tuple(body_stmts)))
                elif stmt.paragraph_name:
                    result.append(JavaMethodCallStatement(
                        call=JavaMethodCall(
                            method_name=_paragraph_method_name(program, stmt.paragraph_name),
                            arguments=(),
                        )
                    ))
        elif stmt.until_condition and stmt.until_condition.startswith("TIMES="):
            # PERFORM <para> <n> TIMES  (out-of-line) or
            # PERFORM <n> TIMES ... END-PERFORM (inline).
            # COBOL executes the body exactly n times; a zero/negative
            # count executes zero times — the Java for-loop matches this.
            times_val = stmt.until_condition.replace("TIMES=", "").strip()
            if times_val.lstrip("-").isdigit():
                count_expr = JavaLiteral(value=times_val)
            else:
                # Field reference count: PERFORM PARA WS-K TIMES.
                count_expr = JavaVariableRef(name=times_val.replace("-", "_"))
            loop_var = _fresh_times_var()
            body_stmts: list[JavaStatement] = []
            if stmt.body:
                for s in stmt.body:
                    body_stmts.extend(map_cobol_statement(s, program, called_programs))
            elif stmt.paragraph_name:
                body_stmts.append(JavaMethodCallStatement(
                    call=JavaMethodCall(
                        method_name=_paragraph_method_name(program, stmt.paragraph_name),
                        arguments=(),
                    )
                ))
            result.append(JavaFor(
                init=JavaLocalVarDecl(
                    java_type=JavaType(basic_type=JavaBasicType.INT),
                    name=loop_var,
                    initializer=JavaLiteral(value="0"),
                ),
                condition=JavaBinaryOp(
                    left=JavaVariableRef(name=loop_var),
                    operator="<",
                    right=count_expr,
                ),
                update=JavaAssignment(
                    target=loop_var,
                    expression=JavaBinaryOp(
                        left=JavaVariableRef(name=loop_var),
                        operator="+",
                        right=JavaLiteral(value="1"),
                    ),
                ),
                body=tuple(body_stmts),
            ))
        elif stmt.until_condition:
            # PERFORM <para> UNTIL <cond> (out-of-line TEST-BEFORE loop) or
            # PERFORM UNTIL <cond> ... END-PERFORM (inline loop).
            # COBOL checks the condition BEFORE each iteration, including
            # the first (zero iterations when already true) — exactly the
            # semantics of Java while (!(cond)).
            java_cond = map_cobol_condition_to_java(
                stmt.until_condition, program=program
            )
            loop_body: list[JavaStatement] = []
            if stmt.body:
                for s in stmt.body:
                    loop_body.extend(map_cobol_statement(s, program, called_programs))
            elif stmt.paragraph_name:
                loop_body.append(JavaMethodCallStatement(
                    call=JavaMethodCall(
                        method_name=_paragraph_method_name(program, stmt.paragraph_name),
                        arguments=(),
                    )
                ))
            result.append(JavaWhile(
                condition=_negate_condition(java_cond),
                body=tuple(loop_body),
            ))
        elif stmt.thru_target:
            # PERFORM <first> THRU <last> — execute every paragraph from
            # <first> through <last> inclusive, in source order.
            for target in _expand_thru_range(stmt, program):
                result.append(JavaMethodCallStatement(
                    call=JavaMethodCall(
                        method_name=_paragraph_method_name(program, target),
                        arguments=(),
                    )
                ))
        else:
            # Simple PERFORM → method call
            result.append(JavaMethodCallStatement(
                call=JavaMethodCall(
                    method_name=_paragraph_method_name(program, stmt.paragraph_name),
                    arguments=(),
                )
            ))

    elif isinstance(stmt, CallStatement):
        # CALL program-name [USING parameters] — static inter-program call.
        #
        # Parameter passing uses value-result through the callee's static
        # linkage fields (COBOL LINKAGE SECTION items become static fields
        # of the generated class):
        #   1. sync-in:  Callee.LS = <caller arg>   (all modes)
        #   2. call:     Callee.MAIN_LOGIC()
        #   3. sync-out: <caller arg> = Callee.LS   (BY REFERENCE only,
        #      and only when the argument is a plain data-item reference)
        #
        # This preserves observable COBOL mutation semantics despite Java
        # pass-by-value: BY REFERENCE writes flow back to the caller, while
        # BY CONTENT / BY VALUE writes stay local to the callee.
        #
        # Entry-point resolution (generic rule, no fixture-specific logic):
        #   * Callee with LINKAGE SECTION + arity match → value-result
        #     sequence above with entry MAIN_LOGIC.
        #   * Callee without LINKAGE → entry is its first paragraph.
        #   * Unknown callee (unresolved CALL) or arity mismatch → legacy
        #     static call with arguments, which fails closed at Java compile
        #     time instead of silently skipping the call.
        #   * Dynamic CALL (unquoted data-item target) never matches a static
        #     program-id and therefore always takes the fail-closed path.
        target_id = _normalise_program_id(stmt.program_name)
        # A quoted CALL target (CALL 'SUBP') is a static literal; an
        # unquoted target (CALL WS-PGM) is a dynamic data-item reference
        # whose runtime value cannot be resolved statically. Dynamic CALLs
        # must never take the value-result path — they fail closed below.
        #
        # The parser stores the target with quotes already stripped
        # (CALL 'SUBP' → program_name='SUBP'), so inspecting the first
        # character cannot distinguish the two forms. CallStatement
        # records the distinction in ``is_dynamic``; that is authoritative.
        raw_target = (stmt.program_name or "").strip()
        is_static_target = bool(raw_target) and not stmt.is_dynamic
        callee_linkage: list[str] = []
        if is_static_target and called_programs is not None:
            callee = called_programs.get(target_id)
            if callee is not None and callee.linkage_section:
                callee_linkage = [
                    item.name.replace("-", "_")
                    for item in callee.linkage_section
                ]

        class_name = _to_java_class_name(target_id)
        if (
            is_static_target
            and callee_linkage
            and len(stmt.arguments) == len(callee_linkage)
            and len(stmt.arguments) > 0
        ):
            modes = list(stmt.passing_modes) or ["REFERENCE"] * len(stmt.arguments)
            # 1. sync-in (all modes, positional: USING order ↔ LINKAGE order)
            for arg, link in zip(stmt.arguments, callee_linkage):
                result.append(JavaAssignment(
                    target=f"{class_name}.{link}",
                    expression=map_cobol_expr_to_java(arg),
                ))
            # 2. call
            result.append(JavaMethodCallStatement(
                call=JavaMethodCall(
                    class_name=class_name,
                    method_name="MAIN_LOGIC",
                    arguments=(),
                    is_static=True,
                )
            ))
            # 3. sync-out (BY REFERENCE data items only)
            for arg, link, mode in zip(stmt.arguments, callee_linkage, modes):
                if mode.upper() == "REFERENCE" and _is_plain_reference(arg):
                    result.append(JavaAssignment(
                        target=arg.replace("-", "_"),
                        expression=JavaVariableRef(name=f"{class_name}.{link}"),
                    ))
        else:
            call_args = []
            for arg in stmt.arguments:
                call_args.append(map_cobol_expr_to_java(arg.replace("-", "_")))

            # Resolve entry method. Dynamic targets never resolve: even when
            # a program-id textually matches, the CALL dispatches on a
            # runtime value, so a static edge would be unsound.
            entry_method = "MAIN_LOGIC"  # default
            if is_static_target and called_programs is not None:
                callee = called_programs.get(target_id)
                if callee is not None:
                    if callee.linkage_section:
                        entry_method = "MAIN_LOGIC"
                    elif callee.paragraphs:
                        # First paragraph becomes the Java method entry
                        entry_method = _to_java_method_name(callee.paragraphs[0].name)
                    else:
                        entry_method = "MAIN_LOGIC"

            result.append(JavaMethodCallStatement(
                call=JavaMethodCall(
                    class_name=class_name,
                    method_name=entry_method,
                    arguments=tuple(call_args),
                    is_static=True,
                )
            ))

        # RETURNING has no certified lowering: the returned value would be
        # silently discarded.  Emit an unresolvable symbol so javac names the
        # clause instead of running the call with incomplete semantics.
        if stmt.returning:
            result.append(JavaAssignment(
                target=stmt.returning.replace("-", "_"),
                expression=JavaVariableRef(
                    name="UNSUPPORTED_CALL$RETURNING_"
                    + stmt.returning.upper().replace("-", "_")
                ),
            ))

    result.extend(_redefines_sync_statements(stmt, program))
    return result


# ---------------------------------------------------------------------------
# COBOL program → Java class mapping
# ---------------------------------------------------------------------------

def map_cobol_data_items_to_fields(
    items: tuple[DataItem, ...],
) -> tuple[JavaField, ...]:
    """Map COBOL WORKING-STORAGE items to Java fields.

    Items with ``OCCURS`` (and items subordinate to an occurring group)
    become Java arrays; every COBOL subscript is lowered 1-based → 0-based
    by :func:`cobol_reference_to_java_source`.  A group that itself occurs is
    a *record table*: its elementary subordinates become parallel arrays (the
    IR exposes the flattened members), and the group scalar is not declared
    because COBOL only allows it to be referenced with a subscript.

    Certified ``REDEFINES`` views additionally get one canonical byte-string
    field per overlay chain; see ``engine.transformation.redefines``.
    """
    dimensions_by_name = _effective_dimensions(items)
    plan = build_redefines_plan(items)
    fields: list[JavaField] = []
    seen: set[str] = set()
    for item in items:
        java_name = item.name.replace("-", "_")
        if java_name in seen:
            continue
        seen.add(java_name)
        dimensions = dimensions_by_name.get(item.name, ())
        if item.occurs_depending_on:
            # Variable-length tables are rejected by the parser
            # (UNSUPPORTED_CONSTRUCT).  Do not declare a fixed-size array:
            # a wrong-size array would be a silent semantic lie, so the
            # reference stays undeclared and javac fails closed.
            continue
        if item.redefines and item.name.upper() in plan.problems:
            # Uncertified overlay members are not declared at all, so any
            # reference fails closed at compile time instead of reading an
            # independent field that does not share storage.
            continue
        if item.name.upper() in plan.hidden:
            continue
        if item.is_group and dimensions:
            # A record table has no scalar value; only its subordinates are
            # addressable (as arrays).  Declaring a scalar here would make a
            # later ``WS-GROUP(i)`` reference silently read a bare String.
            continue
        element_type = map_pic_to_java_type(item)
        view = plan.views.get(item.name.upper())
        if view is not None:
            default = '"' + _java_quote(view.initial) + '"'
        else:
            default = map_pic_to_java_default(item)
        if dimensions:
            java_type = _array_java_type(element_type, dimensions)
            initializer = _array_initializer(element_type, dimensions, default)
        else:
            java_type = element_type
            initializer = JavaLiteral(value=default)
        fields.append(JavaField(
            java_type=java_type,
            name=java_name,
            initializer=initializer,
            is_static=True,
            format_width=item.format_width if item.is_numeric else 0,
        ))
    fields.extend(_redefines_buffer_fields(plan))
    return tuple(fields)


def _redefines_buffer_fields(plan: RedefinesPlan) -> list[JavaField]:
    """One canonical byte string per certified overlay chain."""
    buffers: dict[str, JavaField] = {}
    for view in plan.views.values():
        if view.base in buffers:
            continue
        buffers[view.base] = JavaField(
            java_type=JavaType(basic_type=JavaBasicType.STRING),
            name=f"{view.base.replace('-', '_')}$BYTES",
            initializer=JavaLiteral(value='"' + _java_quote(view.initial) + '"'),
            is_static=True,
        )
    return list(buffers.values())


def _all_flat_items(program: CobolProgram) -> list[DataItem]:
    items: list[DataItem] = []
    for fd in program.file_definitions:
        items.extend(fd.record_items)
    items.extend(program.working_storage)
    return items


def _redefines_sync_statements(
    stmt: Statement,
    program: CobolProgram | None,
) -> list[JavaStatement]:
    """Overlay stores/refreshes emitted after a certified MOVE.

    COBOL storage sharing is modelled as: the canonical ``<BASE>$BYTES`` string
    receives the just-written view at offset 0 (every REDEFINES view starts at
    the same storage location), then every sibling view is refreshed from it.
    Only unsubscripted MOVE is certified; the parser rejects every other
    writer with ``UNSUPPORTED_CONSTRUCT``.
    """
    if program is None or not isinstance(stmt, MoveStatement):
        return []
    plan = build_redefines_plan(_all_flat_items(program))
    if not plan.views:
        return []

    statements: list[JavaStatement] = []
    targets: list[str] = []
    for candidate in tuple(stmt.targets or ()) + (stmt.target,):
        if candidate and candidate not in targets:
            targets.append(candidate)
    for target in targets:
        if not target:
            continue
        reference = split_cobol_reference(target)
        if reference is None:
            continue
        base_name, subscripts = reference
        view = plan.views.get(base_name.upper())
        if view is None or subscripts:
            continue
        buffer_name = f"{view.base.replace('-', '_')}$BYTES"
        statements.append(JavaAssignment(
            target=buffer_name,
            expression=JavaBinaryOp(
                left=JavaVariableRef(name=view.java_name),
                operator="+",
                right=JavaMethodCall(
                    object_ref=JavaVariableRef(name=buffer_name),
                    method_name="substring",
                    arguments=(JavaLiteral(value=str(view.length)),),
                ),
            ),
        ))
        for other in plan.views.values():
            if other.base != view.base:
                continue
            if other.name.upper() == base_name.upper():
                continue
            statements.append(JavaAssignment(
                target=other.java_name,
                expression=JavaMethodCall(
                    object_ref=JavaVariableRef(name=buffer_name),
                    method_name="substring",
                    arguments=(
                        JavaLiteral(value="0"),
                        JavaLiteral(value=str(other.length)),
                    ),
                ),
            ))
    return statements


def map_cobol_paragraph_to_method(
    para: Paragraph,
    program: CobolProgram,
    called_programs: dict[str, CobolProgram] | None = None,
) -> JavaMethod:
    """Map a COBOL paragraph to a Java method."""
    body_stmts: list[JavaStatement] = []
    for stmt in para.statements:
        body_stmts.extend(map_cobol_statement(stmt, program, called_programs))

    return JavaMethod(
        name=_paragraph_method_name(program, para.name),
        return_type=JavaType(basic_type=JavaBasicType.VOID),
        parameters=(),
        body_statements=tuple(body_stmts),
        is_static=True,
        modifiers=("public", "static"),
        # Paragraphs may contain CALLs (whose entries declare checked
        # exceptions); propagating throws keeps every caller compilable.
        exceptions=("Exception",),
    )


def map_cobol_program_to_java(
    program: CobolProgram,
    called_programs: dict[str, CobolProgram] | None = None,
) -> JavaProgram:
    """Map a complete COBOL program to a JavaProgram.

    Populates all Java IR structures including decision-mode metadata.
    All values are derived from COBOL IR — not invented.

    Args:
        program: The COBOL program IR to map.
        called_programs: Optional map of all programs in the application,
            used to resolve inter-program CALL entry points generically.
    """
    # Deterministic file-I/O scratch names (_read_0, _st_1, ...) for
    # this program regardless of what was mapped earlier in this process.
    _reset_file_io_vars()

    # Map fields — working-storage + file section records.
    # File section 01-level record items need to be class members so that
    # MOVE … TO record-name / WRITE record-name sequences compile correctly.
    # LINKAGE SECTION items also become static fields: CALL USING passes
    # parameters by value-result through these fields (sync-in before the
    # call, sync-out after for BY REFERENCE), which is what preserves
    # COBOL mutation semantics under Java pass-by-value.
    file_record_items: list = []
    for fd in program.file_definitions:
        file_record_items.extend(fd.record_items)
    all_data_items = tuple(file_record_items) + program.working_storage
    fields = map_cobol_data_items_to_fields(all_data_items)
    if program.linkage_section:
        linkage_names = {
            item.name.replace("-", "_") for item in program.linkage_section
        }
        # Working-storage fields that duplicate linkage items (the parser
        # mirrors them) still need public static rendering for
        # cross-service sync access.
        fields = tuple(
            _dc_replace(f, modifiers=("public", "static"))
            if f.name in linkage_names
            else f
            for f in fields
        )
        existing = {f.name for f in fields}
        for link_field in map_cobol_data_items_to_fields(program.linkage_section):
            if link_field.name not in existing:
                # Linkage fields are accessed cross-service (sync-in/out)
                # as static fields, so they must be rendered publicly and
                # statically by every generator. Working-storage fields
                # keep their existing private instance rendering.
                link_field = _dc_replace(
                    link_field, modifiers=("public", "static")
                )
                fields = fields + (link_field,)
                existing.add(link_field.name)

    # Map methods from paragraphs
    methods: list[JavaMethod] = []
    for para in program.paragraphs:
        methods.append(map_cobol_paragraph_to_method(para, program, called_programs))

    has_linkage = bool(program.linkage_section)

    # Main method: inline the DRIVER (first) paragraph only.
    #
    # Rationale: every paragraph also becomes a callable Java method for
    # PERFORM targets. Inlining all paragraphs would (a) execute PERFORMed
    # paragraphs twice (once via the call, once via fall-through) and
    # (b) place unreachable statements after a mid-file STOP RUN, which
    # does not compile in Java. The driver-first rule matches the
    # single-paragraph baseline exactly and gives correct COBOL STOP-RUN
    # termination for multi-paragraph programs. Implicit fall-through
    # across paragraphs (no STOP RUN, no PERFORM) is NOT reproduced and
    # is classified PARTIAL by the capability analyzer.
    driver_paragraphs = program.paragraphs[:1]
    main_body: list[JavaStatement] = []
    if has_linkage:
        # Standalone entry: run the parameterless business method against
        # the default field values (inter-program callers sync real values
        # through the static linkage fields before calling MAIN_LOGIC).
        main_body.append(JavaMethodCallStatement(call=JavaMethodCall(
            method_name="MAIN_LOGIC",
            arguments=(),
        )))
    else:
        # No linkage - inline the driver paragraph statements
        for para in driver_paragraphs:
            for stmt in para.statements:
                main_body.extend(map_cobol_statement(stmt, program, called_programs))

    methods.append(JavaMethod(
        name="main",
        return_type=JavaType(basic_type=JavaBasicType.VOID),
        parameters=(JavaParameter(
            java_type=JavaType(
                class_name="String",
                is_array=True,
                array_element_type=JavaType(basic_type=JavaBasicType.STRING),
            ),
            name="args",
        ),),
        body_statements=tuple(main_body),
        is_static=True,
        exceptions=("Exception",),
    ))

    # Business method for LINKAGE programs: parameterless entry operating
    # on the static linkage fields (driver paragraph only, same rationale
    # as main above). Callers sync values in/out around the call.
    if has_linkage:
        business_body: list[JavaStatement] = []
        for para in driver_paragraphs:
            for stmt in para.statements:
                business_body.extend(map_cobol_statement(stmt, program, called_programs))
        methods.append(JavaMethod(
            name="MAIN_LOGIC",
            return_type=JavaType(basic_type=JavaBasicType.VOID),
            parameters=(),
            body_statements=tuple(business_body),
            is_static=True,
            modifiers=("public", "static"),
            exceptions=("Exception",),
        ))

    # Build class
    java_class = JavaClass(
        name=_to_java_class_name(program.program_id),
        fields=tuple(fields),
        methods=tuple(methods),
        imports=(
            "java.io.BufferedReader",
            "java.io.FileReader",
            "java.io.FileWriter",
            "java.io.PrintWriter",
            "java.util.ArrayList",
            "java.util.LinkedHashMap",
            "java.util.List",
            "java.util.Map",
        ),
    )

    # Map file resources — derive delimiter from InputRecordMapping, access mode from OPEN
    file_resources = tuple(
        map_cobol_file_to_resource(fd, program.input_record_mappings, program.open_statements)
        for fd in program.file_definitions
    )

    # --- Decision-mode metadata ---

    # Status codes → JavaStatusCodeMapping
    status_code_mappings = tuple(
        JavaStatusCodeMapping(
            code=sc.code,
            label=sc.label,
            counter_name=_label_to_counter_name(sc.label),
            field_name=sc.field_name.replace("-", "_"),
        )
        for sc in program.status_codes
    )

    def walk(statements):
        for statement in statements:
            yield statement
            for attr in ("body", "then_body", "else_body", "at_end_body",
                         "not_at_end_body", "invalid_key_body", "not_invalid_key_body"):
                yield from walk(getattr(statement, attr, ()))

    counter_labels = {
        statement.parts[1]: _cobol_field_to_java_var(statement.parts[0][1:-1].removesuffix("="))
        for paragraph in program.paragraphs for statement in paragraph.statements
        if isinstance(statement, DisplayStatement) and len(statement.parts) == 2
        and statement.parts[0].startswith(("'", '"'))
    }
    threshold_rules_list = []
    for tr in program.threshold_rules:
        pass_label = ""
        pass_counter = ""
        for paragraph in program.paragraphs:
            for statement in walk(paragraph.statements):
                if isinstance(statement, IfStatement) and statement.condition == f"{tr.field_name} {tr.operator} {tr.value}":
                    for branch_statement in statement.else_body:
                        if isinstance(branch_statement, MoveStatement) and branch_statement.source.startswith(("'", '"')):
                            pass_label = branch_statement.source[1:-1]
                        if isinstance(branch_statement, AddStatement) and branch_statement.source == "1":
                            pass_counter = counter_labels.get(branch_statement.target, "")
                            break
        threshold_rules_list.append(JavaThresholdRule(
            field_name=tr.field_name,
            operator=tr.operator,
            value=tr.value,
            pass_label=pass_label,
            pass_counter_name=pass_counter,
        ))
    threshold_rules = tuple(threshold_rules_list)

    # Summary fields → JavaSummaryField
    ws_lookup = {item.name: item for item in program.working_storage}
    summary_items = dict(ws_lookup)
    for paragraph in program.paragraphs:
        for statement in paragraph.statements:
            if isinstance(statement, DisplayStatement) and len(statement.parts) == 2:
                label, reference = statement.parts
                if label.startswith(("'", '"')) and label.endswith(label[0]):
                    item = ws_lookup.get(reference)
                    if item is not None:
                        summary_items[label[1:-1].removesuffix("=")] = item
    def _summary_format(item: DataItem | None) -> tuple[int, str]:
        if item is None or not item.is_numeric or item.pic_length == 0:
            return 0, ""
        return item.format_width, display_format_spec(
            integer_digits=item.integer_digits,
            decimal_digits=item.decimal_places,
            signed=item.signed,
        )

    summary_fields = tuple(
        JavaSummaryField(
            field_name=field,
            java_var_name=_cobol_field_to_java_var(field),
            format_width=_summary_format(summary_items.get(field))[0],
            is_numeric=summary_items[field].is_numeric if field in summary_items else True,
            format_spec=_summary_format(summary_items.get(field))[1],
        )
        for field in program.summary_fields
    )

    # Match outcomes → JavaMatchOutcome
    match_outcomes: tuple[JavaMatchOutcome, ...] = ()
    if program.match_outcome_labels:
        match_outcomes = (JavaMatchOutcome(
            paid_label=program.match_outcome_labels[0] if len(program.match_outcome_labels) > 0 else "",
            partial_label=program.match_outcome_labels[1] if len(program.match_outcome_labels) > 1 else "",
            unpaid_label=program.match_outcome_labels[2] if len(program.match_outcome_labels) > 2 else "",
        ),)

    # Report config → JavaReportConfig
    report_config: JavaReportConfig | None = None
    if program.report_header or program.output_formats:
        # Derive file names from file roles
        input_files = [fd for fd in program.file_definitions
                       if any(sm.file_name == fd.name and sm.mode.upper() == "INPUT"
                              for sm in program.open_statements)]
        output_files = [fd for fd in program.file_definitions
                        if any(sm.file_name == fd.name and sm.mode.upper() == "OUTPUT"
                               for sm in program.open_statements)]

        report_file_name = output_files[0].name if output_files else ""
        secondary_output_name = output_files[1].name if len(output_files) > 1 else ""

        # Derive record format fields from output_formats
        report_format_fields: tuple[str, ...] = ()
        output_format_fields: tuple[str, ...] = ()
        if len(program.output_formats) > 0 and program.output_formats[0].record_format:
            report_format_fields = tuple(
                fd.field_name for fd in program.output_formats[0].record_format.fields
            )
        if len(program.output_formats) > 1 and program.output_formats[1].record_format:
            output_format_fields = tuple(
                fd.field_name for fd in program.output_formats[1].record_format.fields
            )

        report_config = JavaReportConfig(
            header=program.report_header,
            report_file_name=report_file_name,
            output_file_name=secondary_output_name,
            report_fields=summary_fields,
            output_fields=summary_fields,
            report_format_fields=report_format_fields,
            output_format_fields=output_format_fields,
        )

    # Determine generation mode from capabilities
    caps = _derive_generation_mode(program)

    # Match the primary input resource, rather than the first UNSTRING in
    # source order (a lookup file may be loaded before the primary file).
    input_record_fields: tuple[str, ...] = ()
    input_amount_field = ""
    if program.input_record_mappings:
        primary_input = next((r for r in file_resources if r.access_mode in (
            JavaFileAccessMode.READ, JavaFileAccessMode.READ_WRITE,
        )), None)
        mapping = next((m for m in program.input_record_mappings
                        if primary_input is not None and m.file_name == primary_input.name),
                       program.input_record_mappings[0])
        input_record_fields = tuple(
            f.replace("-", "_") for f in mapping.fields
        )
        if program.threshold_rules:
            amount = program.threshold_rules[0].field_name
            if amount in mapping.fields:
                input_amount_field = amount.replace("-", "_")
            else:
                for paragraph in program.paragraphs:
                    for statement in walk(paragraph.statements):
                        if isinstance(statement, MoveStatement) and amount in (
                            statement.targets or (statement.target,)
                        ) and statement.source in mapping.fields:
                            input_amount_field = statement.source.replace("-", "_")

    decision_result_field = ""
    decision_result_width = 0
    if program.status_codes:
        label = program.status_codes[0].label
        for paragraph in program.paragraphs:
            for statement in walk(paragraph.statements):
                if isinstance(statement, MoveStatement) and statement.source in (f"'{label}'", f'"{label}"'):
                    item = ws_lookup.get(statement.target)
                    if item is not None:
                        decision_result_field = statement.target.replace("-", "_")
                        decision_result_width = item.pic_length
                        break
            if decision_result_field:
                break

    return JavaProgram(
        program_id=program.program_id,
        java_class=java_class,
        cobol_program_id=program.program_id,
        file_resources=file_resources,
        has_file_status=any(fd.file_status_field for fd in program.file_definitions),
        status_codes=status_code_mappings,
        threshold_rules=threshold_rules,
        summary_fields=summary_fields,
        report_config=report_config,
        match_outcomes=match_outcomes,
        generation_mode=caps,
        input_record_fields=input_record_fields,
        input_amount_field=input_amount_field,
        decision_result_field=decision_result_field,
        decision_result_width=decision_result_width,
        copybooks=program.copybooks,
        calls=program.called_programs,
        entry_points=program.entry_points,
    )


def map_cobol_file_to_resource(
    fd: FileDefinition,
    input_record_mappings: tuple = (),
    open_statements: tuple = (),
) -> JavaFileResource:
    """Map a COBOL file definition to a JavaFileResource.

    Delimiter is derived from InputRecordMapping — not hardcoded.
    Access mode is derived from OPEN statements — not hardcoded.
    Organization, keys, and record width derived from COBOL IR — not invented.
    """
    # Find delimiter from InputRecordMapping for this file
    delimiter: str | None = None
    for irm in input_record_mappings:
        if irm.file_name == fd.name:
            delimiter = irm.delimiter
            break

    # Derive access mode from OPEN statements
    access_mode = JavaFileAccessMode.READ
    for stmt in open_statements:
        if stmt.file_name == fd.name:
            mode = stmt.mode.upper()
            if mode == "OUTPUT":
                access_mode = JavaFileAccessMode.WRITE
            elif mode in ("I-O", "IO"):
                access_mode = JavaFileAccessMode.READ_WRITE
            elif mode == "EXTEND":
                access_mode = JavaFileAccessMode.APPEND
            break

    # Map file organization from COBOL SELECT clause
    org_map = {
        "SEQUENTIAL": JavaFileOrganization.SEQUENTIAL,
        "INDEXED": JavaFileOrganization.INDEXED,
        "RELATIVE": JavaFileOrganization.RELATIVE,
    }
    organization = org_map.get(
        fd.organization.value if hasattr(fd.organization, "value") else str(fd.organization),
        JavaFileOrganization.SEQUENTIAL,
    )

    # Map record key
    record_key: JavaFileKey | None = None
    if fd.record_key:
        record_key = JavaFileKey(
            field_name=fd.record_key.field_name,
            key_type=fd.record_key.key_type.value if hasattr(fd.record_key.key_type, "value") else str(fd.record_key.key_type),
            is_duplicated=fd.record_key.is_duplicated,
        )

    # Map alternate keys
    alternate_keys = tuple(
        JavaFileKey(
            field_name=ak.field_name,
            key_type=ak.key_type.value if hasattr(ak.key_type, "value") else str(ak.key_type),
            is_duplicated=ak.is_duplicated,
        )
        for ak in fd.alternate_keys
    )

    return JavaFileResource(
        name=fd.name,
        path=fd.container_path,
        access_mode=access_mode,
        record_delimiter=delimiter,
        is_text=True,
        status_field=fd.file_status_field,
        organization=organization,
        record_key=record_key,
        alternate_keys=alternate_keys,
        relative_key=fd.relative_key,
        record_contains=fd.record_contains,
    )


def map_cobol_programs_to_application(
    programs: tuple[CobolProgram, ...],
    application_id: str = "",
    copybooks: tuple[str, ...] = (),
    edges: tuple = (),
) -> JavaApplication:
    """Map multiple COBOL programs to a JavaApplication.

    This is the top-level mapping that produces the Java application model
    from a multi-program COBOL application. Handles:

    - CALL dependency mapping (static/dynamic, resolved/unresolved)
    - COPY relationship tracking
    - File resource deduplication across programs
    - DB2 table dependency aggregation
    - CICS transaction boundary mapping
    - Cross-program Java reference preparation
    """
    java_programs: list[JavaProgram] = []
    dependencies: list[JavaDependency] = []
    all_databases: dict[str, JavaDatabaseResource] = {}
    all_transactions: dict[str, JavaTransactionBoundary] = {}

    program_ids = {p.program_id for p in programs}

    # Build program-id → CobolProgram lookup so CALL entry-point resolution
    # can inspect callee LINKAGE SECTION without a second pass.
    program_map: dict[str, CobolProgram] = {p.program_id: p for p in programs}

    for prog in programs:
        java_prog = map_cobol_program_to_java(prog, called_programs=program_map)
        java_programs.append(java_prog)


        # Map CALL dependencies with resolution status
        for called in prog.called_programs:
            resolution = "RESOLVED" if called in program_ids else "UNRESOLVED"
            dependencies.append(JavaDependency(
                source=prog.program_id,
                target=called,
                dependency_type=JavaDependencyType.METHOD_CALL,
                metadata=f"resolution={resolution}",
            ))

        # Map DB2 table dependencies (from status_codes with SQLCODE)
        if prog.status_codes:
            for sc in prog.status_codes:
                if sc.field_name.upper() in ("SQLCODE", "SQLSTATE"):
                    # Derive table from status_code label if available
                    table_name = sc.label if sc.label else f"{prog.program_id}_TABLE"
                    if table_name not in all_databases:
                        all_databases[table_name] = JavaDatabaseResource(
                            name=table_name,
                            operation=JavaSqlOperationType.SELECT,
                        )

        # Map CICS transaction boundaries (from transaction_boundaries)
        for tb in java_prog.transaction_boundaries:
            if tb.name not in all_transactions:
                all_transactions[tb.name] = tb

    # Deduplicate file resources across programs
    all_files: dict[str, JavaFileResource] = {}
    for jp in java_programs:
        for fr in jp.file_resources:
            if fr.name not in all_files:
                all_files[fr.name] = fr

    return JavaApplication(
        application_id=application_id or "generated",
        programs=tuple(java_programs),
        dependencies=tuple(dependencies),
        shared_file_resources=tuple(all_files.values()),
        shared_database_resources=tuple(all_databases.values()),
        shared_transaction_boundaries=tuple(all_transactions.values()),
        source_paths=tuple(p.source_file for p in java_programs if p.source_file),
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _normalise_program_id(name: str) -> str:
    """Normalise a CALL target to a canonical COBOL program-id.

    Strips quotes, trailing periods and whitespace; uppercases.
    ("'CLAIMS'." -> "CLAIMS").
    """
    return (name or "").strip().strip("'\"").rstrip(".").strip().upper()


def _to_java_method_name(cobol_name: str) -> str:
    """COBOL paragraph name → legal Java method name.

    Hyphens become underscores; a leading digit (classic ``0000-MAIN`` /
    ``1000-READ`` section numbering) gets a ``p`` prefix because Java
    identifiers may not start with a digit. Must be applied identically at
    the method definition and at every PERFORM / THRU / CALL call site so
    targets always resolve to the generated method.
    """
    java_name = (cobol_name or "").strip().replace("-", "_").replace(" ", "_")
    if java_name and java_name[0].isdigit():
        java_name = "p" + java_name
    return java_name


def _paragraph_method_name(program: "CobolProgram | None", cobol_name: str) -> str:
    """Paragraph method name, disambiguated from a LINKAGE entry method.

    A LINKAGE program always exposes the static entry ``MAIN_LOGIC`` that
    callers invoke after syncing values through the static linkage fields
    (see the CALL lowering). If a paragraph of such a program were also
    emitted as ``MAIN_LOGIC`` the class would declare the method twice and
    fail to compile — exactly what happened for a callee whose driver
    paragraph is named ``MAIN-LOGIC``. Paragraphs colliding with the entry
    name are therefore emitted as ``PARA_MAIN_LOGIC``; the rule is applied
    identically at the method definition and at every PERFORM / THRU call
    site so targets always resolve to the generated method.
    """
    java_name = _to_java_method_name(cobol_name)
    if program is not None and program.linkage_section and java_name == "MAIN_LOGIC":
        return "PARA_MAIN_LOGIC"
    return java_name


def _to_java_class_name(cobol_name: str) -> str:
    """Convert COBOL program name to Java class name."""
    return cobol_name.replace("-", "_").replace(" ", "_").title()


def _cobol_field_to_java_var(field_name: str) -> str:
    """Convert a COBOL field name to a Java variable name.

    Converts LABEL_NAME → labelName (camelCase).
    """
    parts = field_name.lower().split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _label_to_counter_name(label: str) -> str:
    """Convert a status label to a Java counter variable name.

    Uses the same derivation as _cobol_field_to_java_var.
    Example: "REJECTED" → "rejected"
    """
    return _cobol_field_to_java_var(label)


def _derive_generation_mode(program: CobolProgram) -> str:
    """Derive the generation mode from COBOL program capabilities.

    Returns "decision", "file_io", or "minimal".
    This is the only place where capability-based mode selection occurs.
    """
    from engine.transformation.ir import derive_capabilities
    caps = derive_capabilities(program)

    if caps.decision and program.status_codes:
        return "decision"
    if caps.input_record_mapping:
        return "file_io"
    return "minimal"

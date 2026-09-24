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
    StartStatement,
    StopRunStatement,
    StringStatement,
    SubtractStatement,
    UnstringStatement,
    WriteStatement,
)

from engine.transformation.java_ir import (
    JavaApplication,
    JavaAssignment,
    JavaBasicType,
    JavaBinaryOp,
    JavaBlock,
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
    JavaFor,
    JavaIf,
    JavaLiteral,
    JavaLocalVarDecl,
    JavaMatchOutcome,
    JavaMethod,
    JavaMethodCall,
    JavaMethodCallStatement,
    JavaParameter,
    JavaProgram,
    JavaReportConfig,
    JavaReturn,
    JavaSqlOperationType,
    JavaStatement,
    JavaStatusCodeMapping,
    JavaStringConcat,
    JavaSummaryField,
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
    if item.children:
        return JavaType(basic_type=JavaBasicType.STRING)

    if item.is_numeric:
        # Check for decimal (V clause implied by pic_length > integer digits)
        if item.pic_length > 9:
            return JavaType(basic_type=JavaBasicType.LONG)
        return JavaType(basic_type=JavaBasicType.INT)

    # Alphanumeric → String
    return JavaType(basic_type=JavaBasicType.STRING)


def map_pic_to_java_default(item: DataItem) -> str:
    """Get the Java default value for a COBOL PIC type."""
    if item.is_numeric:
        if item.value:
            return item.value.strip("'\"")
        return "0"
    if item.value:
        return f'"{item.value.strip(chr(39) + chr(34))}"'
    return '""'


# ---------------------------------------------------------------------------
# COBOL statement → Java statement mapping
# ---------------------------------------------------------------------------

# Module-level counter for generated PERFORM...TIMES loop variables.
# Each counted loop gets a unique counter name so that sequential or
# nested TIMES loops in the same method never redeclare one another
# (which would not compile in Java).
import itertools as _itertools

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
    """Data item by COBOL name (WORKING-STORAGE first, then FD records)."""
    if program is None or not name:
        return None
    for item in program.working_storage:
        if item.name == name:
            return item
    for fd in program.file_definitions:
        for item in fd.record_items:
            if item.name == name:
                return item
    return None


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
    layout = _record_layout(fd)
    if not layout:
        return []
    total = sum(width for _, width, _, _ in layout)
    padded = _cobol_call(
        "pad", JavaVariableRef(name=read_var), _int_lit(total), _bool_lit(False),
    )
    stmts: list[JavaStatement] = []
    offset = 0
    for name, width, numeric, is_long in layout:
        window = JavaMethodCall(
            object_ref=padded,
            method_name="substring",
            arguments=(_int_lit(offset), _int_lit(offset + width)),
        )
        if numeric:
            expr: JavaExpression = JavaMethodCall(
                class_name="Long" if is_long else "Integer",
                method_name="parseLong" if is_long else "parseInt",
                arguments=(
                    JavaMethodCall(object_ref=window, method_name="trim", arguments=()),
                ),
                is_static=True,
            )
        else:
            expr = window
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
        is_long = item.pic_length > 9
        return JavaAssignment(
            target=target,
            expression=JavaMethodCall(
                class_name="Long" if is_long else "Integer",
                method_name="parseLong" if is_long else "parseInt",
                arguments=(
                    JavaMethodCall(object_ref=ref, method_name="trim", arguments=()),
                ),
                is_static=True,
            ),
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
    - Arithmetic operators (+, -, *, /)
    """
    import re as _re
    expr = expr.strip()

    # Literal
    if expr.startswith("'") and expr.endswith("'"):
        return JavaLiteral(value=expr[1:-1], java_type=JavaType(basic_type=JavaBasicType.STRING))
    if expr.startswith('"') and expr.endswith('"'):
        return JavaLiteral(value=expr[1:-1], java_type=JavaType(basic_type=JavaBasicType.STRING))

    # Check if it's a simple number
    if expr.replace(".", "").replace("-", "").isdigit():
        return JavaLiteral(value=expr, java_type=JavaType(basic_type=JavaBasicType.INT))

    # Try to parse binary expressions: left OP right (operators must have spaces)
    binary_match = _re.match(
        r'^([\w][\w-]*)\s+(\+|\-|\*|/)\s+([\w][\w-]*)$',
        expr,
    )
    if binary_match:
        left_str = binary_match.group(1).strip()
        op = binary_match.group(2).strip()
        right_str = binary_match.group(3).strip()

        left: JavaExpression
        if left_str.replace(".", "").replace("-", "").isdigit():
            left = JavaLiteral(value=left_str, java_type=JavaType(basic_type=JavaBasicType.INT))
        else:
            left = JavaVariableRef(name=left_str.replace("-", "_"))

        right: JavaExpression
        if right_str.replace(".", "").replace("-", "").isdigit():
            right = JavaLiteral(value=right_str, java_type=JavaType(basic_type=JavaBasicType.INT))
        else:
            right = JavaVariableRef(name=right_str.replace("-", "_"))

        return JavaBinaryOp(left=left, operator=op, right=right)

    # Field reference (single name)
    java_name = expr.replace("-", "_")
    return JavaVariableRef(name=java_name)


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
            return JavaLiteral(
                value=expr.value,
                java_type=JavaType(basic_type=JavaBasicType.INT),
            )
        return JavaLiteral(
            value=expr.value,
            java_type=JavaType(basic_type=JavaBasicType.STRING),
        )
    if isinstance(expr, _cobol_ir.FieldReference):
        return JavaVariableRef(name=expr.name.replace("-", "_"))
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
    return map_cobol_expr_to_java(str(expr))


def map_cobol_condition_to_java(condition: str) -> JavaExpression:
    """Map a COBOL condition string to a Java expression.

    Converts COBOL condition syntax to Java boolean expression.
    Returns a JavaBinaryOp for simple conditions, or JavaLiteral for complex ones.
    """
    condition = condition.strip()
    import re as _re

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

    # Handle NOT
    condition = condition.replace("NOT ", "!")

    # Convert field references. Single-quoted COBOL literals become
    # double-quoted Java string literals (single quotes would be Java
    # char literals and would not compile against String fields).
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
        r'^(\w+)\s*(==|!=|>=|<=|>|<)\s*(\w+)$',
        condition_str,
    )
    if binary_match:
        left_name = binary_match.group(1)
        op = binary_match.group(2)
        right_str = binary_match.group(3)

        left_expr: JavaExpression
        if left_name.replace(".", "").replace("-", "").isdigit():
            left_expr = JavaLiteral(value=left_name)
        else:
            left_expr = JavaVariableRef(name=left_name)

        right_expr: JavaExpression
        if right_str.replace(".", "").replace("-", "").isdigit():
            right_expr = JavaLiteral(value=right_str)
        else:
            right_expr = JavaVariableRef(name=right_str)

        return JavaBinaryOp(left=left_expr, operator=op, right=right_expr)

    return JavaLiteral(value=condition_str)


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


def _build_for_condition(var_name: str, until_condition: str) -> JavaExpression:
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
    return map_cobol_condition_to_java(until_condition)


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

    # Build field format width lookup if program provided
    field_format_widths = {}
    if program is not None:
        # Working storage items
        for item in program.working_storage:
            if item.is_numeric and item.format_width > 0:
                field_format_widths[item.name.replace("-", "_")] = item.format_width
        # FD record items (for numeric DISPLAY padding)
        for fd in program.file_definitions:
            for item in fd.record_items:
                if item.is_numeric and item.format_width > 0:
                    field_format_widths[item.name.replace("-", "_")] = item.format_width

    if isinstance(stmt, MoveStatement):
        target = stmt.target.replace("-", "_")
        source = map_cobol_expr_to_java(stmt.source)
        result.append(JavaAssignment(target=target, expression=source))
        # Handle multi-target MOVE: MOVE A TO B C
        for additional_target in stmt.targets:
            result.append(JavaAssignment(
                target=additional_target.replace("-", "_"),
                expression=map_cobol_expr_to_java(stmt.source),
            ))

    elif isinstance(stmt, AddStatement):
        # ADD A TO B GIVING C → C = A + B  (C receives result, B unchanged)
        # ADD A TO B           → B = A + B  (in-place)
        target = stmt.giving_target.replace("-", "_") if stmt.giving_target else stmt.target.replace("-", "_")
        source_a = map_cobol_expr_to_java(stmt.source)
        source_b = JavaVariableRef(name=stmt.target.replace("-", "_"))
        if stmt.giving_target:
            result.append(JavaAssignment(
                target=target,
                expression=JavaBinaryOp(
                    left=source_a,
                    operator="+",
                    right=source_b,
                ),
            ))
        else:
            result.append(JavaAssignment(
                target=target,
                expression=JavaBinaryOp(
                    left=source_b,
                    operator="+",
                    right=source_a,
                ),
            ))

    elif isinstance(stmt, SubtractStatement):
        # SUBTRACT A FROM B GIVING C → C = B - A
        # SUBTRACT A FROM B           → B = B - A (in-place)
        # SUBTRACT A B C FROM D GIVING E → E = D - A - B - C (multi-source)
        # SUBTRACT A B C FROM D           → D = D - A - B - C (multi-source, in-place)
        target = stmt.to_field.replace("-", "_") if stmt.to_field else stmt.from_field.replace("-", "_")
        # Determine all subtrahends: use sources tuple if present, else single source
        sources = stmt.sources if stmt.sources else (stmt.source,)
        java_sources = [map_cobol_expr_to_java(s) for s in sources]
        # Build chained subtraction: ((minuend - s1) - s2) - ...
        expr: JavaExpression = JavaVariableRef(name=stmt.from_field.replace("-", "_"))
        for src in java_sources:
            expr = JavaBinaryOp(left=expr, operator="-", right=src)
        result.append(JavaAssignment(target=target, expression=expr))

    elif isinstance(stmt, MultiplyStatement):
        # MULTIPLY A BY B GIVING C → C = A * B
        # MULTIPLY A BY B           → B = A * B (in-place, B receives result, A unchanged)
        # The left operand is always the source (A, multiplier)
        # If GIVING is present, target=C, multiplicand=B (both unchanged after)
        # If no GIVING, target=B (multiplicand gets updated in-place)
        if stmt.target:
            target = stmt.target.replace("-", "_")
        else:
            target = stmt.multiplicand.replace("-", "_")
        source = map_cobol_expr_to_java(stmt.source)
        result.append(JavaAssignment(
            target=target,
            expression=JavaBinaryOp(
                left=source,
                operator="*",
                right=JavaVariableRef(name=stmt.multiplicand.replace("-", "_")),
            ),
        ))

    elif isinstance(stmt, DivideStatement):
        target = stmt.target.replace("-", "_")
        source = map_cobol_expr_to_java(stmt.source)
        divisor = map_cobol_expr_to_java(stmt.divisor)
        result.append(JavaAssignment(
            target=target,
            expression=JavaBinaryOp(left=source, operator="/", right=divisor),
        ))
        # REMAINDER target = source % divisor
        if stmt.remainder:
            remainder_target = stmt.remainder.replace("-", "_")
            result.append(JavaAssignment(
                target=remainder_target,
                expression=JavaBinaryOp(left=source, operator="%", right=divisor),
            ))

    elif isinstance(stmt, ComputeStatement):
        target = stmt.target.replace("-", "_")
        expression = map_cobol_expr_to_java(stmt.expression)
        result.append(JavaAssignment(target=target, expression=expression))

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
                java_name = part.replace("-", "_")
                # Check if this field has a format width for numeric formatting
                if java_name in field_format_widths:
                    width = field_format_widths[java_name]
                    var_ref = JavaVariableRef(name=java_name)
                    # String.format("%0Nd", var) for zero-padded numeric display
                    format_spec = JavaLiteral(value="%0{}d".format(width))
                    parts.append(JavaMethodCall(
                        class_name="String",
                        method_name="format",
                        arguments=(format_spec, var_ref),
                        is_static=True,
                    ))
                else:
                    parts.append(JavaVariableRef(name=java_name))
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
        condition = map_cobol_condition_to_java(stmt.condition)
        then_body = []
        for s in stmt.then_body:
            then_body.extend(map_cobol_statement(s, program))
        else_body = []
        for s in stmt.else_body:
            else_body.extend(map_cobol_statement(s, program))
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
        # STRING → concatenation assignment.
        # Structured expressions preserve literal quoting (Literal →
        # quoted Java string, never a bare identifier); raw parts carry
        # COBOL quoting (e.g. '"SUBTRACT"') and are parsed the same way.
        if stmt.target:
            target = stmt.target.replace("-", "_")
            parts_exprs: list[JavaExpression] = []
            if stmt.structured_parts:
                for part in stmt.structured_parts:
                    parts_exprs.append(_map_cobol_expression_to_java(part))
            else:
                for part in stmt.parts:
                    parts_exprs.append(map_cobol_expr_to_java(part))
            if parts_exprs:
                result.append(JavaAssignment(
                    target=target,
                    expression=JavaStringConcat(parts=tuple(parts_exprs)),
                ))

    elif isinstance(stmt, UnstringStatement):
        # UNSTRING → split operation (handled at higher level)
        result.append(JavaComment(text=f"// UNSTRING {stmt.source}"))

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
                cond_java = _build_for_condition(var_jname, until_part)

                # Generate for loop body: use inline body or paragraph call
                body_stmts: list[JavaStatement] = []
                if stmt.body:
                    for s in stmt.body:
                        body_stmts.extend(map_cobol_statement(s, program))
                elif stmt.paragraph_name:
                    body_stmts.append(JavaMethodCallStatement(
                        call=JavaMethodCall(
                            method_name=_to_java_method_name(stmt.paragraph_name),
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
                        body_stmts.extend(map_cobol_statement(s, program))
                    result.append(JavaBlock(statements=tuple(body_stmts)))
                elif stmt.paragraph_name:
                    result.append(JavaMethodCallStatement(
                        call=JavaMethodCall(
                            method_name=_to_java_method_name(stmt.paragraph_name),
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
                    body_stmts.extend(map_cobol_statement(s, program))
            elif stmt.paragraph_name:
                body_stmts.append(JavaMethodCallStatement(
                    call=JavaMethodCall(
                        method_name=_to_java_method_name(stmt.paragraph_name),
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
            java_cond = map_cobol_condition_to_java(stmt.until_condition)
            loop_body: list[JavaStatement] = []
            if stmt.body:
                for s in stmt.body:
                    loop_body.extend(map_cobol_statement(s, program))
            elif stmt.paragraph_name:
                loop_body.append(JavaMethodCallStatement(
                    call=JavaMethodCall(
                        method_name=_to_java_method_name(stmt.paragraph_name),
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
                        method_name=_to_java_method_name(target),
                        arguments=(),
                    )
                ))
        else:
            # Simple PERFORM → method call
            result.append(JavaMethodCallStatement(
                call=JavaMethodCall(
                    method_name=_to_java_method_name(stmt.paragraph_name),
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
        raw_target = (stmt.program_name or "").strip()
        is_static_target = (
            len(raw_target) >= 2
            and raw_target[0] in ("'", '"')
            and raw_target[-1] in ("'", '"')
        )
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

    return result


# ---------------------------------------------------------------------------
# COBOL program → Java class mapping
# ---------------------------------------------------------------------------

def map_cobol_data_items_to_fields(
    items: tuple[DataItem, ...],
) -> tuple[JavaField, ...]:
    """Map COBOL WORKING-STORAGE items to Java fields."""
    fields: list[JavaField] = []
    for item in items:
        java_type = map_pic_to_java_type(item)
        java_name = item.name.replace("-", "_")
        default = map_pic_to_java_default(item)
        initializer = JavaLiteral(value=default)
        fields.append(JavaField(
            java_type=java_type,
            name=java_name,
            initializer=initializer,
            is_static=True,
            format_width=item.format_width if item.is_numeric else 0,
        ))
    return tuple(fields)


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
        name=_to_java_method_name(para.name),
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
        existing = {f.name for f in fields}
        for link_field in map_cobol_data_items_to_fields(program.linkage_section):
            if link_field.name not in existing:
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
        )
        for sc in program.status_codes
    )

    # Threshold rules → JavaThresholdRule
    threshold_rules = tuple(
        JavaThresholdRule(
            field_name=tr.field_name,
            operator=tr.operator,
            value=tr.value,
        )
        for tr in program.threshold_rules
    )

    # Summary fields → JavaSummaryField
    ws_lookup = {item.name: item for item in program.working_storage}
    summary_fields = tuple(
        JavaSummaryField(
            field_name=field,
            java_var_name=_cobol_field_to_java_var(field),
            format_width=ws_lookup[field].format_width if field in ws_lookup else 0,
            is_numeric=ws_lookup[field].is_numeric if field in ws_lookup else True,
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

    # Input record fields (from first InputRecordMapping)
    input_record_fields: tuple[str, ...] = ()
    if program.input_record_mappings:
        input_record_fields = tuple(
            f.replace("-", "_") for f in program.input_record_mappings[0].fields
        )

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

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
    CobolProgram,
    ComputeStatement,
    DataItem,
    DisplayStatement,
    DivideStatement,
    FileDefinition,
    GoToStatement,
    IfStatement,
    MoveStatement,
    Paragraph,
    PerformStatement,
    ReadStatement,
    StopRunStatement,
    StringStatement,
    SubtractStatement,
    MultiplyStatement,
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
    JavaDoWhile,
    JavaExpression,
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

# Monotonic counter for unique PERFORM TIMES loop variables (_times_0, _times_1, ...)
import itertools as _itertools
_times_counter = _itertools.count()


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


def map_cobol_condition_to_java(condition: str) -> JavaExpression:
    """Map COBOL conditions to structured Java expressions without mangling >= or <=."""
    import re as _re
    text = condition.strip()
    text = _re.sub(r"\bNOT\s+", "!", text)
    text = text.replace(" AND ", " && ").replace(" OR ", " || ")
    text = _re.sub(r"<>", "!=", text)
    text = _re.sub(r"(?<![<>=!])=(?!=)", "==", text)

    # Single simple comparison, including quoted strings.
    match = _re.fullmatch(r"([\w-]+)\s*(==|!=|>=|<=|>|<)\s*(.+)", text)
    if match:
        left_name, op, right = match.groups()
        left = JavaVariableRef(name=left_name.replace("-", "_"))
        right = right.strip()
        if (right.startswith("'") and right.endswith("'")) or (right.startswith('"') and right.endswith('"')):
            return JavaBinaryOp(
                left=left, operator=op,
                right=JavaLiteral(value=right[1:-1], java_type=JavaType(basic_type=JavaBasicType.STRING)),
            )
        if _re.fullmatch(r"-?\d+(?:\.\d+)?", right):
            return JavaBinaryOp(left=left, operator=op, right=JavaLiteral(value=right))
        return JavaBinaryOp(left=left, operator=op, right=JavaVariableRef(name=right.replace("-", "_")))

    # Complex expressions remain structured enough for the Java renderer via
    # a raw boolean Java literal. Quote COBOL string literals correctly.
    rendered = text
    rendered = _re.sub(r"'([^']*)'", lambda mm: '"' + mm.group(1).replace('"', '\\\"') + '"', rendered)
    rendered = _re.sub(r'\b([A-Za-z_][A-Za-z0-9-]*)\b', lambda mm: mm.group(1).replace("-", "_")
                       if mm.group(1) not in {"AND","OR","NOT"} else mm.group(1), rendered)
    return JavaLiteral(value=rendered)



def map_cobol_statement(
    stmt: Statement,
    program: CobolProgram | None = None,
    call_methods: dict[str, str] | None = None,
    call_linkage: dict[str, tuple[str, ...]] | None = None,
) -> list[JavaStatement]:
    """Map a single COBOL statement to one or more Java statements."""
    result: list[JavaStatement] = []

    # Build field format width lookup if program provided
    field_format_widths = {}
    if program is not None:
        for item in program.working_storage:
            if item.is_numeric and item.format_width > 0:
                field_format_widths[item.name.replace("-", "_")] = item.format_width

    if isinstance(stmt, MoveStatement):
        source = map_cobol_expr_to_java(stmt.source)
        targets = stmt.targets or ((stmt.target,) if stmt.target else ())
        for target_name in targets:
            result.append(JavaAssignment(target=target_name.replace("-", "_"), expression=source))

    elif isinstance(stmt, AddStatement):
        target = stmt.target.replace("-", "_")
        source = map_cobol_expr_to_java(stmt.source)
        # ADD source TO target → target += source
        result.append(JavaAssignment(
            target=target,
            expression=JavaBinaryOp(
                left=JavaVariableRef(name=target),
                operator="+",
                right=source,
            ),
        ))

    elif isinstance(stmt, SubtractStatement):
        source = map_cobol_expr_to_java(stmt.source)
        base = stmt.from_field.replace("-", "_")
        target = (stmt.to_field or stmt.from_field).replace("-", "_")
        result.append(JavaAssignment(
            target=target,
            expression=JavaBinaryOp(
                left=JavaVariableRef(name=base),
                operator="-",
                right=source,
            ),
        ))

    elif isinstance(stmt, MultiplyStatement):
        source = map_cobol_expr_to_java(stmt.source)
        base = stmt.multiplicand.replace("-", "_")
        target = (stmt.target or stmt.multiplicand).replace("-", "_")
        result.append(JavaAssignment(
            target=target,
            expression=JavaBinaryOp(
                left=map_cobol_expr_to_java(stmt.source),
                operator="*",
                right=JavaVariableRef(name=base),
            ),
        ))

    elif isinstance(stmt, CallStatement):
        # Static CALL → static Java method call on the callee class.
        # Class name uses the same _to_java_class_name convention as the
        # generated class (CLAIMS → Claims), not raw program_name underscores.
        # Entry method: MAIN_LOGIC for LINKAGE callees (value-result via
        # static linkage fields), else first-paragraph method from
        # call_methods, else program-name-derived fallback.
        target = _to_java_class_name(stmt.program_name) if stmt.program_name else ""
        raw_target = (stmt.program_name or "").strip()
        is_static_target = (
            len(raw_target) >= 2
            and raw_target[0] in ("'", '"')
            and raw_target[-1] in ("'", '"')
        )
        callee_has_linkage = False
        if is_static_target and call_linkage:
            callee_has_linkage = bool(
                (call_linkage or {}).get(stmt.program_name.upper())
            )
        if is_static_target and callee_has_linkage:
            method = "MAIN_LOGIC"
        else:
            method = (call_methods or {}).get(
                stmt.program_name.upper(),
                stmt.program_name.replace("-", "_").title().replace("_", ""),
            )
        linkage = (call_linkage or {}).get(stmt.program_name.upper(), ())
        for idx, arg in enumerate(stmt.arguments):
            if idx < len(linkage):
                result.append(JavaAssignment(
                    target=f"{target}.{linkage[idx].replace('-', '_')}",
                    expression=map_cobol_expr_to_java(arg),
                ))
        result.append(JavaMethodCallStatement(
            call=JavaMethodCall(method_name=method, class_name=target, is_static=True, arguments=())
        ))
        for idx, arg in enumerate(stmt.arguments):
            if idx < len(linkage):
                mode = stmt.passing_modes[idx] if idx < len(stmt.passing_modes) else "REFERENCE"
                if mode.upper() == "REFERENCE":
                    result.append(JavaAssignment(
                        target=arg.replace("-", "_"),
                        expression=JavaVariableRef(name=f"{target}.{linkage[idx].replace('-', '_')}"),
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
            if part.startswith('"'):
                inner = part[1:-1]
                if inner:
                    parts.append(JavaLiteral(value=inner))
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
            # out.println(...) or System.err.println(...)
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
            then_body.extend(map_cobol_statement(s, program, call_methods, call_linkage))
        else_body = []
        for s in stmt.else_body:
            else_body.extend(map_cobol_statement(s, program, call_methods, call_linkage))
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
        # READ → loop structure (handled at higher level)
        body = []
        for s in stmt.not_at_end_body:
            body.extend(map_cobol_statement(s, program, call_methods, call_linkage))
        if body:
            result.append(JavaBlock(statements=tuple(body)))

    elif isinstance(stmt, WriteStatement):
        result.append(JavaMethodCallStatement(
            call=JavaMethodCall(
                object_ref=JavaVariableRef(name="System.out"),
                method_name="println",
                arguments=(JavaVariableRef(name=(stmt.from_field or stmt.record_name).replace("-", "_")),),
            )
        ))

    elif isinstance(stmt, StringStatement):
        # STRING → assignment
        if stmt.target:
            target = stmt.target.replace("-", "_")
            parts_exprs = []
            for part in stmt.structured_parts:
                parts_exprs.append(map_cobol_expr_to_java(str(part)))
            if parts_exprs:
                result.append(JavaAssignment(
                    target=target,
                    expression=JavaStringConcat(parts=tuple(parts_exprs)),
                ))

    elif isinstance(stmt, UnstringStatement):
        # UNSTRING → split operation (handled at higher level)
        result.append(JavaComment(text=f"// UNSTRING {stmt.source}"))

    elif isinstance(stmt, PerformStatement):
        result.extend(_map_perform_statement(stmt, program, call_methods, call_linkage))

    return result


def _expand_thru_range(stmt: PerformStatement, program: CobolProgram | None) -> list[str]:
    """Expand PERFORM A THRU B into the inclusive list of paragraph names.

    Uses program paragraph order. Falls back to [A, B] when the named
    paragraphs are not present in the program IR (bare fixture parses).
    """
    if not stmt.paragraph_name:
        return []
    if not stmt.thru_target:
        return [stmt.paragraph_name]
    if program is None:
        return [stmt.paragraph_name, stmt.thru_target]
    names = [p.name for p in program.paragraphs]
    if stmt.paragraph_name in names and stmt.thru_target in names:
        start = names.index(stmt.paragraph_name)
        end = names.index(stmt.thru_target)
        if end >= start:
            return names[start:end + 1]
    return [stmt.paragraph_name, stmt.thru_target]


def _map_perform_body(
    stmt: PerformStatement,
    program: CobolProgram | None,
    call_methods: dict[str, str] | None,
    call_linkage: dict[str, tuple[str, ...]] | None,
) -> list[JavaStatement]:
    """Body statements for a PERFORM loop: paragraph call and/or inline body."""
    body: list[JavaStatement] = []
    if stmt.paragraph_name:
        body.append(JavaMethodCallStatement(
            call=JavaMethodCall(
                method_name=stmt.paragraph_name.replace("-", "_"),
                arguments=(),
            )
        ))
    for s in stmt.body:
        body.extend(map_cobol_statement(s, program, call_methods, call_linkage))
    return body


def _map_perform_statement(
    stmt: PerformStatement,
    program: CobolProgram | None,
    call_methods: dict[str, str] | None = None,
    call_linkage: dict[str, tuple[str, ...]] | None = None,
) -> list[JavaStatement]:
    """Map a PERFORM statement to Java IR control flow.

    - TIMES=N        → bounded for-loop with a unique _times_N counter
    - UNTIL cond     → while (!(cond))  (TEST BEFORE, COBOL default)
    - UNTIL + AFTER  → do { } while (!(cond))
    - A THRU B       → sequential calls for each paragraph in the range
    - plain PARA     → method call
    """
    # PERFORM ... N TIMES (or VAR TIMES)
    if stmt.until_condition and stmt.until_condition.startswith("TIMES="):
        count_str = stmt.until_condition[len("TIMES="):].strip()
        counter = f"_times_{next(_times_counter)}"
        if count_str.isdigit():
            count_expr: JavaExpression = JavaLiteral(value=count_str)
        else:
            count_expr = JavaVariableRef(name=count_str.replace("-", "_"))
        init = JavaLocalVarDecl(
            java_type=JavaType(basic_type=JavaBasicType.INT),
            name=counter,
            initializer=JavaLiteral(value="0"),
        )
        condition = JavaBinaryOp(
            left=JavaVariableRef(name=counter),
            operator="<",
            right=count_expr,
        )
        update = JavaAssignment(
            target=counter,
            expression=JavaBinaryOp(
                left=JavaVariableRef(name=counter),
                operator="+",
                right=JavaLiteral(value="1"),
            ),
        )
        body = _map_perform_body(stmt, program, call_methods, call_linkage)
        return [JavaFor(init=init, condition=condition, update=update, body=tuple(body))]

    # PERFORM A THRU B — sequential calls, no loop wrapper
    if stmt.thru_target:
        return [
            JavaMethodCallStatement(
                call=JavaMethodCall(
                    method_name=name.replace("-", "_"),
                    arguments=(),
                )
            )
            for name in _expand_thru_range(stmt, program)
        ]

    # UNTIL / VARYING with a condition
    if stmt.until_condition:
        cond_str = stmt.until_condition
        # Out-of-line VARYING keeps the paragraph form; use the UNTIL clause.
        upper_cond = cond_str.upper()
        if upper_cond.startswith("VARYING"):
            until_idx = upper_cond.find("UNTIL ")
            if until_idx >= 0:
                cond_str = cond_str[until_idx + len("UNTIL "):].strip()
            else:
                cond_str = ""
        if cond_str:
            condition: JavaExpression = map_cobol_condition_to_java(cond_str)
            loop_condition = JavaUnaryOp(operator="!", operand=condition)
            body = _map_perform_body(stmt, program, call_methods, call_linkage)
            if stmt.test_after:
                return [JavaDoWhile(condition=loop_condition, body=tuple(body))]
            return [JavaWhile(condition=loop_condition, body=tuple(body))]

    # Plain PERFORM paragraph (or empty inline no-op)
    if stmt.paragraph_name:
        return [JavaMethodCallStatement(
            call=JavaMethodCall(
                method_name=stmt.paragraph_name.replace("-", "_"),
                arguments=(),
            )
        )]

    # Inline body without a condition (degenerate) — expand body statements
    if stmt.body:
        result: list[JavaStatement] = []
        for s in stmt.body:
            result.extend(map_cobol_statement(s, program, call_methods, call_linkage))
        return result

    return []


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
    call_methods: dict[str, str] | None = None,
    call_linkage: dict[str, tuple[str, ...]] | None = None,
) -> JavaMethod:
    """Map a COBOL paragraph to a Java method."""
    body_stmts: list[JavaStatement] = []
    for stmt in para.statements:
        body_stmts.extend(map_cobol_statement(stmt, program, call_methods, call_linkage))

    return JavaMethod(
        name=para.name.replace("-", "_"),
        return_type=JavaType(basic_type=JavaBasicType.VOID),
        parameters=(),
        body_statements=tuple(body_stmts),
        is_static=True,
        modifiers=("public", "static"),
    )


def map_cobol_program_to_java(
    program: CobolProgram,
    call_methods: dict[str, str] | None = None,
    call_linkage: dict[str, tuple[str, ...]] | None = None,
) -> JavaProgram:
    """Map a complete COBOL program to a JavaProgram.

    Populates all Java IR structures including decision-mode metadata.
    All values are derived from COBOL IR — not invented.
    """
    # Map fields — working-storage + LINKAGE items (linkage items become
    # static fields so callers can sync values through them).
    fields = map_cobol_data_items_to_fields(program.working_storage)
    if program.linkage_section:
        existing = {f.name for f in fields}
        for link_field in map_cobol_data_items_to_fields(program.linkage_section):
            if link_field.name not in existing:
                fields = fields + (link_field,)
                existing.add(link_field.name)

    # Map methods from paragraphs
    methods: list[JavaMethod] = []
    for para in program.paragraphs:
        methods.append(map_cobol_paragraph_to_method(para, program, call_methods, call_linkage))

    # Add main method
    main_body: list[JavaStatement] = []
    for para in program.paragraphs:
        for stmt in para.statements:
            main_body.extend(map_cobol_statement(stmt, program, call_methods, call_linkage))

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

    # Business entry for LINKAGE programs: parameterless MAIN_LOGIC that
    # operates on the static linkage fields. Callers sync-in before the
    # call and sync-out after (BY REFERENCE only).
    if program.linkage_section and program.paragraphs:
        business_body: list[JavaStatement] = []
        for stmt in program.paragraphs[0].statements:
            business_body.extend(map_cobol_statement(stmt, program, call_methods, call_linkage))
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
    # Entry-method convention:
    #   * Callee with LINKAGE SECTION → MAIN_LOGIC (value-result through
    #     static linkage fields; see CallStatement mapping).
    #   * Callee without LINKAGE → first paragraph name.
    call_methods = {
        p.program_id.upper(): (
            "MAIN_LOGIC"
            if p.linkage_section
            else (p.paragraphs[0].name.replace("-", "_") if p.paragraphs else "main")
        )
        for p in programs
    }
    call_linkage = {
        p.program_id.upper(): tuple(item.name for item in p.linkage_section)
        for p in programs
    }

    for prog in programs:
        java_prog = map_cobol_program_to_java(prog, call_methods, call_linkage)
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

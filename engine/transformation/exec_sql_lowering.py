"""Lowering of ``ExecSqlStatement`` to JDBC calls (roadmap unit 12b).

Certified subset, all on a PostgreSQL target (``PostgresDialect`` rewrites the text and binds host
variables to positional markers), proven against the OCESQL + PostgreSQL reference:

* ``CONNECT :user IDENTIFIED BY :password USING :database`` / ``DISCONNECT``
* singleton ``SELECT ... INTO :h1, :h2 FROM ...`` (SQLCODE 0 / 100; host variables unchanged on 100)
* ``INSERT`` / ``UPDATE`` / ``DELETE`` with host variables in the text
* ``COMMIT`` / ``ROLLBACK``
* ``DECLARE c CURSOR FOR SELECT ...`` / ``OPEN`` / ``FETCH c INTO :h...`` / ``CLOSE``

Host variables are elementary, non-table DISPLAY items: ``PIC X(n)``, unsigned or signed integer
``PIC 9(n)`` (n <= 18), and ``PIC 9(i)V9(s)``.  Everything else -- indicator variables, WHENEVER,
dynamic SQL, CALL, ``WITH HOLD`` cursors, a statement the dialect cannot translate, a host variable
outside that set, a program without ``SQLCODE`` / ``SQLSTATE`` -- fails closed with an unresolvable
symbol that names the reason.  The result is the list of reasons (empty when the statement lowers)
and the Java statements.
"""

from __future__ import annotations

from engine.transformation import exec_sql


def _symbol(*reasons: str) -> str:
    return "UNSUPPORTED_EXEC_SQL$" + "$".join(reasons)


def host_item(program, name: str):
    """The data item behind a host variable, or ``None`` when it is not a certified host variable."""
    from engine.transformation.cobol_to_java_mapping import _find_data_item

    item = _find_data_item(program, name)
    if (
        item is None
        or not item.is_elementary
        or item.occurs
        or item.usage not in (None, "", "DISPLAY")
        or item.pic_length <= 0
        or (item.is_numeric and item.pic_length > 18)
    ):
        return None
    return item


def _declared_cursors(program) -> dict[str, str]:
    found: dict[str, str] = {}

    def walk(statements) -> None:
        for statement in statements:
            if type(statement).__name__ == "ExecSqlStatement" and statement.kind == "DECLARE_CURSOR":
                parsed = exec_sql.parse_declare_cursor(statement.sql)
                if parsed:
                    found[parsed[0]] = parsed[1]
            for attribute in ("then_body", "else_body", "body"):
                walk(getattr(statement, attribute, ()) or ())

    for paragraph in program.paragraphs:
        walk(paragraph.statements)
    return found


def unsupported_reasons(stmt, program) -> list[str]:
    """Why ``stmt`` is outside the certified subset (empty when it lowers)."""
    reasons: list[str] = []
    if not stmt.terminated:
        reasons.append("UNTERMINATED")
    if stmt.indicators:
        reasons.append("INDICATOR")
    if program is None or _item(program, "SQLCODE") is None or _item(program, "SQLSTATE") is None:
        reasons.append("SQLCA")
    plan = _plan(stmt, program, reasons)
    if plan is None and not reasons:
        reasons.append("FORM")
    return list(dict.fromkeys(reasons))


def _item(program, name):
    from engine.transformation.cobol_to_java_mapping import _find_data_item

    return _find_data_item(program, name)


def _plan(stmt, program, reasons: list[str]):
    """``(method, sql, bind_names, output_names, extra)`` for a supported statement, else ``None``."""
    from engine.sql.database_dialect import dialect_for

    kind = stmt.kind
    dialect = dialect_for("postgresql")

    def rewrite(text: str):
        result = dialect.rewrite(text)
        if not result.ok:
            reasons.extend("DIALECT_" + issue.upper().replace(" ", "_")[:24] for issue in result.issues)
            return None
        return result

    def hosts_ok(names) -> bool:
        good = True
        for name in names:
            if host_item(program, name) is None:
                reasons.append("HOST_VARIABLE")
                good = False
        return good

    if kind == "CONNECT":
        parts = exec_sql.parse_connect(stmt.sql)
        if parts is None or not hosts_ok(parts):
            return None
        return ("connect", "", parts, (), None)
    if kind == "DISCONNECT":
        return ("disconnect", "", (), (), None) if exec_sql.is_disconnect(stmt.sql) else None
    if kind in ("COMMIT", "ROLLBACK"):
        return (kind.lower(), "", (), (), None) if exec_sql.parse_tx_end(stmt.sql) else None
    if kind in ("INSERT", "UPDATE", "DELETE"):
        result = rewrite(stmt.sql)
        if result is None or not hosts_ok([b.name for b in result.binds]):
            return None
        return ("execute", result.sql, tuple(b.name for b in result.binds), (), None)
    if kind == "SELECT":
        split = exec_sql.split_select_into(stmt.sql)
        if split is None:
            return None
        text, targets = split
        result = rewrite(text)
        if result is None or not hosts_ok([b.name for b in result.binds] + [t[0] for t in targets]):
            return None
        return ("selectInto", result.sql, tuple(b.name for b in result.binds),
                tuple(t[0] for t in targets), None)
    if kind == "DECLARE_CURSOR":
        parsed = exec_sql.parse_declare_cursor(stmt.sql)
        if parsed is None or "HOLD" in stmt.sql.upper().split():
            return None
        result = rewrite(parsed[1])
        if result is None or not hosts_ok([b.name for b in result.binds]):
            return None
        return ("declare", result.sql, (), (), parsed[0])
    if kind in ("OPEN", "FETCH", "CLOSE"):
        parsed = exec_sql.parse_cursor_op(stmt.sql)
        if parsed is None or parsed[0] != kind:
            return None
        name = parsed[1]
        declared = _declared_cursors(program)
        if name not in declared:
            reasons.append("CURSOR_NOT_DECLARED")
            return None
        if kind == "OPEN":
            result = rewrite(declared[name])
            if result is None or not hosts_ok([b.name for b in result.binds]):
                return None
            return ("open", "", tuple(b.name for b in result.binds), (), name)
        if kind == "FETCH":
            outputs = tuple(t[0] for t in parsed[2])
            if not hosts_ok(outputs):
                return None
            return ("fetch", "", (), outputs, name)
        return ("close", "", (), (), name)
    return None


def lower(stmt, program) -> list:
    """Java statements for ``stmt``: JDBC calls when certified, else an unresolvable symbol."""
    from engine.transformation.cobol_to_java_mapping import map_pic_to_java_type
    from engine.transformation.java_ir import (
        JavaAssignment,
        JavaBasicType,
        JavaCast,
        JavaComment,
        JavaLiteral,
        JavaMethodCall,
        JavaMethodCallStatement,
        JavaType,
        JavaVariableRef,
    )

    out: list = [JavaComment(text=f"EXEC SQL {stmt.kind}")]
    reasons = unsupported_reasons(stmt, program)
    if reasons:
        out.append(JavaAssignment(
            target="SQLCODE", expression=JavaVariableRef(name=_symbol(*reasons))))
        return out
    method, sql, binds, outputs, extra = _plan(stmt, program, [])

    def text(value: str) -> JavaLiteral:
        return JavaLiteral(value=value, java_type=JavaType(basic_type=JavaBasicType.STRING))

    def number(value: int) -> JavaLiteral:
        return JavaLiteral(value=str(value), java_type=JavaType(basic_type=JavaBasicType.INT))

    def ref(name: str) -> JavaVariableRef:
        return JavaVariableRef(name=name.replace("-", "_"))

    def call(name: str, arguments: tuple) -> JavaMethodCallStatement:
        return JavaMethodCallStatement(call=JavaMethodCall(
            class_name="CobolSql", method_name=name, arguments=arguments, is_static=True))

    def value_call(name: str, arguments: tuple) -> JavaMethodCall:
        return JavaMethodCall(
            class_name="CobolSql", method_name=name, arguments=arguments, is_static=True)

    if method == "connect":
        out.append(call("connect", tuple(ref(n) for n in binds)))
    elif method in ("disconnect", "commit", "rollback"):
        out.append(call(method, ()))
    elif method == "execute":
        out.append(call("execute", (text(sql), *[ref(n) for n in binds])))
    elif method == "declare":
        out.append(call("declare", (text(extra), text(sql))))
    elif method == "open":
        out.append(call("open", (text(extra), *[ref(n) for n in binds])))
    elif method == "close":
        out.append(call("close", (text(extra),)))
    else:  # selectInto / fetch
        if method == "selectInto":
            out.append(call("selectInto", (text(sql), *[ref(n) for n in binds])))
        else:
            out.append(call("fetch", (text(extra),)))
        for column, name in enumerate(outputs):
            item = host_item(program, name)
            java = ref(name)
            java_type = map_pic_to_java_type(item).basic_type
            value: object
            if not item.is_numeric:
                value = value_call("str", (number(column), number(item.pic_length), java))
            elif item.decimal_places > 0:
                value = value_call("dec", (
                    number(column), number(item.pic_length - item.decimal_places),
                    number(item.decimal_places), java))
            else:
                value = value_call("integer", (number(column), number(item.pic_length), java))
                if java_type == JavaBasicType.INT:
                    value = JavaCast(target_type=JavaType(basic_type=JavaBasicType.INT),
                                     expression=value)
            out.append(JavaAssignment(target=name.replace("-", "_"), expression=value))
    if method != "declare":
        out.append(JavaAssignment(target="SQLCODE", expression=JavaVariableRef(name="CobolSql.code")))
        out.append(JavaAssignment(target="SQLSTATE", expression=JavaVariableRef(name="CobolSql.state")))
    return out

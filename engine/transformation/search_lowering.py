"""Lowering of ``SET`` on indexes and ``SEARCH`` (linear) (roadmap unit 9).

Certified subset, proven against GnuCOBOL 3.1.2 (``tests/integration/test_search_oracle.py``):

* ``OCCURS n INDEXED BY idx...`` on an elementary DISPLAY item: each index is an occurrence number, an ``int``.
* ``SET idx... TO value`` / ``UP BY n`` / ``DOWN BY n`` and ``SET integer-item TO idx``, with integer literals,
  indexes and unsigned integer DISPLAY items.
* ``SEARCH table [VARYING item] [AT END ...] WHEN cond ... [WHEN ...] [END-SEARCH]``: starts at the table's first
  index *as it stands* (no reset), tests the WHEN conditions in order for each element, leaves the index on the
  matching element, or at ``n + 1`` with ``AT END`` taken; an index already past ``n`` goes straight to ``AT END``.
  ``VARYING`` an integer data item: after each advance the item receives the new index value (observed oracle
  behaviour, not a lockstep increment), and stays untouched when the search does not advance.

* ``SEARCH ALL table [AT END ...] WHEN table(idx) = value`` on a table declared ``ASCENDING|DESCENDING KEY IS``
  itself: binary search with ``mid = (lo + hi) / 2`` over ``1..n``, the index left on the match, or on the last
  element probed when AT END is taken (observed oracle behaviour, also for a table that is not in key order).

Not certified, refused by name: ``VARYING`` an index or ``VARYING`` with ``SEARCH ALL``, an index outside ``1..n+1`` at the start of a
SEARCH, tables of groups, non-DISPLAY tables, ``SET`` forms with expressions, a statement with no ``WHEN``.
"""

from __future__ import annotations


def _walk(items):
    for item in items:
        yield item
        yield from _walk(item.children)


def all_items(program) -> list:
    if program is None:
        return []
    return list(_walk([*program.working_storage, *program.linkage_section]))


def index_names(program) -> set[str]:
    return {name.upper() for item in all_items(program) for name in item.indexed_by}


def _data_item(program, name: str):
    from engine.transformation.cobol_to_java_mapping import _find_data_item

    return _find_data_item(program, name)


def _integer_item(item) -> bool:
    return (
        item is not None and item.is_elementary and not item.occurs and item.is_numeric
        and item.decimal_places == 0 and 0 < item.pic_length <= 18
        and item.usage in (None, "", "DISPLAY")
    )


def _is_integer_literal(text: str) -> bool:
    return text.isdigit()


# ------------------------------------------------------------------------------------------- SET


def set_reasons(stmt, program) -> list[str]:
    reasons: list[str] = []
    indexes = index_names(program)
    if not stmt.targets:
        return ["FORM"]
    for target in stmt.targets:
        upper = target.upper()
        if upper in indexes:
            continue
        item = _data_item(program, target)
        if stmt.mode == "TO" and stmt.value.upper() in indexes and _integer_item(item) and not item.signed:
            continue
        reasons.append("TARGET")
    value = stmt.value
    if _is_integer_literal(value):
        pass
    elif value.upper() in indexes:
        if stmt.mode != "TO":
            reasons.append("VALUE")
    elif not _integer_item(_data_item(program, value)):
        reasons.append("VALUE")
    return list(dict.fromkeys(reasons))


def _value_expression(value: str, program):
    from engine.transformation.cobol_to_java_mapping import map_pic_to_java_type
    from engine.transformation.java_ir import (
        JavaBasicType,
        JavaCast,
        JavaLiteral,
        JavaType,
        JavaVariableRef,
    )

    if _is_integer_literal(value):
        return JavaLiteral(value=str(int(value)), java_type=JavaType(basic_type=JavaBasicType.INT))
    ref = JavaVariableRef(name=value.replace("-", "_"))
    if value.upper() in index_names(program):
        return ref
    if map_pic_to_java_type(_data_item(program, value)).basic_type == JavaBasicType.LONG:
        return JavaCast(target_type=JavaType(basic_type=JavaBasicType.INT), expression=ref)
    return ref


def lower_set(stmt, program) -> list:
    from engine.transformation.java_ir import (
        JavaAssignment,
        JavaBasicType,
        JavaBinaryOp,
        JavaComment,
        JavaLiteral,
        JavaType,
        JavaVariableRef,
    )

    out: list = [JavaComment(text=f"SET {' '.join(stmt.targets)}")]
    reasons = set_reasons(stmt, program)
    if reasons:
        out.append(JavaAssignment(
            target=stmt.targets[0].replace("-", "_") if stmt.targets else "UNUSED",
            expression=JavaVariableRef(name="UNSUPPORTED_SET$" + "$".join(reasons))))
        return out
    indexes = index_names(program)
    value = _value_expression(stmt.value, program)
    for target in stmt.targets:
        name = target.replace("-", "_")
        if target.upper() in indexes:
            if stmt.mode == "TO":
                expression = value
            else:
                expression = JavaBinaryOp(
                    left=JavaVariableRef(name=name), operator="+" if stmt.mode == "UP" else "-", right=value)
            out.append(JavaAssignment(target=name, expression=expression))
        else:  # SET integer-item TO index: the occurrence number, kept to the item's digits
            item = _data_item(program, target)
            modulus = JavaLiteral(value=str(10 ** item.pic_length) + ("L" if item.pic_length > 9 else ""),
                                  java_type=JavaType(basic_type=JavaBasicType.LONG if item.pic_length > 9
                                                     else JavaBasicType.INT))
            out.append(JavaAssignment(target=name, expression=JavaBinaryOp(
                left=value, operator="%", right=modulus)))
    return out


# ---------------------------------------------------------------------------------------- SEARCH


def _all_condition(stmt, program) -> str | None:
    """The comparison value of ``WHEN table(idx) = value`` for SEARCH ALL, or None when the shape differs."""
    import re

    table = _data_item(program, stmt.table)
    if table is None or not table.indexed_by or len(stmt.whens) != 1:
        return None
    match = re.fullmatch(
        rf"{re.escape(stmt.table)}\s*\(\s*{re.escape(table.indexed_by[0])}\s*\)\s*=\s*(.+?)\s*",
        stmt.whens[0].condition.strip(), re.IGNORECASE)
    if not match:
        return None
    value = match.group(1)
    if re.fullmatch(r"\d+|'[^'\"]*'|\"[^'\"]*\"", value):
        return value
    if re.fullmatch(r"[A-Za-z][\w-]*", value) and value.upper() not in index_names(program):
        item = _data_item(program, value)
        if item is not None and item.is_elementary and not item.occurs:
            return value
    return None


def search_reasons(stmt, program) -> list[str]:
    reasons = list(stmt.reasons)
    table = _data_item(program, stmt.table)
    if table is None or not table.occurs or table.children or table.usage not in (None, "", "DISPLAY"):
        reasons.append("TABLE")
    elif not table.indexed_by:
        reasons.append("NO_INDEX")
    if stmt.varying:
        if stmt.varying.upper() in index_names(program):
            reasons.append("VARYING_INDEX")
        elif not _integer_item(_data_item(program, stmt.varying)) or _data_item(program, stmt.varying).signed:
            reasons.append("VARYING")
    if not stmt.whens:
        reasons.append("NO_WHEN")
    if stmt.is_all:
        if table is not None and not table.key_order:
            reasons.append("NO_KEY")
        if stmt.whens and _all_condition(stmt, program) is None:
            reasons.append("ALL_WHEN")
    return list(dict.fromkeys(reasons))


def lower_search(stmt, program, map_body) -> list:
    """Java for a SEARCH; ``map_body(statement)`` lowers a nested COBOL statement."""
    from engine.transformation.cobol_to_java_mapping import _fresh_io_var, map_cobol_condition_to_java
    from engine.transformation.java_ir import (
        JavaAssignment,
        JavaBasicType,
        JavaBinaryOp,
        JavaComment,
        JavaIf,
        JavaLiteral,
        JavaLocalVarDecl,
        JavaType,
        JavaUnaryOp,
        JavaVariableRef,
        JavaWhile,
    )

    out: list = [JavaComment(text=f"SEARCH {stmt.table}")]
    reasons = search_reasons(stmt, program)
    if reasons:
        out.append(JavaAssignment(
            target="UNUSED", expression=JavaVariableRef(name="UNSUPPORTED_SEARCH$" + "$".join(reasons))))
        return out
    table = _data_item(program, stmt.table)
    index = JavaVariableRef(name=table.indexed_by[0].replace("-", "_"))
    if stmt.is_all:
        out.extend(_lower_search_all(stmt, program, table, index, map_body))
        return out
    found_name = _fresh_io_var("srch")
    found = JavaVariableRef(name=found_name)
    boolean = JavaType(basic_type=JavaBasicType.BOOLEAN)
    one = JavaLiteral(value="1", java_type=JavaType(basic_type=JavaBasicType.INT))

    advance: list = [JavaAssignment(target=index.name, expression=JavaBinaryOp(
        left=index, operator="+", right=one))]
    if stmt.varying:
        varying = _data_item(program, stmt.varying)
        modulus = JavaLiteral(value=str(10 ** varying.pic_length) + ("L" if varying.pic_length > 9 else ""),
                              java_type=JavaType(basic_type=JavaBasicType.LONG if varying.pic_length > 9
                                                 else JavaBasicType.INT))
        advance.append(JavaAssignment(
            target=stmt.varying.replace("-", "_"),
            expression=JavaBinaryOp(left=index, operator="%", right=modulus)))

    chain: tuple = tuple(advance)
    for when in reversed(stmt.whens):
        body = []
        for nested in when.body:
            body.extend(map_body(nested))
        body.append(JavaAssignment(target=found_name, expression=JavaVariableRef(name="true")))
        chain = (JavaIf(
            condition=map_cobol_condition_to_java(when.condition, program=program),
            then_body=tuple(body), else_body=chain),)

    limit = JavaLiteral(value=str(table.occurs), java_type=JavaType(basic_type=JavaBasicType.INT))
    # a bare name renders unquoted; a string-typed literal would be quoted
    out.append(JavaLocalVarDecl(java_type=boolean, name=found_name,
                                initializer=JavaVariableRef(name="false")))
    out.append(JavaWhile(
        condition=JavaBinaryOp(
            left=JavaUnaryOp(operator="!", operand=found), operator="&&",
            right=JavaBinaryOp(left=index, operator="<=", right=limit)),
        body=chain))
    if stmt.at_end:
        at_end = []
        for nested in stmt.at_end:
            at_end.extend(map_body(nested))
        out.append(JavaIf(condition=JavaUnaryOp(operator="!", operand=found), then_body=tuple(at_end)))
    return out


def _lower_search_all(stmt, program, table, index, map_body) -> list:
    """Binary search: ``mid = (lo + hi) / 2`` over ``1..n``, as GnuCOBOL does (tests/integration/test_search_oracle.py)."""
    from engine.transformation.cobol_to_java_mapping import _fresh_io_var, map_cobol_condition_to_java
    from engine.transformation.java_ir import (
        JavaAssignment,
        JavaBasicType,
        JavaBinaryOp,
        JavaIf,
        JavaLiteral,
        JavaLocalVarDecl,
        JavaType,
        JavaUnaryOp,
        JavaVariableRef,
        JavaWhile,
    )

    value = _all_condition(stmt, program)
    assert value is not None  # search_reasons refused every other shape
    integer = JavaType(basic_type=JavaBasicType.INT)
    boolean = JavaType(basic_type=JavaBasicType.BOOLEAN)

    def number(text: str):
        return JavaLiteral(value=text, java_type=integer)

    lo_name, hi_name, found_name = _fresh_io_var("lo"), _fresh_io_var("hi"), _fresh_io_var("srch")
    lo, hi, found = JavaVariableRef(name=lo_name), JavaVariableRef(name=hi_name), JavaVariableRef(name=found_name)
    # ascending: a probe below the value moves lo up; descending: a probe above it does
    before = "<" if table.key_order == "ASCENDING" else ">"
    probe = f"{stmt.table}({table.indexed_by[0]}) {before} {value}"
    body = []
    for nested in stmt.whens[0].body:
        body.extend(map_body(nested))
    body.append(JavaAssignment(target=found_name, expression=JavaVariableRef(name="true")))
    step = JavaIf(
        condition=map_cobol_condition_to_java(stmt.whens[0].condition, program=program),
        then_body=tuple(body),
        else_body=(JavaIf(
            condition=map_cobol_condition_to_java(probe, program=program),
            then_body=(JavaAssignment(target=lo_name, expression=JavaBinaryOp(
                left=index, operator="+", right=number("1"))),),
            else_body=(JavaAssignment(target=hi_name, expression=JavaBinaryOp(
                left=index, operator="-", right=number("1"))),)),))
    out: list = [
        JavaLocalVarDecl(java_type=integer, name=lo_name, initializer=number("1")),
        JavaLocalVarDecl(java_type=integer, name=hi_name, initializer=number(str(table.occurs))),
        JavaLocalVarDecl(java_type=boolean, name=found_name, initializer=JavaVariableRef(name="false")),
        JavaWhile(
            condition=JavaBinaryOp(
                left=JavaUnaryOp(operator="!", operand=found), operator="&&",
                right=JavaBinaryOp(left=lo, operator="<=", right=hi)),
            body=(JavaAssignment(target=index.name, expression=JavaBinaryOp(
                left=JavaBinaryOp(left=lo, operator="+", right=hi), operator="/", right=number("2"))), step)),
    ]
    if stmt.at_end:
        at_end = []
        for nested in stmt.at_end:
            at_end.extend(map_body(nested))
        out.append(JavaIf(condition=JavaUnaryOp(operator="!", operand=found), then_body=tuple(at_end)))
    return out

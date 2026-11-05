"""Lowering of ``SortStatement`` to ``CobolSort.run`` (roadmap unit 9).

Certified subset: ``SORT sd ON ASCENDING|DESCENDING KEY k... USING f1 GIVING f2`` where

* ``sd`` is an SD entry, ``f1`` and ``f2`` are different LINE SEQUENTIAL FDs, and all three records are the same
  fixed length (sum of DISPLAY leaf items; no REDEFINES, OCCURS or non-DISPLAY usage);
* every key is an elementary item of the SD record: alphanumeric, or unsigned numeric DISPLAY (compared as
  digits, which is numeric order at equal width).

Everything else -- INPUT/OUTPUT PROCEDURE, several USING/GIVING files, COLLATING SEQUENCE, record-sequential
files, signed or binary keys, an unknown file -- fails closed with an unresolvable method name that names the
reason, so ``javac`` reports it instead of a sort running with different semantics.
"""

from __future__ import annotations


def _leaves(item, offset: int, out: dict, problems: list[str]) -> int:
    """Append ``name -> (offset, length, item)`` for the leaves of ``item``; returns the new offset."""
    if item.redefines:
        problems.append("REDEFINES")
    if item.occurs:
        problems.append("OCCURS")
    if item.children:
        for child in item.children:
            if child.level == 88:
                continue
            offset = _leaves(child, offset, out, problems)
        return offset
    if (item.usage or "").upper() not in ("", "DISPLAY"):
        problems.append("USAGE")
    if item.pic_length <= 0:
        problems.append("NO_PIC")
    out[item.name.upper()] = (offset, item.pic_length, item)
    return offset + item.pic_length


def layout(file_def) -> "tuple[dict, int] | None":
    """``({leaf name: (offset, length, item)}, record length)`` or ``None`` when not certifiable."""
    if len(file_def.record_groups) != 1:
        return None
    leaves: dict = {}
    problems: list[str] = []
    total = _leaves(file_def.record_groups[0], 0, leaves, problems)
    return (leaves, total) if not problems and total > 0 else None


def _file(program, name):
    from engine.transformation.cobol_to_java_mapping import _find_file_def

    return _find_file_def(program, name)


def unsupported_reasons(stmt, program) -> list[str]:
    reasons = list(stmt.reasons)
    if reasons:
        return reasons
    sd = _file(program, stmt.sort_file)
    using = _file(program, stmt.using[0])
    giving = _file(program, stmt.giving[0])
    if sd is None or not sd.is_sort_file:
        reasons.append("SD")
    if using is None or giving is None or using.is_sort_file or giving.is_sort_file:
        reasons.append("FILES")
    elif using.name.upper() == giving.name.upper():
        reasons.append("SAME_FILE")
    if reasons:
        return reasons
    for role, file_def in (("USING", using), ("GIVING", giving)):
        if file_def.record_sequential:
            reasons.append(f"{role}_RECORD_SEQUENTIAL")
    sd_layout, using_layout, giving_layout = layout(sd), layout(using), layout(giving)
    if sd_layout is None or using_layout is None or giving_layout is None:
        reasons.append("RECORD_LAYOUT")
    elif not sd_layout[1] == using_layout[1] == giving_layout[1]:
        reasons.append("RECORD_LENGTHS")
    if sd_layout is not None:
        for key, _ in stmt.keys:
            entry = sd_layout[0].get(key.upper())
            if entry is None:
                reasons.append("KEY_NOT_ELEMENTARY")
                continue
            item = entry[2]
            if item.is_numeric and (item.signed or item.decimal_places < 0):
                reasons.append("KEY_SIGNED")
    return list(dict.fromkeys(reasons))


def key_specs(stmt, program) -> tuple[str, ...]:
    sd_layout = layout(_file(program, stmt.sort_file))
    assert sd_layout is not None  # only called for a statement that passed unsupported_reasons
    specs = []
    for key, direction in stmt.keys:
        offset, length, _ = sd_layout[0][key.upper()]
        specs.append(f"{'D' if direction == 'DESCENDING' else 'A'}:{offset}:{length}")
    return tuple(specs)


def lower(stmt, program) -> list:
    from engine.transformation.cobol_to_java_mapping import _int_lit, _resolve_path, _str_lit
    from engine.transformation.java_ir import JavaComment, JavaMethodCall, JavaMethodCallStatement

    out: list = [JavaComment(text=f"SORT {stmt.sort_file}")]
    reasons = unsupported_reasons(stmt, program)
    if reasons:
        out.append(JavaMethodCallStatement(call=JavaMethodCall(
            class_name="CobolSort",
            method_name="UNSUPPORTED_SORT$" + "$".join(reasons),
            arguments=(),
            is_static=True,
        )))
        return out
    using = _file(program, stmt.using[0])
    giving = _file(program, stmt.giving[0])
    sd_layout = layout(_file(program, stmt.sort_file))
    assert sd_layout is not None  # unsupported_reasons already accepted the layout
    length = sd_layout[1]
    in_path, out_path = _resolve_path(using), _resolve_path(giving)
    if in_path is None or out_path is None:
        out.append(JavaMethodCallStatement(call=JavaMethodCall(
            class_name="CobolSort", method_name="UNSUPPORTED_SORT$FILE_PATH", arguments=(), is_static=True)))
        return out
    out.append(JavaMethodCallStatement(call=JavaMethodCall(
        class_name="CobolSort",
        method_name="run",
        arguments=(_str_lit(in_path), _str_lit(out_path), _int_lit(length),
                   *[_str_lit(spec) for spec in key_specs(stmt, program)]),
        is_static=True,
    )))
    return out

"""Lowering of ``SortStatement`` (SORT and MERGE) to ``CobolSort.run`` (roadmap unit 9).

Certified subset: ``SORT|MERGE sd ON ASCENDING|DESCENDING KEY k... USING f1 [f2...] GIVING g`` where

* ``sd`` is an SD entry, the USING files and ``g`` are different LINE SEQUENTIAL FDs, and all the records are the
  same fixed length (several USING files are concatenated in the order written, then sorted stably: GnuCOBOL's MERGE
  does exactly that, even for inputs that are not in key order) (sum of DISPLAY leaf items; no REDEFINES, OCCURS or non-DISPLAY usage);
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
    inputs = [_file(program, name) for name in stmt.using]
    giving = _file(program, stmt.giving[0])
    if sd is None or not sd.is_sort_file:
        reasons.append("SD")
    if giving is None or giving.is_sort_file or any(f is None or f.is_sort_file for f in inputs):
        reasons.append("FILES")
    elif any(f.name.upper() == giving.name.upper() for f in inputs):
        reasons.append("SAME_FILE")
    elif len({f.name.upper() for f in inputs}) != len(inputs):
        reasons.append("DUPLICATE_USING")
    if reasons:
        return reasons
    for role, file_def in [("USING", f) for f in inputs] + [("GIVING", giving)]:
        if file_def.record_sequential:
            reasons.append(f"{role}_RECORD_SEQUENTIAL")
        if ";" in (file_def.container_path or ""):
            reasons.append("PATH")
    sd_layout = layout(sd)
    others = [layout(f) for f in [*inputs, giving]]
    if sd_layout is None or any(entry is None for entry in others):
        reasons.append("RECORD_LAYOUT")
    elif any(entry[1] != sd_layout[1] for entry in others if entry is not None):
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

    out: list = [JavaComment(text=f"{stmt.kind} {stmt.sort_file}")]
    reasons = unsupported_reasons(stmt, program)
    if reasons:
        out.append(JavaMethodCallStatement(call=JavaMethodCall(
            class_name="CobolSort",
            method_name=f"UNSUPPORTED_{stmt.kind}$" + "$".join(reasons),
            arguments=(),
            is_static=True,
        )))
        return out
    giving = _file(program, stmt.giving[0])
    sd_layout = layout(_file(program, stmt.sort_file))
    assert sd_layout is not None  # unsupported_reasons already accepted the layout
    length = sd_layout[1]
    in_paths = [_resolve_path(_file(program, name)) for name in stmt.using]
    out_path = _resolve_path(giving)
    in_path = ";".join(p for p in in_paths if p is not None)
    if out_path is None or None in in_paths:
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

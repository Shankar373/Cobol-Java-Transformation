"""Qualified data names: ``field OF group`` / ``field IN group`` (roadmap unit 36).

Every data item becomes one Java field named after it, so two items that share a name used to be refused. COBOL allows
the same name under different groups and tells them apart by qualification. This pass runs on the cleaned source lines,
before the data and procedure divisions are parsed:

* each name that is declared more than once gets a deterministic unique name per declaration (``A-OF-REC``,
  ``A-OF-SUB-OF-REC``: the name and its ancestor chain), so no two items collide;
* each ``A OF G [OF H ...]`` in the procedure division is resolved against the declared ancestor chains and rewritten to
  the unique name of the one item it designates; a qualified reference to a name that is not duplicated drops its
  (valid) qualifier;
* an unqualified reference to a duplicated name, a qualification that matches no item or several items, and a
  duplicated name used in a data-division clause (REDEFINES, OCCURS DEPENDING ON, RENAMES ...) are left as they are, so
  the existing diagnostics keep refusing them (GnuCOBOL rejects the first two as ambiguous too).

Behaviour pinned by the GnuCOBOL 3.1.2 differential ``tests/integration/test_qualified_oracle.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DECLARATION = re.compile(r"^\s*(\d{1,2})\s+([A-Z0-9][\w-]*)(?=[\s.]|$)", re.IGNORECASE)
_QUALIFIED = re.compile(r"(?<![\w-])([A-Z0-9][\w-]*)((?:\s+(?:OF|IN)\s+[A-Z0-9][\w-]*)+)", re.IGNORECASE)
_QUALIFIER = re.compile(r"\s+(?:OF|IN)\s+([A-Z0-9][\w-]*)", re.IGNORECASE)
_CORRESPONDING_WORD = re.compile(r"(?<![\w-])CORR(?:ESPONDING)?(?![\w-])", re.IGNORECASE)
_PICTURE = re.compile(r"(?<![\w-])PIC(?:TURE)?\s+(?:IS\s+)?\S+", re.IGNORECASE)
_WORD = re.compile(r"(?<![\w-])[A-Z0-9][\w-]*", re.IGNORECASE)


@dataclass
class _Item:
    name: str  # upper-case declared name
    ancestors: tuple[str, ...]  # nearest parent first
    line: int
    unique: str = ""  # the name every reference is rewritten to
    parent: int = -1  # index of the enclosing group in the item list
    text: str = ""  # the declaration sentence (clauses may continue on following lines)
    children: list[int] | None = None  # item indexes, in source order (``None`` until the tree is built)


def _mask(text: str) -> str:
    """``text`` with the inside of quoted literals blanked (same length), so a literal is never rewritten."""
    out: list[str] = []
    quote = ""
    for char in text:
        if quote:
            out.append(char if char == quote else " ")
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            out.append(char)
        else:
            out.append(char)
    return "".join(out)


def _divisions(lines: list[str]) -> tuple[int, int]:
    """Index of the first DATA DIVISION line and of the PROCEDURE DIVISION line (``-1`` when absent)."""
    data = procedure = -1
    for index, line in enumerate(lines):
        upper = line.strip().upper()
        if data < 0 and upper.startswith("DATA DIVISION"):
            data = index
        elif procedure < 0 and upper.startswith("PROCEDURE DIVISION"):
            procedure = index
    return data, procedure


_CORRESPONDING = re.compile(
    r"^(\s*)(MOVE|ADD|SUBTRACT)\s+(?:CORRESPONDING|CORR)\s+(.+?)\s+(TO|FROM)\s+(.+?)(\.?)\s*$", re.IGNORECASE)
_OPERAND = re.compile(r"^([A-Z0-9][\w-]*)((?:\s+(?:OF|IN)\s+[A-Z0-9][\w-]*)*)$", re.IGNORECASE)
_NOT_CORRESPONDING = re.compile(r"\b(?:OCCURS|REDEFINES|RENAMES)\b", re.IGNORECASE)


_NUMERIC_PICTURE = re.compile(r"PIC(?:TURE)?\s+(?:IS\s+)?S?[9V]+(?:\(\d+\))?[9V]*(?:\(\d+\))?[9V]*\s*(?:\.|$|\s)", re.IGNORECASE)


def _is_numeric(item: _Item) -> bool:
    """An elementary DISPLAY numeric item (a plain ``9`` / ``S9`` / ``V`` picture, no USAGE clause)."""
    return bool(_NUMERIC_PICTURE.search(item.text)) and not re.search(
        r"(?:COMP|COMPUTATIONAL|BINARY|PACKED|SIGN|USAGE)", item.text, re.IGNORECASE)


_QUALIFIER_CHAIN = re.compile(r"^\s*([A-Z0-9][\w-]*(?:\s+(?:OF|IN)\s+[A-Z0-9][\w-]*)*)(.*)$", re.IGNORECASE)
_LEADING_QUALIFIER = re.compile(r"^(\s*)((?:OF|IN)\s+[A-Z0-9][\w-]*(?:\s+(?:OF|IN)\s+[A-Z0-9][\w-]*)*)(.*)$", re.IGNORECASE)


def _join_split_qualifiers(lines: list[str], by_name: dict[str, list[_Item]]) -> list[str]:
    """Move an ``OF name`` that starts a line back onto the previous line when that line ends with a data name.

    A qualified reference may be wrapped between the name and its qualifier (``AMT`` / ``OF GRP1``); the resolver reads
    one line at a time, so the two halves are put back together first.
    """
    out: list[str] = []
    for line in lines:
        if out:
            tail = _mask(out[-1]).split()
            if len(tail) >= 2 and tail[-1].upper() in ("OF", "IN") and tail[-2].upper() in by_name and line.strip():
                chain = _QUALIFIER_CHAIN.match(line)
                if chain is not None:
                    out[-1] = out[-1].rstrip() + " " + chain.group(1)
                    if chain.group(2).strip():
                        out.append(line[: len(line) - len(line.lstrip())] + chain.group(2).lstrip())
                    continue
        found = _LEADING_QUALIFIER.match(line)
        if found is not None and out:
            tokens = _mask(out[-1]).split()
            if tokens and tokens[-1].rstrip(".").upper() in by_name and not tokens[-1].endswith("."):
                out[-1] = out[-1].rstrip() + " " + found.group(2)
                rest = found.group(3)
                if rest.strip():
                    out.append(found.group(1) + rest.lstrip())
                continue
        out.append(line)
    return out


def _group_of(operand: str, items: list[_Item], by_name: dict[str, list[_Item]]) -> int | None:
    """Index of the group item an operand (``G`` or ``G OF H``) names, ``None`` unless exactly one matches."""
    found = _OPERAND.match(operand.strip())
    if found is None:
        return None
    name = found.group(1).upper()
    qualifiers = [q.group(1).upper() for q in _QUALIFIER.finditer(found.group(2))]
    matches = []
    for item in by_name.get(name, []):
        chain = list(item.ancestors)
        position = 0
        for qualifier in qualifiers:
            try:
                position = chain.index(qualifier, position) + 1
            except ValueError:
                break
        else:
            matches.append(item)
    if len(matches) != 1:
        return None
    return items.index(matches[0])


def _corresponding_pairs(
    source: int, target: int, items: list[_Item], source_path: tuple[str, ...], target_path: tuple[str, ...],
    pairs: list[tuple[tuple[str, ...], tuple[str, ...], _Item, _Item]],
) -> str:
    """Fill ``pairs`` with the elementary items of two groups that correspond; returns a refusal reason or ``""``.

    Items correspond when they have the same name and the same qualification below the two groups. Both elementary:
    a pair. Both groups: recursion. One of each, or an item with OCCURS / REDEFINES: the statement is refused.
    """
    source_item, target_item = items[source], items[target]
    for child in source_item.children or []:
        a = items[child]
        if a.name == "FILLER":
            continue
        match = next((c for c in (target_item.children or []) if items[c].name == a.name), None)
        if match is None:
            continue
        b = items[match]
        for item in (a, b):
            if _NOT_CORRESPONDING.search(item.text):
                return f"{item.name} has OCCURS or REDEFINES"
        a_group, b_group = bool(a.children), bool(b.children)
        if a_group != b_group:
            return f"{a.name} is a group in one operand and elementary in the other"
        if a_group:
            reason = _corresponding_pairs(
                child, match, items, (*source_path, a.name), (*target_path, b.name), pairs)
            if reason:
                return reason
        else:
            pairs.append(((*source_path, a.name), (*target_path, b.name), a, b))
    return ""


def _expand_corresponding(line: str, items: list[_Item], by_name: dict[str, list[_Item]], problems: list[str]) -> list[str]:
    """``MOVE / ADD / SUBTRACT CORRESPONDING a TO|FROM b`` as one plain statement per corresponding elementary pair."""
    found = _CORRESPONDING.match(line)
    if found is None:
        return [line]
    indent, verb, left, preposition, right, period = found.groups()
    verb = verb.upper()
    if (verb == "SUBTRACT") != (preposition.upper() == "FROM"):
        return [line]
    if re.search(r"\b(?:ROUNDED|ON\s+SIZE\s+ERROR|SIZE\s+ERROR)\b", right, re.IGNORECASE):
        problems.append(f"{verb} CORRESPONDING with ROUNDED or SIZE ERROR is not lowered")
        return [line]
    source = _group_of(left, items, by_name)
    target = _group_of(right, items, by_name)
    if source is None or target is None or not items[source].children or not items[target].children:
        problems.append(f"{verb} CORRESPONDING operands must each name one group item ({left} / {right})")
        return [line]
    pairs: list[tuple[tuple[str, ...], tuple[str, ...], _Item, _Item]] = []
    reason = _corresponding_pairs(source, target, items, (), (), pairs)
    if reason:
        problems.append(f"{verb} CORRESPONDING {left} {preposition} {right}: {reason}")
        return [line]
    if verb != "MOVE":
        # ADD / SUBTRACT CORRESPONDING work on the pairs of which both items are numeric; the others are skipped
        pairs = [pair for pair in pairs if _is_numeric(pair[2]) and _is_numeric(pair[3])]
    if not pairs:
        problems.append(f"{verb} CORRESPONDING {left} {preposition} {right}: no corresponding items")
        return [line]

    def reference(path: tuple[str, ...], group_text: str) -> str:
        # leaf OF subgroup ... OF group-operand (the operand's own qualifiers follow it unchanged)
        return " OF ".join((*reversed(path), group_text))

    out = []
    for index, (a_path, b_path, _a, _b) in enumerate(pairs):
        a, b = reference(a_path, left.strip()), reference(b_path, right.strip())
        end = period if index == len(pairs) - 1 else ""
        if verb == "MOVE":
            out.append(f"{indent}MOVE {a} TO {b}{end}")
        elif verb == "ADD":
            out.append(f"{indent}ADD {a} TO {b}{end}")
        else:
            out.append(f"{indent}SUBTRACT {a} FROM {b}{end}")
    return out


def resolve_qualified_names(lines: list[str]) -> tuple[list[str], list[str]]:
    """The source lines with duplicated names made unique and qualified references resolved, and the problems found."""
    data, procedure = _divisions(lines)
    if data < 0 or procedure < 0 or procedure < data:
        return lines, []
    items: list[_Item] = []
    stack: list[tuple[int, str, int]] = []
    declaration_lines: dict[int, str] = {}
    for index in range(data + 1, procedure):
        found = _DECLARATION.match(lines[index])
        if found is None:
            continue
        level, name = int(found.group(1)), found.group(2).upper()
        if level in (66, 88):
            continue
        if level == 77:
            stack = []
        else:
            while stack and stack[-1][0] >= level:
                stack.pop()
        declaration_lines[index] = name
        sentence = lines[index]
        scan = index
        while not sentence.rstrip().endswith(".") and scan + 1 < procedure and scan - index < 20:
            scan += 1
            sentence += " " + lines[scan].strip()
        items.append(_Item(
            name=name, ancestors=tuple(n for _, n, _ in reversed(stack)), line=index,
            parent=stack[-1][2] if stack else -1, text=sentence))
        if level != 77:
            stack.append((level, name, len(items) - 1))

    by_name: dict[str, list[_Item]] = {}
    for item in items:
        if item.name != "FILLER":
            by_name.setdefault(item.name, []).append(item)
    duplicated = {name for name, group in by_name.items() if len(group) > 1}
    # a duplicated name that a data-division clause names (REDEFINES X, DEPENDING ON X, ...) stays refused
    for index in range(data + 1, procedure):
        # the picture string is not a name (``PIC X(4)`` must not count as a use of a field called X)
        masked = _PICTURE.sub(" ", _mask(lines[index]))
        declared = declaration_lines.get(index)
        seen_declared = False
        for word in _WORD.finditer(masked):
            token = word.group(0).upper()
            if token in duplicated:
                if token == declared and not seen_declared:
                    seen_declared = True
                    continue
                duplicated.discard(token)
    if not by_name:
        return lines, []

    taken = {item.name for item in items}
    for name in duplicated:
        for item in by_name[name]:
            candidate = "-OF-".join((name, *item.ancestors))
            while candidate in taken:
                candidate += "-X"
            taken.add(candidate)
            item.unique = candidate
    for name, group in by_name.items():
        if name not in duplicated:
            group[0].unique = name

    problems: list[str] = []
    result = list(lines)
    for index, item in ((i.line, i) for i in items if i.name in duplicated):
        found = _DECLARATION.match(result[index])
        assert found is not None
        result[index] = result[index][: found.start(2)] + item.unique + result[index][found.end(2):]

    def resolve(name: str, qualifiers: list[str]) -> str | None:
        candidates = by_name.get(name.upper())
        if not candidates:
            return None
        matches = []
        for item in candidates:
            chain = list(item.ancestors)
            position = 0
            for qualifier in qualifiers:
                try:
                    position = chain.index(qualifier.upper(), position) + 1
                except ValueError:
                    break
            else:
                matches.append(item)
        if len(matches) != 1:
            problems.append(
                f"Qualified name {name} OF {' OF '.join(qualifiers)} designates {len(matches)} data items: "
                "only an unambiguous qualification is lowered")
            return None
        return matches[0].unique or None

    for position, item in enumerate(items):
        if item.parent >= 0:
            parent = items[item.parent]
            if parent.children is None:
                parent.children = []
            parent.children.append(position)
    expanded: list[str] = []
    for line in _join_split_qualifiers(result[procedure:], by_name):
        expanded.extend(_expand_corresponding(line, items, by_name, problems))
    result = result[:procedure] + expanded

    for index in range(procedure, len(result)):
        line = result[index]
        masked = _mask(line)
        pieces: list[str] = []
        cursor = 0
        for found in _QUALIFIED.finditer(masked):
            qualifiers = [q.group(1) for q in _QUALIFIER.finditer(found.group(2))]
            target = resolve(found.group(1), qualifiers)
            if target is None:
                continue
            pieces.append(line[cursor:found.start()])
            pieces.append(target)
            cursor = found.end()
        if pieces:
            result[index] = "".join(pieces) + line[cursor:]

    # a CORRESPONDING the expansion did not take (wrapped over several lines, ROUNDED, nested in another statement)
    # must not reach the parser, which would read it as a plain group MOVE or ADD
    for index in range(procedure, len(result)):
        if "CORR" in result[index].upper() and _CORRESPONDING_WORD.search(_mask(result[index])) and not (
                {"CORR", "CORRESPONDING"} & set(by_name)):
            problems.append(
                "CORRESPONDING is lowered only as a single-line MOVE / ADD / SUBTRACT between two groups "
                f"({result[index].strip()[:60]})")
    leftover = sorted(duplicated)
    if leftover:
        for index in range(procedure, len(result)):
            masked = _mask(result[index])
            for word in _WORD.finditer(masked):
                if word.group(0).upper() in duplicated and word.group(0).upper() in leftover:
                    problems.append(
                        f"Data name {word.group(0).upper()} is declared more than once and referenced without a "
                        "(resolvable) qualification")
                    leftover.remove(word.group(0).upper())
    return result, problems

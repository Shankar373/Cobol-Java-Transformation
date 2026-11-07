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
_WORD = re.compile(r"(?<![\w-])[A-Z0-9][\w-]*", re.IGNORECASE)


@dataclass
class _Item:
    name: str  # upper-case declared name
    ancestors: tuple[str, ...]  # nearest parent first
    line: int
    unique: str = ""  # the name every reference is rewritten to


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


def resolve_qualified_names(lines: list[str]) -> tuple[list[str], list[str]]:
    """The source lines with duplicated names made unique and qualified references resolved, and the problems found."""
    data, procedure = _divisions(lines)
    if data < 0 or procedure < 0 or procedure < data:
        return lines, []
    items: list[_Item] = []
    stack: list[tuple[int, str]] = []
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
        items.append(_Item(name=name, ancestors=tuple(n for _, n in reversed(stack)), line=index))
        if level != 77:
            stack.append((level, name))

    by_name: dict[str, list[_Item]] = {}
    for item in items:
        if item.name != "FILLER":
            by_name.setdefault(item.name, []).append(item)
    duplicated = {name for name, group in by_name.items() if len(group) > 1}
    # a duplicated name that a data-division clause names (REDEFINES X, DEPENDING ON X, ...) stays refused
    for index in range(data + 1, procedure):
        masked = _mask(lines[index])
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

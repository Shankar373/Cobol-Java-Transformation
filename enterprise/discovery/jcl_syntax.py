"""JCL statement reader: continuation, comments, in-stream data, operand splitting and symbol substitution.

The reader is a lexer, not an interpreter: it produces statements with their position and the in-stream data bodies
(``DD *``) that follow them, and leaves meaning to :mod:`scan_jcl`.  It never expands procedures from outside the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SEQUENCE = re.compile(r"^.{72}\d{8}\s*$|^.{72}[A-Za-z0-9 ]{8}$")
_SYMBOL = re.compile(r"&([A-Za-z#@$][A-Za-z0-9#@$]{0,7})(\.?)")
_NAME_OK = re.compile(r"^[A-Za-z#@$][A-Za-z0-9#@$]{0,7}$")


@dataclass
class Statement:
    """One JCL statement (continuations folded)."""

    line: int
    name: str
    op: str
    operands: str
    #: For ``DD *`` / ``DD DATA``: the in-stream text and the line it starts on.
    data: list[tuple[int, str]] = field(default_factory=list)


def _clean(raw: str) -> str:
    line = raw.rstrip("\r\n").expandtabs(8)
    if len(line) >= 80 and line[72:80].strip().isdigit():
        line = line[:72]
    return line.rstrip()


def split_top(text: str, separator: str = ",") -> list[str]:
    """Split on ``separator`` outside quotes and parentheses."""
    parts, depth, quote, current = [], 0, "", []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
        elif ch == "'":
            quote = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(depth - 1, 0)
            current.append(ch)
        elif ch == separator and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _operand_field(rest: str) -> tuple[str, bool]:
    """``(operands, continued)``: the text up to the first blank outside quotes/parentheses, and whether it ends in a comma."""
    depth, quote, end = 0, "", len(rest)
    for index, ch in enumerate(rest):
        if quote:
            if ch == quote:
                quote = ""
        elif ch == "'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif ch == " " and depth == 0:
            end = index
            break
    operands = rest[:end]
    return operands, operands.endswith(",")


def read_statements(text: str) -> tuple[list[Statement], int, list[tuple[int, str]]]:
    """``(statements, comment_lines, problems)``; problems are ``(line, message)`` for malformed constructs."""
    lines = [_clean(raw) for raw in text.splitlines()]
    statements: list[Statement] = []
    problems: list[tuple[int, str]] = []
    comments = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        number = index + 1
        index += 1
        if line.startswith("//*"):
            comments += 1
            continue
        if line.startswith("/*") or not line.startswith("//") or line.strip() == "//":
            continue
        body = line[2:]
        if body[:1] == " ":
            name, rest = "", body.lstrip()
        else:
            name, _, rest = body.partition(" ")
            rest = rest.lstrip()
        op, _, remainder = rest.partition(" ")
        op = op.upper()
        remainder = remainder.lstrip()
        operands, continued = _operand_field(remainder)
        while continued and index < len(lines) and lines[index].startswith("//") and not lines[index].startswith("//*"):
            follow = lines[index][2:].lstrip()
            index += 1
            more, continued = _operand_field(follow)
            operands += more
        if name and not _NAME_OK.match(name.split(".")[0]) and not name.startswith("*"):
            problems.append((number, f"JCL name {name[:12]!r} is not a valid 1-8 character name"))
        statement = Statement(number, name, op, operands)
        if op == "DD" and re.match(r"^(\*|DATA)(,|$)", operands.upper()):
            statement.data, index = _read_instream(lines, index, operands)
        statements.append(statement)
    return statements, comments, problems


def _read_instream(lines: list[str], index: int, operands: str) -> tuple[list[tuple[int, str]], int]:
    delimiter = "/*"
    match = re.search(r"DLM=(?:'([^']+)'|(\S{2}))", operands.upper())
    if match:
        delimiter = match.group(1) or match.group(2)
    is_data = operands.upper().startswith("DATA")
    body: list[tuple[int, str]] = []
    while index < len(lines):
        line = lines[index]
        if line.startswith(delimiter) or (not is_data and line.startswith("//") and delimiter == "/*"):
            if line.startswith(delimiter):
                index += 1
            break
        body.append((index + 1, line))
        index += 1
    return body, index


def parse_operands(text: str) -> list[tuple[str, str]]:
    """``[(KEY, value)]``; positional operands have an empty key."""
    out = []
    for item in split_top(text):
        key, equals, value = item.partition("=")
        if equals and re.match(r"^[A-Za-z#@$][A-Za-z0-9#@$-]*$", key.strip()):
            out.append((key.strip().upper(), value.strip()))
        else:
            out.append(("", item))
    return out


def operand(operands: list[tuple[str, str]], key: str) -> str:
    return next((value for k, value in operands if k == key), "")


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def substitute(value: str, symbols: dict[str, str]) -> tuple[str, list[str]]:
    """Replace ``&NAME.`` / ``&NAME`` using ``symbols``; return ``(text, names still unresolved)``.

    ``&&NAME`` is a temporary-dataset marker, not a symbol, and is left alone.
    """
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        start = match.start()
        if start > 0 and value[start - 1] == "&":
            return match.group(0)
        name = match.group(1).upper()
        if name in symbols:
            return symbols[name]
        missing.append(name)
        return match.group(0)

    return _SYMBOL.sub(replace, value), sorted(set(missing))

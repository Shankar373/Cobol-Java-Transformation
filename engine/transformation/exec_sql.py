"""EXEC SQL regions as IR: statement kind, host variables and their direction, WHENEVER, INCLUDE.

An ``EXEC SQL ... END-EXEC`` region is one COBOL statement.  Before this module the statement
parser did not know the region: a ``SELECT`` vanished and the ``DELETE`` / ``OPEN`` inside it
were parsed as COBOL file verbs.  The region is now captured whole, as an ``ExecSqlStatement``;
no Java mapping exists for it, so the mapper and the capability analysis still refuse it
(roadmap unit 10 produces the IR; unit 12 lowers a supported subset).
"""

from __future__ import annotations

import re

_STRING = re.compile(r"'(?:[^']|'')*'")
_HOST = re.compile(
    r":([A-Za-z][A-Za-z0-9-]*)(?:\s+INDICATOR)?(?:\s*:\s*([A-Za-z][A-Za-z0-9-]*))?",
    re.IGNORECASE)
_INTO = re.compile(
    r"\bINTO\b(.*?)(?=\bFROM\b|\bWHERE\b|\bVALUES\b|\bFOR\b|$)", re.IGNORECASE | re.DOTALL)
_WHENEVER = re.compile(
    r"^WHENEVER\s+(NOT\s+FOUND|SQLERROR|SQLWARNING)\s+"
    r"(CONTINUE|GO\s*TO\s+([A-Za-z0-9-]+)|GOTO\s+([A-Za-z0-9-]+))\s*$",
    re.IGNORECASE)
_INCLUDE = re.compile(r"^INCLUDE\s+([A-Za-z0-9-]+)\s*$", re.IGNORECASE)
_KINDS = ("SELECT", "INSERT", "UPDATE", "DELETE", "DECLARE", "OPEN", "FETCH", "CLOSE", "COMMIT",
          "ROLLBACK", "PREPARE", "EXECUTE", "CALL", "WHENEVER", "INCLUDE", "SET", "LOCK", "GRANT",
          "CONNECT", "SAVEPOINT", "RELEASE", "DESCRIBE", "VALUES", "MERGE", "TRUNCATE", "BEGIN",
          "END")


def classify(sql_text: str) -> dict:
    """Facts about one region's SQL text (without the EXEC SQL / END-EXEC markers)."""
    text = " ".join(sql_text.split())
    cleaned = _STRING.sub("''", text)
    words = cleaned.split(None, 1)
    first = words[0].upper().rstrip(";") if words else ""
    kind = first if first in _KINDS else "OTHER"
    if kind == "DECLARE" and re.search(r"\bCURSOR\b", cleaned, re.IGNORECASE):
        kind = "DECLARE_CURSOR"
    outputs: list[str] = []
    indicators: list[str] = []
    for match in _INTO.finditer(cleaned):
        for host in _HOST.finditer(match.group(1)):
            outputs.append(host.group(1).upper())
            if host.group(2):
                indicators.append(host.group(2).upper())
    inputs: list[str] = []
    stripped = _INTO.sub(" ", cleaned)
    for host in _HOST.finditer(stripped):
        inputs.append(host.group(1).upper())
        if host.group(2):
            indicators.append(host.group(2).upper())
    whenever: tuple[str, ...] = ()
    include = ""
    bare = cleaned.strip().rstrip(";")
    if kind == "WHENEVER":
        m = _WHENEVER.match(bare)
        if m:
            target = (m.group(3) or m.group(4) or "").upper()
            whenever = (re.sub(r"\s+", " ", m.group(1).upper()),
                        "GOTO" if target else "CONTINUE", target)
    if kind == "INCLUDE":
        m = _INCLUDE.match(bare)
        include = m.group(1).upper() if m else ""
    return {
        "kind": kind,
        "inputs": tuple(dict.fromkeys(inputs)),
        "outputs": tuple(dict.fromkeys(outputs)),
        "indicators": tuple(dict.fromkeys(indicators)),
        "whenever": whenever,
        "include": include,
    }


_INCLUDE_REGION = re.compile(
    r"\bEXEC\s+SQL\s+INCLUDE\s+([A-Za-z0-9-]+)\s+END-EXEC", re.IGNORECASE)


def find_includes(code_lines: list[str]) -> tuple[str, ...]:
    """``EXEC SQL INCLUDE <member>`` members in source order (``SQLCA``, DCLGEN members)."""
    text = " ".join(" ".join(line.split()) for line in code_lines)
    return tuple(dict.fromkeys(m.group(1).upper() for m in _INCLUDE_REGION.finditer(text)))


def collect_region(lines: list[str], start: int) -> tuple[str, int, bool]:
    """Join lines from ``EXEC SQL`` to ``END-EXEC``: ``(sql_text, next_index, terminated)``.

    An unterminated region runs to the end of the input and is reported by the caller.
    """
    body = re.sub(r"^EXEC\s+SQL\b", "", lines[start].strip(), flags=re.IGNORECASE)
    parts: list[str] = []
    i = start
    while True:
        end = re.search(r"\bEND-EXEC\b", body, re.IGNORECASE)
        if end:
            parts.append(body[: end.start()])
            return " ".join(p.strip() for p in parts if p.strip()), i + 1, True
        parts.append(body)
        i += 1
        if i >= len(lines):
            return " ".join(p.strip() for p in parts if p.strip()), i, False
        body = lines[i].strip()

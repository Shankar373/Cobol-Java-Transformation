"""COBOL reference-format reading shared by the oracle and the parser: the engine face of the one reader.

Layer 4 (P2): ``enterprise.discovery.cobol_text.read_source`` is the single reference-format reader —
format directives (``>>SOURCE FORMAT``, Micro Focus ``$SET SOURCEFORMAT``), mid-file switches,
compiler cards, debug lines and continuation folding are decided there and nowhere else.  This module
renders the text the compiler sees from those decisions and keeps the engine's strict fail-closed
errors (a continuation that continues nothing, an open literal not resumed by a quote, a literal
holding both quote characters).  Discovery and the parser therefore read the same bytes at the same
positions (layer model, contract 3): a file with a mid-file switch, a ``$SET`` card or a ``CBL`` card
is read per line, never re-detected here.

In fixed format the compiler ignores the program-identification area — every column after 72 — so the
parser drops it too; otherwise it would translate characters the compiled COBOL program never contains
(e.g. a data name cut at column 72, or sequence numbers in columns 73-80).
"""

from __future__ import annotations

import re

from enterprise.discovery.cobol_text import (
    FIXED_TEXT_END,
    format_from_directive,
    read_source,
)

#: Last column of the fixed-format program text area (Area B ends here).
FIXED_FORMAT_TEXT_END = FIXED_TEXT_END


def _line_is_comment(line: str) -> bool:
    """True for fixed- or free-format comment lines."""
    if line.startswith("*") or line.startswith("/"):
        return True
    if len(line) > 6 and line[6] in "*/":
        return True
    return line.lstrip().startswith("*>")


def detect_source_format(text: str) -> str:
    """Classify COBOL source text as ``"free"`` or ``"fixed"`` — the file's *start* format.

    The decision comes from the single reader (:func:`enterprise.discovery.cobol_text.detect_format`):
    a format directive before any code wins, else a code character in columns 1-6 means free.
    Compiler cards and ``$SET`` lines are directives, never code, so they never decide the format.

    A ``$SET SOURCEFORMAT VARIABLE`` file maps to the fixed flag for the compiler command line only:
    the named refusal ``REFERENCE_FORMAT_VARIABLE_UNSUPPORTED`` is reported by
    :func:`reference_format_errors`, so it is never silently read as fixed.
    """
    return "free" if read_source(text).start_format == "free" else "fixed"


def _open_quote(text: str) -> str | None:
    """Quote character of an alphanumeric literal still open at the end of
    ``text`` (program-text columns only), else ``None``.  A doubled quote
    inside a literal (``'IT''S'``) closes and reopens it, which leaves the
    state unchanged — exactly the COBOL escaping rule."""
    quote: str | None = None
    for ch in text:
        if quote is None:
            if ch in "\"'":
                quote = ch
        elif ch == quote:
            quote = None
    return quote


def code_mentions(text: str, word: str) -> bool:
    """True when ``word`` occurs as a COBOL word in program code — not inside
    a literal, a comment line or an inline ``*>`` comment.  ``text`` is read
    the way the compiler reads it (:func:`compiler_visible_text`)."""
    pattern = re.compile(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", re.IGNORECASE)
    for line in compiler_visible_text(text).split("\n"):
        if _line_is_comment(line):
            continue
        code = re.sub(r"\"[^\"]*\"|'[^']*'", "''", line).split("*>", 1)[0]
        if pattern.search(code):
            return True
    return False


def unquote_literal(text: str) -> str:
    """Value of a quoted literal (canonical spelling, see
    :func:`_canonical_literals`), or ``text`` unchanged when it is not one.

    Only the matching delimiters are removed: ``'SAY "HI"'`` is
    ``SAY "HI"`` — stripping every quote character from both ends would
    eat the value's own trailing quote.
    """
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _canonical_literals(code: str) -> tuple[str, str | None]:
    """Rewrite literals that use the doubled-quote escape.

    COBOL writes a quote inside a literal by doubling it: ``'IT''S'`` is
    ``IT'S``.  Downstream tokenizers only know literals without escapes, so
    such a literal is re-delimited with the other quote character
    (``"IT'S"``) — the same value in a form every consumer reads correctly.
    A literal whose value holds both quote characters has no such form and
    is reported (fail closed).  Literals without a doubled quote, inline
    ``*>`` comments and an unterminated literal are left as written.
    Returns the rewritten text and an error, if any.
    """
    out: list[str] = []
    i = 0
    while i < len(code):
        ch = code[i]
        if ch == "*" and code.startswith("*>", i):
            out.append(code[i:])
            break
        if ch not in "\"'":
            out.append(ch)
            i += 1
            continue
        j = i + 1
        value: list[str] = []
        while j < len(code):
            if code[j] == ch:
                if code.startswith(ch * 2, j):
                    value.append(ch)
                    j += 2
                    continue
                break
            value.append(code[j])
            j += 1
        if j >= len(code):  # unterminated: leave the rest as written
            out.append(code[i:])
            break
        written = code[i:j + 1]
        text = "".join(value)
        if ch not in text:
            out.append(written)
        else:
            other = "'" if ch == '"' else '"'
            if other in text:
                return code, (
                    f"literal {written} holds both quote characters; no "
                    "certified Java form"
                )
            out.append(other + text + other)
        i = j + 1
    return "".join(out), None


def _variable_line(text: str) -> int:
    """1-based line of the ``$SET SOURCEFORMAT VARIABLE`` directive (``0`` when none)."""
    for number, raw in enumerate(text.split("\n"), start=1):
        if format_from_directive(raw) == "variable":
            return number
    return 0


def _normalize(text: str) -> tuple[list[str], list[str]]:
    """Compiler-visible lines plus every reference-format problem found (by name).

    One pass over the decisions of the single reader (:func:`read_source`):

    * per-line format — a fixed segment is sliced to columns 1-72 and folded;
      a free segment is kept whole; ``>>SOURCE``/``$SET``/card lines are dropped
      (never statements, layer 4 acceptance criterion 4) while keeping the line
      count so diagnostics keep their line numbers;
    * continuation folding with the strict GnuCOBOL 3.1.2 rules and errors —
      an anchor is a real program-text line (never a directive, card or comment);
    * doubled-quote literals canonicalised per line, in the segment's format.
    """
    read = read_source(text)
    errors: list[str] = []
    if read.format == "variable":
        errors.append(
            f"line {_variable_line(text)}: REFERENCE_FORMAT_VARIABLE_UNSUPPORTED: "
            "$SET SOURCEFORMAT VARIABLE is not supported: refused by name, never read as fixed"
        )
    raw_lines = text.split("\n")
    # The active format of every physical line: the start format, updated by each switch in line order.
    line_formats: list[str] = []
    current = read.start_format
    switches = dict(read.switches)
    for number in range(1, len(raw_lines) + 1):
        if number in switches:
            current = switches[number]
        line_formats.append(current)
    lines: list[str] = [
        raw.rstrip("\r")[:FIXED_FORMAT_TEXT_END] if line_formats[number] == "fixed" else raw
        for number, raw in enumerate(raw_lines)
    ]
    # Directives, cards and dead conditional branches are never statements: drop them from the
    # compiler-visible text (line count kept so diagnostics keep their line numbers).
    dropped = {number for number, kind in read.skipped if kind in ("directive", "card", "dead-branch")}
    for number in dropped:
        lines[number - 1] = ""
    # A directive/card/comment/dead line is not program text: it never anchors a continuation.
    not_anchor = {number for number, kind in read.skipped
                  if kind in ("directive", "card", "comment", "dead-branch")}
    last_code: int | None = None
    for number, line in enumerate(lines):
        if line_formats[number] != "fixed":
            continue  # free-format segments have no continuation indicator
        indicator = line[6] if len(line) > 6 else " "
        if indicator != "-":
            if line[7:].strip() and indicator not in "*/" and (number + 1) not in not_anchor:
                last_code = number
            continue
        resumed = line[7:].lstrip()
        if last_code is None:
            errors.append(f"line {number + 1}: continuation line with nothing to continue")
            continue
        continued = lines[last_code]
        quote = _open_quote(continued[7:])
        if quote is not None:
            if not resumed.startswith(quote):
                errors.append(
                    f"line {number + 1}: continuation of an open literal must "
                    f"resume with {quote}"
                )
                continue
            lines[last_code] = continued.ljust(FIXED_FORMAT_TEXT_END) + resumed[1:]
        else:
            lines[last_code] = continued.rstrip() + resumed
        lines[number] = ""
    for number, line in enumerate(lines):
        code_from = 7 if line_formats[number] == "fixed" else 0
        if _line_is_comment(line) or not line[code_from:].strip():
            continue
        code, error = _canonical_literals(line[code_from:])
        if error is not None:
            errors.append(f"line {number + 1}: {error}")
        lines[number] = line[:code_from] + code
    return lines, errors


def reference_format_errors(text: str) -> list[str]:
    """Problems that stop ``text`` from being read faithfully: malformed
    fixed-format continuation lines, literals holding both quote characters
    and the named ``REFERENCE_FORMAT_VARIABLE_UNSUPPORTED`` refusal.  Empty
    when there are none."""
    return _normalize(text)[1]


def compiler_visible_text(text: str) -> str:
    """The source text the compiler reads, in a canonical spelling.

    Rendered from the single reader's decisions: fixed segments keep columns
    1-72 with continuation lines folded (see :func:`_normalize`), free segments
    are kept whole, ``>>SOURCE``/``$SET``/compiler-card lines are dropped, and
    in both formats literals using the doubled-quote escape are re-delimited
    (see :func:`_canonical_literals`).  Line structure is preserved so
    diagnostics keep their line numbers.
    """
    return "\n".join(_normalize(text)[0])

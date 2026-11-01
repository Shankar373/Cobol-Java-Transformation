"""COBOL reference-format detection shared by the oracle and the parser.

The oracle compiles a source as free format only when it looks free format
(``DockerOracleAdapter.detect_source_format`` delegates here), and the
parser must read the same text the compiler reads.  In fixed format the
compiler ignores the program-identification area — every column after 72 —
so the parser drops it too; otherwise it would translate characters the
compiled COBOL program never contains (e.g. a data name cut at column 72,
or sequence numbers in columns 73-80).
"""

from __future__ import annotations

import re

#: Last column of the fixed-format program text area (Area B ends here).
FIXED_FORMAT_TEXT_END = 72


def _line_is_comment(line: str) -> bool:
    """True for fixed- or free-format comment lines."""
    if line.startswith("*") or line.startswith("/"):
        return True
    if len(line) > 6 and line[6] in "*/":
        return True
    return line.lstrip().startswith("*>")


def detect_source_format(text: str) -> str:
    """Classify COBOL source text as ``"free"`` or ``"fixed"``.

    An explicit ``>>SOURCE FORMAT`` directive takes precedence. In its
    absence fixed format is assumed unless a code line places a
    non-digit, non-space character in the sequence area (columns 1-6):
    that is impossible in fixed format and is characteristic of free
    format, where code may begin at column 1.
    """
    for raw in text.splitlines():
        upper = raw.strip().upper()
        if upper.startswith(">>SOURCE") and "FORMAT" in upper:
            if "FREE" in upper:
                return "free"
            if "FIXED" in upper:
                return "fixed"
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip() or _line_is_comment(line):
            continue
        if any(ch not in "0123456789 " for ch in line[:6]):
            return "free"
    return "fixed"


#: Column-7 indicator of a fixed-format continuation line.
_CONTINUATION = "-"


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


def _fold_continuations(text: str) -> tuple[list[str], list[str]]:
    """Fixed-format lines (columns 1-72) with continuation lines folded in.

    GnuCOBOL 3.1.2 rules (``tests/transformation/
    test_fixed_format_continuation.py``):

    * an alphanumeric literal open at the end of the continued line runs
      through column 72 — its trailing spaces are part of the literal — and
      resumes after the first quote of the continuation line;
    * any other text continues with the continuation line's first non-blank
      character, with no space in between.

    The continuation line itself becomes blank, so line numbers are kept.
    Returns the lines and a description of every malformed continuation
    (nothing to continue; an open literal not resumed by a quote).
    """
    lines = [line.rstrip("\r")[:FIXED_FORMAT_TEXT_END] for line in text.split("\n")]
    errors: list[str] = []
    last_code: int | None = None
    for number, line in enumerate(lines):
        indicator = line[6] if len(line) > 6 else " "
        if indicator != _CONTINUATION:
            if line[7:].strip() and indicator not in "*/":
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
    return lines, errors


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


def _normalize(text: str) -> tuple[list[str], list[str]]:
    """Compiler-visible lines plus every reference-format problem found."""
    if detect_source_format(text) == "fixed":
        lines, errors = _fold_continuations(text)
        code_from = 7
    else:
        lines, errors, code_from = text.split("\n"), [], 0
    for number, line in enumerate(lines):
        if _line_is_comment(line) or not line[code_from:].strip():
            continue
        code, error = _canonical_literals(line[code_from:])
        if error is not None:
            errors.append(f"line {number + 1}: {error}")
        lines[number] = line[:code_from] + code
    return lines, errors


def reference_format_errors(text: str) -> list[str]:
    """Problems that stop ``text`` from being read faithfully: malformed
    fixed-format continuation lines, and literals holding both quote
    characters.  Empty when there are none."""
    return _normalize(text)[1]


def compiler_visible_text(text: str) -> str:
    """The source text the compiler reads, in a canonical spelling.

    Fixed format: columns 1-72 only, with continuation lines folded into the
    line they continue (see :func:`_fold_continuations`).  In both formats
    literals using the doubled-quote escape are re-delimited (see
    :func:`_canonical_literals`).  Line structure is preserved so
    diagnostics keep their line numbers.
    """
    return "\n".join(_normalize(text)[0])

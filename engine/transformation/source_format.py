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
    FIXED_TEXT_START,
    SourceLine,
    format_from_directive,
    read_source,
    strip_free_comment,
)
from engine.transformation.source_positions import (
    ContinuationSegment,
    PositionedLine,
    SourceSpan,
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


def source_formats(text: str) -> tuple[str, ...]:
    """Every reference format the file uses, in order of first use: the start format, then each switch.

    Truthful where :func:`detect_source_format` (the *start* format, for oracle flag callers) is not:
    ``("fixed", "free")`` for a fixed file with a ``>>SOURCE FORMAT FREE`` segment.
    """
    read = read_source(text)
    seen = [read.start_format]
    for _line, new in read.switches:
        if new not in seen:
            seen.append(new)
    return tuple(seen)


def has_format_switch(text: str) -> bool:
    """True when the file changes reference format mid-file (``>>SOURCE FORMAT`` / ``$SET SOURCEFORMAT``)."""
    return bool(read_source(text).switches)


def mixed_format_refusal(text: str, name: str = "") -> str | None:
    """The named refusal for a file that switches reference format mid-file, else ``None``.

    The compile flag of the reference lanes (``cobc -free`` / default fixed) is chosen once per
    compilation unit from the file's *start* format (:func:`detect_source_format`); a file that
    switches format (``>>SOURCE FORMAT`` / ``$SET SOURCEFORMAT``) cannot be represented by that one
    flag, so those lanes refuse it by name — never compile it under the start flag.  The parser itself
    reads such a file per line and needs no refusal.
    """
    read = read_source(text)
    if not read.switches:
        return None
    line, new = read.switches[0]
    where = f"{name}:{line}" if name else f"line {line}"
    return (f"REFERENCE_FORMAT_MIXED_UNSUPPORTED: {where}: the reference format changes mid-file "
            f"({read.start_format} -> {new}); one compile flag cannot represent it, so it is refused by name, "
            "never compiled under the start format")


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


def _line_formats(read, count: int) -> list[str]:
    """The active format of every physical line: the start format, updated by each switch in line order."""
    formats: list[str] = []
    current = read.start_format
    switches = dict(read.switches)
    for number in range(1, count + 1):
        if number in switches:
            current = switches[number]
        formats.append(current)
    return formats


def _fold_continuations(
    lines: list[str],
    line_formats: list[str],
    not_anchor: set[int],
    errors: list[str],
) -> tuple[dict[int, list[ContinuationSegment]], set[int]]:
    """Fold fixed-format continuation lines into the lines they continue (strict GnuCOBOL 3.1.2 rules).

    Mutates ``lines`` in place (a local working copy) and returns, per anchor line index, the segments
    that record where each folded piece physically came from, plus the indexes folded away.
    """
    segments: dict[int, list[ContinuationSegment]] = {}
    folded: set[int] = set()
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
        lead = len(line[7:]) - len(resumed)
        quote = _open_quote(continued[7:])
        if quote is not None:
            if not resumed.startswith(quote):
                errors.append(
                    f"line {number + 1}: continuation of an open literal must "
                    f"resume with {quote}"
                )
                continue
            padded = continued.ljust(FIXED_FORMAT_TEXT_END)
            lines[last_code] = padded + resumed[1:]
            origin = SourceSpan("", number + 1, FIXED_TEXT_START + lead + 2)  # after the resuming quote
            offset = len(padded)
        else:
            head = continued.rstrip()
            lines[last_code] = head + resumed
            origin = SourceSpan("", number + 1, FIXED_TEXT_START + lead + 1)
            offset = len(head)
        segments.setdefault(last_code, []).append(ContinuationSegment(offset, origin))
        lines[number] = ""
        folded.add(number)
    return segments, folded


def _line_kind(source_text: str, fmt: str, number: int, skipped: dict[int, str], folded: set[int]) -> str:
    """Why a physical line carries (or does not carry) program text."""
    reader_kind = skipped.get(number)
    if reader_kind in ("directive", "card", "dead-branch"):
        return reader_kind
    if (number - 1) in folded:
        return "continuation"
    if not source_text.strip():
        return "blank"
    if fmt == "fixed":
        indicator = source_text[6] if len(source_text) > 6 else " "
        if source_text[:1] in ("*", "/") or indicator in "*/":
            return "comment"
        if indicator in "dD":
            return "debug"
    return "code"


def _positioned(text: str, file: str = "") -> tuple[tuple[PositionedLine, ...], list[str]]:
    """Positioned compiler-visible lines plus every reference-format problem found (by name).

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
    line_formats = _line_formats(read, len(raw_lines))
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
    segments, folded = _fold_continuations(lines, line_formats, not_anchor, errors)
    source_lines = list(lines)
    skipped = dict(read.skipped)
    positioned: list[PositionedLine] = []
    for number, line in enumerate(lines):
        fmt = line_formats[number]
        code_from = 7 if fmt == "fixed" else 0
        if not (_line_is_comment(line) or not line[code_from:].strip()):
            code, error = _canonical_literals(line[code_from:])
            if error is not None:
                errors.append(f"line {number + 1}: {error}")
            line = line[:code_from] + code
        source = source_lines[number]
        kind = _line_kind(source, fmt, number + 1, skipped, folded)
        code_text = strip_free_comment(source[code_from:]) if kind == "code" else ""
        if kind == "code" and not code_text.strip():
            kind = "comment"  # only a ``*>`` comment: no program text
        positioned.append(PositionedLine(
            span=SourceSpan(file, number + 1, 1), text=line, source_text=source, format=fmt,
            code_offset=code_from, kind=kind, code=code_text if kind == "code" else "",
            continuations=tuple(
                ContinuationSegment(seg.offset, SourceSpan(file, seg.span.line, seg.span.column))
                for seg in segments.get(number, ())),
        ))
    return tuple(positioned), errors


def positioned_lines(text: str, file: str = "") -> tuple[PositionedLine, ...]:
    """The compiler-visible lines of ``text``, one per physical line, with their physical origins.

    ``compiler_visible_text(text)`` is exactly ``"\\n".join(line.text for line in positioned_lines(text))``.
    """
    return _positioned(text, file)[0]


def positioned_token_lines(text: str, file: str = "") -> list[SourceLine]:
    """The engine's program-text lines as :class:`SourceLine` (physical line, text, column offset).

    Cutting these with ``cobol_text.tokenize`` yields the token stream the engine reads; layer 4's
    parity tests compare it with the discovery stream at every ``(line, column)``.
    """
    return [
        SourceLine(p.line, p.code, p.code_offset, bool(p.continuations))
        for p in positioned_lines(text, file) if p.kind == "code"
    ]


def comment_free_lines(text: str, *, keep_line_numbers: bool = False) -> list[str]:
    """The compiler-visible lines of ``text`` without comment text: the engine's one comment-stripping view.

    Comment and debug (``D``) lines are removed (replaced by ``""`` when ``keep_line_numbers`` so the list
    stays aligned with the physical lines) and a free-format or floating ``*>`` tail is cut where the
    single reader says the comment starts (never inside a literal).  Every other line is the compiler-visible
    text of :func:`positioned_lines`, literals kept.
    """
    out: list[str] = []
    for line in positioned_lines(text):
        if line.kind in ("comment", "debug"):
            if keep_line_numbers:
                out.append("")
            continue
        out.append(strip_free_comment(line.text) if line.kind == "code" else line.text)
    return out


def program_text(text: str) -> str:
    """The program text a verb scan may look at: :func:`comment_free_lines` joined, line structure kept.

    Comment, debug, card, directive and dead-branch lines are blank and a ``*>`` tail is cut, so a verb
    written there (``PROGRAM-ID``, ``CALL``, ``COPY``, ...) is never seen.
    """
    return "\n".join(comment_free_lines(text, keep_line_numbers=True))


def _normalize(text: str) -> tuple[list[str], list[str]]:
    """Compiler-visible lines plus every reference-format problem found (by name)."""
    positioned, errors = _positioned(text)
    return [line.text for line in positioned], errors


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

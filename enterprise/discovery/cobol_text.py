"""COBOL source normalisation and tokenising for discovery, with exact source positions.

Discovery must read programs the full parser would refuse, so this module does not parse COBOL: it removes what
the compiler removes (sequence area, comments, continuation breaks), then cuts the text into tokens that each
remember their original ``(line, column)``.  Every finding built on a token is therefore traceable to the byte
position the customer wrote, whatever the reference format.

Reference formats handled: fixed (columns 8-72 are program text), free (``>>SOURCE FORMAT FREE``, ``*>`` comments),
and mid-file switches between the two.  Micro Focus ``$SET SOURCEFORMAT`` is honoured as well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import NamedTuple

FIXED_TEXT_END = 72
FIXED_TEXT_START = 7  # zero-based offset of column 8

_FORMAT_DIRECTIVE = re.compile(r">>\s*SOURCE\s+(?:FORMAT\s+)?(?:IS\s+)?(FREE|FIXED)", re.IGNORECASE)
_MF_SET = re.compile(r"^\s*\$\s*SET\b(.*)$", re.IGNORECASE)
_MF_FORMAT = re.compile(r"SOURCEFORMAT\s*[\"'(]*\s*(FREE|FIXED|VARIABLE)", re.IGNORECASE)
#: Library-manager include cards (Panvalet ``-INC``, Librarian ``++INCLUDE``) sit in column 1, outside program text.
_CARD_LINE = re.compile(r"^(?:-INC|\+\+INCLUDE|%INCLUDE|CBL|PROCESS)\s", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z0-9_$#@][A-Za-z0-9_$#@-]*")
_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")
#: ``>>`` keywords of conditional compilation: evaluated (``DEFINE``/``IF``/``ELSE``/``END-IF``) or
#: refused by name (``ELIF``/``EVALUATE``/``WHEN``/``CALL*``); anything else is a plain directive.
_CONDITIONAL_KEYWORDS = frozenset({"DEFINE", "IF", "ELIF", "ELSE", "END-IF", "EVALUATE", "WHEN"})
#: Micro Focus dollar conditionals (``$IF``/``$DEFINE``/``$ELSE``/``$ELIF``/``$END``): recognised only
#: to refuse by name — never evaluated, never silently ignored.  ``$SET`` is not one of these.
_MF_CONDITIONAL = re.compile(r"\$(?:IF|ELIF|ELSE|END|DEFINE)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Token:
    """One lexical item with the position of its first character (1-based line and column)."""

    kind: str  # "word" | "literal" | "number" | "punct" | "pseudo"
    text: str
    line: int
    column: int

    @property
    def upper(self) -> str:
        return self.text.upper()


@dataclass(frozen=True)
class SourceLine:
    """A program-text line after sequence/indicator removal."""

    number: int  # 1-based physical line
    text: str
    column_offset: int  # physical column (0-based) of ``text[0]``
    continued: bool = False


@dataclass(frozen=True)
class Directive:
    line: int
    text: str


@dataclass(frozen=True)
class Card:
    """A column-1 compiler or library-manager card (``CBL``/``PROCESS``/``-INC``/``++INCLUDE``/``%INCLUDE``).

    Cards are not program text: the reader drops the line and reports it here, so no other module
    re-reads raw lines to find them.  ``text`` is what follows the keyword (options or the member name).
    """

    line: int
    column: int       # 1-based; cards are recognised in column 1 only
    keyword: str      # uppercased card keyword
    text: str         # the rest of the line, stripped
    text_column: int = 0  # 1-based column of ``text[0]`` (0 when the card has no text)


@dataclass
class SourceRead:
    """The result of :func:`read_source` — everything the one reader decided about one file."""

    start_format: str            # ``free`` | ``fixed`` | ``variable``
    format: str                  # the format the file ends in
    lines: list[SourceLine]      # discovery rendering (comments removed, continuations folded)
    directives: list[Directive]  # every ``>>``/``$SET`` directive line
    switches: tuple[tuple[int, str], ...]   # ``(line, new_format)`` for each actual format change
    skipped: tuple[tuple[int, str], ...]    # ``(line, kind)`` of dropped physical lines:
                                            # ``directive`` | ``card`` | ``debug`` | ``comment`` |
                                            # ``dead-branch``
    conditional: str = "none"      # ``none`` | ``evaluated`` | ``unevaluated`` — the CDF verdict (criterion 5)
    conditional_line: int = 0      # physical line of the first directive outside the subset (0 = none)
    cards: tuple[Card, ...] = ()   # every live column-1 card, in line order (dead branches excluded)


def _is_fixed_comment(line: str) -> bool:
    return len(line) > 6 and line[6] in "*/"


def format_from_directive(line: str) -> str | None:
    """The reference format a directive line sets (``free``/``fixed``/``variable``), else ``None``.

    The single detector for format directives — ``>>SOURCE FORMAT`` and Micro Focus
    ``$SET SOURCEFORMAT`` — used by :func:`read_source` and by the ``DialectProfile`` builder,
    so no module re-derives a format decision of its own (layer model, contract 3).
    """
    match = _FORMAT_DIRECTIVE.search(line)
    if match:
        return match.group(1).lower()
    mf = _MF_SET.match(line)
    if mf:
        found = _MF_FORMAT.search(mf.group(1))
        if found:
            return {"FREE": "free", "FIXED": "fixed", "VARIABLE": "variable"}[found.group(1).upper()]
    return None


def _strip_free_comment(text: str) -> str:
    """Cut a free-format ``*>`` inline comment, ignoring one that sits inside a literal."""
    quote = ""
    index = 0
    while index < len(text):
        ch = text[index]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "*" and text[index:index + 2] == "*>":
            return text[:index]
        index += 1
    return text


#: Public name of the one inline-comment cutter, for the engine face of the reader.
strip_free_comment = _strip_free_comment


def _literal(text: str) -> tuple[str, float | str] | None:
    """``("num", value)`` for a numeric or ``("str", value)`` for a quoted literal; None when neither."""
    if _NUMBER.fullmatch(text):
        return "num", float(text)
    single = re.fullmatch(r"'([^']*)'", text)
    if single is not None:
        return "str", single.group(1)
    double = re.fullmatch(r'"([^"]*)"', text)
    if double is not None:
        return "str", double.group(1)
    return None


def _operand(text: str) -> str | tuple[str, float | str] | None:
    """A CDF variable (its uppercased name) or a literal; None when the text is neither (never guessed)."""
    text = text.strip()
    if not text:
        return None
    if text[0] in "'\"":
        return _literal(text)
    if _NUMBER.fullmatch(text):
        return "num", float(text)
    if _WORD.fullmatch(text):
        return text.upper()
    return None


#: RelOps of the ``>>IF`` conditional expression, longest word form first (GnuCOBOL 2.5).
_RELOP = re.compile(
    r"(?P<op>GREATER\s+THAN\s+OR\s+EQUAL\s+TO|LESS\s+THAN\s+OR\s+EQUAL\s+TO|GREATER\s+THAN|LESS\s+THAN|"
    r"NOT\s+EQUAL\s+TO|EQUAL\s+TO|>=|<=|<>|=|>|<)",
    re.IGNORECASE,
)
_RELOP_WORDS = {
    "EQUAL TO": "=", "NOT EQUAL TO": "<>",
    "GREATER THAN": ">", "GREATER THAN OR EQUAL TO": ">=",
    "LESS THAN": "<", "LESS THAN OR EQUAL TO": "<=",
}


def _split_comparison(expr: str) -> tuple[str, str, str] | None:
    """``(left, symbol-op, right)`` around the first supported RelOp, else None (nothing is invented)."""
    match = _RELOP.search(expr)
    if match is None:
        return None
    op = _RELOP_WORDS.get(re.sub(r"\s+", " ", match.group("op").upper()), match.group("op"))
    left, right = expr[:match.start()].strip(), expr[match.end():].strip()
    if not left or not right:
        return None
    return left, op, right


_DEFINE_FORM = re.compile(r"(?:CONSTANT\s+)?(" + _WORD.pattern + r")\s+(?:AS\s+)?(\S.*)$", re.IGNORECASE)
_DEFINED_FORM = re.compile(r"(" + _WORD.pattern + r")\s+IS\s+(NOT\s+)?(DEFINED|SET)", re.IGNORECASE)


class _Frame(NamedTuple):
    """One open ``>>IF``: whether its ``IF``/``ELSE`` branch is live inside the enclosing frames."""

    line: int            # the ``>>IF`` line, so an unbalanced directive can be refused there
    parent_active: bool  # activity inherited from the enclosing frames at push time
    taken: bool          # the ``IF`` branch is live when the condition held
    else_seen: bool      # a ``>>ELSE`` has flipped the branch


class _Conditionals:
    """Evaluation of the GnuCOBOL CDF subset inside :func:`read_source` (layer 4, criterion 5).

    Evaluated exactly as written: ``>>DEFINE [CONSTANT] name AS literal`` (numeric or quoted;
    ``AS OFF`` removes the definition; ``AS PARAMETER`` is refused — its value is not in the
    source), ``>>IF name IS [NOT] DEFINED|SET`` and ``literal RelOp name|literal`` with the
    RelOps ``= <> > < >= <=`` and their word forms, plus ``>>ELSE`` and ``>>END-IF``, nested.

    Refused by name — the verdict becomes ``unevaluated``, both branches are kept and discovery
    reports ``CONDITIONAL_COMPILATION_UNEVALUATED``: ``>>ELIF``, ``>>EVALUATE``, ``>>WHEN``,
    ``>>CALL*``, a comparison on an undefined name, a numeric against an alphanumeric operand, a
    redefinition without ``OVERRIDE``, an unbalanced ``>>IF``, and the Micro Focus dollar family
    (``$IF``/``$DEFINE``/``$ELSE``/``$ELIF``/``$END``).  A refusal is never a default: undecided
    means no line is dropped.  Non-conditional ``>>`` directives (``>>SOURCE``, ``>>PAGE``, ...)
    are ignored here — they decide nothing about branches.
    """

    def __init__(self) -> None:
        self.defines: dict[str, tuple[str, float | str]] = {}
        self._frames: list[_Frame] = []
        self.refusal = 0   #: physical line of the first directive outside the subset (0 = none)
        self.saw = False   #: a conditional directive was present at all

    def directive(self, text: str, line: int) -> None:
        """Apply one ``>>`` directive line: evaluated, refused, or ignored as a plain directive."""
        body = text[2:].lstrip() if text.startswith(">>") else text.lstrip()
        parts = body.split(None, 1)
        keyword = parts[0].upper() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        if keyword not in _CONDITIONAL_KEYWORDS and not keyword.startswith("CALL"):
            return
        self.saw = True
        if keyword == "DEFINE":
            self._define(rest, line)
        elif keyword == "IF":
            self._if(rest, line)
        elif keyword == "ELSE":
            self._else(line)
        elif keyword == "END-IF":
            self._end_if(line)
        else:
            self._refuse(line)  # >>ELIF, >>EVALUATE, >>WHEN, >>CALL*: never evaluated

    def dollar(self, line: int) -> None:
        """A Micro Focus ``$IF``/``$DEFINE``/``$ELSE``/``$ELIF``/``$END`` line: refused, never evaluated."""
        self.saw = True
        self._refuse(line)

    def finish(self) -> None:
        """An unclosed ``>>IF`` at end of file is refused at its own line, never silently closed."""
        if self._frames and not self.refusal:
            self._refuse(self._frames[0].line)

    @property
    def active(self) -> bool:
        """Whether program text at this point is in a live branch (always True once undecided)."""
        if self.refusal or not self._frames:
            return True
        frame = self._frames[-1]
        return frame.parent_active and (frame.taken != frame.else_seen)

    @property
    def state(self) -> str:
        """``none`` (no conditional directives), ``evaluated``, or ``unevaluated`` (refused)."""
        if self.refusal:
            return "unevaluated"
        return "evaluated" if self.saw else "none"

    def _refuse(self, line: int) -> None:
        if not self.refusal:
            self.refusal = line

    def _define(self, rest: str, line: int) -> None:
        match = _DEFINE_FORM.match(rest.strip())
        if match is None:
            self._refuse(line)  # no name or no value: never a variable invented here
            return
        name, value = match.group(1).upper(), match.group(2).strip()
        override = bool(re.search(r"\s+OVERRIDE$", value, re.IGNORECASE))
        if override:
            value = re.sub(r"\s+OVERRIDE$", "", value, flags=re.IGNORECASE).strip()
        if value.upper() == "OFF":
            self.defines.pop(name, None)  # ``AS OFF`` removes the definition; removing nothing is a no-op
            return
        if value.upper() == "PARAMETER":
            self._refuse(line)  # the value comes from the environment, not from this source
            return
        typed = _literal(value)
        if typed is None:
            self._refuse(line)  # a bare word is not a literal: never guessed
            return
        if name in self.defines and not override:
            self._refuse(line)  # a redefinition without OVERRIDE is an error to the compiler, too
            return
        self.defines[name] = typed

    def _if(self, rest: str, line: int) -> None:
        taken = self._condition(rest)
        if taken is None:
            self._refuse(line)
            taken = True  # undecided keeps the branch (the refusal already keeps every branch)
        self._frames.append(_Frame(line, self.active, taken, False))

    def _else(self, line: int) -> None:
        if not self._frames or self._frames[-1].else_seen:
            self._refuse(line)  # a second >>ELSE, or one with no open >>IF
            return
        self._frames[-1] = self._frames[-1]._replace(else_seen=True)

    def _end_if(self, line: int) -> None:
        if not self._frames:
            self._refuse(line)  # >>END-IF with no open >>IF
            return
        self._frames.pop()

    def _condition(self, expr: str) -> bool | None:
        """The value of one ``>>IF`` condition, or None when it is outside the evaluated subset."""
        defined = _DEFINED_FORM.fullmatch(expr.strip())
        if defined is not None:
            return (defined.group(1).upper() in self.defines) != bool(defined.group(2))
        split = _split_comparison(expr)
        if split is None:
            return None
        left_text, op, right_text = split
        left, right = _operand(left_text), _operand(right_text)
        if left is None or right is None:
            return None
        values: list[tuple[str, float | str]] = []
        for item in (left, right):
            if isinstance(item, str):
                found = self.defines.get(item)
                if found is None:
                    return None  # undefined or valueless: the branch cannot be decided
                values.append(found)
            else:
                values.append(item)
        if values[0][0] != values[1][0]:
            return None  # numeric against alphanumeric: never a conversion the reader invents
        if values[0][0] == "num":
            # Same tag on both sides (checked above), so both stored values are floats.
            first_num, second_num = values[0][1], values[1][1]
            if isinstance(first_num, float) and isinstance(second_num, float):
                return {"=": first_num == second_num, "<>": first_num != second_num,
                        ">": first_num > second_num, "<": first_num < second_num,
                        ">=": first_num >= second_num, "<=": first_num <= second_num}[op]
            return None
        first_str, second_str = values[0][1], values[1][1]
        if isinstance(first_str, str) and isinstance(second_str, str):
            return {"=": first_str == second_str, "<>": first_str != second_str,
                    ">": first_str > second_str, "<": first_str < second_str,
                    ">=": first_str >= second_str, "<=": first_str <= second_str}[op]
        return None


def detect_format(text: str) -> str:
    """The format the file *starts* in: a format directive before any code wins (``>>SOURCE`` or Micro Focus
    ``$SET SOURCEFORMAT``), else a code character in columns 1-6 is free.  Directive lines (``>>...``,
    Micro Focus ``$`` directives) and cards are never code, so they never decide the format."""
    for raw in text.splitlines():
        line = raw.rstrip("\r\n").expandtabs(8)
        directive = format_from_directive(line)
        if directive is not None:
            return directive
        stripped = line.strip()
        if not stripped or _is_fixed_comment(line) or stripped.startswith("*>") or line.startswith(("*", "/")) \
                or _CARD_LINE.match(line) or _MF_SET.match(line) or stripped.startswith(">>") \
                or _MF_CONDITIONAL.match(stripped):
            continue
        return "free" if any(ch not in "0123456789 " for ch in line[:6]) else "fixed"
    return "fixed"


def read_source(text: str) -> "SourceRead":
    """The one reference-format reader.

    Returns a :class:`SourceRead`: the format the file starts and ends in (``"variable"`` under
    ``$SET SOURCEFORMAT VARIABLE``), the discovery rendering ``lines`` (comments removed, fixed-format
    continuations folded, dead conditional branches dropped), every ``>>``/``$SET`` directive, the
    ``(line, new_format)`` switches that actually changed the format, the ``(line, kind)`` of every
    physical line the reader dropped (``directive``/``card``/``debug``/``comment``/``dead-branch``)
    so the engine face of the reader can drop the same lines, and the conditional-compilation
    verdict (``conditional``/``conditional_line``, criterion 5).  Discovery (``logical_lines``) and
    the engine (``transformation/source_format``) both read through this function; no other module
    may re-derive format state (layer model, contract 3).
    """
    start_format = detect_format(text)
    fmt = start_format
    lines: list[SourceLine] = []
    directives: list[Directive] = []
    switches: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []
    cards: list[Card] = []
    # First pass: every conditional directive decides branch activity before any line is rendered,
    # so a refusal near the end keeps branches an eager pass would already have dropped.
    conditionals = _Conditionals()
    activity: dict[int, bool] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r\n").expandtabs(8)
        stripped = line.strip()
        if stripped.startswith(">>"):
            conditionals.directive(stripped, number)
        elif _MF_CONDITIONAL.match(stripped):
            conditionals.dollar(number)
        activity[number] = conditionals.active
    conditionals.finish()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r\n").expandtabs(8)
        stripped = line.strip()
        new = format_from_directive(line)
        if new is not None:
            directives.append(Directive(number, stripped))
            skipped.append((number, "directive"))
            if new != fmt:
                switches.append((number, new))
                fmt = new
            continue
        if _MF_SET.match(line):
            directives.append(Directive(number, stripped))
            skipped.append((number, "directive"))
            continue
        if stripped.startswith(">>"):
            directives.append(Directive(number, stripped))
            skipped.append((number, "directive"))
            continue
        if _MF_CONDITIONAL.match(stripped):
            directives.append(Directive(number, stripped))
            skipped.append((number, "directive"))
            continue
        if not activity[number]:
            # An evaluated dead branch: the compiler never sees these lines, so neither does discovery.
            if stripped:
                skipped.append((number, "dead-branch"))
            continue
        if _CARD_LINE.match(line) and (fmt == "free" or not (_is_fixed_comment(line) or line.startswith(("*", "/")))):
            # A library/compiler card sits in column 1 in either format (none of these words starts a COBOL statement).
            skipped.append((number, "card"))
            keyword, _, rest = line.partition(" ")
            lead = len(rest) - len(rest.lstrip())
            cards.append(Card(number, 1, keyword.upper(), rest.strip(), len(keyword) + 2 + lead))
            continue
        if fmt == "free":
            body = _strip_free_comment(line)
            if body.strip():
                lines.append(SourceLine(number, body, 0))
            continue
        if not stripped or _is_fixed_comment(line):
            continue
        if line.startswith(("*", "/")):
            skipped.append((number, "comment"))
            continue
        indicator = line[6] if len(line) > 6 else " "
        body = line[FIXED_TEXT_START:FIXED_TEXT_END]
        if indicator in "dD":
            skipped.append((number, "debug"))
            continue  # debugging line: compiled only under WITH DEBUGGING MODE
        if indicator == "-" and lines:
            if not _open_quote(lines[-1].text):
                body = _strip_free_comment(body)  # COBOL 2002 ``*>`` is a comment in fixed format too
            folded = _fold(lines[-1], body)
            # A continued literal resumes unstripped (its ``*>`` may be literal text); once folded, a ``*>`` that is
            # outside every literal is a comment and must not reach the tokens (engine face: ``PositionedLine.code``).
            lines[-1] = replace(folded, text=_strip_free_comment(folded.text))
            continue
        body = _strip_free_comment(body)  # COBOL 2002 ``*>`` is a comment in fixed format too
        if body.strip():
            lines.append(SourceLine(number, body, FIXED_TEXT_START))
    return SourceRead(start_format=start_format, format=fmt, lines=lines, directives=directives,
                      switches=tuple(switches), skipped=tuple(skipped),
                      conditional=conditionals.state, conditional_line=conditionals.refusal,
                      cards=tuple(cards))


def logical_lines(text: str) -> tuple[str, list[SourceLine], list[Directive]]:
    """Return ``(format, lines, directives)`` with comments removed and fixed-format continuations folded.

    ``format`` is the format the file ends in: ``"mixed"`` when a directive switched it, ``"variable"`` under
    ``$SET SOURCEFORMAT VARIABLE`` (which later stages refuse by name — never a silent fixed read).  See
    :func:`read_source` for the switch records.
    """
    read = read_source(text)
    if read.format == "variable":
        return "variable", read.lines, read.directives
    return ("mixed" if read.switches else read.format), read.lines, read.directives


def _fold(previous: SourceLine, continuation: str) -> SourceLine:
    """Append a continuation line to ``previous``; an open literal resumes after the opening quote.

    GnuCOBOL 3.1.2 semantics (oracle-pinned in ``tests/transformation/test_fixed_format_continuation.py``):
    a literal runs through column 72 and resumes after its quote; any other text joins the continuation's
    first non-blank character with **no space in between** — ``WS-AL`` + ``PHA`` is ``WS-ALPHA``, not two
    names.  Both reader faces fold identically (layer 4 acceptance criterion 2).
    """
    quote = _open_quote(previous.text)
    rest = continuation.lstrip(" ")
    if quote:
        # The literal runs to column 72 (trailing blanks count); the continuation resumes after a quote.
        padded = previous.text.ljust(FIXED_TEXT_END - FIXED_TEXT_START)
        rest = rest[1:] if rest[:1] == quote else rest
        return SourceLine(previous.number, padded + rest, previous.column_offset, True)
    return SourceLine(previous.number, previous.text.rstrip() + rest, previous.column_offset, True)


def _open_quote(text: str) -> str:
    quote = ""
    for ch in text:
        if not quote and ch in "\"'":
            quote = ch
        elif ch == quote:
            quote = ""
    return quote


def tokenize(lines: list[SourceLine]) -> list[Token]:
    """Cut normalised lines into tokens; strings keep their quotes stripped and ``''`` collapsed."""
    tokens: list[Token] = []
    for line in lines:
        text = line.text
        index, length = 0, len(text)
        while index < length:
            ch = text[index]
            column = line.column_offset + index + 1
            if ch in " \t":
                index += 1
                continue
            if ch in "\"'":
                value, index = _read_literal(text, index)
                tokens.append(Token("literal", value, line.number, column))
                continue
            if ch in "xXzZnNbBgG" and index + 1 < length and text[index + 1] in "\"'":
                value, index = _read_literal(text, index + 1)
                tokens.append(Token("literal", value, line.number, column))
                continue
            if ch == "=" and text[index:index + 2] == "==":
                end = text.find("==", index + 2)
                if end != -1:
                    tokens.append(Token("pseudo", text[index + 2:end].strip(), line.number, column))
                    index = end + 2
                    continue
            word = _WORD.match(text, index)
            if word:
                tokens.append(Token("word", word.group(0).rstrip("-"), line.number, column))
                index = word.end() if not word.group(0).endswith("-") else word.end() - 1
                continue
            number = _NUMBER.match(text, index)
            if number and (ch.isdigit() or ch in "+-"):
                tokens.append(Token("number", number.group(0), line.number, column))
                index = number.end()
                continue
            tokens.append(Token("punct", ch, line.number, column))
            index += 1
    return tokens


def _read_literal(text: str, start: int) -> tuple[str, int]:
    quote = text[start]
    index, out = start + 1, []
    while index < len(text):
        ch = text[index]
        if ch == quote:
            if text[index:index + 2] == quote * 2:
                out.append(quote)
                index += 2
                continue
            return "".join(out), index + 1
        out.append(ch)
        index += 1
    return "".join(out), index  # unterminated: keep what there is (reported by the scanner)


def split_statements(tokens: list[Token]) -> list[list[Token]]:
    """Group tokens into period-terminated sentences; a ``.`` inside an EXEC block never splits it."""
    return [sentence for _, sentence in split_indexed(tokens)]


def split_indexed(tokens: list[Token]) -> list[tuple[int, list[Token]]]:
    """Like :func:`split_statements`, but each sentence comes with the index of its first token in ``tokens``."""
    sentences: list[tuple[int, list[Token]]] = []
    current: list[Token] = []
    first = 0
    in_exec = False
    for index, token in enumerate(tokens):
        if token.kind == "word" and token.upper == "EXEC":
            in_exec = True
        elif token.kind == "word" and token.upper == "END-EXEC":
            in_exec = False
        if token.kind == "punct" and token.text == "." and not in_exec:
            if current:
                sentences.append((first, current))
                current = []
            continue
        if not current:
            first = index
        current.append(token)
    if current:
        sentences.append((first, current))
    return sentences

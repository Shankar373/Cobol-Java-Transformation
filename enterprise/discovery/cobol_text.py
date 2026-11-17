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
from dataclasses import dataclass

FIXED_TEXT_END = 72
FIXED_TEXT_START = 7  # zero-based offset of column 8

_FORMAT_DIRECTIVE = re.compile(r">>\s*SOURCE\s+(?:FORMAT\s+)?(?:IS\s+)?(FREE|FIXED)", re.IGNORECASE)
_MF_SET = re.compile(r"^\s*\$\s*SET\b(.*)$", re.IGNORECASE)
_MF_FORMAT = re.compile(r"SOURCEFORMAT\s*[\"'(]*\s*(FREE|FIXED|VARIABLE)", re.IGNORECASE)
#: Library-manager include cards (Panvalet ``-INC``, Librarian ``++INCLUDE``) sit in column 1, outside program text.
_CARD_LINE = re.compile(r"^(?:-INC|\+\+INCLUDE|%INCLUDE)\s", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z0-9_$#@][A-Za-z0-9_$#@-]*")
_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")


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


def _is_fixed_comment(line: str) -> bool:
    return len(line) > 6 and line[6] in "*/"


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


def detect_format(text: str) -> str:
    """The format the file *starts* in: a directive before any code wins, else a code character in columns 1-6 is free."""
    for raw in text.splitlines():
        match = _FORMAT_DIRECTIVE.search(raw)
        if match:
            return match.group(1).lower()
        line = raw.rstrip("\r\n").expandtabs(8)
        stripped = line.strip()
        if not stripped or _is_fixed_comment(line) or stripped.startswith("*>") or line.startswith(("*", "/")):
            continue
        return "free" if any(ch not in "0123456789 " for ch in line[:6]) else "fixed"
    return "fixed"



def logical_lines(text: str) -> tuple[str, list[SourceLine], list[Directive]]:
    """Return ``(format, lines, directives)`` with comments removed and fixed-format continuations folded.

    ``format`` is the format the file starts in (``"mixed"`` when a directive switches it later).  Folded
    continuation text keeps the line number and column of the first physical line, so spans stay anchored there.
    """
    start_format = detect_format(text)
    fmt = start_format
    switched = False
    lines: list[SourceLine] = []
    directives: list[Directive] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r\n").expandtabs(8)
        stripped = line.strip()
        match = _FORMAT_DIRECTIVE.search(line)
        if match:
            directives.append(Directive(number, stripped))
            new = match.group(1).lower()
            switched = switched or new != fmt
            fmt = new
            continue
        mf = _MF_SET.match(line)
        if mf:
            directives.append(Directive(number, stripped))
            found = _MF_FORMAT.search(mf.group(1))
            if found:
                new = "free" if found.group(1).upper() == "FREE" else "fixed"
                switched = switched or new != fmt
                fmt = new
            continue
        if stripped.startswith(">>"):
            directives.append(Directive(number, stripped))
            continue
        if fmt == "free":
            body = _strip_free_comment(line)
            if body.strip():
                lines.append(SourceLine(number, body, 0))
            continue
        if not stripped or _is_fixed_comment(line):
            continue
        if line.startswith(("*", "/")) or _CARD_LINE.match(line):
            continue
        indicator = line[6] if len(line) > 6 else " "
        body = line[FIXED_TEXT_START:FIXED_TEXT_END]
        if indicator in "dD":
            continue  # debugging line: compiled only under WITH DEBUGGING MODE
        if indicator == "-" and lines:
            lines[-1] = _fold(lines[-1], body)
            continue
        if body.strip():
            lines.append(SourceLine(number, body, FIXED_TEXT_START))
    return ("mixed" if switched else start_format), lines, directives


def _fold(previous: SourceLine, continuation: str) -> SourceLine:
    """Append a continuation line to ``previous``; an open literal resumes after the opening quote."""
    quote = _open_quote(previous.text)
    rest = continuation.lstrip(" ")
    if quote:
        # The literal runs to column 72 (trailing blanks count); the continuation resumes after a quote.
        padded = previous.text.ljust(FIXED_TEXT_END - FIXED_TEXT_START)
        rest = rest[1:] if rest[:1] == quote else rest
        return SourceLine(previous.number, padded + rest, previous.column_offset, True)
    return SourceLine(previous.number, previous.text.rstrip() + " " + rest, previous.column_offset, True)


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

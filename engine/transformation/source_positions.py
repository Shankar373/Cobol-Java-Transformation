"""Position-carrying lines of the engine face of the one reference-format reader (Layer 4).

``engine.transformation.source_format`` builds these from :func:`enterprise.discovery.cobol_text.read_source`
(the only reader).  :class:`PositionedLine` is one *physical* line of the file together with what the engine
decided about it: the compiler-visible text (the exact string ``compiler_visible_text`` joins), the
program-text area, the segment's reference format, why a line carries no code, and where every continuation
segment came from.  ``compiler_visible_text`` is rendered from these lines, so the string view and the
position view cannot diverge.

Shape and invariants:

* One :class:`PositionedLine` per physical line, in file order, so ``lines[i].line == i + 1``.
* ``text`` is the compiler-visible line (literals canonicalised, columns 73+ dropped in fixed format);
  ``source_text`` is the same line *before* literal canonicalisation (doubled-quote literals shrink by one
  character in ``text``).  Positions (``code_offset``, :meth:`PositionedLine.span_at`) index ``source_text``.
* A fixed-format continuation line is folded into the line it continues: it has ``kind == "continuation"``
  and empty text, and the anchor line records a :class:`ContinuationSegment` per folded line, so a token on
  a folded line resolves to its true physical ``file:line:column`` through :meth:`PositionedLine.span_at`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: ``kind`` values: a line with program text, or why a physical line carries none.
LINE_KINDS = ("code", "blank", "comment", "debug", "directive", "card", "dead-branch", "continuation")


@dataclass(frozen=True)
class SourceSpan:
    """A physical position: ``file`` (may be empty), 1-based ``line`` and 1-based ``column``."""

    file: str
    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}" if self.file else f"{self.line}:{self.column}"


@dataclass(frozen=True)
class ContinuationSegment:
    """``source_text[offset:]`` (up to the next segment) came from the physical position ``span``."""

    offset: int
    span: SourceSpan


@dataclass(frozen=True)
class PositionedLine:
    """One physical line with its compiler-visible text and where that text came from."""

    span: SourceSpan                 # origin of ``text[0]`` (column 1 of the physical line)
    text: str                        # the compiler-visible line (byte-identical to compiler_visible_text)
    source_text: str                 # the folded line before literal canonicalisation
    format: str                      # ``fixed`` | ``free`` | ``variable`` — the segment's format
    code_offset: int                 # index of program text in ``source_text`` (7 fixed, 0 free)
    kind: str                        # one of LINE_KINDS
    code: str = ""                   # program text with ``*>`` comments cut (empty unless kind == "code")
    continuations: tuple[ContinuationSegment, ...] = ()

    @property
    def line(self) -> int:
        return self.span.line

    def span_at(self, offset: int) -> SourceSpan:
        """The physical position of ``source_text[offset]``, following folded continuation lines."""
        origin = self.span
        base = 0
        for segment in self.continuations:
            if segment.offset <= offset:
                origin, base = segment.span, segment.offset
        return SourceSpan(origin.file, origin.line, origin.column + offset - base)

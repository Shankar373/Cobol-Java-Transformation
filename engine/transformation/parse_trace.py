"""Where the parser read each statement and declaration (Layer 5, phase P1): a trace *beside* the frozen IR.

``CobolParser.parse_traced`` returns the same ``CobolProgram`` ``parse`` returns plus a :class:`ParseTrace`.  The IR
classes are untouched (generated Java and every IR equality stay as they were); the trace says, for every
statement and every program-text data declaration the parser produced, which logical code line it started on and what
is known about that line's physical position.  ``engine.semantic_facts.span`` turns a trace into spans.

Nothing here reads source text.  Positions come from the one reference-format reader through
``source_positions.PositionedLine`` (physical line, folded continuations) and ``qualified_names``'s origin vector
(a wrapped qualifier or a CORRESPONDING expansion changes the line count; the vector says which input line every
output line derives from).  A fact that cannot be placed is *named* (``SPAN_*`` codes), never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Why a position is not exact (closed set; each is a documented limitation, not an error).
SPAN_NOTES = (
    "SPAN_COLUMN_TAB",              # a TAB precedes the first character: the engine does not expand tabs
    "SPAN_REWRITTEN_REPLACE",       # an active REPLACE changed the line's text
    "SPAN_INLINE_FRAGMENT",         # a statement written inline after another on one logical line
    "SPAN_COLUMN_LITERAL",          # reserved: a doubled-quote literal shifts later columns on the line
)


@dataclass(frozen=True)
class LogicalLine:
    """One logical code line the statement parser read (``ParseTrace.lines[i]`` is logical line ``i``).

    ``line``/``column`` are the physical position of its first character in the text handed to ``parse``;
    ``end_line`` is the physical line of the last code line joined into it.  ``line == 0`` means unmappable.
    ``note`` is empty when the position is exact, else one of :data:`SPAN_NOTES`.
    """

    line: int
    column: int
    end_line: int
    note: str = ""


@dataclass(frozen=True)
class StatementFrame:
    """A statement the parser produced.  ``statement`` is kept so its ``id`` cannot be reused while the trace lives."""

    statement: Any
    start: int          # logical line index of the statement's first line (the enclosing statement's for inline ones)
    inline: bool        # True: parsed from a fragment of one logical line, so only that line is known
    depth: int          # nesting depth of ``_parse_statement`` calls when it was produced


@dataclass(frozen=True)
class DeclarationFrame:
    """A data-description entry parsed from program text (``item`` is kept alive for the same reason)."""

    item: Any
    start: int          # logical line index of the entry's first line
    end: int            # logical line index of the entry's last line (the one holding its period)
    section: str        # ``working-storage`` | ``linkage``


@dataclass(frozen=True)
class ParseTrace:
    """The positions of one ``parse``: logical lines plus the statement and declaration frames."""

    lines: tuple[LogicalLine, ...] = ()
    statements: tuple[StatementFrame, ...] = ()
    declarations: tuple[DeclarationFrame, ...] = ()
    #: ``paragraph name -> logical line index`` of the paragraph header, in source order.
    paragraphs: tuple[tuple[str, int], ...] = ()
    #: ``(kind, NAME, logical index)`` of each ``PROGRAM-ID`` / ``END PROGRAM`` header (``kind``: program-id | end-program).
    programs: tuple[tuple[str, str, int], ...] = ()
    #: ``(clause, NAME, logical index)`` of each program-text data entry carrying a clause the IR does not model:
    #: ``RENAMES`` (a level-66 entry), ``GLOBAL`` or ``EXTERNAL``.
    entry_notes: tuple[tuple[str, str, int], ...] = ()
    #: ``(generated unique name, declared name, ancestors nearest first)`` for each declaration ``qualified_names``
    #: renamed (a name declared more than once); the IR carries the generated name, the source spelling is here.
    renames: tuple[tuple[str, str, tuple[str, ...]], ...] = ()

    def statement_index(self) -> dict[int, StatementFrame]:
        """``id(statement) -> frame`` (identity, never equality: two equal statements are two statements).  A frame
        from the program's own lines wins over an inline-fragment frame of the same object."""
        index: dict[int, StatementFrame] = {}
        for frame in self.statements:
            held = index.get(id(frame.statement))
            if held is None or (held.inline and not frame.inline):
                index[id(frame.statement)] = frame
        return index

    def declaration_index(self) -> dict[int, DeclarationFrame]:
        return {id(frame.item): frame for frame in self.declarations}

"""Source spans for parsed declarations and statements (Layer 5, phase P1).

A :class:`Span` says where a fact was read: the file that physically holds the text, the 1-based line and column,
and the COPY statements it was expanded through (outermost first).  It is built from the parser's
:class:`~engine.transformation.parse_trace.ParseTrace` (positions from the one reference-format reader) and an
optional :class:`~engine.transformation.copy_origins.CopyOriginMap` (for text a COPY expansion spliced in); nothing
here reads or searches source text.

Exactness is part of the value, never implied:

* ``exact=True`` ``basis="token"``: ``(file, line, column)`` is the physical position of the fact's first token.
* ``exact=False``: the line is right (or the statement it is inside begins there) but the column is not claimed;
  ``note`` names why (``SPAN_COLUMN_TAB``, ``SPAN_REWRITTEN_REPLACE``, ``SPAN_INLINE_FRAGMENT``,
  ``SPAN_COPY_COLUMN_UNPROVEN``) and ``basis`` says what the position is (``line``, ``statement`` or ``copy-site``).
* No span at all: the fact is still listed, with ``span is None`` and a named ``code`` (``SPAN_UNAVAILABLE`` for a
  statement or declaration the trace cannot place, ``SPAN_SYNTHETIC_DECLARATION`` for an item the parser adds itself,
  ``SPAN_FILE_SECTION_NOT_TRACED`` for FILE SECTION records).  ``SpanTable.unplaced`` is that inventory; a consumer
  must never substitute a neighbouring line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.transformation.copy_origins import CopyOriginMap
from engine.transformation.group_storage import iter_data_items
from engine.transformation.parse_trace import ParseTrace

#: What a span's position is (closed set).
SPAN_BASES = ("token", "line", "statement", "copy-site")

#: Named reasons a fact has no span or an inexact one (closed set; each one is documented in LAYER5_DESIGN.md 2.2).
SPAN_CODES = (
    "SPAN_UNAVAILABLE",
    "SPAN_SYNTHETIC_DECLARATION",
    "SPAN_FILE_SECTION_NOT_TRACED",
    "SPAN_COLUMN_TAB",
    "SPAN_REWRITTEN_REPLACE",
    "SPAN_INLINE_FRAGMENT",
    "SPAN_COPY_COLUMN_UNPROVEN",
    "SPAN_COPY_SITE_ONLY",
    "SPAN_LOWERED_FROM_PARENT",
    "SPAN_OPERAND_NOT_LOCATED",
)


@dataclass(frozen=True)
class CopyFrame:
    """One COPY statement on the way to a fact, outermost first (``copy_origins.CopyHop`` rendered as data)."""

    file: str
    line: int
    target: str


@dataclass(frozen=True)
class Span:
    """Where a fact was read.  ``end_line``/``end_column`` of ``0`` mean "not tracked"."""

    file: str
    line: int
    column: int
    end_line: int = 0
    end_column: int = 0
    via_copy: tuple[CopyFrame, ...] = ()
    basis: str = "token"
    exact: bool = True
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Canonical JSON shape: ADR-0013's ``{file,line,column,via_copy[]}`` plus the additive fields (design D2)."""
        return {
            "basis": self.basis, "column": self.column, "end_column": self.end_column, "end_line": self.end_line,
            "exact": self.exact, "file": self.file, "line": self.line, "note": self.note,
            "via_copy": [{"file": f.file, "line": f.line, "target": f.target} for f in self.via_copy],
        }


@dataclass(frozen=True)
class SpannedStatement:
    statement: Any
    paragraph: str
    ordinal: int            # position among the paragraph's statements in depth-first order
    span: Span | None
    code: str               # "" when spanned, else the SPAN_* reason it is not


@dataclass(frozen=True)
class SpannedDeclaration:
    item: Any
    name: str
    section: str            # working-storage | linkage
    span: Span | None
    code: str


@dataclass(frozen=True)
class SpanTable:
    """Every statement and program-text declaration of one parsed program with its span (or its named reason)."""

    file: str
    statements: tuple[SpannedStatement, ...] = ()
    declarations: tuple[SpannedDeclaration, ...] = ()
    paragraphs: tuple[tuple[str, Span | None], ...] = ()

    def unplaced(self) -> tuple[tuple[str, str, str], ...]:
        """``(kind, subject, code)`` of every fact without a span, sorted: the shrink-only inventory."""
        rows = [("statement", f"{s.paragraph}#{s.ordinal}:{type(s.statement).__name__}", s.code)
                for s in self.statements if s.span is None]
        rows += [("declaration", d.name, d.code) for d in self.declarations if d.span is None]
        return tuple(sorted(rows))

    def inexact(self) -> tuple[tuple[str, str, str], ...]:
        """``(kind, subject, note)`` of every fact whose span is not exact."""
        rows = [("statement", f"{s.paragraph}#{s.ordinal}:{type(s.statement).__name__}", s.span.note)
                for s in self.statements if s.span is not None and not s.span.exact]
        rows += [("declaration", d.name, d.span.note) for d in self.declarations
                 if d.span is not None and not d.span.exact]
        return tuple(sorted(rows))


def _place(trace: ParseTrace, logical: int, *, file: str, origins: CopyOriginMap | None,
           inline: bool = False, end_logical: int | None = None) -> Span | None:
    """The span of logical line ``logical`` (or ``None`` when the trace has no physical position for it)."""
    if not 0 <= logical < len(trace.lines):
        return None
    where = trace.lines[logical]
    if where.line <= 0:
        return None
    end_line = trace.lines[end_logical].end_line if end_logical is not None and end_logical < len(trace.lines) else 0
    note = where.note
    if origins is None:
        # the text handed to parse is the file itself
        if inline:
            return Span(file, where.line, 0, basis="statement", exact=False, note="SPAN_INLINE_FRAGMENT")
        if note:
            return Span(file, where.line, 0, end_line, basis="line", exact=False, note=note)
        return Span(file, where.line, where.column, end_line)
    try:
        origin = origins.origin_of(where.line)
    except IndexError:
        return None
    via = tuple(CopyFrame(h.file, h.line, h.target) for h in origin.via)
    origin_file = origin.file or file
    if end_line:
        # ``end_line`` is in expanded-text coordinates like ``where.line``: map it the same way, and claim it only when
        # it lands in the same physical file outside any COPY (else "not tracked", never a shifted number)
        try:
            end_origin = origins.origin_of(end_line)
        except IndexError:
            end_origin = None
        end_line = end_origin.line if (end_origin is not None and end_origin.exact and not end_origin.via
                                       and end_origin.file == origin.file) else 0
    if not origin.exact:
        return Span(origin_file, origin.line, 0, via_copy=via, basis="copy-site", exact=False, note="SPAN_COPY_SITE_ONLY")
    if via:
        # the line is the copybook's own physical line; its text was re-indented/rewritten by the expansion, so the
        # column inside it is not claimed
        return Span(origin_file, origin.line, 0, via_copy=via, basis="line", exact=False, note="SPAN_COPY_COLUMN_UNPROVEN")
    if inline:
        return Span(origin_file, origin.line, 0, basis="statement", exact=False, note="SPAN_INLINE_FRAGMENT")
    if note:
        return Span(origin_file, origin.line, 0, end_line, basis="line", exact=False, note=note)
    return Span(origin_file, origin.line, where.column, end_line)


def _walk(statements: Any, parent: Any = None):
    """``(statement, enclosing statement or None)`` depth first, in the order ``control_flow.walk_statements`` yields."""
    for statement in statements:
        yield statement, parent
        for value in getattr(statement, "__dict__", {}).values():
            if isinstance(value, (tuple, list)):
                nested = [v for v in value if hasattr(v, "__dataclass_fields__")]
                if nested:
                    yield from _walk(nested, statement)


def build_span_table(program: Any, trace: ParseTrace, *, file: str = "",
                     origins: CopyOriginMap | None = None) -> SpanTable:
    """Span every statement and program-text declaration of ``program`` from ``trace``.

    ``file`` names the text handed to ``parse`` (``""`` for an anonymous string).  ``origins`` is the origin map of
    that text when COPY expansion produced it (``fd_copybooks.expand_fd_copybooks(...).origins``).
    """
    statement_frames = trace.statement_index()
    declaration_frames = trace.declaration_index()

    statements: list[SpannedStatement] = []
    placed: dict[int, Span] = {}        # id(statement) -> its span, for children that inherit it
    for paragraph in program.paragraphs:
        for ordinal, (statement, parent) in enumerate(_walk(paragraph.statements)):
            frame = statement_frames.get(id(statement))
            span = (None if frame is None else
                    _place(trace, frame.start, file=file, origins=origins, inline=frame.inline))
            code = ""
            if span is None:
                # a statement the parser lowered out of another one (EVALUATE's WHEN chain becomes nested IFs) has no
                # frame of its own: it lies inside its enclosing statement, whose start is the only position claimed
                inherited = placed.get(id(parent)) if parent is not None else None
                if inherited is not None:
                    span = Span(inherited.file, inherited.line, 0, via_copy=inherited.via_copy, basis="statement",
                                exact=False, note="SPAN_LOWERED_FROM_PARENT")
                else:
                    code = "SPAN_UNAVAILABLE"
            if span is not None:
                placed[id(statement)] = span
            statements.append(SpannedStatement(statement, paragraph.name, ordinal, span, code))

    declarations: list[SpannedDeclaration] = []
    for section, roots in (("working-storage", program.working_storage), ("linkage", program.linkage_section)):
        for item in iter_data_items(roots):
            decl_frame = declaration_frames.get(id(item))
            if decl_frame is None:
                declarations.append(SpannedDeclaration(item, item.name, section, None, "SPAN_SYNTHETIC_DECLARATION"))
                continue
            span = _place(trace, decl_frame.start, file=file, origins=origins, end_logical=decl_frame.end)
            declarations.append(SpannedDeclaration(item, item.name, section, span,
                                                   "" if span is not None else "SPAN_UNAVAILABLE"))
    for definition in program.file_definitions:
        for item in iter_data_items(definition.record_groups):
            decl_frame = declaration_frames.get(id(item))
            span = (None if decl_frame is None else
                    _place(trace, decl_frame.start, file=file, origins=origins, end_logical=decl_frame.end))
            declarations.append(SpannedDeclaration(
                item, item.name, "file", span, "" if span is not None else "SPAN_FILE_SECTION_NOT_TRACED"))

    paragraphs = tuple((name, _place(trace, index, file=file, origins=origins)) for name, index in trace.paragraphs)
    return SpanTable(file, tuple(statements), tuple(declarations), paragraphs)


def copybook_declaration_spans(model: Any, *, copy_site: CopyFrame | None = None) -> tuple[SpannedDeclaration, ...]:
    """Spans of the declarations of one parsed copybook (``copybook_model.CopybookModel``).

    A copybook's text is a separate text from the program's (its records are merged at IR level), so its
    declarations are placed by the copybook's own origin map: the physical file and line the entry was read from
    (a nested COPY's file when it came through one) and the COPY statements on the way.  ``copy_site`` is the
    program's own COPY statement (file, line, member) and becomes the outermost ``via_copy`` frame.  The column is
    never claimed: the expansion re-indents copybook lines, so ``basis="line"``, ``exact=False``,
    ``SPAN_COPY_COLUMN_UNPROVEN`` (or ``SPAN_COPY_SITE_ONLY`` when a REPLACING text split the lines).
    """
    origins: CopyOriginMap | None = model.origins
    outer = (copy_site,) if copy_site is not None else ()
    spanned: list[SpannedDeclaration] = []
    for frame in model.declarations:
        span: Span | None = None
        if origins is not None:
            try:
                origin = origins.origin_of(frame.start + 1)
            except IndexError:
                origin = None
            if origin is not None:
                via = outer + tuple(CopyFrame(h.file, h.line, h.target) for h in origin.via)
                if origin.exact:
                    span = Span(origin.file, origin.line, 0, via_copy=via, basis="line", exact=False,
                                note="SPAN_COPY_COLUMN_UNPROVEN")
                else:
                    span = Span(origin.file, origin.line, 0, via_copy=via, basis="copy-site", exact=False,
                                note="SPAN_COPY_SITE_ONLY")
        spanned.append(SpannedDeclaration(frame.item, frame.item.name, "copybook", span,
                                          "" if span is not None else "SPAN_UNAVAILABLE"))
    return tuple(spanned)

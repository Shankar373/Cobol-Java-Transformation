"""Declarations, scopes and deterministic identities (Layer 5, phase P2).

A :class:`SymbolTable` lists every declaration of one parsed program exactly once: the program itself, its entry
points, paragraphs, files (FD/SD), records, data items, condition names, index names and a closed list of special
registers.  It is built from the parser's frozen IR plus the P1 :class:`~engine.semantic_facts.span.SpanTable`; nothing
here reads source text or resolves names a second time (``qualified_names`` stays the one qualification algorithm; the
table records the same ancestor chain it uses).

Identity (design 3.4) never depends on file enumeration order or on object identity::

    decl_id = "sym:" + scope_id + "/" + kind + ":" + "/".join(reversed(qualification)) + "/" + NAME + "#" + K

``K`` is the 1-based ordinal among declarations of the same scope, kind, qualification and name, in source order.

What is *not* modelled is named, never guessed (``UNSUPPORTED_CODES``): a level-66 RENAMES entry (the parser refuses it
and no item reaches the IR), the GLOBAL and EXTERNAL data clauses (the parser does not read them), a second program in
the same source (nested or batched: the IR keeps one program, so declarations from the second program's text are
marked, never merged into the first program's scope), and two declarations with the same name and the same
qualification chain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from engine.semantic_facts.span import Span, SpanTable
from engine.transformation.file_ownership import record_ownership
from engine.transformation.parse_trace import ParseTrace

#: Closed vocabulary of declaration kinds.
DECL_KINDS = (
    "program", "entry", "paragraph", "file", "record", "data-item", "condition-name",
    "rename", "index-name", "linkage-param", "special-register",
)

#: Closed vocabulary of reasons a declaration or program feature is not modelled (design 3.3).
UNSUPPORTED_CODES = (
    "NESTED_PROGRAM_NOT_MODELLED",
    "RENAMES_NOT_MODELLED",
    "GLOBAL_CLAUSE_NOT_READ",
    "EXTERNAL_CLAUSE_NOT_READ",
    "DUPLICATE_DECLARATION_SAME_QUALIFICATION",
)

#: Registers every program has without declaring them.  Each is read or written by the engine's own lowering today
#: (``RETURN-CODE``: CALL/GOBACK; ``SORT-RETURN``: SORT; ``TALLY``: INSPECT TALLYING); anything else is not claimed.
SPECIAL_REGISTERS = ("RETURN-CODE", "SORT-RETURN", "TALLY")

_NOTE_CODES = {"RENAMES": "RENAMES_NOT_MODELLED", "GLOBAL": "GLOBAL_CLAUSE_NOT_READ",
               "EXTERNAL": "EXTERNAL_CLAUSE_NOT_READ"}

#: Declaration kinds that become a node in the discovery graph, and that node's kind (``scoped_node_id``).  Files,
#: records and special registers are mapped in P6 from the graph that actually exists, not guessed here.
_GRAPH_KIND = {"paragraph": "paragraph", "data-item": "data-item", "condition-name": "data-item",
               "index-name": "data-item", "linkage-param": "data-item"}


@dataclass(frozen=True)
class Scope:
    scope_id: str           # "program:PAYROLL"
    kind: str               # "program"
    parent: str             # enclosing scope ("" : nesting is not modelled)
    global_names: frozenset[str] = frozenset()   # names whose GLOBAL clause the trace saw (visibility not modelled)


@dataclass(frozen=True)
class Declaration:
    decl_id: str
    kind: str
    name: str                # upper-case source spelling; FILLER keeps "FILLER" and is never addressable
    level: int               # 0 for non-data
    scope: str
    parent: str              # decl_id of the enclosing group / FD / program ("" for roots)
    qualification: tuple[str, ...]   # ancestor names, nearest first (== qualified_names _Item.ancestors)
    section: str             # working-storage | linkage | file | ""
    graph_node_id: str       # "" when the discovery graph has no such node kind
    graph_node_collapsed: bool
    origin_member: str       # the copybook file the text came from when a COPY expanded it, else ""
    template_id: str         # "tpl:..." shared by every program that copies the same member line, else ""
    span: Span | None
    span_code: str           # why span is None ("" when spanned)
    attributes: tuple[tuple[str, str], ...]
    unsupported: str         # "" or an UNSUPPORTED_CODES member
    addressable: bool = True


@dataclass(frozen=True)
class UnsupportedFact:
    """Something in the program the symbol model cannot represent, with its place when known."""

    code: str
    subject: str
    span: Span | None = None


@dataclass(frozen=True)
class SymbolTable:
    file: str
    scopes: tuple[Scope, ...]
    declarations: tuple[Declaration, ...]
    unsupported: tuple[UnsupportedFact, ...] = ()

    @property
    def complete(self) -> bool:
        """False when anything was named unsupported: a consumer must not read absence as proof."""
        return not self.unsupported and not any(d.unsupported for d in self.declarations)

    def by_id(self) -> dict[str, Declaration]:
        return {d.decl_id: d for d in self.declarations}

    def named(self, name: str) -> tuple[Declaration, ...]:
        upper = name.upper()
        return tuple(d for d in self.declarations if d.name == upper and d.addressable)

    def unsupported_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for code in [u.code for u in self.unsupported] + [d.unsupported for d in self.declarations if d.unsupported]:
            counts[code] = counts.get(code, 0) + 1
        return dict(sorted(counts.items()))


def _attributes(item: Any) -> tuple[tuple[str, str], ...]:
    pairs = {
        "usage": item.usage or "", "occurs": "" if item.occurs is None else str(item.occurs),
        "depends_on": item.occurs_depending_on or "", "redefines": item.redefines or "",
        "pic_type": item.pic_type.name if getattr(item, "pic_type", None) is not None else "",
        "pic_length": str(item.pic_length) if item.pic_length else "",
        "indexed_by": ",".join(item.indexed_by),
    }
    return tuple(sorted((k, v) for k, v in pairs.items() if v))


def graph_node_id(scope_id: str, kind: str, name: str) -> str:
    """The discovery graph's id for ``name`` declared in ``scope_id`` (same formula as ``cobol_structure.scoped_node_id``,
    which a test compares against; the engine does not import discovery)."""
    graph_kind = _GRAPH_KIND.get(kind)
    if graph_kind is None:
        return ""
    return f"{graph_kind}:{scope_id.partition(':')[2]}/{name.upper()}"


class _Builder:
    def __init__(self, scope_id: str, table: SpanTable, notes: dict[tuple[str, str], str],
                 foreign_from: int, program: Any, trace: ParseTrace) -> None:
        self.scope_id = scope_id
        self.item_spans = {id(d.item): d for d in table.declarations}
        self.notes = notes
        self.foreign_from = foreign_from
        self.ordinals: dict[tuple[str, str, tuple[str, ...], str], int] = {}
        self.rows: list[Declaration] = []
        self.seen: set[int] = set()
        self.using = {name.upper() for name in program.using_parameters}
        self.frames = trace.declaration_index()
        #: generated unique name -> declared name (qualified_names renames a name declared more than once)
        self.declared = {unique: name for unique, name, _ancestors in trace.renames}

    def _id(self, kind: str, qualification: tuple[str, ...], name: str) -> str:
        key = (self.scope_id, kind, qualification, name)
        self.ordinals[key] = self.ordinals.get(key, 0) + 1
        chain = "/".join(reversed(qualification))
        return f"sym:{self.scope_id}/{kind}:{chain}{'/' if chain else ''}{name}#{self.ordinals[key]}"

    def add(self, kind: str, name: str, *, level: int = 0, parent: str = "", qualification: tuple[str, ...] = (),
            section: str = "", span: Span | None = None, span_code: str = "",
            attributes: tuple[tuple[str, str], ...] = (), unsupported: str = "") -> str:
        name = name.upper()
        decl_id = self._id(kind, qualification, name)
        member = span.file if span is not None and span.via_copy else ""
        template = ("tpl:" + hashlib.sha256(f"{member}|{span.line}|{name}".encode()).hexdigest()[:16]
                    if member and span is not None else "")
        self.rows.append(Declaration(
            decl_id, kind, name, level, self.scope_id, parent, qualification, section,
            graph_node_id(self.scope_id, kind, name), False, member, template, span, span_code, attributes,
            unsupported, addressable=name != "FILLER"))
        return decl_id

    def item(self, item: Any, parent: str, qualification: tuple[str, ...], section: str, *,
             record: bool = False) -> None:
        if id(item) in self.seen:
            return
        self.seen.add(id(item))
        spanned = self.item_spans.get(id(item))
        if spanned is not None:
            span, span_code = spanned.span, spanned.code
        else:
            # FILE SECTION records are not traced (P1); any other untraced item is a real gap and says so
            span, span_code = None, "SPAN_FILE_SECTION_NOT_TRACED" if section == "file" else "SPAN_UNAVAILABLE"
        generated = item.name.upper()
        name = self.declared.get(generated, generated)
        if record:
            kind = "record"
        elif item.level == 88:
            kind = "condition-name"
        elif section == "linkage" and item.level in (1, 77) and name in self.using:
            kind = "linkage-param"
        else:
            kind = "data-item"
        note = self.notes.get(("item", generated))
        unsupported = _NOTE_CODES.get(note, "") if note else ""
        if self._foreign(item):
            unsupported = "NESTED_PROGRAM_NOT_MODELLED"
        attributes = _attributes(item)
        if generated != name:
            attributes = tuple(sorted(attributes + (("generated_name", generated),)))
        decl_id = self.add(kind, name, level=item.level, parent=parent, qualification=qualification,
                           section=section, span=span, span_code=span_code, attributes=attributes,
                           unsupported=unsupported)
        for index_name in item.indexed_by:
            self.add("index-name", index_name, level=0, parent=decl_id, qualification=(name, *qualification),
                     section=section, span=span, span_code=span_code, unsupported=unsupported)
        child_chain = qualification if item.level == 88 else (name, *qualification)
        for child in item.children:
            self.item(child, decl_id, child_chain, section)

    def _foreign(self, item: Any) -> bool:
        """True when the entry was read from the text of a second program (logical index at or after its header)."""
        frame = self.frames.get(id(item))
        return frame is not None and self.foreign_from > 0 and frame.start >= self.foreign_from


def build_symbol_table(program: Any, trace: ParseTrace, spans: SpanTable, *, scope_id: str = "") -> SymbolTable:
    """The declarations of ``program`` (as parsed with ``trace``/``spans``), each exactly once, in source order."""
    program_name = (program.program_id or "UNKNOWN").upper()
    # ``scope_id`` is given by a caller that holds several files whose programs share a PROGRAM-ID (the document builder
    # then qualifies it with the file, so no two scopes collide)
    scope_id = scope_id or f"program:{program_name}"

    markers = [m for m in trace.programs if m[0] == "program-id"]
    foreign_from = 0
    unsupported: list[UnsupportedFact] = []
    if len(markers) > 1:
        # a second PROGRAM-ID: nested or batched.  Everything from it on belongs to a program the IR does not model.
        first_foreign = markers[1][2]
        foreign_from = first_foreign
        for _, name, index in markers[1:]:
            unsupported.append(UnsupportedFact("NESTED_PROGRAM_NOT_MODELLED", name or "?",
                                               _marker_span(trace, index, spans)))

    notes: dict[tuple[str, str], str] = {}
    global_names: set[str] = set()
    for clause, name, index in trace.entry_notes:
        if clause == "RENAMES":
            unsupported.append(UnsupportedFact("RENAMES_NOT_MODELLED", name, _marker_span(trace, index, spans)))
        else:
            notes[("item", name)] = clause
            if clause == "GLOBAL":
                global_names.add(name)

    builder = _Builder(scope_id, spans, notes, foreign_from, program, trace)
    program_id = builder.add("program", program_name)
    for entry in program.entry_points:
        builder.add("entry", entry.strip("'\"").upper(), parent=program_id)
    paragraph_places: dict[str, list[tuple[Span | None, int]]] = {}
    for (name, logical), (_, span) in zip(trace.paragraphs, spans.paragraphs):
        paragraph_places.setdefault(name.upper(), []).append((span, logical))
    for paragraph in program.paragraphs:
        queue = paragraph_places.get(paragraph.name.upper(), [])
        span, logical = queue.pop(0) if queue else (None, -1)
        # a paragraph header read from a second program's text is that program's, not this scope's
        foreign = foreign_from > 0 and logical >= foreign_from
        builder.add("paragraph", paragraph.name, parent=program_id, span=span,
                    span_code="" if span is not None else "SPAN_UNAVAILABLE",
                    unsupported="NESTED_PROGRAM_NOT_MODELLED" if foreign else "")

    ownership = record_ownership(program.file_definitions)
    for definition in program.file_definitions:
        file_id = builder.add("file", definition.name, parent=program_id, section="file",
                              span_code="SPAN_FILE_SECTION_NOT_TRACED",
                              attributes=tuple(sorted({"assign_kind": definition.assign_kind,
                                                       "organization": definition.organization.name,
                                                       "sort_file": str(definition.is_sort_file).lower()}.items())))
        for record in definition.record_groups:
            owners = ownership.candidates(record.name)
            builder.item(record, file_id, (), "file", record=True)
            if len(owners) > 1:
                row = builder.rows[-1]
                # a record declared under two FDs is addressable program-wide but not owned by either
                builder.rows[-1] = _with_attributes(row, (("owners", ",".join(owners)),))
    # the parser also appends LINKAGE items to working_storage (lowering reads them there) as equal copies: they are
    # declared once, as LINKAGE
    for root in program.linkage_section:
        builder.item(root, program_id, (), "linkage")
    for root in program.working_storage:
        if root not in program.linkage_section:
            builder.item(root, program_id, (), "working-storage")

    declared_special = {d.name for d in builder.rows if d.kind in ("data-item", "linkage-param")}
    for register in SPECIAL_REGISTERS:
        if register not in declared_special:
            builder.add("special-register", register, parent=program_id, attributes=(("builtin", "true"),))

    rows = _finish(builder.rows)
    scope = Scope(scope_id, "program", "", frozenset(global_names))
    return SymbolTable(spans.file, (scope,), rows, tuple(sorted(unsupported, key=_unsupported_key)))


def _with_attributes(row: Declaration, extra: tuple[tuple[str, str], ...]) -> Declaration:
    return Declaration(**{**row.__dict__, "attributes": tuple(sorted(row.attributes + extra))})


def _finish(rows: list[Declaration]) -> tuple[Declaration, ...]:
    """Mark graph-node collapse and same-qualification duplicates (both need the whole list)."""
    graph_count: dict[str, int] = {}
    for row in rows:
        if row.graph_node_id:
            graph_count[row.graph_node_id] = graph_count.get(row.graph_node_id, 0) + 1
    same_chain: dict[tuple[str, tuple[str, ...], str], int] = {}
    for row in rows:
        if row.addressable and row.kind in ("data-item", "linkage-param", "record", "condition-name"):
            key = (row.kind, row.qualification, row.name)
            same_chain[key] = same_chain.get(key, 0) + 1
    out: list[Declaration] = []
    for row in rows:
        collapsed = bool(row.graph_node_id) and graph_count[row.graph_node_id] > 1
        unsupported = row.unsupported
        if (not unsupported and row.addressable
                and same_chain.get((row.kind, row.qualification, row.name), 0) > 1):
            unsupported = "DUPLICATE_DECLARATION_SAME_QUALIFICATION"
        out.append(Declaration(**{**row.__dict__, "graph_node_collapsed": collapsed, "unsupported": unsupported}))
    return tuple(out)


def _unsupported_key(fact: UnsupportedFact) -> tuple[str, str, int]:
    return fact.code, fact.subject, fact.span.line if fact.span else 0


def _marker_span(trace: ParseTrace, logical: int, spans: SpanTable) -> Span | None:
    if not 0 <= logical < len(trace.lines) or trace.lines[logical].line <= 0:
        return None
    where = trace.lines[logical]
    return Span(spans.file, where.line, where.column, basis="line" if where.note else "token",
                exact=not where.note, note=where.note)

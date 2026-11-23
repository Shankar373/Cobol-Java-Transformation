# Layer 5 design: project-wide semantic facts

Status: **design accepted for L5-P1 only (section 11); P1 implemented, P2-P7 still design.** Written against
`HEAD 6f683dd` on `codex/enterprise-phases-continuation` (2026-11-23) and revised at `be00388` with the entry probes
(section 11) and the owner decisions D1-D4, D9 (section 9.3). Everything outside section 11.2 is unimplemented. Deterministic, open-source only, **no LLM**, no network.

Governing documents: `docs/decisions/ADR-0013_LAYER5_SEMANTIC_FACTS_AND_LAYER6_APPLICATION_IR.md` (ADR-0013),
`docs/architecture/LAYER_MODEL.md` (LM), `docs/discovery/DIALECT_PARSER_FRONTEND_AUDIT.md` (L4 audit, closure record
at its end) and `docs/discovery/KNOWLEDGE_GRAPH_AUDIT.md` (KG audit, Phase 0 addendum).

Evidence convention. `path:line` is something this design's author read at HEAD. `[V]` = read and quoted/paraphrased
from the cited line. `[UNVERIFIED]` = inferred, not read, or needs a probe before the phase that depends on it starts.
Where a number says "about" the author did not count it exactly.

Entry state: `docs/discovery/LAYER4_RESIDUAL_DISPOSITION.md` exists (committed in `8d54a42`) and now carries the recorded
owner decisions for every Layer 4 residual; section 8.0 and section 10 are ticked against it with evidence in section 11.

---

## 0. What exists, and what Layer 5 may not duplicate

| Capability | Existing authority (single) | Evidence |
|---|---|---|
| Reading reference format, cards, directives, dead branches, continuation folding | `enterprise/discovery/cobol_text.read_source` -> `SourceRead` | `cobol_text.py:81-96`, `:378`; engine face `source_format.py:3-15` |
| Positioned physical lines incl. folded continuations | `PositionedLine.span_at` | `source_positions.py:50-73` |
| COPY origin of every expanded line | `CopyOriginMap` / `OriginSpan` / `OriginBuilder` | `copy_origins.py` (class `OriginSpan` with `via` hops and `exact`; `origin_of` raises `IndexError` out of range) |
| Dialect / format / library order per file | `DialectProfile`, `profile_id`, `library_winner` | `dialect_profile.py:58-98`; `library_order.py:67-91` |
| COPY REPLACING grammar | `copy_replacing.parse_clause` | `copy_replacing.py:65-86` |
| Statement IR | `CobolParser.parse` -> frozen `CobolProgram` | `cobol_parser.py:586`, `:728`; `ir.py:1034` |
| Relationship vocabulary, edge identity, `graph_id` | `enterprise/discovery/graph.py` | `graph.py:48`, `:88`, `:114`, `:153`, `:195` |
| Graph build from facts/refs | `resolve.build_graph` | `resolve.py:723` |

What is **not** there (the gaps Layer 5 fills), each [V]:

1. **No positions in the IR.** `FieldReference` is only `name: str` (`ir.py:86-95`); statements carry no span; the
   parser keeps `last_line_map` beside the IR, and it is `()` "when a text-rewriting pass changed the number of lines
   in a way that cannot be mapped back" (`cobol_parser.py:608-619`, assigned at `:899`). L4 audit says so too
   (`DIALECT_PARSER_FRONTEND_AUDIT.md:118-119`).
2. **No symbol table or scope object.** Resolution is a text rewrite: `resolve_qualified_names` renames duplicated
   declarations to `A-OF-REC` and rewrites `A OF REC` to that name (`qualified_names.py:1-17`, `:224-296`). After the
   rewrite the qualifier chain is gone from the IR (`FieldReference.name` is the rewritten string).
3. **Discovery's structure scan is a first-verb sentence scanner.** `_procedure_sentence` dispatches on `words[0]`
   (`cobol_structure.py:306-328`), so a `MOVE`/`PERFORM`/`GO TO` inside `IF ... END-IF` yields no edge (KG audit
   addendum, `KNOWLEDGE_GRAPH_AUDIT.md:116-118`). Only an inline `PERFORM` is searched for nested `PERFORM`
   (`cobol_structure.py:313-318`).
4. **Parallel fact makers.** `application_discovery._extract_calls` (regex `USING\s+(.+?)(?:\.|$)`, split on
   whitespace, `application_discovery.py:474-515`), `_extract_entry_points` (`:585-599`), `_build_dependency_graph`
   with free-text `DependencyEdge.metadata` (`:664-727`), `engine/jcl/dd_binding.py` (SELECT -> DD, `:1-14`),
   `modernization/external_dependency_edges.py` (`:1-30`), `subsystem_calls.py` (`:1-25`), plus
   `capability_analyzer._analyze_call_linkage_arity` (`:447-492`, counts `level == 1` LINKAGE items versus
   `len(stmt.arguments)`; modes explicitly unused).
5. **Three statement walkers.** `control_flow.walk_statements` (`control_flow.py:66-74`, walks `__dict__` values that
   are tuples/lists of dataclasses), `capability_analyzer._iter_call_statements` over a hand-listed
   `_LINKAGE_WALK_ATTRS` (`capability_analyzer.py:133-156`), and `cobol_parser._walk_statements` (`:200-207`).
   [UNVERIFIED whether the hand list misses a body attribute.]
6. **The engine parser handles one program per file.** A grep of `cobol_parser.py` for `END PROGRAM` / nested-program
   handling found no hit; discovery models nesting (`cobol_structure._program_and_division`, `:124-144`;
   `resolve._program` filters `:nested`, `resolve.py:496-497`). [V by absence of grep hits; confirm with a probe.]

The design below adds **no parser, no resolver, no symbol table, no graph authority** beyond what is named as a
*refactoring of an existing one into a shared core*; section 1.3 states exactly which existing function becomes which.

---

## 1. Architecture decision and ownership

### 1.1 Options for consuming `cobol_parser`

| | A. Trace beside the IR (**chosen**) | B. Span fields on the frozen IR | C. Consume IR only, re-scan for positions | D. Grow discovery's `cobol_structure` into a full statement parser |
|---|---|---|---|---|
| Mechanism | `CobolParser.parse_traced()` returns `(CobolProgram, ParseTrace)`; `parse()` unchanged. The trace is built from data the parser already holds (`code_numbers`, `PositionedLine`, `_parse_statement` call frames) | add `span: Span\|None = field(default=None, compare=False, repr=False)` to ~35 IR classes | locate each IR statement by regex over the source | extend `scan_structure` to nested statements and PIC/OCCURS |
| Generation hashes | untouched by construction (IR objects unchanged) | probably untouched, but `dataclasses.replace`, any `__dict__` walk (`control_flow.walk_statements` iterates `__dict__`, `control_flow.py:70-71`) and pickling/hash users all see the new field [UNVERIFIED which do] | untouched | untouched |
| Second parser? | no | no | **yes** (regex positions = a parser) | **yes** (second full statement parser; discovery has no PIC/OCCURS/IR: `DataDecl` has `kind,name,level,line,column,owner,record,file` only, `cobol_structure.py:96-107`) |
| Nested statements | trace frames per `_parse_statement` call, plus inherited line for inline fragments | the constructor site must be touched at every `Statement(...)` call (a large edit in a 5602-line file) | cannot | possible, large |
| Fail-closed | a statement object not found in the final IR walk has no span => `SPAN_UNAVAILABLE` fact | a `None` span => same | guess | n/a |
| Risk | identity of IR objects across `dataclasses.replace` (see 2.6) | hash/serialisation drift; edits at every constructor | wrong by construction | duplicates the engine's hardest module; violates ADR-0013 decision 4 |

**Decision: Option A.** Reasons, tied to evidence:

* The IR deliberately stays position-free so generation is byte-identical (`cobol_parser.py:614-618` docstring of
  `last_line_map`; L4 audit residual `:118-119`). A trace that never enters the IR cannot change generated output;
  `tools/generation_hashes.py --check docs/audits/generation_hashes.json` proves it (55 apps x 2 runtimes,
  `DIALECT_PARSER_FRONTEND_AUDIT.md:92`).
* The data a trace needs already exists inside `parse`: `code_numbers` (physical line of each cleaned line,
  `cobol_parser.py:846`), `PositionedLine.span_at` (true physical origin through folded continuations,
  `source_positions.py:66-73`), the single choke point `_parse_statement(lines, start)` (`:2474`) through which
  block statements pass with a real logical-line index, and `_parse_inline_statements` (`:3599`) through which inline
  statements pass as synthetic one-element lists.
* Option D contradicts ADR-0013 §Decision 4 ("no new parser") and is the duplication the KG audit already flags.
* Option C is a second parser by another name.

### 1.2 Ownership (new modules; nothing existing moves)

```
engine/transformation/parse_trace.py     # frozen dataclasses only: ParseTrace, StatementTrace, DeclTrace, UseSite
engine/transformation/cobol_parser.py    # + parse_traced(); parse() delegates and returns the same IR
engine/transformation/qualified_names.py# resolution core exposes UseSite records; text rewrite becomes a projection (1.3)
engine/semantic_facts/                   # NEW package: Layer 5
    __init__.py
    span.py          # Span, CopyFrame, SpanBasis; builds from PositionedLine + OriginSpan
    symbols.py       # Declaration, Scope, SymbolTable (the one symbol table)
    references.py    # Reference, Access, classification table by IR class
    resolution.py    # Resolution record + mapping to graph vocabulary
    facts.py         # Fact kinds, closed vocabularies (FACT_KINDS, L5_RULES, UNSUPPORTED_CODES)
    calls.py         # CALL/USING/LINKAGE binding
    document.py      # SemanticFacts document, canonical JSON, semantic_id
    build.py         # orchestrator: sources -> document (the only entry point)
    graph_bridge.py  # read-only: edges for SELECT/DD/DSN/SQL/JCL taken from the graph, never recomputed
tests/semantic_facts/                    # NEW
```

Why `engine/semantic_facts/` and not `enterprise/discovery/`: Layer 5 needs the engine IR (PIC, OCCURS, statements),
which discovery does not have (L4 audit residual, KG audit finding). LM contract 1 lets the engine reach discovery
**only** through `graph_view`, `kg_query`/`kg_store` and `traceability` (`LAYER_MODEL.md:54-58`), enforced by
`tests/discovery/test_engine_graph_lint.py`. `graph_bridge.py` therefore reads the graph through a new read accessor
added to `graph_view` (or `kg_query`), **never** by importing `resolve`/`scan_cobol`. [UNVERIFIED: the exact import
allow-list in the lint test; read it in full before L5-P6.]

### 1.3 What is authoritative for what

| Concern | Authority | Layer 5's relation |
|---|---|---|
| Characters, lines, formats, directives, dead branches | `cobol_text.read_source` (single reader), through `source_format.positioned_lines` | consume `PositionedLine`; never re-read bytes (ADR-0013 §5, "Layer 4 -> 5") |
| Dialect, library order | `DialectProfile`, `library_winner` | consume; record `profile_id` per file; never re-detect |
| Statement and data structure (PIC, OCCURS, REDEFINES, level, statement kinds, bodies) | `CobolParser` IR | the only structure source for semantic classification |
| Where a statement/declaration is | `ParseTrace` (new, produced **by** the parser) | consume |
| Name binding and qualification | the **resolution core of `qualified_names`**, refactored to emit `UseSite` records | the `SymbolTable` is built from the same declaration list; the text rewrite becomes a function of those records (differential test, 8: L5-P2) |
| Relationships between artefacts | the knowledge graph (`graph.py`, vocabulary closed) | Layer 5 emits relations **only** by handing facts to the existing graph path; it reads existing edges for SELECT->DD->DSN etc. |
| Facts document | `engine/semantic_facts/document.py` | the sole producer (ADR-0013 §Decision 2) |

Concretely, the two things that are "refactored into a shared core" rather than duplicated:

1. `qualified_names.resolve_qualified_names`: today it (a) discovers declarations with `_DECLARATION` regex
   (`qualified_names.py:30`, loop `:233-257`), (b) names duplicates (`:262-271`), (c) resolves `OF/IN` chains
   (`resolve()`, `:296-317`) and (d) rewrites text (`:277-293`, `:318-340`). L5-P2 splits (a)-(c) into a function that
   returns data, and (d) consumes that data. The output text must stay **byte-identical** (differential test over the
   whole fixture corpus and the GnuCOBOL differential `tests/integration/test_qualified_oracle.py`, named in the module
   docstring, `qualified_names.py:15-16`).
2. `scoped_node_id` (`cobol_structure.py:47-55`) stays the only graph node-id spelling; the symbol table *maps to* it
   (3.5), it does not invent another.

### 1.4 Why this does not need a second anything

* **Second parser:** no. New code never matches COBOL grammar; it classifies already-parsed IR nodes and aligns
  operand names to already-tokenised positions (2.5).
* **Second resolver:** no. One resolution core (qualified_names) emits records; Layer 5 wraps them with the
  `resolved|ambiguous|unresolved|dynamic|unsupported` vocabulary.
* **Second symbol table:** no. `SymbolTable` replaces the in-function `_Item` list (`qualified_names.py:33-40`) and the
  `_record_owner`/`_file_records` dicts of the parser (`cobol_parser.py:594-606`) only as *consumers*; those are
  retired in L5-P7 after parity (7).
* **Second graph authority:** no. Facts about files/DD/DSN/SQL come **from** graph edges; facts Layer 5 computes
  (paragraph/data references) are offered to the graph through `graph.py` only (section 5.6).

---

## 2. Source spans and COPY-origin provenance

### 2.1 `Span`

```python
@dataclass(frozen=True)
class CopyFrame:                 # one COPY statement on the way, outermost first; == copy_origins.CopyHop
    file: str                    # file holding the COPY statement
    line: int                    # 1-based physical line of the COPY statement
    target: str                  # member named by the COPY

@dataclass(frozen=True)
class Span:
    file: str                    # file that PHYSICALLY holds the text (copybook file for copybook text)
    line: int                    # 1-based physical line in `file`
    column: int                  # 1-based physical column of the first character; 0 only if basis is "copy-site"
    end_line: int = 0            # 0 = unknown / not tracked
    end_column: int = 0
    via_copy: tuple[CopyFrame, ...] = ()
    basis: str = "token"         # "token" | "line" | "statement" | "copy-site"   (closed, SPAN_BASES)
    exact: bool = True           # False when basis != "token" or any rewrite touched the line (2.4)
```

Canonical JSON (keys sorted by the shared canonicaliser, 5.5):

```json
{"basis":"token","column":12,"end_column":19,"end_line":57,"exact":true,
 "file":"cpy/CUSTREC.cpy","line":57,
 "via_copy":[{"file":"src/PAY.cbl","line":31,"target":"CUSTREC"}]}
```

`via_copy[0]` is the outermost COPY (the program's), the last element the innermost; this is `OriginSpan.via`
(`copy_origins.py`, field `via`, "outermost first") rendered per hop. A program-local line has `via_copy == []`.
ADR-0013 §5 requires `span {file,line,column,via_copy[]}`; `end_line`, `end_column`, `basis`, `exact` are additive
fields (open decision D2).

### 2.2 Exact vs inexact (the contract)

| Situation | file/line | column | `basis` / `exact` | Source of truth |
|---|---|---|---|---|
| Program text, fixed format, no continuation | exact | exact | `token`/true | `PositionedLine.span`, `span_at` (`source_positions.py:66-73`) |
| Token on a folded continuation line | exact (true physical line) | exact | `token`/true | `ContinuationSegment` -> `span_at`; **engine only**: discovery tokens on folded lines keep first-line coordinates (L4 audit `:116-117`), so discovery tokens are never a position source for L5 |
| Mixed format file | per-line format (`PositionedLine.format`) | exact | `token`/true | `source_format._line_formats`, `PositionedLine.format` (`source_positions.py:56`) |
| Line with a TAB | exact | **inexact** | `line`/false, code `SPAN_COLUMN_TAB` | engine does not `expandtabs`, discovery uses `splitlines()` (L4 audit `:113-115`) |
| Statement nested inline in one logical line (`IF A THEN MOVE 1 TO B ELSE ...`) | the logical line | position within the line if the fragment is found exactly once after the previous fragment's cursor; else statement start | `token`/true or `statement`/false | `_parse_inline_statements` hands fragments as synthetic lists (`cobol_parser.py:3599`, `synthetic = [fragment]`) |
| Line rewritten by `REPLACE` | exact | inexact | `line`/false, code `SPAN_REWRITTEN_REPLACE` | `_apply_replace_directives` keeps line count and `kept` numbers (`cobol_parser.py:664-713`) but changes text |
| Copybook line, no REPLACING | exact physical line in the copybook | inexact today: `_strip_sequence_numbers` strips sequence area and `lstrip()`s (`copybook_model.py:507-527`) | `line`/false until L5-P1 passes the column offset through | proposal 2.3 |
| Copybook line, REPLACING changed that line | exact (line structure kept) | inexact | `line`/false, `SPAN_REWRITTEN_COPY_REPLACING` | `copy_origins.py` docstring: REPLACING "rewrites words inside lines and keeps the line structure" |
| REPLACING text contains a newline | **not** the copybook line | n/a | `copy-site`/false: line = the COPY statement's line | `copybook_model.py:655-658` builds `OriginSpan(..., 1, (), exact=False)` for every expanded line; `copy_origins.py` docstring: "never a guessed copybook line" |
| FD-section COPY | the COPY statement | n/a | `copy-site`/false | `fd_copybooks.py:142` `OriginSpan(_hop.file, _hop.line, (), exact=False)`; also `fd_copybooks.py:57-60` |
| Declaration whose name was generated (`A-OF-REC`) | span of the *declaration token* `A` | exact | `token` | 2.4 |
| Reference `A OF REC` rewritten to `A-OF-REC` | span of `A` .. `REC` as written in source | exact (pre-rewrite sites) | `token` | `UseSite` records emitted before rewriting (2.4) |
| Anything the trace cannot place | named fact `SPAN_UNAVAILABLE`, `span` absent | - | - | 2.6 fail-closed rule |

### 2.3 Building a span from the existing maps (one function, no new reader)

```
span_for(logical_line_ref, column_hint) =
    physical = positioned_line.span_at(offset)            # file="" for the program; true line/col, continuation-aware
    origin   = copy_origin_map.origin_of(physical.line)   # file/line/via/exact of the *expanded* text
    -> Span(file=origin.file, line=origin.line (+ in-line offset kept), column=physical.column,
            via_copy=[CopyFrame(h.file,h.line,h.target) for h in origin.via],
            basis=..., exact=origin.exact and not rewritten and not tab)
```

Important: `CopyOriginMap` indexes **expanded** text lines (`origin_of(expanded_line)`), while `PositionedLine.line`
indexes the text the parser was handed. These coincide only if the text handed to `parse()` is the expanded text.
`application_discovery._parse_program_unit` reads the program file and `materialize_copybooks_into_program` merges
copybook records at IR level without rewriting the source (`copybook_model.py:667-684` docstring: "The COBOL source is
never rewritten and files are never concatenated"), so for **data-division copybooks the program text and the
copybook text are two separate texts** and the map is per copybook model (`CopybookModel.origins`,
`copybook_model.py:107`). Therefore: a declaration coming from a copybook is spanned by the *copybook's* positioned
lines with `via_copy = [CopyFrame(program file, line of the program's COPY statement, member)] + origin.via`;
the program-side COPY statement site comes from the program's own `PositionedLine`s. [UNVERIFIED: which input text the
FD path passes to `parse` after `expand_fd_copybooks`; read `fd_copybooks.py:79-149` and its call site in the phase.]

P1 proposal (additive): `_expand_copybook_traced` and `_parse_copybook_expanded` already preserve line count
(`"\n".join`, `copybook_model.py:507-527`); extend them to also return a parallel `tuple[int, ...]` of column offsets
removed per line, so declaration columns in copybooks become exact for lines REPLACING did not touch. Until then the
rule in 2.2 applies (line exact, column inexact).

### 2.4 Surviving the text-rewrite passes in `cobol_parser.parse` (the hard part)

The pipeline after cleaning is (`cobol_parser.py:854-899`): `_apply_replace_directives` (keeps count, `kept` numbers) ->
`resolve_qualified_names` (**changes line count**: `_join_split_qualifiers` merges lines, `_expand_corresponding`
expands one line into several, `qualified_names.py:91-118`, `:178-222`, `:290-293`) -> `rewrite_next_sentence` (keeps
count, rewrites text in place, `next_sentence.py:34-80`) -> logical-line join of `TO`/`IF` continuations and trailing
`.` lines (`cobol_parser.py:862-896`) -> `last_line_map` set only `if mapped` (`:899`).
`mapped = len(code_lines) == len(code_numbers)` after qualified names and again after next-sentence (`:855`, `:857`).

Hence today **any** program that uses CORRESPONDING expansion or a split qualifier has an empty `last_line_map`. That
is acceptable for the IR consumer, not for Layer 5. Proposed mechanism, three parts:

**(a) Every pass returns an origin vector, not only text.** Change the internal helpers to return
`(lines, origin)` where `origin[i]` is a tuple of source-line indexes the output line `i` derives from
(`(k,)` for a 1:1 line, `(k, k+1)` for a joined pair, `(k,)` repeated for each line a CORRESPONDING expansion
produces). `resolve_qualified_names`'s public signature and its text output stay identical (it is called elsewhere;
[UNVERIFIED which callers] - add `resolve_qualified_names_traced` and make the old name a one-line wrapper).
`rewrite_next_sentence` and `_apply_replace_directives` are already 1:1.

**(b) Reference sites are captured *before* rewriting.** In the use-resolution loop (`qualified_names.py:318-340`)
the pre-rewrite line is in hand and `_QUALIFIED.finditer(masked)` yields `found.start()`, `found.end()` and the
qualifier chain. Emit one record per use:

```python
@dataclass(frozen=True)
class UseSite:
    line_index: int                 # index into the pre-rewrite code_lines (maps to a physical line via code_numbers)
    start: int                      # offset in that cleaned line
    end: int
    name: str                       # as written, upper-cased
    qualifiers: tuple[str, ...]     # as written, nearest first
    targets: tuple[int, ...]        # indexes of candidate declarations (len==1 resolved, >1 ambiguous, 0 unresolved)
    rewritten_to: str               # "" when the text was left alone (refused/ambiguous)
```

Unqualified names are `UseSite`s too (qualifiers `()`), collected with the existing `_WORD` scan the module already
runs for the leftover-duplicate check (`qualified_names.py:342-361`). The column is exact when the line was not
changed by `REPLACE` (the caller compares pre- and post-REPLACE line text; `changed` is a per-line boolean), the format
is not a tab line, and the line is not a continuation join; otherwise the site degrades to `line`/`exact=False` with
the named code from 2.2 - never a guessed column.

**(c) Statements: line from the trace, column from alignment.**
`parse_traced` records, in `_parse_statement` (`:2474`), a frame `(start_index, depth)` and the produced IR object id;
after the parse the IR is walked once (reusing `control_flow.walk_statements` semantics) and each reachable statement
object is matched to its frame by `id()`. Statements created by inline fragments inherit the enclosing frame's
logical line. A frame whose object is not in the final IR (replaced by `dataclasses.replace` or discarded) yields no
span: `SPAN_UNAVAILABLE`. The set of statements with no span is a **pinned inventory** (shrink-only, like
`ALLOWED_STRUCTURE_PARSERS`, `test_engine_graph_lint.py:30`, `:99-101`).

Operand -> token alignment (references inside statements): for a statement with logical-line range `[a, b]` the
operand names the IR reports (e.g. `MoveStatement.source/targets`, `ir.py:493-501`) are matched, in order, against the
`UseSite`s of those lines (b above). A statement whose IR operands and UseSites disagree in count or name is marked
`SPAN_OPERAND_MISALIGNED` and its references take the statement span, `exact=False`. This is checked by a count
identity, not by trust.

### 2.5 Testable mechanism and fail-closed rule

* **Position parity test** (extends the Phase 0 method of
  `tests/transformation/test_positions_parity_layer4.py`, L4 audit `:86`): for each of the 7 fixtures and for new
  fixtures (CORRESPONDING, split qualifier, REPLACE, nested COPY, continuation, mixed format), every `Declaration` and
  every `Reference` span must satisfy `source_text[span.column-1 : ...]` (read through the **same reader**) equal to
  the token text it claims; one-edit variants (insert a blank, move a line) must change the span, as in Phase 0.
* **Round-trip test:** for every exact span, re-reading the file named by `span.file` at `span.line/column` and
  upper-casing yields `name` (for copybook spans, the physical copybook file).
* **Mutation checks (must fail):** remove the origin-vector from `_join_split_qualifiers`; skip `REPLACE` exactness
  flag; drop `via_copy`; collapse `span_at` to the first line of a continuation.
* **Fail-closed rule (normative):** if a span cannot be proven by the rules above, the fact is **still emitted**
  (the declaration/reference exists) with `span: null` plus a diagnostic fact
  `{"kind":"diagnostic","code":"SPAN_UNAVAILABLE","subject":...}`; no consumer may substitute a neighbouring line.
  A fact whose span is `exact=false` carries `confidence != "certain"` (5.3) only when the fact's *meaning* depends on
  position; a declaration whose name and scope are known stays `certain` with an inexact span.
* **Never:** a span is never computed from the rewritten text, never from discovery's token coordinates on folded
  continuation lines, never from `str.find` over the whole file.

### 2.6 Known hazards of Option A

* `id()` matching breaks if the parser post-processes IR objects with `dataclasses.replace` after construction.
  [UNVERIFIED how often; grep `replace(` in `cobol_parser.py` in L5-P1.] Mitigation: the pinned inventory above; or
  record spans in a `ParseTrace` keyed by `(paragraph, ordinal path)` computed by a deterministic post-walk, if
  `id()` proves unreliable.
* Two statements with identical content are distinct objects; `id()` distinguishes them, equality would not.

---

## 3. Symbol and scope model

### 3.1 Declaration identity

```python
@dataclass(frozen=True)
class Declaration:
    decl_id: str            # 3.4
    kind: str               # DECL_KINDS (closed): program, entry, section, paragraph, data-item, record, condition-name,
                            #   rename, index-name, file, copybook-member, linkage-param
    name: str               # upper-case source spelling, "" never (FILLER has kind data-item, name "FILLER", not addressable)
    level: int              # 0 for non-data; 1-49, 66, 77, 88 otherwise
    scope: str              # scope_id of the enclosing Scope (3.2)
    parent: str             # decl_id of the enclosing group/FD/program, "" for roots
    qualification: tuple[str, ...]   # ancestor names nearest-first (== qualified_names _Item.ancestors, :33-40)
    section: str            # WORKING-STORAGE | LOCAL-STORAGE | LINKAGE | FILE | ... or ""
    origin_member: str      # copybook file when the text came from a COPY, else ""
    template_id: str        # copybook-local identity (3.4), "" for program text
    graph_node_id: str      # scoped_node_id(owner, name, graph_kind) (3.5), "" when the graph has no such node
    graph_node_collapsed: bool  # True when 2+ declarations share graph_node_id (duplicate names)
    span: Span | None
    attributes: tuple[tuple[str, str], ...]  # sorted (k, v): usage, pic_kind, occurs, depends_on, redefines, global, external ...
    unsupported: str        # "" or a code from UNSUPPORTED_CODES (3.3)
```

### 3.2 Scopes

```python
@dataclass(frozen=True)
class Scope:
    scope_id: str           # "program:PAYROLL" | "program:OUTER/INNER" | "copybook:cpy/C.cpy" (template scope)
    kind: str               # "run-unit" | "program" | "copybook-template"
    parent: str             # enclosing scope_id; "" for the run-unit root
    global_names: frozenset[str]   # names declared GLOBAL here (visible in contained programs)
```

Rules (each cites what exists, or is marked as new behaviour):

| Rule | Behaviour | Existing support |
|---|---|---|
| Program scope | every declaration of a program lives in `program:<PROGRAM-ID>` (upper-case) | `scoped_node_id` uses `program:NAME` as owner (`cobol_structure.py:47-55`, owner chosen at `:208`) |
| Nested programs | contained program scope's `parent` is the containing program's scope; `END PROGRAM` closes it | discovery has the program stack (`cobol_structure.py:124-144`); **engine parser does not** [UNVERIFIED, 0.6] => until L5-P2b a file with a nested `PROGRAM-ID` gets `unsupported(NESTED_PROGRAM_NOT_MODELLED)` for the *contained* program's facts, never merged into the outer scope |
| GLOBAL | name visible in all contained programs; a contained program may redeclare it (inner wins; recorded as `shadow`) | new; parser support for the `GLOBAL` clause [UNVERIFIED]. Default: record `attributes[global]=true` only when the clause is read, else `unsupported(GLOBAL_CLAUSE_NOT_READ)` |
| EXTERNAL | one storage area per run unit keyed by name: declarations in two programs with the same EXTERNAL name are linked by a relation `external-peer` (no merge) | new; `cobol_parser.py:1625-1632` treats `EXTERNAL` only as an ASSIGN word [V]; the data clause is [UNVERIFIED] |
| LINKAGE SECTION | `section="LINKAGE"`; positional parameters come from `PROCEDURE DIVISION USING` (`CobolProgram.using_parameters`, `ir.py` CobolProgram; parser `_parse_procedure_using`, `cobol_parser.py:2309`) | [V] fields; modelling here is new |
| FILE SECTION | an FD is a declaration of kind `file`; each 01 under it kind `record` with `parent=file`; records are addressable program-wide | `RecordOwnership` and the explicit "ownership is a FILE SECTION fact, ambiguous when declared under 2 FDs" rule (`file_ownership.py:1-14`); L5 consumes `record_ownership`, does not recompute |
| Copybook re-use per program | the **same copybook file declares different `Declaration`s in each program** that copies it, because REPLACING pairs and library winner are per COPY (`copybook_model.py:925-934`: a name resolved to different files per program is program-specific; `_unit_replacing_pairs` `:808`) | `template_id` links them (3.4) |
| Levels | 01-49 data-item/record; **77** independent item (`qualified_names.py:239-241` resets the stack for 77); **88** condition-name child of the preceding item, never a qualifier owner (`qualified_names.py:236` skips 66/88 for duplicate naming); **66** RENAMES: the parser refuses it with a named warning (`cobol_parser.py:2097-2100` [V line range from grep]) => `Declaration(kind="rename", unsupported="RENAMES_NOT_MODELLED")`, span from the entry's trace | partial |
| OCCURS / INDEXED BY | `occurs`, `occurs_depending_on`, `indexed_by` already on `DataItem` (`ir.py:248-300`); each `INDEXED BY` name is a `index-name` declaration child of the table item (the IR comment already calls it "an occurrence-number item") | [V] |
| REDEFINES | `DataItem.redefines` names the base; Layer 5 resolves the name **in scope** into `redefines_decl_id`; a REDEFINES naming a duplicated name stays refused (`qualified_names.py:245-257` docstring + loop that discards duplicated names mentioned in data clauses) => `ambiguous` with candidates | [V] |
| Duplicate names | within one scope, same name under different groups: allowed, distinguished by qualification chain; same name with identical chain: `ambiguous` redefinition => `unsupported(DUPLICATE_DECLARATION_SAME_QUALIFICATION)` | partial (today both get `A-OF-REC`-style names; identical chains would collide and take `-X`, `qualified_names.py:262-268`) |
| Shadow | an inner-scope declaration of a name visible from an outer scope (GLOBAL) is recorded as relation `shadows` | new |
| FILLER | declared, never addressable, never an ambiguity candidate (`qualified_names.py:253` excludes it from `by_name`; discovery skips FILLER nodes, `cobol_structure.py:226-228`) | [V] |
| Paragraph / section | declared per program; names unique per program; duplicate paragraph name => `ambiguous` | graph resolves them via `declarations` dict (`resolve.py:408-422`) |
| Index/special registers | `RETURN-CODE`, `SQLCODE`, `SQLCA`, `TALLY`...: `kind="special-register"` declarations from a closed list in `facts.py`; `with_sqlca_fields` exists (`cobol_parser.py:4714`) | [V] existence; the list is new and must be justified per phase |

### 3.3 Closed vocabularies owned by Layer 5

`DECL_KINDS`, `REF_KINDS`, `ACCESS` (3.6/4.2), `FACT_KINDS` (5.4), `L5_RULES` (rule ids), `UNSUPPORTED_CODES`,
`SPAN_BASES`. Each is an import-time constant like `graph.RESOLVER_RULES` (`graph.py:97-110` pattern); constructing a
fact outside them raises (fail closed, same discipline as `Edge.__post_init__`, `graph.py:273-289`). They are **not**
added to `EDGE_RELATIONS`/`UNRESOLVED_REASONS` (contract 4 = a schema change that moves five artefacts together,
`LAYER_MODEL.md:120-123`); 5.2 shows the one-way mapping.

### 3.4 Deterministic ids

`decl_id` must not depend on file enumeration order.

```
decl_id = "sym:" + scope_id + "/" + kind_tag + ":" + "/".join(reversed(qualification)) + "/" + NAME + "#" + K
K = 1-based ordinal among declarations in the same scope with the same (kind, qualification, NAME),
    ordered by (declaring physical file, physical line, physical column)     # position, never discovery order
template_id = "tpl:" + sha256(copybook_path || "\0" || copybook_digest || "\0" || local_line || "\0" || NAME)[:16]
```

* The ordinal key is the declaration position in its own file, so two programs copying the same copybook give
  `sym:program:A/.../NAME#1` and `sym:program:B/.../NAME#1` that share `template_id`; the per-program id exists because
  REPLACING and the library winner differ per program (`copybook_model.py:925-934`).
* Qualification in the id makes `AMT OF GRP1` and `AMT OF GRP2` two ids; the existing graph id
  `data-item:PAYROLL/AMT` (`scoped_node_id`) cannot (it has no qualification), which is `graph_node_collapsed`.
* A generated unique name (`A-OF-REC`, `qualified_names.py:262-268`) is an **attribute** (`generated_name`), not part
  of identity: if the qualification algorithm changes the id does not.
* Stable under: reordering files in the checkpoint, adding an unrelated file, running twice. Changes under: editing
  the declaring file's bytes (by design), different library winner (different `origin_member`).

### 3.5 Relation to graph node ids

| Layer 5 declaration | Graph node (existing) | Rule |
|---|---|---|
| program | `program:NAME` (`resolve._program`, `resolve.py:494-522`) | `graph_node_id` = that id; nested programs: graph tags them `:nested` (`resolve.py:496`) |
| paragraph / section | `paragraph:PROG/NAME`, `section:PROG/NAME` via `scoped_node_id` | exact |
| data-item / record | `data-item:PROG/NAME`, `record-layout:PROG/NAME`; for a copybook-owned item `data-item:cpy/C.cpy/NAME` (`resolve._link_copybook_declarations` links program `contains` those, `resolve.py:753-792`) | name-level only; qualified duplicates collapse -> `graph_node_collapsed=true` |
| file | `logical-file`/`file` nodes (`resolve._logical_file`, `:475`) | exact when the graph has it |
| copybook member | `copybook:NAME` - **one node per name** even when programs resolve it differently (L4 audit `:120-121`, KG addendum `:111-112`) | `origin_member` carries the real path; no attempt to fix the graph here |

Layer 5 never changes a graph id; doing so would change `graph_id` (sha256 of nodes+edges, `graph.py:195-198`) and
would be a Layer 3 schema decision (LM contract 4).

---

## 4. Qualified-name and reference resolution; typed references

### 4.1 Resolution algorithm (extends `qualified_names.resolve`, `:296-317`)

For each `UseSite` (2.4b) with `name N` and written qualifiers `q1 ... qn` (nearest first):

1. candidates = declarations in the **scope chain** (current program, then GLOBAL names of enclosing programs, then
   special registers) whose `name == N` and whose ancestor chain contains `q1 ... qn` as a subsequence in order
   (this is exactly `chain.index(qualifier, position)`, `qualified_names.py:301-309`; the subsequence rule is the
   COBOL "OF/IN chain need not be contiguous" rule as implemented and oracle-pinned, `qualified_names.py:15-16`).
2. 0 candidates -> `unresolved(missing-data-item)` (graph vocabulary, `graph.py:54-73`).
3. exactly 1 -> `resolved`.
4. >1 -> `ambiguous` with `candidates = [decl_id,...]` sorted by `decl_id`. The text rewrite still refuses such a use
   (it leaves the text alone, `qualified_names.py:310-316` appends the problem and returns `None`); Layer 5 reports the
   same fact with its candidates, which the text pass could not.
5. Implicit qualification: an unqualified use of a duplicated name is `ambiguous` (GnuCOBOL rejects it too,
   `qualified_names.py:6-12`); an unqualified use of a name declared once is `resolved`.
6. A qualifier name that is not an ancestor of any candidate -> `unresolved(missing-data-item)` with
   `detail.qualifier_unmatched=<name>`.
7. Conflicts with paragraph names: a word may be a data name and a paragraph; the classification (4.2) decides which
   namespace is consulted (a `PERFORM X` consults paragraphs/sections; a `MOVE X` data). A word valid in both and
   used where the verb allows both => `ambiguous` across namespaces.

Subscripts / reference modification: `X(I J)` and `X(2:3)` -> the **base** name resolves; each subscript is a
separate use (`read`); the reference carries `subscripts=[ref ids]`, `refmod=true`. `_DATA_REFERENCE`-style
parsing exists in `capability_analyzer.py:~160` (`_DATA_REFERENCE = ...(?:\s*\([^()]*\))?`) [V pattern, usage
[UNVERIFIED]]; Layer 5 takes subscripts from the IR operand string via the one tokenizer
(`cobol_text.tokenize`, `cobol_text.py:516`), not a new regex.

CORRESPONDING: today expanded to per-pair statements by `_expand_corresponding` (`qualified_names.py:178-222`) or
refused (`:342-352`). Layer 5 records the **group pair** (`corresponding_of: [src_group, dst_group]`) and the
expanded pair list as facts with `rule="l5.corresponding-pair"`; a CORRESPONDING the expansion refuses is
`unsupported(CORRESPONDING_FORM_NOT_LOWERED)` with the statement span.

### 4.2 Typed references and access classification

```python
@dataclass(frozen=True)
class Reference:
    ref_id: str                     # "ref:" + decl owner statement id + "#" + ordinal      (deterministic)
    kind: str                       # REF_KINDS: data, paragraph, section, file, program, copy, condition, index, host-var
    access: str                     # ACCESS: def, use, read, write, modify, call, perform, goto, open, close, none
    owner_stmt: str                 # stmt_id of the containing statement
    name: str                       # as written
    qualifiers: tuple[str, ...]
    resolution: Resolution          # 5.1
    span: Span | None
    subscripts: tuple[str, ...] = ()   # ref_ids
    refmod: bool = False
```

`stmt_id = "stmt:" + program scope + "/" + paragraph + "/" + path` where `path` is the ordinal path of the statement
among its siblings through nested bodies (e.g. `3.1.2`): deterministic from the IR alone.

Classification table (mapping from `ir.py` statement classes; field names as read at `ir.py:429-885`). `R` read, `W`
write, `M` modify (read+write), `D` def (declaration site, section 3).

| IR class | reads | writes | modifies | other |
|---|---|---|---|---|
| `OpenStatement` / `CloseStatement` | - | - | - | file ref, `access=open|close`, `mode` from `.mode` |
| `ReadStatement` | `key` | `into_field`; the file's record area (`record_name`) | - | file ref `access=read`; bodies `at_end_body`, `not_at_end_body`, `invalid_key_body`, `not_invalid_key_body` walked |
| `StartStatement` | `key` | - | - | file ref |
| `WriteStatement` / `RewriteStatement` | `from_field` | record area (`record_name`) | - | file ref `access=write` / rewrite |
| `DeleteStatement` | - | - | - | file ref |
| `MoveStatement` | `source` (`source_expr`) | `targets` (`target_ref`) | - | literals are not references |
| `AddStatement` | `source` | `giving_target` | `target` (when no GIVING) | `rounded`, size-error bodies |
| `SubtractStatement` | `source`, `sources` | `to_field` (GIVING) | `from_field` | |
| `MultiplyStatement` | `source` | `target` (GIVING) | `multiplicand` when no GIVING | |
| `DivideStatement` | `source`, `divisor` | `target`, `remainder` | - | the IR is `target` for both INTO/GIVING [UNVERIFIED: which form maps to modify] |
| `ComputeStatement` | `expression_expr` names | `target` | - | |
| `IfStatement` | names in `structured_condition` | - | - | then/else bodies walked. A condition with no `structured_condition` => `unsupported(CONDITION_UNSTRUCTURED)`, never regex-scraped |
| `PerformStatement` | `until_condition` names | - | `VARYING` index (if the IR carries it [UNVERIFIED]) | paragraph ref `access=perform` to `paragraph_name`; `thru_target` second ref; `body` walked |
| `GoToStatement` | - | - | - | paragraph ref `access=goto`; an empty/data-name target => `dynamic` (KG: `cobol_structure` emits dynamic for GO TO over a data name, `cobol_structure.py` module docstring) |
| `CallStatement` | each `arguments[i]` per `passing_modes[i]`: REFERENCE => `modify` (callee may write) unless callee-proven read-only (5.4), CONTENT/VALUE => `read` | `returning` => `write` | - | program ref `access=call` to `program_name`; `is_dynamic` => dynamic (6.1) |
| `UnstringStatement` | `source`, `delimiter` | `targets`, `pointer`, `tallying_pointer` | `varying_pointer` [UNVERIFIED direction] | |
| `StringStatement` | `parts`/`structured_parts`, delimiters | `target` | `pointer` | |
| `DisplayStatement` | `parts` | - | - | |
| `SetConditionStatement` | - | the condition's parent item `W` (an `88` SET TO TRUE writes the parent) | - | condition-name ref |
| `SetIndexStatement` | `value` | - | `targets` | index refs |
| `AcceptStatement` | `source` (if a name) | `target` | - | |
| `InitializeStatement` | `replacing` values | `targets` | - | `all_to_value` |
| `InspectStatement` | - | `counter` | `target` for `REPLACING`/`CONVERTING`, read for `TALLYING` | |
| `SearchStatement` | `table`, `varying`, when-conditions | `varying` index modify | - | |
| `SortStatement` | `keys` | - | - | `using`/`giving` are files; `sort_file` an SD |
| `ExecSqlStatement` | `inputs` (host variables in) | `outputs` (host variables out), `indicators` | - | SQL tables go through graph edges (6.3) |
| `Stop/Goback/ExitProgram/ExitPerform` | - | - | - | control facts |

`EVALUATE` has **no class in the `Statement` union** (`ir.py` union listing; no `EvaluateStatement`), so how it is
lowered is [UNVERIFIED]; a statement the IR cannot represent produces `unsupported(<code>)` at its span. The parser
already tracks "unparsed" statements with `_emit_unparsed` (`cobol_parser.py:~640`); Layer 5 consumes
`parser.diagnostics` (`:624-631`) as `unsupported` facts instead of losing them.

Nested bodies: walk with **one** shared walker. `control_flow.walk_statements` (`control_flow.py:66-74`) is the
candidate; L5-P3 proves by test that it reaches every body attribute that `_LINKAGE_WALK_ATTRS`
(`capability_analyzer.py:133-156`) and `_walk_statements` (`cobol_parser.py:200-207`) reach, over the corpus, then the
other two retire.

---

## 5. Resolution states and the semantic-fact contract

### 5.1 States and the mapping to the graph vocabulary

```python
@dataclass(frozen=True)
class Resolution:
    state: str                          # "resolved" | "ambiguous" | "unresolved" | "dynamic" | "unsupported"
    candidates: tuple[str, ...] = ()    # decl_ids / program ids / literal values, sorted
    reason: str = ""                    # for unresolved: a key of graph.UNRESOLVED_REASONS; for unsupported: an UNSUPPORTED_CODE
    variable: str = ""                  # for dynamic: the data item carrying the value
    confidence: str = "certain"         # one of graph.CONFIDENCE_VALUES
    rule: str = ""                      # an L5_RULES id
```

| Layer 5 `state` | graph `resolution` | graph fields | graph `confidence` | notes |
|---|---|---|---|---|
| `resolved` | `resolved` (or `external` for platform/system targets, as `resolve._program` does, `resolve.py:513-518`) | - | `certain` (`derived` when the resolution used the library-winner or a REPLACING rewrite) | |
| `ambiguous` | `ambiguous` | `candidates` | `heuristic` (`confidence_for`, `graph.py:144-151`) | the graph keeps candidate **paths** for programs/copybooks (`resolve.py:411-414`); Layer 5 keeps `decl_id`s |
| `unresolved` | `unresolved` | `reason` in `UNRESOLVED_REASONS` (`graph.py:54-73`: `missing-program`, `missing-copybook`, `missing-paragraph`, `missing-data-item`, `missing-logical-file`, ...) | `unresolved` | **no new reasons** |
| `dynamic` | `unresolved` + `dynamic=True` + `variable` + `candidates` | `reason="dynamic-target"` (`graph.py:61`, non-blocking) | `heuristic` when literals were followed (`MOVE literal TO var`, `scan_cobol.py:9`, `:73`), else `unresolved` | the graph has **no** `dynamic` resolution value (`RESOLUTIONS = ("resolved","external","ambiguous","unresolved")`, `graph.py:48`), so the fork is Layer 5's `state`, the graph keeps the existing encoding |
| `unsupported` | **no edge** | - | - | Layer 5 only: a named code (3.3). Never a graph edge, never an invented `UNRESOLVED_REASONS` key. The facts document is the only place it lives |

Rule: consumers branch on `state`/`confidence`/`reason`, **never on message text** (ADR-0013 §5). One test enforces
that every fact with `state != resolved` carries a non-empty `reason` or `candidates`, mirroring
`Edge.__post_init__` (`graph.py:273-289`).

### 5.2 Fact record

```python
@dataclass(frozen=True)
class Fact:
    fact_id: str            # "fact:" + sha256(kind|subject|span key|rule)[:16]  - content derived, not an enumerate()
    kind: str               # FACT_KINDS (5.4)
    subject: str            # decl_id | stmt_id | ref_id | "program:NAME" ...
    span: Span | None
    resolution: Resolution
    rule: str               # L5_RULES id  (one per producing rule; mirrors graph.RESOLVER_RULES discipline)
    attributes: tuple[tuple[str, str], ...]    # sorted
```

Canonical JSON of one fact:

```json
{"attributes":{"access":"modify","arg_index":"2","mode":"REFERENCE"},
 "fact_id":"fact:8d1c9a0f2b7e4c11","kind":"call-binding","rule":"l5.call-using",
 "resolution":{"candidates":[],"confidence":"certain","reason":"","rule":"l5.call-using","state":"resolved","variable":""},
 "span":{"basis":"token","column":28,"end_column":36,"end_line":88,"exact":true,"file":"src/PAY.cbl","line":88,"via_copy":[]},
 "subject":"ref:stmt:program:PAY/MAIN-PARA/2.1#2"}
```

### 5.3 Confidence

`certain` = resolved from exact spans and a unique declaration; `derived` = resolved through a documented rewrite
(REPLACING, library winner, qualified-name uniquification); `heuristic` = ambiguous or dynamic-with-literals;
`unresolved` only with `state` unresolved/dynamic-without-literals (the graph invariant that the two agree,
`graph.py:288-289`, is copied). An inexact span lowers confidence only when the fact is positional (e.g. an edge
identity includes line/column, `graph.edge_identity`, `graph.py:153-178`) - for facts that feed graph edges, the edge
needs a file/line/column (`graph.py:274-275` refuses otherwise), so a fact with `span=null` produces **no** edge and
instead a `SPAN_UNAVAILABLE` diagnostic.

### 5.4 Fact kinds (closed `FACT_KINDS`)

| Group | Kinds |
|---|---|
| Declarations | `program`, `entry`, `copybook-member`, `section`, `paragraph`, `file`, `record`, `data-item`, `condition-name`, `rename`, `index-name`, `linkage-param`, `special-register` |
| References | `data-ref`, `paragraph-ref`, `section-ref`, `file-ref`, `program-ref`, `condition-ref`, `index-ref`, `host-var-ref` |
| Structure | `contains` (group->child), `redefines`, `occurs`, `renames`, `shadows`, `external-peer`, `record-owner` (FD->record, from `file_ownership`) |
| Layout | `record-layout` (offset/size per item where the usage is certified; else `unsupported(LAYOUT_USAGE_UNCERTIFIED)`; fields on `DataItem` for this are `sign_separate`, `synchronized`, `usage`, `ir.py:~292-302`, ADR-0009 comment; sizes already computed by `redefines.py`/`group_storage.py` which Layer 5 *calls*, not reimplements) |
| Flow | `performs`, `goes-to`, `falls-through` (consecutive paragraphs), `reaches` is **derived, not stored** (computed by consumers over `performs/goes-to/falls-through`, avoiding a second reachability engine; `kg_query` already owns reachability, LM contract 1) |
| Data flow | `def-use` (reference -> reaching declaration; **intra-program** only), `call-binding` (arg -> parameter), `file-binding` (6.3) |
| Cross program | `call` (CALL site -> callee program), `cancel`, `entry-call`, `call-binding`, `call-arity`, `call-size-compat` |
| External | `sql-host-var`, `sql-table` (via graph), `jcl-dd-binding` (via graph), `copy-site` |
| Meta | `diagnostic` (`SPAN_UNAVAILABLE`, `SPAN_OPERAND_MISALIGNED`, ... ), `refusal` (a frontend refusal from the profile: `OO_COBOL_UNSUPPORTED`, `SCREEN_SECTION_UNSUPPORTED`, `REFERENCE_FORMAT_MIXED_UNSUPPORTED`, `CONDITIONAL_COMPILATION_UNEVALUATED`, `cobol_parser.py:728-790` (approx.); `source_format.py:81-97`) |

### 5.5 Document schema, identity, determinism

```json
{
  "schema": "systemaops.semantic-facts/1.0",
  "header": {
    "semantic_id": "<sha256 hex>",
    "facts_digest": "<sha256 hex of body only>",
    "checkpoint_id": "<layer 1>", "source_digest": "<layer 1>",
    "graph_id": "<layer 3, or \"\" if the graph was not supplied>",
    "profile_ids": [["src/PAY.cbl", "<profile_id>"], ["cpy/C.cpy", "<profile_id>"]],
    "id_algorithm": "sha256", "tool": "systemaops-semantic-facts", "tool_version": "<__version__>",
    "complete": true,
    "unsupported_summary": {"RENAMES_NOT_MODELLED": 2}
  },
  "scopes": [...], "declarations": [...], "references": [...], "facts": [...]
}
```

* `semantic_id = sha256(canonical_bytes({"body": body, "bindings": {checkpoint_id, source_digest, graph_id,
  profile_ids}}))`; `facts_digest = sha256(canonical_bytes(body))`. `semantic_id` covers the bindings so the same facts
  under another graph or profile are a different document; `facts_digest` lets two checkpoints be diffed on content
  alone. This mirrors `graph_id_of` (`graph.py:195-198`). Recommendation D1 below.
* Canonical bytes: **reuse** `graph._canonical_bytes` (`graph.py:189-192`: sorted keys, compact separators,
  `ensure_ascii=True`, sets/tuples sorted). It is underscore-private; L5-P4 exposes it as `graph.canonical_bytes`
  (a pure alias; `graph_id` unchanged, proven by `test_kg_acceptance.py` criterion 1, `KNOWLEDGE_GRAPH_AUDIT.md:86`)
  rather than copying it.
* Determinism rules: no timestamps, no absolute host paths (paths are checkpoint-relative, as `DialectProfile.file`),
  no `id()`, no dict-order dependence, no set iteration without `sorted`, `fact_id` content-derived, all lists sorted
  by `(file, line, column, kind, subject)` then `fact_id`. Same checkpoint + same profiles + same graph => identical
  bytes on two runs and under file-order permutation (test: shuffle input order; assert `semantic_id` equal).
* `complete=false` if any unsupported/unspanned fact exists whose absence could change a consumer's conclusion;
  consumers must read `unsupported_summary` (fail closed).

### 5.6 Sealing into evidence (conditional key)

Follow the existing pattern exactly, three places:

1. `engine/evidence/models.py`: add `semantic_facts: tuple[tuple[str,str], ...] = ()` beside `graph_traceability`/
   `dialect_profiles` (`models.py:428-431`), and in `canonical_evidence_graph` add
   `if manifest.semantic_facts: graph["semantic_facts"] = dict(manifest.semantic_facts)` after the two existing
   conditional blocks (`models.py:261-268`). Manifests without it keep their hash (the stated purpose of the pattern,
   comment at `:262-263`, `:266-267`).
2. `engine/evidence/integrity.py`: a `SEMANTIC_FACTS_BINDING_MISMATCH` violation next to `PROFILE_BINDING_MISMATCH`
   (`integrity.py:72`, check `:323-351`): pairs well-formed (`semantic_id`, `facts_digest`, `graph_id`), no duplicates,
   and **cross-field consistency**: `graph_id` equals the `graph_traceability` pair's `graph_id`, and the
   `profile_ids` equal `dialect_profiles`.
3. API: `api/readiness.py` already carries `library_orders` and `dialect_profiles` in the readiness record
   (`readiness.py:88-89`, `:98-112`); add the analogous record entry (policy-version bump, `readiness.py:29`).
   **Dependency [V]:** `api/service.py` does not supply `knowledge_graph_path`/`graph_traceability`, so real runs carry
   no `graph_id` (KG addendum `:108-110`; LM `:157`). Until that wiring exists, `header.graph_id=""` and the
   binding check requires the empty string to match an absent `graph_traceability`; the facts document is still sealed.

---

## 6. Cross-program and external-resource facts

### 6.1 CALL / USING / LINKAGE

Inputs (all already parsed): `CallStatement.program_name/arguments/passing_modes/is_dynamic/returning`
(`ir.py:560-571`), parser `_parse_call` (`cobol_parser.py:3394-3475`), header `CobolProgram.using_parameters`
(`ir.py`), `linkage_section` items.

Known defects Layer 5 must not inherit: the parser tokenises `USING` by `split()` and treats `BY` as a mode switch
(`cobol_parser.py:3454-3468`); literals with spaces (`'A B'`) and `OMITTED` are mis-split; `application_discovery`
splits on whitespace with a regex (`:497-505`). Layer 5 builds argument lists from the **tokenizer**
(`cobol_text.tokenize`, literals are one token) over the statement's logical-line range, and checks the IR's
`arguments` for count/name agreement, diverging -> `SPAN_OPERAND_MISALIGNED` + `unsupported(CALL_USING_UNPARSED)`.

Facts:

| Fact | Content | Resolution |
|---|---|---|
| `call` | CALL site -> callee. literal target: `program:NAME`; matched against declared programs by `normalize_cobol_name` (the join the analyzer uses, `application_discovery.py:679-681`) | `resolved` / `ambiguous` (same PROGRAM-ID in several files: graph already lists `candidates`, `resolve.py:518-521`) / `unresolved(missing-program)` / `external` for system programs (`resolve.py:513-518`) |
| `call` dynamic | `CALL WS-PROG`: target variable; candidates = literals Layer 5 can prove (VALUE clause of the item, `MOVE literal TO` chain as `scan_cobol` does, `scan_cobol.py:9,73,497-501`) | `dynamic`, `candidates=[literals]`, `variable` |
| `call-arity` | arguments passed vs callee header `USING` count (not `level==1` count, which is what the analyzer uses today, `capability_analyzer.py:474-478`): `OMITTED` counts as present | `resolved` match / mismatch is a *finding fact* `state=resolved, attributes.arity_ok=false` - a mismatch is a true fact, not an unresolved reference |
| `call-binding` | arg *i* <-> callee header parameter *i*: caller decl_id, callee linkage decl_id, `mode` (`BY REFERENCE/CONTENT/VALUE`), `returning` | per pair |
| `call-size-compat` | for each pair where both items have a certified layout: byte size, PIC class (numeric/alphanumeric), usage; verdict `equal`, `caller_smaller`, `caller_larger`, `class_mismatch`, `unknown` | `unknown` + `unsupported(LAYOUT_USAGE_UNCERTIFIED)` when either side's layout is not certified (never a guess); `BY VALUE` requires numeric elementary on both sides (else `class_mismatch`) |
| `entry` | `ENTRY 'NAME'` is a second entry point of the program: `Declaration(kind="entry")`, callable as a `call` target | `application_discovery._extract_entry_points` regex (`:585-599`) retires (7); discovery already handles `ENTRY` literal (`scan_cobol.py:278`) |
| `cancel` | `CANCEL 'NAME'` -> `program-ref access=call`... recorded as fact kind `cancel` (discovery already folds `CANCEL` into the CALL scan, `scan_cobol.py:276`); the engine IR has no `CancelStatement` | [UNVERIFIED engine handling] -> `unsupported(CANCEL_NOT_IN_IR)` until the parser emits it |
| nested programs | a CALL resolves first against programs **contained in the caller's program** (COBOL rule), then the run unit | new; until the engine parser models nesting (0.6) a CALL inside a nested file resolves against the file's program ids only and carries `rule=l5.call-flat` + `confidence=derived` |
| copybook-in-copybook | a CALL appearing in copybook text has `via_copy`; its caller is the *including program* (per-program declarations, 3.2) | span chain handles it; discovery assigns copybook-resident CALLs to `file:<path>` owner, `scoped_node_id` (`cobol_structure.py:208`), the facts layer re-owns them per including program |

Subsystem calls: `CALL 'MQOPEN'`, `'CBLTDLI'`, ... remain classified by `classify_call` in discovery and
`subsystem_calls.py` (lowering). Layer 5 does not re-classify; for a CALL the graph already routed to a subsystem node
(not `calls`), the fact is `external-call` with the **graph's** destination node id.

### 6.2 What is read from the graph vs computed

| Fact | Source |
|---|---|
| Program-to-program `calls`, `copies`, `contains`, `defines` | **graph** (existing edges, with the engine's CALL detail replaced by Layer 5 `call` facts in L5-P7) |
| SELECT -> logical file -> DD -> DSN -> vsam-cluster | **graph** (`assigns-file`, `binds-ddname`, `uses-dataset`, relation names `graph.py:88-111`; node kinds `logical-file`, `dd`, `dataset`, `vsam-cluster`, `graph.py:75-86`) |
| EXEC SQL tables, `uses-db2`, `sql-reads/writes` | **graph** for tables; `sql-binds-hostvar` is in the vocabulary, **host-variable resolution to declarations** is computed by Layer 5 (`ExecSqlStatement.inputs/outputs/indicators`, `ir.py:805-` [V fields]) |
| Paragraph/data **references with nesting** | **computed** (the graph lacks them: KG addendum `:116-118`) |
| Access/def-use, qualified resolution, spans with `via_copy`, call binding/arity/size | **computed** |
| JCL step/DD/proc facts | **graph** (JCL parsing is `scan_jcl`; engine duplicates `jcl_parser`, `jcl_dependencies`, `jcl_discovery`, `jcl/preprocess`, KG addendum `:122-123`: **not covered by the lint inventory**, so Layer 5 must not read them) |

Declared-but-not-emitted relations (`sql-reads`, `sql-writes`, `mq-put`, `ims-call`, ... `LAYER_MODEL.md:153`):
Layer 5 may **propose** emitting `reads-item`/`writes-item`/`performs`/`goes-to` for nested statements through
`graph.py` (`resolve.py`) in L5-P6; adding any *new* relation is a Layer 3 schema change and an open owner decision
(D6), not something this design does.

### 6.3 File/VSAM/SQL chain

`file-binding` fact = join of: Layer 5 `file` declaration (SELECT/FD, from `FileDefinition.assign_kind`
LITERAL|DDNAME, `ir.py:392-427`) with graph edges. States: `resolved` (DD found), `unresolved(missing-dd |
unbound-ddname | missing-logical-file)` (reasons exist, `graph.py:62-72`), `ambiguous` (several steps bind
different DSNs: `candidates`), `dynamic` (not applicable), `unsupported(GDG_GENERATION_NOT_RESOLVED)` for `(+1)`
datasets (`dd_binding.py:14-15` documents "catalogued and flagged 'not resolved'"). The engine's `BOUND/UNBOUND/
LITERAL_PATH/UNUSED_DD` statuses (`dd_binding.py:1-14`) map one-to-one in the differential test of L5-P6/7.

---

## 7. Retirement and consolidation of duplicates

Each retirement is blocked by a **differential test that compares old output to the Layer 5 projection over the full
fixture corpus and a synthetic stress corpus, byte-for-byte after normalisation**, plus the standing gates
(`tools/generation_hashes.py --check`, `tests/discovery/test_engine_graph_lint.py` shrink-only inventory,
`[certify]` where listed).

| # | Duplicate | Replace with | Differential test that must pass first | Lint/inventory effect |
|---|---|---|---|---|
| R1 | three statement walkers (`control_flow.walk_statements`, `capability_analyzer._iter_call_statements`, `cobol_parser._walk_statements`) | `control_flow.walk_statements` | for every IR in the corpus, same ordered statement identity sequence; a unit test that every dataclass-typed attribute holding statements is reached | none (not in the allow-list); smaller code |
| R2 | `application_discovery._extract_calls` + `_extract_entry_points` (regex over text, `:474-515`, `:585-599`) | Layer 5 `call`/`entry` facts projected to `ProgramCall` | `ProgramCall` tuples (caller, target, arguments, call_type) equal on all fixtures; on a stress corpus (literal with spaces, `OMITTED`, `BY CONTENT`, nested `IF`) the new output is **different only in documented defects**, listed in the test, each with a fixture | `application_discovery` stays in `ALLOWED_STRUCTURE_PARSERS` until its remaining regexes go; entry must be removed only when its own scanning is gone |
| R3 | `capability_analyzer._analyze_call_linkage_arity` (`:447-492`) | Layer 5 `call-arity` facts | verdict equality on the corpus **plus** new fixtures where header-USING count differs from `level==1` count; the capability verdict must never become *more* permissive for an existing UNSUPPORTED fixture (guard test) | `[certify]` (capability_analyzer is Layer 7; `docs/CAPABILITY_MATRIX.md` row if any text changes) |
| R4 | `DependencyEdge.metadata` free text (`ir.py:1115`, set at `application_discovery.py:701-705`) | typed edges (Layer 6 projection) | every consumer of `metadata` strings listed by grep and migrated; equality of (source,target,edge_type) set | Layer 6 phase, not Layer 5 |
| R5 | `dd_binding` SELECT->DD (`engine/jcl/dd_binding.py`) | graph `assigns-file`/`binds-ddname` + Layer 5 `file-binding` | status equality (`BOUND/UNBOUND/LITERAL_PATH/UNUSED_DD`) on the JCL fixtures | not in the lint inventory (KG addendum `:122-123`); add it to a new lint first |
| R6 | `external_dependency_edges` text scans for MQ/IMS/DB2/CICS (`:1-30`); it still masks comments itself (L4 audit `:125-126`) | graph facts + Layer 5 host-var resolution | ledger entries (kind, visible, classification, proof state, required) equal on the corpus; the column-6-`*` fixture decision (owner, D8) resolved first | shrink `ALLOWED_STRUCTURE_PARSERS` |
| R7 | parser-internal ownership dicts `_record_owner*`, `_file_records` (`cobol_parser.py:594-606`) | `RecordOwnership` via `file_ownership.record_ownership` consumed through the symbol table | `file_ownership` parity: same owner/ambiguity map | internal |
| R8 | `qualified_names._Item` list (`:33-40`) | `SymbolTable` | text output identical (1.3) | none |
| R9 | `subsystem_calls` | **stays** for lowering (it is a justified exception, `test_engine_graph_lint.py` allow-list); argument/queue *resolution* reads Layer 5 | no retirement now | none |

Order: R1 (zero risk) -> R8 (inside L5-P2) -> R7 -> R2 -> R3 -> R5 -> R6 -> R4 (Layer 6). Nothing is deleted in the
phase that introduces its replacement; deletion is the **next** phase after one green CI on the differential test, so
a bad replacement never takes the old code with it.

---

## 8. Phased roadmap

Every phase: hermetic suite and coverage floor green; `python tools/generation_hashes.py --check
docs/audits/generation_hashes.json` identical (Layer 5 must not change generated output, `LAYER_MODEL.md:167-168`);
`tests/discovery/test_engine_graph_lint.py` and `test_single_reader_lint.py` inventories do not grow
(`DIALECT_PARSER_FRONTEND_AUDIT.md:102-104`); mypy ratchet, dependency map regenerated from the tracked set
(`6f683dd` shows the project does this); KG benchmark threshold `3.0` unchanged. `[certify]` is required when a phase
touches `engine/modernization/capability_analyzer.py`, `engine/verdict/derivation.py`, generation, or oracle digest
pinning (do-not-regress areas, `LAYER_MODEL.md:171-172`). Per the project memory, one commit/push per phase; CI runs
full suites, local runs focused tests only.

### 8.0 Entry conditions

1. ADR-0013 Phase 0 rows P0.1-P0.8 accepted (ADR table) and the Layer 4 closure record accepted: "Closure is accepted
   when CI and certification on the commit that carries this record are green" (`DIALECT_PARSER_FRONTEND_AUDIT.md:127`).
   [UNVERIFIED that CI for `6f683dd` is green.]
2. `docs/discovery/LAYER4_RESIDUAL_DISPOSITION.md` - **pending**; must exist and give each residual an owner, status and
   target phase: (i) tab handling (`:113-115`), (ii) discovery tokens on folded continuation lines (`:116-117`),
   (iii) FD-section/nested COPY library search (`:120-121`), (iv) `external_dependency_edges` comment masking
   (`:125-126`), (v) unused `DialectProfile.unsupported` consumption and `std` from profile (`:111-112`).
3. `api/service.py` supplies `graph_id` to the run (else `header.graph_id=""`, 5.6): **done, section 11.3.**
4. Owner decisions D1-D4 (section 9) answered: **done, section 9.3.**

### L5-P1 - Spans (no new facts yet)

* **Scope:** `ParseTrace`, `parse_traced`, `Span`/`CopyFrame`, origin vectors through the rewrite passes (2.4),
  copybook column offsets (2.3), statement frames, pinned unspanned inventory.
* **Modules:** `engine/transformation/{parse_trace.py (new), cobol_parser.py, qualified_names.py,
  copybook_model.py, fd_copybooks.py}`, `engine/semantic_facts/span.py` (new).
* **New tests (mutation-sensitive):** position round-trip over declarations and statements for 7+ fixtures
  (including CORRESPONDING, split qualifier, REPLACE, nested COPY with REPLACING, continuation, mixed format, tab line);
  one-edit variants must move spans; mutation list in 2.5; `last_line_map` is non-empty for the CORRESPONDING and
  split-qualifier fixtures (it is empty today [V by code reading, `cobol_parser.py:855`; confirm by probe]);
  unspanned inventory pinned and shrink-only.
* **Acceptance:** every parsed statement and declaration of every fixture is either spanned (round-trip passes) or in
  the pinned inventory with a named code; `parse()` IR **equal** and generation hashes identical.
* **Determinism / refusal:** `SPAN_UNAVAILABLE`, `SPAN_COLUMN_TAB`, `SPAN_REWRITTEN_REPLACE`,
  `SPAN_REWRITTEN_COPY_REPLACING`, `SPAN_OPERAND_MISALIGNED` are named; never a guessed position.
* **Gates:** hash tool, lints, mypy. `[certify]`: not needed unless `cobol_parser.py` edits are classified as
  generation-affecting by the project's certify rule [UNVERIFIED; ask owner, D9].
* **Risks:** `id()` matching (2.6); the qualified-names change touches an oracle-pinned module.

### L5-P2 - Symbols and scopes

* **Scope:** `Declaration`, `Scope`, `SymbolTable`; declaration list consumed by `qualified_names` (R8); deterministic
  ids (3.4); `graph_node_id` mapping (3.5); level 66/77/88, OCCURS/INDEXED BY, REDEFINES resolution; FD/record
  ownership via `file_ownership`; per-program copybook declarations; `unsupported` codes for RENAMES, nested programs,
  GLOBAL/EXTERNAL where the parser cannot read them.
* **Modules:** `engine/semantic_facts/{symbols,facts}.py`, `qualified_names.py`, `cobol_parser.py` (declaration trace).
* **New tests:** id stability under file-order shuffle and unrelated-file addition; same copybook in two programs with
  different REPLACING gives two `decl_id`s sharing `template_id`; duplicate name under two groups yields two ids and
  `graph_node_collapsed`; `resolve_qualified_names` text **byte-identical** old vs new on the corpus; `RENAMES`,
  nested-program fixtures produce `unsupported`; one-edit variants (rename a group) change dependent ids only.
* **Acceptance:** every declaration the IR holds has exactly one `Declaration`; none is invented; the IR-to-symbol count
  identity holds (flattened items in `materialize_copybooks_into_program` are marked `derived_from` the original so they
  are not counted twice, `copybook_model.py:667-684` appends flattened leaves as top-level items).
* **Gates:** hash tool; the GnuCOBOL differential `tests/integration/test_qualified_oracle.py` (needs the oracle:
  CI); lints.
* **Risks:** flattened-leaf duplicates in the IR; `GLOBAL`/`EXTERNAL`/nested not read by the parser (probe first).

### L5-P3 - References and resolution

* **Scope:** `UseSite` emission (2.4b), `Reference`, classification table (4.2), resolution (4.1), shared walker (R1),
  `unsupported` conversion of parser diagnostics, `CORRESPONDING` pair facts.
* **Modules:** `engine/semantic_facts/{references,resolution}.py`, `qualified_names.py`, `control_flow.py` (no change),
  retire the two other walkers.
* **New tests:** statement-class table is exhaustive: a test enumerates the `Statement` union (`ir.py` union) and fails
  if a class has no row (mutation: add a class); every nested body reached (fixtures with `MOVE` inside `IF ... END-IF`,
  `PERFORM` inside `EVALUATE`/`AT END`); access direction per class (ADD modifies, MOVE source reads, ...); ambiguous
  qualified reference lists exactly the candidates; unresolved qualifier; subscript/ref-mod; a fixture where the first
  verb is `IF` and the nested `MOVE` is found (the case `cobol_structure` misses).
* **Acceptance:** for every program, the set of data names the IR references equals the set of Layer 5 references
  (count identity), with no reference lacking a `Resolution`.
* **Gates:** hash tool; lints; `[certify]` not required.
* **Risks:** `EVALUATE` lowering unknown (4.2); direction of `DivideStatement`/`PerformStatement VARYING` fields.

### L5-P4 - Document, identity, sealing

* **Scope:** `SemanticFacts` document, canonical JSON, `semantic_id`/`facts_digest`, `build.py` orchestrator, store/CLI
  entry (a function; API route is a later decision), evidence conditional key + integrity check (5.6), readiness record
  field.
* **Modules:** `engine/semantic_facts/{document,build}.py`, `enterprise/discovery/graph.py` (alias
  `canonical_bytes` only), `engine/evidence/{models,integrity}.py`, `api/readiness.py`.
* **New tests:** two runs and shuffled input give identical bytes; tamper with any fact -> `semantic_id` mismatch and
  `SEMANTIC_FACTS_BINDING_MISMATCH`; a manifest **without** `semantic_facts` keeps its existing sealed hash (golden
  test with a stored hash); manifest with it changes the seal; `graph_id` cross-check; `profile_ids` cross-check.
* **Acceptance:** evidence round-trip with tamper test (like Phase 0 P0.4); a document for a refused file records the
  refusal as a fact.
* **Gates:** hash tool (graph alias must leave `graph_id` unchanged: run `test_kg_acceptance`); **`[certify]` required**
  (evidence manifest seal is Layer 13).
* **Risks:** touching evidence hashing; `graph_id` absent in real runs (5.6).

### L5-P5 - Cross-program facts

* **Scope:** `calls.py`: call/dynamic call, arity (header USING), binding, size/class compatibility, ENTRY, CANCEL (as
  `unsupported` if the IR lacks it), nested programs where modelled, copybook-in-copybook owner.
* **New tests:** fixtures with BY REFERENCE/CONTENT/VALUE, OMITTED, RETURNING, literal-with-space argument,
  mismatched arity, PIC size mismatch (X(5) vs X(10); 9(4) vs X(4); COMP-3 vs DISPLAY -> `unknown` or
  `class_mismatch` as specified), dynamic call with two `MOVE literal` candidates; mutation: change one PIC length,
  the compat verdict must change.
* **Acceptance:** R2/R3 differential reports are produced (not yet retired); every `CallStatement` in the IR has a
  `call` fact.
* **Gates:** lints, hash tool; `[certify]` not needed until R3 retires (it touches `capability_analyzer`).
* **Risks:** layout certification is partial (usage coverage); PIC of numeric-edited items.

### L5-P6 - Files, VSAM, SQL, JCL from the graph

* **Scope:** `graph_bridge.py` read accessor on `graph_view`; `file-binding`, host-var resolution; proposal to emit
  nested `performs`/`goes-to`/`reads-item`/`writes-item` edges **through `graph.py`** (existing relations only).
* **Tests:** SELECT->DD->DSN->cluster chain fixtures incl. GDG `(+1)`; unbound DD; two steps binding different DSNs
  (`ambiguous`); lint proving `engine/semantic_facts` imports discovery only via `graph_view`/`kg_query`; benchmark
  stays within threshold `3.0`.
* **Acceptance:** nested `MOVE`/`PERFORM` edges appear in the graph for the fixture `cobol_structure` misses and
  `graph_id` changes **only** by those added edges (diff test via `kg_query.diff`); no edge without
  file/line/column.
* **Gates:** KG benchmark, `test_kg_acceptance`, lints, hash tool; `[certify]` if the graph schema/relation set is
  touched (it must not be).
* **Risks:** edge volume growth (10k scale benchmark); the 73 declared rules vs 7 stamped (KG addendum `:119-121`)
  means new edges must use existing rule ids or add `l5-*` rules - adding rules is a `RESOLVER_RULES` change (closed
  set, `graph.py:97-110`): decision D6.

### L5-P7 - Retirement (R1-R8, section 7)

One retirement per commit-phase pair; each deletes code only after its differential test has been green in CI once.
`[certify]` required for R3. Inventories shrink.

### Beyond Layer 5

Layer 6 projection (typed edges, R4) and the migration of `CobolProgram` consumers is Layer 6 work (ADR-0013 §3) and
is **not** scheduled here.

---

## 9. Non-goals and open owner decisions

### 9.1 Non-goals

* No LLM, no network, no proprietary compiler (`DIALECT_PARSER_FRONTEND_AUDIT.md:68-69`).
* No new parser, resolver, symbol table or graph authority; no change to the Statement IR classes or to generated Java.
* No Layer 6 projection, no typed-edge migration, no change to Layers 7-14 verdicts (only retire duplicate fact makers
  with differential proof).
* No inter-procedural value propagation or constant propagation: `def-use` is intra-program; the only cross-program
  data-flow fact is the CALL argument-to-parameter binding.
* No runtime equivalence claims, no CICS/IMS/MQ command-body semantics (discovery records resources only), no OO COBOL,
  no `SCREEN SECTION`, no `ALTER`, no `COPY` in the procedure division beyond what the single expansion path already
  does [UNVERIFIED which path handles procedure-division COPY].
* No change to the closed graph vocabulary and no deviation from `LAYER_MODEL.md` contracts 1-4 without an ADR.
* No claim about GnuCOBOL being the customer's compiler (`compilers.py:396-397`, per L4 audit `:69`).

### 9.2 Open owner decisions (recommendation each)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Does `semantic_id` cover the bindings (checkpoint, graph, profiles) or only the body? | Cover both; publish `facts_digest` for body-only diffing (5.5). |
| D2 | Extend `span` beyond ADR-0013's `{file,line,column,via_copy[]}` with `end_*`, `basis`, `exact`? | Yes; additive, documented in this file and the ADR amendment at L5-P1. |
| D3 | Package home: `engine/semantic_facts/` (engine IR access) vs `enterprise/discovery/` | `engine/semantic_facts/`, with graph access only via `graph_view`/`kg_query`; revisit if the lint seam proves too narrow. |
| D4 | Is nested-program support in the engine parser in scope for L5-P2, or recorded as `unsupported(NESTED_PROGRAM_NOT_MODELLED)` until later? | Record as unsupported in P2 (honest), schedule parser support only if a corpus program needs it; probe first (0.6). |
| D5 | Do `GLOBAL`/`EXTERNAL` clauses get parsed now? | Parse the clause into `attributes` only (no semantics beyond visibility) in P2 if the parser change is small; else `unsupported`. |
| D6 | Add `l5-*` resolver rules and/or new relations to the graph vocabulary? | No new relations. New rule ids only if nested-edge emission (P6) needs them; one coordinated change, with `RESOLVER_RULES` and docs together (contract 4). |
| D7 | Interprocedural reaching definitions | Defer past P7; keep `call-binding` as the hook. |
| D8 | `external_dependency_edges` column-6-`*` fixture (L4 audit `:125-126`) | Fix the fixture to a real comment indicator in column 7 as the single reader reads it; prerequisite of R6. |
| D9 | Is a `[certify]` run required for parser/qualified-names edits that are provably output-neutral (hash tool identical)? | Treat `cobol_parser.py`/`qualified_names.py` edits as `[certify]` because they sit under the generator; owner confirms. |
| D10 | Should the document be stored (`kg_store`-style tables) or only sealed + regenerated? | Regenerate deterministically from the checkpoint; store only `semantic_id` in evidence in P4; a store is a later decision. |
| D11 | Policy: do ambiguous references or unresolved dynamic CALLs lower readiness? (`LAYER_MODEL.md:147` assigns it to layer 2 as an open policy decision) | Facts carry the state; readiness policy stays a layer 2 decision, informed by `complete`/`unsupported_summary`. |

### 9.3 Decisions recorded 2026-11-23 (D1-D4, D9)

Recorded on the project owner's instruction of 2026-11-23 to "resolve decisions D1-D4 and D9". Each adopts the
recommendation above after the entry probes (section 11); each is reversible by an ADR-0013 amendment. D5-D8, D10
and D11 stay open: none of them blocks P1.

| # | Decision (resolved) | Basis |
|---|---|---|
| D1 | `semantic_id` covers the bindings (checkpoint, graph, profiles) and the body; `facts_digest` is the body-only digest for diffing. Applies from L5-P4; nothing in P1 is hashed. | Same pattern as `graph_id_of`; a binding change must change the seal. |
| D2 | `Span` extends ADR-0013's `{file,line,column,via_copy[]}` with `end_line`, `end_column`, `basis`, `exact` and a named `note`. Additive. **Implemented in P1** (`engine/semantic_facts/span.py`); ADR-0013 carries the amendment. | A span that cannot say "inexact" would imply exactness (design 2.2). |
| D3 | Package home is `engine/semantic_facts/`; graph access only through `graph_view`/`kg_query` (P6). `test_engine_graph_lint` and `test_single_reader_lint` pass with the package in place (P1 imports no discovery module). | Needs the engine IR; the lint seam is intact. |
| D4 | Nested programs are **recorded as unsupported** in P2 (`NESTED_PROGRAM_NOT_MODELLED`), not modelled. Probe (a) shows the engine parser neither models nor refuses them today (section 11.1); that over-acceptance is a separate owner item, not changed here. | Parser support would change which programs generate; no corpus program is nested (11.1). |
| D9 | Edits to `cobol_parser.py` and `qualified_names.py` **are** `[certify]` changes even when the hash tool is identical, because they sit under the generator. P1's commit carries `[certify]`. | The hash tool proves generation, not the oracle verdicts or the evidence seal. |

---

## 10. What must be true before L5-P1 starts

- [x] ADR-0013 Phase 0 rows accepted and the Layer 4 closure commit's CI **and** certification are green. Evidence:
      CI fast checks 45155941742, Full integration validation 45155984410, Corpus certification 45155990012 and
      Supply chain 45155941625 all `success` on `be00388` (durations in `docs/operations/CI_LEVELS.md`).
- [x] `docs/discovery/LAYER4_RESIDUAL_DISPOSITION.md` exists with a disposition and a recorded owner decision per residual.
- [x] Probes done and recorded: (a)-(f) in section 11.1.
- [x] Decisions D1-D4 and D9 answered (section 9.3).
- [x] `tests/discovery/test_engine_graph_lint.py` and `test_single_reader_lint.py` pass with `engine/semantic_facts/` present.
- [x] `python tools/generation_hashes.py --check docs/audits/generation_hashes.json` identical (110 builds) with the P1 change.
- [x] A fixture set for P1 exists: CORRESPONDING, split qualifier, REPLACE, COPY REPLACING (newline case), nested COPY,
      fixed continuation, mixed format, tab line, FD COPY - `tests/semantic_facts/test_span_p1.py` - plus every repo
      COBOL fixture round-tripped.
- [x] `header.graph_id`: **wired** (section 11.3), not accepted-empty.

---

## 11. Entry probes, the P1 implementation, and the graph_id wiring (added at `be00388`)

### 11.1 Probe results (each was UNVERIFIED above)

| Probe | Result (observed by running the parser / reading the code) | Consequence |
|---|---|---|
| (a) nested-program file | `parse()` returns the **outer** `PROGRAM-ID` and merges the contained program's paragraphs into it, including a bogus paragraph named `PROGRAM-ID`; only `UNSUPPORTED_CONSTRUCT` *warnings* are emitted (`Skipped unsupported statement: IDENTIFICATION DIVISION.`, `END PROGRAM ...`), no error. The two repo fixtures with `END PROGRAM` are single programs. | The engine silently over-accepts nested programs. Layer 5 records `NESTED_PROGRAM_NOT_MODELLED` (D4); turning the engine's warning into a refusal is a **new owner item** (it can change which inputs generate), not done. |
| (b) `dataclasses.replace` inside `cobol_parser.py` | three sites: two on `FileDefinition` (`:983`, `:1970`), one on a statement (`_parse_with_size_error`, the `[NOT] ON SIZE ERROR` bodies). | `id()` matching is sound if the frame is recorded on what `_parse_statement` *returns* (it is: the replaced object is the returned one); the dropped pre-replace object stays pinned by the trace so its `id` cannot be reused. |
| (c) text `fd_copybooks` hands to `parse` | `application_discovery` parses `expansion.source` (the FD COPY statements expanded in place); the program text and the data-division copybook texts are separate. | Program-text spans use `expansion.origins`; copybook declarations use `CopybookModel.origins`. Both implemented in P1. |
| (d) callers of `resolve_qualified_names` | exactly one: `cobol_parser.parse` (plus tests). | Safe to add `resolve_qualified_names_traced`; the old name is a wrapper with byte-identical output. |
| (e) `last_line_map` empty | **Only for CORRESPONDING** expansion. A wrapped (split) qualifier keeps the map (the design's claim that it empties it was wrong). | P1 closes the CORRESPONDING gap with an origin vector; `last_line_map` is now complete for every fixture. |
| (f) how `EVALUATE` is lowered | to a chain of `IfStatement`s (`WHEN` -> `IF`, later `WHEN`s as nested `else_body` IFs); there is no `EvaluateStatement` in the IR. | The nested lowered IFs have no source frame of their own: P1 gives them the enclosing statement's start as `SPAN_LOWERED_FROM_PARENT` (inexact), never an invented line. |

### 11.2 What L5-P1 implements, and where it differs from sections 2 and 8

Implemented (`tests/semantic_facts/test_span_p1.py`):

* `engine/transformation/parse_trace.py` (`ParseTrace`, `LogicalLine`, `StatementFrame`, `DeclarationFrame`) and
  `CobolParser.parse_traced()`; `parse()` and every IR class are unchanged (`parse_traced(...)[0] == parse(...)`).
* `qualified_names.resolve_qualified_names_traced` (origin vector); `cobol_parser` remaps physical line numbers through it.
* Statement frames recorded by a wrapper around `_parse_statement`; declaration frames from
  `parse_data_description_lines(..., base=, section=)` (entry start and end line); `CopybookModel.declarations`.
* `engine/semantic_facts/span.py`: `Span`, `CopyFrame`, `build_span_table`, `copybook_declaration_spans`, named
  `SPAN_CODES`, `SpanTable.unplaced()` / `.inexact()` inventories.
* Measured on the 78 repo COBOL fixtures (`fixtures/**/*.cob|*.cbl`): 1,608 statements, 0 unplaced, 0 mis-positioned
  exact spans; 51 inline clause bodies (`SPAN_INLINE_FRAGMENT`) and 34 EVALUATE-lowered statements
  (`SPAN_LOWERED_FROM_PARENT`) carry inexact spans; the only unplaced facts are 63 FILE SECTION record items
  (`SPAN_FILE_SECTION_NOT_TRACED`) and 4 parser-added items (`SPAN_SYNTHETIC_DECLARATION`). The test pins those as the
  only allowed reasons.

Deliberate differences from the design (all narrowings, none a guess):

* **Statements carry a start position only** (`end_line == 0`): a statement's end index is not uniform across the ~30
  statement parsers, and a joined or qualifier-expanded logical line cannot give a true last line. Declarations do carry
  `end_line` (data-division entries are never joined or expanded).
* **No `UseSite` / reference spans and no operand alignment** (2.4b): references are L5-P3 facts; P1 spans declarations
  and statements only.
* **Copybook declaration columns are never claimed** (`SPAN_COPY_COLUMN_UNPROVEN`): the expansion re-indents lines and
  the one reader cannot be re-run on a single copybook line without a second reader. The line and the full COPY chain
  (program COPY statement, nested COPY statements, physical file/line) are exact.
* **FILE SECTION records are not traced** (they are parsed by a scratch parser per FD): named
  `SPAN_FILE_SECTION_NOT_TRACED`, shrink-only; scheduled with P2 (declarations).
* The program's own COPY-statement site for a data-division copybook is supplied by the caller (`copy_site=`); extracting
  it from `_extract_copybooks` is P2.
* Spans are positions, not behaviour: no GnuCOBOL differential is involved.

### 11.3 `graph_id` is wired (design 5.6 dependency closed)

`api/readiness.assess_workspace` records the discovery report's `dependency_graph.graph_id` in the readiness record
(`POLICY_VERSION` 4, so stored records are re-assessed); `Service._run_validation` passes it as
`PipelineConfig.graph_traceability = (("graph_id", id),)` and it is sealed in the evidence manifest through the existing
conditional key. **Limit, stated plainly:** this is the lineage "this run was generated from the source whose discovery
produced graph X"; it is *not* the `traceability_overlay_id` (generated class -> graph node). Enabling the overlay in the
API means passing the graph file to `ModernizationConfig.knowledge_graph_path`, which makes an untraceable generated
class a generation failure (`_trace_to_graph`): that changes run outcomes and is deferred to a separate, certified step.
`tests/test_library_order_profile_api.py` covers the record, the sealed manifest and a mutation check.

---

## 12. Entry policies and L5-P2 (symbols and scopes)

### 12.1 Policies resolved conservatively (`enterprise/discovery/source_policy.py`, parser)

| Question | Policy | Where it is enforced |
|---|---|---|
| Compiler options (`CBL`/`PROCESS`/`$SET`) | Every option has one class: `LISTING` (ignorable), `DIALECT` (already in the profile), `SEMANTIC` (changes generated meaning; the engine models none), `UNCLASSIFIED`. `SEMANTIC` and `UNCLASSIFIED` are *unmodelled*: facts derived under them are incomplete, never read as "default". The profile (and so `profile_id`) is unchanged. | `classify_option`, `unmodelled_options`; consumed as diagnostics by the P4 document |
| Line terminators | LF and CRLF are read; a **lone CR** is refused by name (`LINE_TERMINATOR_LONE_CR_UNSUPPORTED`). Before this, a mixed file parsed to zero statements with *no diagnostic*. | `CobolParser.parse`, `line_terminator_policy` |
| Tabs | A TAB before the first character makes the column inexact (`SPAN_COLUMN_TAB`); the **line number is never affected**. | P1 spans |
| JCL flavour | `//name JOB\|EXEC\|DD...` (name in column 3) is `ZOS`; `// JOB`, `// DLBL`, `/&` are `VSE`; a mix or anything else is `UNKNOWN`. Only `ZOS` may be read as z/OS JCL. | `jcl_flavour` |
| Nested programs | The IR holds one program. A second `PROGRAM-ID` makes every declaration and paragraph read from its text `unsupported(NESTED_PROGRAM_NOT_MODELLED)`; they are never merged into the first program's scope and `SymbolTable.complete` is false. | `ParseTrace.programs`, `symbols.build_symbol_table` |

### 12.2 What L5-P2 implements, and where it differs from section 3

* `engine/semantic_facts/symbols.py`: `Declaration`, `Scope`, `SymbolTable`, `UnsupportedFact`; closed `DECL_KINDS`,
  `UNSUPPORTED_CODES`, `SPECIAL_REGISTERS` (`RETURN-CODE`, `SORT-RETURN`, `TALLY`).
* Identity is exactly 3.4 (`sym:<scope>/<kind>:<ancestors reversed>/<NAME>#K`); the ordinal follows IR (= source) order.
* **Source spelling is recovered.** `qualified_names` renames a name declared twice (`AMT-OF-REC1`) *before* the parser
  runs, so the IR carries the generated name. The rename list is now exposed (`resolve_qualified_names_detailed`,
  `ParseTrace.renames`); the declaration keeps the source name and records the generated one as `generated_name`.
  `resolve_qualified_names` / `_traced` are unchanged wrappers.
* The parser also keeps equal copies of LINKAGE items in `working_storage`; each is declared once, as `linkage`/
  `linkage-param`.
* `RENAMES`, `GLOBAL`, `EXTERNAL` are not modelled by the parser; `ParseTrace.entry_notes` records where they were
  written and the table names them (`RENAMES_NOT_MODELLED`, `GLOBAL_CLAUSE_NOT_READ`, `EXTERNAL_CLAUSE_NOT_READ`).
* `graph_node_id` is set only for kinds whose graph node kind is certain (paragraph, data items); files, records and
  special registers are mapped from the real graph in P6, not guessed. `test_graph_node_ids_match_the_discovery_formula`
  pins the formula against `cobol_structure.scoped_node_id`.
* `origin_member`/`template_id` come from the span's COPY chain (member file, local line, name); the copybook digest is
  not part of `template_id` yet (P4 binds digests through the checkpoint).
* **Deviations / limits:** paragraphs only (the IR has no SECTION unit; `section` kind is not produced); nested-program
  *scopes* are not built (fail-closed instead, 12.1); `qualified_names._Item` (R8) is not yet replaced (P7);
  FILE SECTION record spans remain `SPAN_FILE_SECTION_NOT_TRACED`.

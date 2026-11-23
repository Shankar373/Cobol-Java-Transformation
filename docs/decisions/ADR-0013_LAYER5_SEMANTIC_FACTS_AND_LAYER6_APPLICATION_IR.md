# ADR-0013 Layer 5 is project-wide semantic facts; Layer 6 is their canonical Application IR

Status: accepted (Phase 0 of the Layer 5 roadmap; branch `codex/enterprise-phases-continuation`).
Deterministic, open-source only, no LLM. Supersedes the Layer 5 and Layer 6 rows of
`docs/architecture/LAYER_MODEL.md` as they stood at `9655239`.

## Context

`LAYER_MODEL.md` defined Layer 5 as "parse-tree semantic analysis (inter-program data flow)", marked
**not started, do not start**, and Layer 6 as "Semantic IR" (`cobol_parser`, `ir`, `qualified_names`,
...), built. The read-only Layer 5 audit of `9655239` found that this split does not describe the code:

* `CobolParser` already produces statement-level IR, which is what the old Layer 5 row said it would
  produce, so the Layer 5 / Layer 6 boundary was blurred.
* The engine IR carries **no source positions** and there is **no symbol table or scope object**;
  name resolution is a text rewrite (`qualified_names`) plus a linear lookup.
* CALL / COPY / file / table facts are computed by several independent components
  (`scan_cobol`, `application_discovery`, the parser's `CallStatement`/`FileDefinition`,
  `external_dependency_edges`, `dd_binding`, `jcl_discovery`).
* `docs/KNOWN_ISSUES.md` called the same work "Layer 4".

## Decision

1. **The "do not start" gate is lifted only in this order:** Phase 0 prerequisites (this ADR and the
   items below) are accepted and Layer 4 is formally closed *before* any Layer 5 implementation begins.
   This ADR does not start Layer 5.

2. **Layer 5 — Project-wide semantic facts.** Layer 5 owns, and is the only producer of, a
   deterministic *semantic-facts document* for one checkpoint:
   declarations and scopes (programs, copybooks, sections, paragraphs, data items, files),
   typed references with def/use classification, qualified-name resolution, record layouts,
   CALL / `USING` / `LINKAGE` relationships, control-flow and data-flow relationships,
   file / VSAM / SQL / JCL relationships, and the resolution status of every reference
   (`resolved`, `ambiguous` with candidates, `unresolved`, `dynamic` with candidate literals,
   `unsupported` with a named code). Every fact carries a source span with its COPY-origin chain.

3. **Layer 6 — Canonical COBOL Application IR.** Layer 6 is a *projection* of Layer 5 facts for
   consumption by capability analysis, planning and generation. It adds no fact that is not in the
   Layer 5 document; a Layer 6 datum without a Layer 5 fact is a defect. Typed edges replace the
   free-text `DependencyEdge.metadata` strings. The existing `CobolProgram` / `CobolApplication` IR
   is the starting point and stays in force until the projection replaces it, phase by phase.

4. **Reuse, no parallel authorities.** Layer 5 builds on, and does not duplicate:
   `enterprise/discovery/cobol_text` (the single reader), `DialectProfile`, `copy_replacing`,
   `library_order`, the `CobolParser` statement IR (extended with spans), and the knowledge graph.
   Relationship facts reach the graph only through `enterprise/discovery/graph.py` / `resolve`
   (Integration contract 1); the relation vocabulary stays closed (contract 4). No new parser, no new
   graph authority, no second symbol table, no second dependency resolver. The lint inventories in
   `tests/discovery/test_engine_graph_lint.py` may only shrink.

5. **Contracts.**

   | Boundary | Contract |
   |---|---|
   | Layer 4 → 5 | `SourceRead` / `SourceLine` / `Token` (and the engine's positioned lines derived from them), `DialectProfile` + `profile_id`, named frontend refusals, `library_winner` with per-program orders. Layer 5 never re-detects format, dialect or library order. |
   | Layer 5 → 6 | Semantic-facts document: canonical JSON (sorted keys, no timestamps), content-addressed `semantic_id`, bound to `checkpoint_id`, `profile_id`s and `graph_id`; fact = `kind`, `subject`, `span {file,line,column,via_copy[]}`, `resolution`, `confidence`, `rule`. |
   | Layer 6 → 7/8/9 | Application IR projection with typed edges; consumers branch on `resolution`/`confidence`, never on message text. |
   | Evidence | Identities are sealed with the existing conditional-key pattern (`evidence/models.py`, `graph_traceability`) so manifests without them keep their hashes. |

6. **Fail closed.** An unsupported, ambiguous, dynamic or unresolvable construct produces a named
   fact or refusal, never a guess or a silent default. No existing gate is weakened: `[certify]`,
   byte-identical generation hashes (`tools/generation_hashes.py`), coverage floor, mypy ratchet,
   dependency map, and the do-not-regress areas (`engine/verdict/derivation.py`, GO TO handling,
   oracle digest pinning).

## Phase 0 prerequisites (acceptance for Layer 4 closure)

| # | Prerequisite | Closed by |
|---|---|---|
| P0.1 | Closed-vocabulary seam: a JCL ref the graph cannot hold must not abort `build_graph` (DB2 `BIND MEMBER`) | graph-level regression test |
| P0.2 | Layer 4 parity and compiler-card tests are mutation-sensitive, not tautologies | replaced tests |
| P0.3 | Per-program JCLLIB / SYSLIB / `-I` library order reaches generation in the real pipeline | api → `ModernizationConfig` → generator |
| P0.4 | `DialectProfile` ids flow API → `PipelineConfig` → sealed evidence | evidence round-trip + tamper test |
| P0.5 | Position-preserving engine input, per-segment mixed-format handling, COPY-origin map | positioned lines, origin map |
| P0.6 | Single-reader enforcement is behavioural, not only an import check | strengthened lint, shrink-only allowlist |
| P0.7 | Reproducible byte-identical generation-hash tool with a committed baseline | `tools/generation_hashes.py` |
| P0.8 | Architecture and audit documentation reconciled with the code | this ADR, `LAYER_MODEL.md`, audits |

## Consequences

* Layer 5 may begin only after every row above is accepted and recorded in
  `docs/discovery/DIALECT_PARSER_FRONTEND_AUDIT.md` (Layer 4 closure record).
* Limitations deliberately left open by Phase 0 are listed in the closure record, not hidden.
* Layer numbering in older documents (`KNOWN_ISSUES.md` "Layer 4" for data flow and parser retirement;
  `PHASE6A_UNIVERSAL_IR.md`, where "6A" is a phase label) is reconciled in the same change.

## Amendment 2026-11-23: span shape (design decision D2) and the P1 entry

* The `span` of a fact is `{file, line, column, via_copy[]}` **plus** the additive fields `end_line`, `end_column`,
  `basis` (`token` | `line` | `statement` | `copy-site`), `exact` and `note` (a named `SPAN_*` reason when not exact).
  Existing readers of the four ADR fields are unaffected. `exact=False` means the line is right (or, for `statement`,
  the span points at the statement a fact lies inside) and the column is not claimed. A fact that cannot be placed has
  no span and a named code; a consumer never substitutes a neighbouring line. Implemented in
  `engine/semantic_facts/span.py` (Layer 5 phase P1); details and measured results in `LAYER5_DESIGN.md` 11.2.
* The Layer 5 entry checklist (`LAYER5_DESIGN.md` section 10) is satisfied and D1-D4, D9 are resolved (section 9.3).
  Phases P2-P7 are not started.

## Amendment 2026-11-23: Layer 6 entry

* Layer 6 is designed in `docs/architecture/LAYER6_DESIGN.md` and implemented as `engine/application_ir` (pure projection, no fact
  not in the Layer 5 document; `coverage` and `verify` prove it) with a content-addressed `ir_id` bound to `semantic_id` and
  sealed through the conditional key `application_ir`.
* R4: `DependencyEdge` carries typed `resolution`, `call_type`, `mode`, `attributes`; `metadata` is a derived rendering.
* Not started by this amendment: switching capability analysis, planning or generation to the IR (see the design, section 7).

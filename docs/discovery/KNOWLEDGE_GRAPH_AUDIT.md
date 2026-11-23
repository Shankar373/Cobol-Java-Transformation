# Layer 3 audit: Enterprise Knowledge Graph (reconciled with the shipped Knowledge Graph 2.0)

Original read-only audit 2026-11-18; **reconciled 2026-11-19** against the implementation on
branch `codex/enterprise-phases-continuation` (from `c1be7b6`). The original document said
"Nothing was built for this layer" — that was true when written and is false now: the target
architecture section below was implemented by `0f77696` (Knowledge Graph 2.0) and hardened by
`f083b1a`. Deterministic, no LLM, open-source only. Layer ownership for every remaining gap is
fixed in `docs/architecture/LAYER_MODEL.md`.

## What exists (as built)

| Capability | Evidence | Verdict |
|---|---|---|
| Schema `systemaops.knowledge-graph/2.0` (1.0 still emitted/upgradeable); header with `graph_id` (sha256 of canonical nodes+edges), `checkpoint_id`, `source_digest`, `parent_graph_id`, `created_from`, `tool` + scanner versions | `enterprise/discovery/graph.py:40-46,435-448`; populated in `discover.py:404-406` | shipped |
| 50 node kinds, 48 relations (closed, fail-closed membership), 4 confidence values, 20 modes, 9 scopes, 73 resolver rules | `graph.py:75-141` | shipped |
| Every edge requires file/line/column plus `rule`, `confidence`, `mode`, `scope`; construction without them raises | `graph.py:241-294`; `tests/discovery/test_kg_acceptance.py` (criteria 2) | shipped |
| Provenance on edges: checkpoint id, tool version on the document (never in `graph_id`) | `graph.py:368-376,435-448` | shipped |
| Builder: estate-wide name index, 20+ per-kind resolvers, library-order rule `copy-library-order` (SYSLIB / JCLLIB / `-I` applied, losers kept in `candidates`) | `resolve.py:201-575` | shipped |
| COBOL structure: sections, paragraphs, `performs`/`goes-to`, file verbs (`reads-file`/`writes-file`/`rewrites-file` with modes), `moves-to`/`reads-item`/`writes-item`, data-item/record-layout/screen-field nodes, COPY REPLACING pairs in `detail` | `cobol_structure.py`, surfaced in `scan_cobol.py:118-141` | shipped |
| JCL: steps as nodes, `contains`, compile steps, JCLLIB/SYSLIB library order | `resolve.py:517-557,740-748` | shipped |
| Embedded subsystems: `accesses-table` with read/write mode, `sql-binds-hostvar`, `cics-link/xctl/load`, `starts-transaction`, `uses-map`, `uses-cics-file`, `uses-mq` with put/get mode, `uses-ims` | `scan_embedded.py` | shipped (coarse relation names below) |
| Persistence: SQLite `kg_snapshot`/`kg_node`/`kg_edge`/`kg_unresolved` (migration 0003), indexed by graph/src/dst/relation, fail-closed save (graph_id mismatch, round-trip, unresolved row counts), row queries never read `document` | `kg_store.py:93-130,233`; `enterprise/migrations/0003_knowledge_graph.up.sql` | shipped |
| Query library: neighbors, reachable, impact, slice (own `graph_id` + `parent_graph_id`), path, diff (added/removed/changed) | `kg_query.py` | shipped |
| Exporters: JSON / DOT / GraphML / CSV, deterministic, collision-disambiguated, XML-safe | `kg_export.py:34,87-192` | shipped |
| Read-only API `GET /discovery/runs/{id}/kg{,/nodes,/node,/neighbors,/impact,/path,/slice,/diff,/export}`, viewer role, bounded limits, 422/400 never 500 | `api/discovery_routes.py:41-272`; `tests/discovery/test_kg_api_security.py` | shipped |
| UI: Knowledge Graph page (nodes, blocking, impact, path, slice, diff tabs), snapshot header, exports, capped deterministic ring view | `frontend/src/pages/KnowledgeGraph.tsx`, `components/kg/*`, 17 frontend tests | shipped |
| Estate view derives only from the graph (`proof_state` PROVEN/PARTIAL/BLOCKED/UNPROVEN), opens no file | `graph_view.py`; import-lint `tests/discovery/test_engine_graph_lint.py:134-163` | shipped |
| Traceability: `generated-from` overlay wired into the modernization pipeline, `graph_id` + overlay id travel in the sealed evidence manifest (test-proven round trip) | `traceability.py:125-194`, `engine/graph_traceability.py`, `pipeline.py:511-582`, `evidence/models.py:408`; `test_traceability_pipeline_e2e.py:177-188` | shipped (production wiring below) |
| Scale benchmark: per-file budget, query budget, doubling ratio ≤ 3.0 (threshold unchanged; measurement made stable by `c1be7b6`) | `tests/discovery/test_kg_scale_benchmark.py` | shipped |

## What the original audit listed as gaps — closure status

| Original gap | Status |
|---|---|
| 1. Transformation does not use the discovery graph | **closed** for estate/API (`graph_view`, `estate_from_graph`, api/estate.py); the IR-building parsers remain, inventoried and shrink-only in `test_engine_graph_lint.py` |
| 2. Missing entities (paragraph, data item, step, Java class, run…) | **closed** (`section`, `paragraph`, `data-item`, `record-layout`, `step`, `screen-field`, `java-class`, `java-method`, `test-case`, `run` emitted); `column`, `requirement` still vocabulary-only |
| 3. Missing relationships (performs/goes-to, read/write direction, sql modes, generated-from…) | **closed** for control flow, file verbs, data flow, `sql-binds-hostvar`, traceability; `sql-reads`, `sql-writes`, `cics-op`, `mq-put`, `mq-get`, `ims-call`, `implements` still vocabulary-only (coarser spellings emitted instead) |
| 4. Resolution: library order recorded not applied; REPLACING not parsed; no per-edge confidence | **closed** for library order (`resolve.py:517-557`) and confidence (`Edge.__post_init__`); REPLACING recorded (not expanded — by design); the two REPLACING *parsers* still disagree → layer 4 (this task) |
| 5. No `graph_id`/checkpoint id/tool version on the document | **closed** (`graph.py:435-448`) |
| 6. No neighbours/impact/slice/diff/export/store | **closed** (all shipped) |
| 7. No traceability to Java | **closed** mechanism-wise (overlay + manifest round trip); production API wiring still absent (below) |

## Remaining gaps (honest), with owning layer

Owning layers per `docs/architecture/LAYER_MODEL.md`.

1. **Production API does not wire traceability** (layer 14): `api/service.py` builds
   `ModernizationConfig` without `knowledge_graph_path` and `PipelineConfig` without
   `graph_traceability`, so real runs carry no `graph_id` in the manifest — only tests/CLI do.
2. **`verified-by` is manual** (layer 11→13): `record_verification` runs only after a VERIFIED
   verdict and has no production caller yet (`docs/KNOWN_ISSUES.md:23`).
3. **Manifest vs final overlay id** (layer 13): the manifest carries the generation-stage
   overlay; the final overlay (with `verified-by`) differs (`docs/KNOWN_ISSUES.md:25`).
4. **Declared-but-unemitted vocabulary** (layer 3): relations `sql-reads`, `sql-writes`,
   `cics-op`, `mq-put`, `mq-get`, `ims-call`, `implements`; node kinds `column`,
   `requirement` (`docs/KNOWN_ISSUES.md:21`).
5. **REPLACING/library-order parity with the engine** (layer 4): discovery records pairs the
   engine refuses (literal operands), and the engine's search path is not yet the JCL order —
   both are Layer 4 P3 acceptance (criteria 8/9 of the Layer 4 audit).
6. **Data flow is intra-program only** (layer 5): inter-program propagation needs a real
   parse tree — **layer 5 is not started and must not be started**.
7. **UI cap** (layer 14): 60-node ring layout, no deep link.
8. **Scale** (layer 3): the 10k budget covers the graph pipeline, not `discover()`
   (`docs/KNOWN_ISSUES.md:31`).
9. **`EXEC` past column 72** (surface layer 3, contract layer 4): reported as
   `EXEC_NOT_CLOSED`, never silently mis-attributed.

## Phases (original plan) — status

* P1 schema 2.0 + `graph_id` + rule/confidence/mode + store + query/diff + read-only API —
  **done** (`0f77696`).
* P2 paragraph/PERFORM/data-item/file-verb scanning, shared REPLACING and control-flow
  modules, library-order resolution — **done** for scanning and library order; the shared
  REPLACING module is Layer 4 P3 (this task).
* P3 SQL read/write and CICS/MQ/IMS operation modes, record layouts, columns — **done** for
  modes via `accesses-table`/`uses-mq` modes and record layouts; `column` nodes open (gap 4).
* P4 engine adapter, retire parallel structures, `generated-from`/`verified-by`, `graph_id`
  in evidence — **done** for adapter/overlay/manifest; retirement inventory stays shrink-only;
  production wiring is gap 1.
* P5 UI views, exports, scale benchmark — **done**.

## Acceptance criteria — proof status

| # | Criterion | Status |
|---|---|---|
| 1 | Byte-identical graph/`graph_id`, order independent | **proven** (`test_kg_acceptance.py` criterion 1) |
| 2 | Every edge has file/line/column/rule/confidence; missing raises | **proven** (criterion 2 tests) |
| 3 | No engine module re-parses what discovery parses (import lint); estate view graph-only | **proven** (`test_engine_graph_lint.py`, allowlist shrink-only) |
| 4 | PERFORM/GO TO/READ/WRITE/REWRITE edges with modes | **proven** (criterion 4) |
| 5 | COPY REPLACING pairs in `detail`; expansion linked | **proven** (criterion 5) |
| 6 | Library order JCLLIB/SYSLIB; loser in `candidates` | **proven** (criterion 6) |
| 7 | Impact equals brute-force transitive set | **proven** (criterion 7) |
| 8 | Diff of two checkpoints; empty for identical input | **proven** (criterion 8) |
| 9 | Every generated Java class has `generated-from` in the same `graph_id` | **proven** (`test_traceability_pipeline_e2e.py`; production wiring = gap 1) |
| 10 | Unresolved/blocking edges preserved on store import | **proven** (criterion 10, store tests) |
| 11 | 10k corpus within budget, store queryable without loading JSON | **proven** (`test_kg_scale_benchmark.py`; `kg_store` row queries) |

## Out of scope (unchanged)

Inter-program data flow (layer 5, not started), emitting the declared-but-unused vocabulary
without a coordinated UI change, force-directed UI, `discover()`-level 10k budget, and any
change to the store schema or the edge identity rules without a dedicated review.

## Phase 0 addendum (2026-11-23, ADR-0013; Layer 5 audit of `9655239`)

Changes to the gaps above, and findings that were not in this document:

* **Gap 1 (production wiring) - partly closed.** The API run path now carries per-program library orders and
  `DialectProfile` ids into generation and the sealed manifest. `knowledge_graph_path` / `graph_traceability` are
  still not supplied by `api/service.py`, so real runs still carry no `graph_id`.
* **Gap 5 (library-order parity) - closed for generation.** One authority (`library_winner`, `orders_for_program`);
  the graph keeps a single `copybook:NAME` node per name, so per-program winners are visible in edges/candidates only.
* **New defect, fixed:** JCL `BIND ... MEMBER` emitted relation `binds`, which is not in `EDGE_RELATIONS`;
  `Edge.__post_init__` raised and aborted `build_graph`. It is now `uses-db2` to a `dbrm` node, with a graph-level
  regression test (`tests/discovery/test_resolve_graph.py`).
* **New finding, open (Layer 5):** `cobol_structure` dispatches on the first verb of a period-terminated sentence, so a
  `PERFORM`/`GO TO`/`MOVE` nested inside `IF ... END-IF` emits no edge. Criterion 4 above is proven for sentence-initial
  statements only.
* **New finding, open (layer 3):** of the 73 declared resolver rules only about 7 ids are stamped, so `by_rule` carries
  almost no semantics; `NODE_KINDS` is not enforced (`dbrm`, `object-member` are emitted outside it).
* **New finding, open:** parallel implementations of SELECT -> DD binding (`engine/jcl/dd_binding.py`), JCL parsing
  (`engine/transformation/jcl_parser`, `jcl_dependencies`, `jcl_discovery`, `engine/jcl/preprocess`) and table/queue
  discovery (`external_dependency_edges`) remain; the lint inventory does not cover JCL parsers.

# The fourteen-layer model: ownership and integration contracts

Authoritative, 2026-11-19; Layer 5/6 definitions and corrections amended 2026-11-23 (rows 5-8 reconciled with the built state 2026-11-24) by
`docs/decisions/ADR-0013_LAYER5_SEMANTIC_FACTS_AND_LAYER6_APPLICATION_IR.md` (branch
`codex/enterprise-phases-continuation`, from `c1be7b6`).
This document assigns **one owning layer** to every capability and to every open limitation
of layers 1–3, and states the four integration contracts that cross layer boundaries
(graph input, immutable source/checkpoint identity, `DialectProfile`, semantic relationships).
Deterministic, open-source only, no LLM.

It supersedes layer-ownership asides scattered in audits and `docs/KNOWN_ISSUES.md`; the
per-layer audits stay the evidence record:

| Layer | Audit / evidence record |
|---|---|
| 1, 2 | `docs/discovery/LAYER_AUDIT.md` |
| 3 | `docs/discovery/KNOWLEDGE_GRAPH_AUDIT.md` (reconciled 2026-11-19) |
| 4 | `docs/discovery/DIALECT_PARSER_FRONTEND_AUDIT.md` (acceptance contract and closure record) |
| 5, 6 | `docs/decisions/ADR-0013_LAYER5_SEMANTIC_FACTS_AND_LAYER6_APPLICATION_IR.md` |

## The layers

Status key: **built** (shipped and tested), **extended** (this task extends it), **not started**
(no code, explicitly out of scope now).

| # | Layer | Owns (modules) | Produces / contract point | Status |
|---|---|---|---|---|
| 1 | Secure ingestion and immutable inventory | `enterprise/ingest/**`, `enterprise/discovery/{model,inventory,limits,zipsource,gitingest,remotegit,checkpoint,checkpoint_core,discover,runs}` | Sealed content-addressed **checkpoint**: `checkpoint_id`, `source_digest`; bytes never change after seal | built |
| 2 | Application, compiler and build discovery | `enterprise/discovery/{classify,scan_cobol,scan_jcl,scan_embedded,scan_bms,cobol_structure,applications,compilers,resolve,readiness}` | Facts/refs with `file:line:column`, toolchain requirements, advisory GnuCOBOL compatibility verdicts, **readiness gate** | built |
| 3 | Enterprise knowledge graph and traceability | `enterprise/discovery/{graph,kg_store,kg_query,kg_export,graph_view,traceability}`, `engine/graph_traceability.py`, KG routes in `api/discovery_routes.py`, `frontend/src/pages/KnowledgeGraph.tsx` | Versioned graph documents (`graph_id`), durable `kg_*` store, queries/exports, estate view, `generated-from`/`verified-by` overlays | built |
| 4 | Dialect-aware parser frontend | `enterprise/discovery/cobol_text.py` (single reference-format reader), `enterprise/discovery/dialect_profile.py`, the shared REPLACING and library-order modules, `engine/transformation/{source_format,source_positions,copy_origins}.py` (the engine-facing face: positioned lines, COPY-origin map), conditional-compilation evaluation/refusal | **`DialectProfile` + `profile_id`**, normalized source lines/tokens, named frontend refusals (`REFERENCE_FORMAT_*`, `CONDITIONAL_COMPILATION_UNEVALUATED`, …) | built; closure record in the Layer 4 audit (Phase 0, ADR-0013) |
| 5 | Project-wide semantic facts (ADR-0013) | `engine/semantic_facts/**` | A deterministic, content-addressed semantic-facts document (`semantic_id`): declarations/scopes, typed references with def/use, qualified names, CALL/USING/LINKAGE, file relationships, resolution status, spans with COPY-origin chains, named unsupported reasons | built (P1-P7; `docs/architecture/LAYER5_DESIGN.md` section 17 states what is not done) |
| 6 | Canonical COBOL Application IR (ADR-0013); per-program parser IR | `engine/application_ir/**` (projection, `ir_id`, consumers); `engine/transformation/{cobol_parser,ir,qualified_names,next_sentence,exec_sql,sql_parser,subsystem_calls,cics_java_mapping}`, `engine/source_hash.py` | The Layer 5 facts projected as a typed Application IR that adds no fact absent from Layer 5; programs and statements stay with the parser IR, which remains authoritative (retained producers R2/R3/R5/R6) | built and formally closed (`LAYER6_DESIGN.md` section 10) |
| 7 | Capability analysis and the refusal ledger | `engine/modernization/{capability_analyzer,ir_unsupported,capability_record}.py`, `engine/transformation/semantic_capability.py`, `docs/CAPABILITY_MATRIX.md` | SUPPORTED/PARTIAL/UNSUPPORTED/UNAVAILABLE/UNKNOWN per component, GnuCOBOL-proof pinned; Application IR findings with Layer 5 provenance; IR-keyed capability record in the sealed manifest | built (`LAYER7_DESIGN.md`) |
| 8 | Modernization planning | `engine/modernization/{transformation_plan,plan_evidence,plan_graph,pipeline}.py`, `engine/transformation/{application_discovery,entrypoint}.py`; `modernization_planner.py` is EXPERIMENTAL and unused in production | `TransformationPlan`: evidence reconciled fail-closed, dependency order and blocking, oracle plan derived from the programs, provenance per component, fail-closed SKIP | built (`LAYER8_DESIGN.md`) |
| 9 | Java generation | `engine/transformation/{producer,java_generator,application_generator,java_render,spring_boot_generator,manifest}.py` | Byte-deterministic Java project + `ProducerManifest` | built |
| 10 | Build, packaging and runtime targets | `engine/candidate/**`, `engine/execution/**`, `engine/docker_cli.py`, `engine/transformation/runtime_adapters.py` | Runnable artifact per runtime target | built |
| 11 | GnuCOBOL oracle and differential execution | `engine/oracle/**`, `engine/comparators/**`, `engine/jcl/**` | Oracle build/run results identified by `oracle_id` | built |
| 12 | Verification and verdict | `engine/verification/**`, `engine/verdict/**`, `scripts/e2e/verify_independent.py` | Fail-closed verdict; single `VERIFIED` derivation site | built |
| 13 | Evidence, contracts and audit trail | `engine/evidence/**`, `contracts/**`, `api/artifact_seal.py` | Sealed evidence manifest (identity fields below) | built |
| 14 | Control plane, API, UI and deployment | `api/**`, `frontend/**`, `enterprise/{db,jobs,quotas,contracts}.py`, `deployment/**` | Authenticated API, persistence, UI, production deployment | built |

Rule: a capability belongs to the layer that *produces its contract point*, not to the layer
that first noticed a gap in it. Gaps recorded in audits are re-assigned below.

## Integration contract 1 — graph input

The dependency/knowledge graph has exactly one structural producer.

* **Who may add nodes/edges:** the layer-2 scanners (facts/refs) and the layer-3 resolver
  (`resolve.build_graph`) — through `enterprise/discovery/graph.py` only. Every edge carries
  `file`, `line`, `column`, `rule`, `confidence` (fail-closed `Edge.__post_init__`,
  `graph.py:273`).
* **Who may read it:** the engine reaches discovery only through
  `enterprise/discovery/graph_view` (estate view), `kg_query`/`kg_store` (impact/reachability)
  and `traceability` (overlay). Enforced statically by
  `tests/discovery/test_engine_graph_lint.py` (estate import restriction + the
  `ALLOWED_STRUCTURE_PARSERS` inventory, which may only shrink).
* **What may not happen:** no `engine/` module re-parses COBOL structure *to build graph
  facts*; the estate view derives only from the graph (`estate_from_graph` opens no file,
  lint-enforced); graph documents are immutable — changes ship as a new document or an
  overlay with `parent_graph_id`, never an in-place edit.
* **Writes of overlays:** `generated-from`/`verified-by` come from
  `engine/graph_traceability.py` through `TraceabilityOverlay` (cross-graph edges refused).

## Integration contract 2 — immutable source and checkpoint identity

Identity is a chain of content-addressed values; each link names the algorithm and the bytes
it hashed. Nothing in the chain is recomputed from a different byte set.

| Value | Defined by | Covers |
|---|---|---|
| `checkpoint_id`, `source_digest` | layer 1 (`checkpoint*.py`) | the uploaded bytes |
| `graph_id` | layer 3 (`graph.py:195`, sha256 of canonical nodes+edges; header carries `checkpoint_id`, `source_digest`, `tool`, `parent_graph_id`) | one graph document |
| `profile_id` | layer 4 (`dialect_profile.py`, sha256 of canonical profile JSON) | one file's `DialectProfile` |
| `oracle_id` | layer 11 (`engine/domain/identities.py`) | the pinned GnuCOBOL toolchain identity |
| evidence manifest seal | layer 13 (`engine/evidence/models.py`, `api/artifact_seal.py`) | the run's evidence, including `graph_traceability` pairs |

Rules: a checkpoint's bytes are read-only after seal; a graph references its checkpoint, never
re-reads bytes; the evidence manifest records `graph_id` (+ overlay id) and the `profile_id`s
of the sources that were transformed; every consumer verifies the value it was handed instead
of recomputing it.

## Integration contract 3 — `DialectProfile`

One frozen, deterministic record per COBOL/copybook file; **the** dialect and reference-format
authority for every later stage.

* **Producer:** layer 4 only — `enterprise/discovery/dialect_profile.build_profiles()`, fed
  from discovery facts, `cobol_text.logical_lines` and `compilers.std_for_dialect`. Canonical
  JSON; `profile_id = sha256(bytes)`.
* **Fields:** `file`, `dialect` (+`confidence`, honest `basis`), `reference_format`
  (`fixed|free|variable|mixed`) with switch lines, `compiler_options`, `directive_state`,
  `library_order`, `unsupported` (construct names), `oracle` (`gnucobol-3.1.2`, selected
  `-std`, format flag).
* **Consumers (all read, none re-derive).** Wired today (Phase 0): the discovery report; the API run path
  (`api/readiness.py` -> `PipelineConfig.dialect_profiles` -> sealed evidence manifest, conditional key, with an
  integrity check); the engine's mixed-format refusal. **Not yet wired** (stated intent, tracked in the Layer 4
  closure record): engine consumption of `unsupported` by layers 7/8, `profile_id` in the producer manifest
  (would change hashes of untouched output), and `-std=` from the profile in the oracle. Intended consumers:
  * layer 2 compatibility lane — `-std`/format flags and `NOT_ATTEMPTED_REFERENCE_FORMAT`;
  * layer 4 engine frontend — named refusals before parsing (OO, `SCREEN SECTION`,
    `VARIABLE`, unevaluated `>>IF`);
  * layer 7 capability analysis and layer 8 planning — `unsupported` feeds fail-closed plans;
  * layer 9 generation — `profile_id` recorded in the producer manifest (still unwired; Layer 9 records `docs/architecture/LAYER9_DESIGN.md` §5 instead);
  * layer 11 oracle — `-std=`/format flag and `profile_id` recorded beside `oracle_id`;
  * layer 13 evidence — `profile_id` sealed with the run.
* **Prohibition (lint-enforced from layer 4 onward - imports by `test_engine_graph_lint.py`, behaviour by
  `test_single_reader_lint.py` with a shrink-only inventory):** no module may re-detect dialect or
  reference format on its own. Reading source requires exactly one reader
  (`enterprise/discovery/cobol_text`); deriving dialect requires exactly one profile builder.
  Advisory approximations (the syntax-check lane) stay labelled as today.

## Integration contract 4 — semantic relationships

The KG relation vocabulary in `graph.py:88-111` (`EDGE_RELATIONS`, closed) is the only
spelling of a semantic relationship anywhere in the platform — API responses, exports,
estate view, UI and traceability all consume it.

* Adding a relation is a schema change: `EDGE_RELATIONS`, resolver rules, `EDGE_MODES`,
  export/UI columns and this document's vocabulary table move together, and a producer test
  must show the new relation actually emitted (declared-but-unemitted names are tracked as a
  layer-3 gap, never documented as working).
* Every edge carries `mode` (read/write/…), `confidence`, `rule` and `scope`; consumers must
  branch on `confidence`/`blocking` rather than assume certainty.
* Identity of an edge is `(src, dst, relation, rule, file, line, column)` + clause/detail
  digests (`graph.py`, `edge_identity`); reason is excluded so diff can show resolution
  transitions.

## Layer 1–3 limitations and their owning layer

Every open item from `docs/discovery/LAYER_AUDIT.md`, the Layer-3 section of
`docs/KNOWN_ISSUES.md` and the reconciled `KNOWLEDGE_GRAPH_AUDIT.md`, re-assigned to the layer
that owns the fix.

| Limitation | Recorded in | Owning layer | Note |
|---|---|---|---|
| Store key not required in production (checksum-only seal without it) | LAYER_AUDIT D4 | 1 | deployment control |
| Long Windows paths report a misleading error | LAYER_AUDIT D5 | 1 | |
| Crash recovery does not sweep `discovery-stage-*` / `.CP-*.tmp-*` | LAYER_AUDIT D7 | 1 | |
| Git symlink/submodule refusal runs after checkout | LAYER_AUDIT D9 | 1 | mitigated by `core.symlinks=false` + ls-tree precheck |
| `/source` served without re-verifying the checkpoint | LAYER_AUDIT D10 | 1 | re-hash on read |
| Symlink refusal tests skipped on Windows hosts | LAYER_AUDIT | 1 (test infra) | run on Linux CI |
| No rate limit or queue bound on discovery; UI loses the run on reload | LAYER_AUDIT D8, UI note | 14 | closed for readiness assessments (L14-P2: `CONTROL_PLANE_MAX_READINESS_ASSESSMENTS`, 429 when reached; the `/discovery/runs` pool was already bounded at 2 workers); the UI half (run lost on reload) stays open |
| Readiness gate not re-checked by `UniversalModernizationPipeline.execute` / background workers | LAYER_AUDIT open | 14 | closed: both background workers re-check the gate before any generation/validation work (L14-P1); the engine stays a pure orchestrator |
| Legacy `/estate`, `/decomposition` endpoints use the old discovery | LAYER_AUDIT open | 14 | audited 2026-11-26: wording stale — they read through the sanctioned `graph_view` (layer-2 scanners + `resolve.build_graph`); the remaining cost is a second scan pass per request (`LAYER14_DESIGN.md` §6) |
| Ambiguous references and unresolved dynamic CALLs do not lower readiness | LAYER_AUDIT open | 2 | policy decision |
| Container image tag mutable (`gnucobol-ocesql:latest`), digest not recorded | LAYER_AUDIT open | 10 | image identity (provenance recorded for Maven/runtime images already) |
| Build flags (`-std`, `-free`, `-I` order) detected but not applied to the compile plan | LAYER_AUDIT open, KG audit gap 12 | 4 | profile ids and per-program library order now reach generation and evidence; `-std=` to the oracle stays open (recorded as `default`); the syntax lane stays advisory |
| Library search order was a heuristic (nearest/shortest), JCLLIB/SYSLIB/-I recorded but not applied | LAYER_AUDIT open, KG audit gap 4 | 4 | closed for generation (Phase 0): one authority (`library_winner`, `orders_for_program`) applied per program through the API run path. Open: FD-section COPY and nested COPYs use the global search set; the graph keeps one `copybook:NAME` node per name |
| `COBOL REPLACING` parsed twice with different rules | KG audit gap 11 | 4 | closed: one shared REPLACING module (`copy_replacing.py`) |
| Duplicate dependency parsers in the engine (`application_discovery`, `copybook_model`, `cobol_parser`, …) | KNOWN_ISSUES:17 | 6, 7, 8 (inventory in `test_engine_graph_lint.py`) | layer 4 retires what belongs to the frontend (REPLACING/library order); the IR-building parsers stay with their justification and may only shrink |
| `ims-call`/`mq-put`/`mq-get` (+`sql-reads`, `sql-writes`, `cics-op`, `implements`, `column`, `requirement`) declared but not emitted | KNOWN_ISSUES:21 | 3 | coordinated resolver+UI rename, or removed from the vocabulary at a schema bump |
| `verified-by` not automatic after a VERIFIED verdict | KNOWN_ISSUES:23 | 11→13 | the verifier (11) produces the verdict; wiring `record_verification` into the run is evidence (13) plumbing |
| Evidence manifest carries the generation-stage overlay id, not the final one | KNOWN_ISSUES:25 | 13 | |
| Java mapping is name-based (regex class/method scan) | KNOWN_ISSUES:27 | 9 | generation-side identity |
| API path never supplies `knowledge_graph_path` / `graph_traceability` (production manifests carry none) | reconciled KG audit | 14 | control-plane wiring; audited 2026-11-26: manifests carry the `graph_id` lineage, the traceability overlay stays absent (`LAYER14_DESIGN.md` §6) |
| Data flow intra-program only; needs a real parse tree | KNOWN_ISSUES:28 | **5** | not started; ADR-0013 defines the scope and the entry conditions |
| UI node-link view capped at 60 nodes, no deep link | KNOWN_ISSUES:29 | 14 | recorded as a Layer 14 limit (`LAYER14_DESIGN.md` §6), not fixed |
| `EXEC` past column 72 reported `EXEC_NOT_CLOSED` | KNOWN_ISSUES:30 | 4→3 | fixed-format reading is layer 4's contract; the scanner error stays layer 3's surface |
| 10k scale: `discover()` itself not in the benchmark budget | KNOWN_ISSUES:31 | 3 | benchmark covers the graph pipeline only |
| Non-ASCII `PIC X`, numeric risks, VSAM subset, etc. | KNOWN_ISSUES full-audit sections | 7 / 11 / 12 | semantic-proof areas, unchanged by this task |

## Change rules

* Layer 4 acceptance is `docs/discovery/DIALECT_PARSER_FRONTEND_AUDIT.md` (11 criteria; closure record at its end).
* Layers 5 and 6 are built and closed (their design documents record what is done and what is not). Byte-identical generation is checked with
  `python tools/generation_hashes.py --check docs/audits/generation_hashes.json`.
* Generation output of untouched fixtures must stay byte-identical (hash before/after, method
  of `docs/audits/CHANGE_LEDGER.md`); the KG benchmark threshold stays `3.0`.
* `engine/verdict/derivation.py`, GO TO handling and oracle digest pinning remain
  do-not-regress areas (CONTRIBUTING.md).
* No new LLM calls, no new network access, no weakening of an existing gate.

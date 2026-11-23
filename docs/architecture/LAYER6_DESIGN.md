# Layer 6 design: Canonical COBOL Application IR

Status: **accepted for implementation (2026-11-23)**, written at `e240374`. Governing decision: ADR-0013 (Layer 6 is a
*projection* of Layer 5 facts, adds no fact, typed edges replace `DependencyEdge.metadata`). Deterministic, open source only,
no LLM. Layer 5 exceptions R2, R3, R5, R6 stay open and are **not** touched or relabelled here.

## 1. Audit (what exists)

| Thing | Where | Role today |
|---|---|---|
| Statement/declaration IR | `engine/transformation/ir.py` (`CobolProgram`, `DataItem`, 32 statement classes), produced only by `cobol_parser` | Parsing authority and the input to Java generation. **Unchanged by Layer 6.** |
| Application IR | `ir.py` `CobolApplication`, `CobolProgramUnit`, `ProgramCall`, `CopybookReference`, `FileDependency`, `DependencyEdge` | Built by `ApplicationDiscovery`; consumed by capability analysis, planning, generation. Free-text `DependencyEdge.metadata`. |
| Semantic facts | `engine/semantic_facts` (Layer 5) | Declarations, typed references, calls, file/SQL/JCL facts, spans, resolution states, `semantic_id`, sealed in evidence. |
| Graph | `enterprise/discovery/graph*` | Read-only authority for estate relations; vocabulary closed. |

`DependencyEdge.metadata` (R4) - producers: `application_discovery.py:701-725` (CALL `resolution=..;call_type=..`, FILE
`mode=..`). Consumers that parse the text: `capability_analyzer._analyze_call`, `modernization_planner` (2 sites),
`transformation_plan` (1 site), and about 20 tests. `JclDependency.metadata` and `JavaDependency.metadata` are different
classes, are not `DependencyEdge`, and are out of scope (listed as limits).

## 2. Ownership

* **Layer 5** owns facts. **Layer 6** owns only the *projection*: `engine/application_ir/`. A Layer 6 datum without a Layer 5
  `decl_id`/`ref_id`/`fact_id` is a defect; a test checks every element carries one that exists in the document.
* The parser stays the parsing authority; the reader stays single; the graph stays read-only through Layer 5's bridge
  (Layer 6 never opens the graph). No second symbol table, resolver or graph.
* The existing `CobolApplication` stays in force; consumers move one at a time, each behind a differential test.

## 3. Shape

`ApplicationIR` (frozen dataclasses, tuples only): `header` (bindings), `programs`, `declarations`, `references`,
`edges`, `unsupported`. Each element keeps the Layer 5 id, span (with COPY chain), resolution state, confidence and
named reason verbatim. `IREdge` is typed: `kind` in a closed `EDGE_KINDS` (call, perform, goto, falls-through, reads-item,
writes-item, file-binding, sql-table, jcl-dd), `source`/`target` ids, `resolution`, `provenance` (the fact id), no text field.

Identity: `ir_id = sha256(canonical({"body": body, "bindings": {semantic_id, facts_digest, graph_id, tool}}))`; canonical bytes
are `graph.canonical_bytes`. `ir_id` therefore changes with any fact and with any binding; `verify` re-projects the
document and compares, so a tampered IR is not just checksum-detected but provably not the projection of its facts.
**No fact lost:** every document fact is either projected or in a closed, documented `NOT_PROJECTED_KINDS`; a test fails on a
new kind that is in neither.

## 4. R4 (typed edges)

`DependencyEdge` gains typed fields `resolution`, `call_type`, `mode` and `attributes`; the legacy `metadata=` string is
accepted by a compatibility shim that parses it into the typed fields (unknown keys are kept in `attributes`, nothing is
dropped) and `metadata` is thereafter a *derived* canonical rendering, never a source of truth. Consumers read typed
fields; a lint test forbids reading `.metadata` in `engine/` and `api/` outside the shim. Tests that asserted the text keep
asserting the same facts through the typed fields.

## 5. Phases

| Phase | Content | Gate |
|---|---|---|
| L6-P1 | R4: typed `DependencyEdge`, producers and 4 consumers migrated, lint | hashes identical; capability/planner/discovery suites; `[certify]` (capability analyzer) |
| L6-P2 | `engine/application_ir`: model, projection, canonical serialization, `verify`, no-loss test | determinism + mutation tests over the fixture corpus |
| L6-P3 | Evidence key `application_ir` (+integrity: bound to `semantic_facts`), API wiring, tamper tests | `[certify]` (evidence seal) |
| L6-P4 | Differential: IR-derived CALL/FILE edges vs `ApplicationDiscovery` edges; documented differences; consumer migration status | differential report |

## 6. Not in scope / limits (stated up front)

Generation does not consume the Application IR in this layer's delivery: generation reads the parser IR and its output
bytes are pinned; moving it is a differential per construct and is recorded as not done unless proven. D6 (nested graph
edges) is investigated as a documented proposal only; the closed graph vocabulary and resolver rules are unchanged.

## 7. Implementation status and completion matrix (at the commit that carries this section)

| Phase | Delivered | Evidence |
|---|---|---|
| D0 design | this document | accepted |
| P1 / R4 | `DependencyEdge` typed; `application_discovery` producers and the capability analyzer, planner (2 sites) and transformation plan read the typed fields; a lint test forbids `.metadata` reads in `engine/` and `api/` | generation hashes identical (110 builds); 1,405 focused tests; `tests/application_ir/test_dependency_edge_typed.py` |
| P2 IR | `engine/application_ir` (`model`, `project`, `legacy`): immutable, typed, canonical, content-addressed; `coverage` (no loss, no invention) and `verify` (re-projection) | whole-corpus projection loses nothing; shuffle determinism; 11 tamper mutations incl. a forged-but-self-consistent IR |
| P3 evidence/API | `EvidenceManifest.application_ir` (conditional key; legacy seal unchanged), `APPLICATION_IR_BINDING_MISMATCH` (exact keys, hex, bound to the recorded `semantic_facts`), serialization, `PipelineConfig`, API `document_lineage` (one document, IR projected from it) | `tests/evidence/test_application_ir_evidence.py`, API tests incl. reproducibility from source and a removal mutation |
| P4 consumers | `legacy.call_edges(ir)` reproduces `ApplicationDiscovery`'s CALL edges exactly on every fixture application (14 CALL edges, 0 differences) and the capability report is identical from either source (a forged edge changes it) | `tests/application_ir/test_consumer_differential.py` |
| D6 | investigated: no vocabulary/rule change needed; the decision is granularity and volume (`D6_NESTED_EDGES_INVESTIGATION.md`) | measured, nothing emitted |

### Not done (stated, not hidden)

* **No consumer is switched.** The capability analyzer, the planner and Java generation still read `CobolApplication` and the
  parser IR; the IR is proven *able* to replace the CALL edges (differential), and the migration of each consumer is a further
  step. Java generation is not migrated at all (its output bytes are pinned; it reads the parser IR, which stays the parsing
  authority).
* **R4 scope.** `DependencyEdge.metadata` is retired as a source of truth (typed fields, derived legacy rendering kept so
  existing readers and ~20 tests keep passing). `JclDependency.metadata` and `JavaDependency.metadata` are different classes and
  are unchanged. FILE and COPY `DependencyEdge`s are still produced by `ApplicationDiscovery` (the IR has no COPY edges and no
  per-statement read/write operation for files); `legacy` projects CALL edges only.
* The IR inherits every Layer 5 limit: copybook text is not expanded, nested programs and GLOBAL/EXTERNAL/RENAMES are named
  unsupported, dynamic-call candidates are a lower bound, and Layer 5 exceptions R2, R3, R5 and R6 remain open.
* The manifest binds `ir_id` and `semantic_id`; as for Layer 5 no document is persisted beside it, so admission checks shape and
  the link to `semantic_facts`, and the seal makes the pair tamper-evident after sealing.

Layer 6 is therefore **not declared complete**: the IR, its identity, evidence and API integration, R4 and a proven first
consumer differential exist; consumer migration (capability, planning, generation) is open.

## 8. Consumer migration plan (decision 2026-11-23: COBOL language coverage is frozen; complete the platform on the certified subset)

Audit of consumers of application-level relationships (all read `CobolApplication`): `capability_analyzer.analyze` (CALL edges,
cycles, arity), `modernization_planner` (call relationships, entry programs, copybook and file plans), `transformation_plan`
(unresolved calls, call graph), `modernization/pipeline` (counts), `application_generator` (call edges for entry selection).
One adapter serves them all: `application_ir.consume` (`ir_for_application`, `canonical_call_edges`).

Rules for every milestone: the IR is the source and discovery is the cross-check; if they disagree the discovery value is kept
and the disagreement is surfaced as an UNSUPPORTED finding (fail closed); an IR that cannot speak for the whole application is not
used; behaviour without an IR is unchanged; each switch lands with a contract (identical reports over every fixture application),
a unit (the fail-closed rules), a mutation (a wrong IR value is detected) and an integration test.

| Milestone | Scope | Status |
|---|---|---|
| M1 | `CapabilityAnalyzer.analyze(..., ir=)`: CALL edges (classification, cycles, arity input) from the IR; the modernization pipeline passes the IR | implemented, `tests/application_ir/test_m1_capability.py` |
| M2 | `ModernizationPlanner` and the pipeline plan phase: call relationships, entry programs (verified against the IR) and the transformation plan reads, via `consume.canonical_application` | implemented, `tests/application_ir/test_m2_planner.py` |
| M3 | FILE and COPY relationships with provenance: Layer 5 `copy-site` facts resolved through the one copybook resolver; `legacy.copybook_references` / `file_dependencies`; `consume.canonicalize` verifies all four relationship kinds | implemented, `tests/application_ir/test_m3_copy_file.py` |
| M4 | Java generation's application-level input (entry selection call graph) from the IR; the parser IR stays the statement-generation authority | planned |

Retained producers R2, R3, R5, R6 are untouched by this plan: M1 does not remove `_extract_calls`, `_analyze_call_linkage_arity`,
`dd_binding` or `external_dependency_edges`.

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

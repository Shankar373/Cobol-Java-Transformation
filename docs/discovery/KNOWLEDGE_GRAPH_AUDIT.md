# Layer 3 audit: Enterprise Knowledge Graph (gap analysis and direction)

Read-only audit, 2026-11-18, branch `codex/enterprise-phases-continuation`. Nothing was built for this layer. Deterministic, no LLM, open-source only.

## What exists
| Capability | Evidence | Verdict |
|---|---|---|
| Graph model `Node`/`Edge` (frozen), resolutions resolved/external/ambiguous/unresolved, 12 reasons with a `blocking` flag, `SCHEMA_VERSION systemaops.dependency-graph/1.0`, sorted deterministic output | `enterprise/discovery/graph.py:22-170` | solid base |
| Provenance: every edge requires file, line, column | `graph.py:128` | file:line only; no checkpoint id, tool version or confidence on the document or edges |
| Builder: one estate-wide name index, 20+ per-kind resolvers | `resolve.py:201-442` | name based |
| Node kinds: file, program, copybook, proc, job, jcl-member, table, dd, dataset, vsam-cluster, bms-mapset/map, transaction, cics-file, mq-queue, utility, runtime, directory, load-module, dynamic | `resolve.py` | no paragraph, data item, step, Java or test nodes |
| Relations: calls, copies, defines, assigns-file, uses-dataset, executes, includes, uses-library, links, accesses-table, uses-ims/mq/queue/map/cics-file, cics-link/xctl/load | scanners, `resolve.py` | no direction or operation (read/write) |
| Applications (union-find) | `applications.py` | exists |
| Persistence: JSON per checkpoint, no DB table, no index | `discover.py:303-328`, `api/store.py` | no queryable store |
| API/UI: run submit/list/get/verify/source/artefact download; counts and JSON download only | `api/discovery_routes.py`, `Discovery.tsx` | no query, impact, slice, diff, export or graph view |
| Transformation consumes discovery | `api/readiness.py` only | gate verdict only, not edges |

## Gaps
1. **Transformation does not use the discovery graph.** No `engine/` module imports `enterprise.discovery`. Four parallel structures exist: `engine/transformation/application_discovery.py` (regex CALL/COPY scan), `engine/estate/model.py` (own Node/Edge/Estate with PROVEN/PARTIAL/BLOCKED/UNPROVEN), `copybook_resolver.py`/`copybook_model.py` (own search path and the only COPY REPLACING parser), `jcl_discovery.py`/`jcl_dependencies.py`. Resolution rules exist twice and can disagree (copybook order, REPLACING).
2. **Missing entities:** section/paragraph, data item and record layout (exist in `engine/transformation/ir.py`), column, JCL step as a node, screen field, Java class/method, generated artefact, test/oracle run, requirement, run/checkpoint.
3. **Missing relationships:** performs/goes-to; reads/writes data item; MOVE data flow; READ/WRITE/REWRITE direction; SQL read vs write, host-variable binding, columns; MQ put/get; generated-from; verified-by.
4. **Resolution:** library order (JCLLIB, SYSLIB, `-I`) is recorded, not applied; `COPY ... REPLACING` pairs are not parsed in discovery; no per-edge confidence; ambiguity still picks a best candidate.
5. **Versioning/provenance:** no `graph_id`, checkpoint id, tool version or parent snapshot on the graph document.
6. **Capabilities:** no neighbours, impact, slice, diff, DOT/GraphML/CSV export, index or incremental update; one in-memory JSON document.
7. **Traceability to Java:** no generated-from metadata links Java to graph nodes; the evidence manifest carries no graph id.

## Target architecture (extend `graph.py`, do not rebuild)
Discovery stays the single producer of the structural graph; the engine reads it through one adapter and `engine/estate/model.py` becomes a view that only adds `proof_state`.

* **Schema `systemaops.knowledge-graph/2.0`** (superset; 1.0 still emitted): header `graph_id` (sha256 of canonical bytes), `checkpoint_id`, `source_digest`, `tool` + scanner versions, source-derived `created_from`, `parent_graph_id`. Edge adds `mode`, `confidence` (certain/derived/heuristic/unresolved), `rule` (resolver rule id), `scope`. New kinds: section, paragraph, data-item, record-layout, column, step, screen-field, java-class, java-method, test-case, requirement, run. New relations: performs, goes-to, reads-item, writes-item, moves-to (intra-program only), reads/writes/rewrites-file, sql-reads, sql-writes, sql-binds-hostvar, cics-op, mq-put/get, ims-call, contains, generated-from, verified-by, implements.
* **Store:** sqlite `kg_snapshot/kg_node/kg_edge/kg_unresolved` keyed by `graph_id` through the existing `enterprise/db.py` and migrations; JSON stays the canonical export.
* **Query library (pure Python):** neighbors, reachable, impact(node, direction, depth), slice, diff, path; exporters JSON/DOT/GraphML/CSV.
* **API (viewer role):** `GET /discovery/runs/{id}/kg/{node|neighbors|impact|slice|diff|export}`; UI graph page with node list, impact panel, unresolved list and diff.
* **Limit:** data flow is intra-program MOVE/compute and file/table I/O only; inter-program propagation needs a real parse tree (GnuCOBOL `cobc -E`/tree output or ProLeap are open-source options).

## Phases
P1 schema 2.0, `graph_id`, `rule/confidence/mode`, store, query and diff library, read-only API. P2 paragraph/PERFORM/data-item/file-verb scanning, shared REPLACING and control-flow modules, library-order resolution. P3 SQL read/write and CICS/MQ/IMS operation modes, record layouts, columns. P4 engine adapter, retire the parallel dependency structures, `generated-from`/`verified-by` edges, `graph_id` in the evidence manifest. P5 UI views, exports, scale benchmark.

## Acceptance criteria
1. Same input gives a byte-identical graph and `graph_id`, independent of input order.
2. Every edge has file, line, column, `rule` and `confidence`; constructing one without them raises.
3. No `engine/` module parses COBOL structure that discovery also parses (import-lint test); the estate view derives only from the graph.
4. PERFORM/GO TO/READ/WRITE/REWRITE fixture yields the expected edges with correct `mode` and lines.
5. COPY REPLACING fixture: pairs in `detail`; expanded data items linked to the including program.
6. Library-order fixture: same-named copybooks resolve by JCLLIB/SYSLIB order; the loser is in `candidates`.
7. Impact of a copybook equals a brute-force transitive set of programs, jobs and applications.
8. Diff of two checkpoints lists added/removed/changed nodes and edges; empty for identical input.
9. Every generated Java class has a `generated-from` edge to a program node in the same `graph_id`.
10. Unresolved and blocking edges are never dropped on store import (row counts equal the JSON).
11. A 10k-file corpus completes within a documented time and memory budget, and the store is queryable without loading the whole JSON.

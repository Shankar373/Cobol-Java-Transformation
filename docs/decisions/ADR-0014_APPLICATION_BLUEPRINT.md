# ADR-0014: Application Blueprint (`systemaops.application-blueprint/1.0`)

Status: accepted for implementation (Stage 1, phases B0-B1). Plan: `docs/roadmap/STAGE_1_BLUEPRINT_IMPLEMENTATION_PLAN.md`.
Layer 1-3 contract (see `docs/architecture/LAYER_MODEL.md`, integration contract 2). Deterministic, open-source only, no LLM.

## Context

Discovery already produces eight artefacts per checkpoint (report, dependency graph, inventory, unresolved references, compatibility,
applications, readiness, summary). Nothing names the *estate as a whole*: no single document says what the estate is (inventory, applications,
programs, resources, build, integrations, unresolved dependencies, architecture graph) under one content-addressed identity tied to the
immutable checkpoint. Downstream stages (semantic facts, IR, planning, evidence) therefore bind to loose files.

## Decision

Add one derived document, the **Application Blueprint**, written beside the other artefacts as `application-blueprint.json` and served at
`GET /discovery/runs/{run_id}/blueprint`.

* **A manifest plus summaries, not a copy.** It carries the facts a reader needs to understand the estate and references the bulky
  artefacts (graph, inventory, unresolved list, compatibility) by `file`, `sha256` and `bytes`. It adds no fact that is absent from the
  discovery report, graph or inventory; it is a pure function of them (no scanning, no clock, no network, no absolute path).
* **Identity.** `blueprint_id = sha256(canonical JSON of the document without its own blueprint_id)`, same canonical encoding as `graph_id`
  (`graph.canonical_bytes`). `identity` repeats `checkpoint_id`, `source_digest`, `graph_id`; every consumer verifies instead of recomputing.
* **Immutable.** Changes ship as a new document for a new checkpoint; a blueprint is never edited in place.

## Schema (top-level keys)

| Key | Content |
|---|---|
| `schema_version`, `blueprint_id`, `tool` | constants and identity |
| `identity` | `checkpoint_id`, `source_digest`, `graph_id`, `source` (`kind`, `origin`, `ref`, `commit`, `tree_id`, `archive_sha256`) |
| `estate` | files, directories, bytes, `files_by_class`, `source_formats`, scanned count |
| `artefacts` | `name -> {file, sha256, bytes}` for report, graph, inventory, unresolved, compatibility, applications, readiness, summary |
| `applications` | per application: id, name, readiness, programs, jobs, copybooks, entry points, `files` count, resources, resource counts by kind, compiler verdicts, unresolved totals, `architecture` (edge count, relation counts, dependency kinds) |
| `entry_points`, `relationships` | as in `applications.json` (shared resources between applications) |
| `programs` | name, file, line, kind, source format, `profile_id`, calls, copybooks, DB2 tables, CICS, MQ, IMS, logical files |
| `resources` | `datasets`, `vsam`, `db2` (`plans`, `tables`, `stored_procedures`): id, kind, origin, reference count |
| `integrations` | `cics`, `mq`, `ims`, `utilities`: id, kind, origin, reference count |
| `build` | compile/link steps, invocations, targets, runtime settings, runtime dependencies, required toolchains |
| `unresolved` | total, blocking, non-blocking, ambiguous, counts by reason, the blocking references (bounded) |
| `architecture` | `graph_id`, graph statistics, node-kind and relation counts, export formats served by `/kg/export` |
| `completeness`, `readiness`, `limitations` | gate status and checks, readiness status and blockers, the report's limitations verbatim |

Bounded lists are cut deterministically (sorted, then first N) and carry `*_total` so a cut is never silent.

## Consequences

* Blueprint bytes are covered by the same scrub and determinism tests as every discovery artefact.
* Not done here (later phases): applications bound to a blueprint (B2), consumption from the checkpoint (B3), Layer 5/6 identities inside the
  blueprint (`semantic_id`, `ir_id` are optional keys added by the run path, never by discovery).

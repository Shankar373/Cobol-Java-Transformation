# Stage 1 (Ingestion and Discovery): audit and Application Blueprint implementation plan

Audit date 2026-11-27, branch `codex/enterprise-phases-continuation`. Target flow: ZIP / Git / directory -> immutable checkpoint -> Application Blueprint.
Evidence: code read of `enterprise/discovery/{discover,applications,report,runs}.py`, `api/{readiness,service,app,discovery_routes}.py`;
subset run `tests/discovery/{test_discover_e2e,test_checkpoint,test_directory_links,test_api}.py` = 120 passed, 2 skipped (symlink, Windows host).
Not audited: frontend, full suite.

## Verdict: partially implemented

| Step | Status |
|---|---|
| ZIP ingestion (`zipsource.py`) | done |
| Git ingestion, local and remote (`gitingest.py`, `remotegit.py`) | done |
| Directory ingestion | done, internal only (not accepted by the API, by design) |
| Immutable checkpoint (`checkpoint*.py`) | done |
| Discovery artefacts (inventory, graph, applications, readiness, compatibility, dialect profiles) | done |
| **Application Blueprint** | **not implemented** (no schema, id, builder or endpoint) |

## Gaps

1. No Application Blueprint: eight separate artefacts, no single document or `blueprint_id` bound to `checkpoint_id`; Layer 5/6 `semantic_id`/`ir_id` not included.
2. Immutability chain breaks at the application boundary: `POST /applications/{id}/ingest` extracts via legacy `api/ingestion.py` into a mutable workspace, then
   checkpoints the extracted directory (not the uploaded ZIP bytes). The engine never re-verifies a checkpoint; modernization reads `cobol_source_path`.
3. Git is reachable only through `/discovery/runs/git`, not application creation.
4. Two discoveries: `GET /applications/{id}/discovery` re-runs legacy `discover_application` on the mutable folder.
5. ADR-0012 (object storage, queue, worker leases) not wired to discovery; `enterprise/ingest/github.py` and `enterprise/storage/` unused by the API.
6. Open Layer 1 items (`docs/discovery/LAYER_AUDIT.md`): D4 store key optional, D5 long Windows paths, D7 crash sweep, D9 git symlink refusal after checkout,
   D10 `/source` not re-verified, UI loses run on reload.

## Plan

| Phase | Work | Exit criterion |
|---|---|---|
| B0 Spec (**done**, ADR-0014) | `systemaops.application-blueprint/1.0` schema + ADR: checkpoint identity, inventory digest, `graph_id`, applications and entry points, dialect profiles, library orders, readiness, toolchain requirements, limitations, optional `semantic_id`/`ir_id`; `blueprint_id` = sha256 of canonical JSON | schema and ADR reviewed |
| B1 Builder (**done**, `blueprint.py`, `tests/discovery/test_blueprint.py`) | `enterprise/discovery/blueprint.py`, pure function of existing artefacts (no new scanning); publish `application-blueprint.json`; `GET /discovery/runs/{id}/blueprint` | byte-deterministic; `blueprint_id`, `graph_id`, `checkpoint_id` cross-verify |
| B2 One ingestion path | application ZIP ingest goes through `zipsource`, seals original archive bytes; `checkpoint_id` and `blueprint_id` stored on application and run records | application `checkpoint_id` = hash of uploaded bytes; legacy extraction removed |
| B3 Immutable consumption | pipeline and `/source` read from, or verify the seal of, the checkpoint (closes D10); drop folder-fingerprint workaround | editing the workspace after ingest fails closed (test) |
| B4 Git/directory for applications | `POST /applications/{id}/ingest/git` pinned to a commit under the existing network policy; directory stays internal or admin-allowlisted | ZIP and Git applications yield the same blueprint shape |
| B5 One discovery | `/applications/{id}/discovery` served from blueprint/report; retire `discover_application` | single source of discovery facts |
| B6 Hardening | close D4, D5, D7, D9; persist runs in UI; object storage and worker queue per ADR-0012 | Layer 1 open list empty; symlink tests run on Linux CI |
| B7 Acceptance | ZIP/Git/directory matrix on COBOL fixtures; tampered checkpoint refused at every consumer; `tools/generation_hashes.py --check docs/audits/generation_hashes.json` unchanged | acceptance audit recorded in `docs/audits/` |

Rules: deterministic, no LLM, fail closed, one commit per phase, focused local tests only (CI runs the full suites).

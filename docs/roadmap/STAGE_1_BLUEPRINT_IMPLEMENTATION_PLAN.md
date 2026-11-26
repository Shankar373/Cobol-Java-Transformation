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
| B2 One ingestion path (**done, revised**) | Every ingested source is pinned (`api/source_pin.py`, table `source_pins`): `content_digest` of the workspace, `checkpoint_id`, `source_digest`, `blueprint_id`, `origin_kind`/`origin_ref` (SHA-256 of the uploaded ZIP, or the commit for Git). `readiness.blueprint_id` on ingest; `GET /applications/{id}/blueprint` serves the verified pinned blueprint. **Revised scope:** the checkpoint seals the extracted tree the pipeline consumes (the upload hash is recorded in the pin); the legacy extractor stays because its tree-root detection and limits are product behaviour. Retaining the original upload bytes moves to B6 (object storage). | pin written at ingest; blueprint endpoint verified (`tests/discovery/test_source_pin.py`) |
| B3 Immutable consumption (**done**) | `_require_ready` (modernize, revalidate, VSAM, both background workers) calls `enforce_pin`: workspace content digest, checkpoint re-hash and blueprint id must still match the pin, else 409; refresh never re-pins; re-ingest is the only way to change a source; a source with no pin is pinned on first use (`origin_kind=unpinned`). `/discovery/runs/{id}/source` refuses bytes that differ from the inventory digest (D10 closed). | editing the workspace, the checkpoint or the blueprint after ingest fails closed (tests) |
| B4 Git for applications (**done**) | `POST /applications/{id}/ingest/git` (https only, `ref` resolved to and pinned at a commit, operator network policy): discovery seals the Git checkpoint, its tree is materialized into a writable workspace (`materialize_checkpoint`, checkpoint verified first), then the ZIP path's `_adopt_workspace` runs (discovery, readiness, pin with `origin_kind=git`, commit and Git checkpoint id). Directory input stays internal (never accepted from a caller: it would read the server's disk). | ZIP and Git applications yield the same blueprint shape (`tests/discovery/test_application_git_ingest.py`) |
| B5 One discovery (**done, revised**) | `GET /applications/{id}/discovery` now names the `checkpoint_id` and `blueprint_id` its source is pinned to, and a parity test proves the legacy view and the blueprint agree on programs, copybooks and calls. **Revised scope:** `discover_application` is kept as the compatibility projection the engine and UI still consume (run discovery snapshots, generation); retiring it is a separate engine change, tracked as open. The blueprint is the authoritative description. | `tests/discovery/test_discovery_parity.py` |
| B6 Hardening (**partly done**) | **Done:** D4 (production refuses new discovery and fails `/ready` without `SYSTEMAOPS_STORE_KEY`; the compose file requires it), D7 (startup sweeps `discovery-stage-*` and `.<id>.tmp-*` older than 1 h; published checkpoints and young staging are kept), D10 (B3). **Not done:** D5 (long Windows paths message), D9 (git symlink refusal after checkout, mitigated by `core.symlinks=false` and the `ls-tree` precheck), UI keeps the run across reload, retaining the original upload bytes, object storage and a worker queue for discovery (ADR-0012), Linux CI symlink tests. | `tests/discovery/test_layer1_hardening_b6.py` |
| B7 Acceptance (**done**) | ZIP/Git/directory matrix, idempotent reuse and tamper detection (`tests/discovery/test_stage1_acceptance.py`); generation hashes identical; record in `docs/audits/STAGE_1_ACCEPTANCE_2026-11-27.md` | acceptance audit recorded |

Rules: deterministic, no LLM, fail closed, one commit per phase, focused local tests only (CI runs the full suites).

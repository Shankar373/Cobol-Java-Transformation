# Stage 1 acceptance (Ingestion and Discovery -> immutable checkpoint -> Application Blueprint), 2026-11-27

Branch `codex/enterprise-phases-continuation`. Plan: `docs/roadmap/STAGE_1_BLUEPRINT_IMPLEMENTATION_PLAN.md`; decision: `docs/decisions/ADR-0014_APPLICATION_BLUEPRINT.md`.
Local evidence only; the CI run for these commits is not yet recorded (per the batching rule CI runs the full suites).

## Verdict

**Stage 1 is implemented end to end for ZIP, Git and directory sources**, with the scope revisions and open items below. Nothing here is
production-certified: "verified" means checked by the tests and runs listed.

| Step | Status | Evidence |
|---|---|---|
| ZIP, Git (local and remote https), directory ingestion | done (directory internal only by design) | `test_discover_e2e`, `test_git_ingestion`, `test_remote_git*`, `test_zip_security_and_guards` |
| Immutable checkpoint (content addressed, read-only, sealed, tamper detection) | done | `test_checkpoint*`, `test_stage1_acceptance` |
| Application Blueprint (`systemaops.application-blueprint/1.0`, `blueprint_id`) | done (B0, B1) | `test_blueprint` (15) |
| Application bound to checkpoint and blueprint (pin), drift refused at every gate consumer | done (B2, B3) | `test_source_pin` (7) |
| Application from a pinned Git commit | done (B4) | `test_application_git_ingest` (5) |
| Application discovery view bound to the blueprint, parity proven | done, revised (B5) | `test_discovery_parity` (3) |
| D4 seal key in production, D7 stale staging sweep, D10 `/source` integrity | done (B6) | `test_layer1_hardening_b6` (5) |
| Same estate => same description for ZIP, Git, directory; reuse is idempotent; tamper detected | done (B7) | `test_stage1_acceptance` (4) |

## Results of this check

* `tests/discovery` (KG scale benchmark deselected): 1162 passed, 7 skipped (symlink creation not permitted on this Windows host, one Docker-lane test, one Windows zip-name case).
* API, enterprise, deployment and security suites that exercise the changed paths: 366 passed, 41 skipped.
* `python tools/generation_hashes.py --check docs/audits/generation_hashes.json`: identical, 55 apps x 2 runtimes = 110 builds. No generation code changed.
* `ruff` clean on `api`, `enterprise`, `tests/discovery`; `mypy` reports no error in the new modules (the repository's baseline errors are elsewhere).

## Scope revisions (decided, not defects)

1. The checkpoint of an application seals the **extracted tree the pipeline consumes**; the SHA-256 of the uploaded ZIP is recorded in the pin
   (`origin_ref`). The original upload bytes are not retained (moves to the object-storage work).
2. The legacy extractor (`api/ingestion.ingest_zip`) stays: its tree-root detection and limits are product behaviour.
3. `api/ingestion.discover_application` stays as the compatibility projection the engine and UI consume; the blueprint is authoritative and
   the parity test guards drift. Retiring it is an engine change.
4. A source ingested before pins existed is pinned on first use (`origin_kind=unpinned`, trust on first use).
5. Operational: production now **requires** `SYSTEMAOPS_STORE_KEY` (compose file, `.env.production.example`, `/ready` check `checkpoint_seal`).
   An existing production deployment must add the key before upgrading; checkpoints sealed without a key will fail verification once a key is configured.

## Still open (Stage 1)

* D5 (misleading error for long Windows paths); D9 (git symlink refusal runs after checkout; mitigated by `core.symlinks=false` and the `ls-tree` precheck).
* The UI loses the discovery run on reload; the frontend does not list the blueprint as a downloadable artefact.
* ADR-0012 object storage, queue and worker leases for discovery (discovery runs on a 2-thread pool against local disk).
* Layer 5/6 identities (`semantic_id`, `ir_id`) are not yet inside the blueprint (they stay in the run's evidence lineage).
* Symlink refusal tests need a Linux CI run; CI for this branch is not yet recorded.

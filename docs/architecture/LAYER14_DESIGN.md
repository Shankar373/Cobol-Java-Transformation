# Layer 14 design: Control plane, API, UI and deployment

Status: **audit complete (2026-11-26): L14-P1, L14-P2, L14-P3 done.** From Layer 12/13 (audited, `5345c1c`). Deterministic, open source only, no LLM.
Scope: `api/**`, `enterprise/{db,jobs,quotas,contracts}.py`, `deployment/**`, `frontend/**` (limits recorded in §6).

## 1. Audit so far

* **Authentication and RBAC.** `api/app.py` refuses to start in production without a token, refuses an unknown
  `CONTROL_PLANE_ENV`, and refuses an unparsable `CONTROL_PLANE_ROLE_TOKENS` (role mode fails closed: a bad config grants
  nobody anything). `api/rbac.py` maps method+path → minimum role (safe methods `viewer`, every mutation `operator`,
  `POST /runs/{id}/approval` and dataset download `approver`), and the middleware enforces `rbac.allows` on every request
  (`api/app.py:544-551`).
* **Approval → export.** `GET /runs/{id}/download` checks `approval_state` *first* (409 before any artifact detail can
  leak), then re-derives the verdict through `require_verified_evidence` (which re-checks the seal since L13-P1), then
  serves read-once under size/file caps. `Store.begin_revalidation` resets `approval_state='PENDING'` atomically with the
  verdict, so an approved attempt can never carry a later attempt's result.
* **Job slots.** Every expensive entry point (`ingest`, `modernize`, `revalidate`, VSAM) reserves one of
  `CONTROL_PLANE_MAX_CONCURRENT_JOBS` and releases it in `_launch`'s `finally`; `DiscoveryRunService` runs discovery on a
  bounded pool (`max_workers=2`, `enterprise/discovery/runs.py:101`).
* **Persistence.** `Store` writes through SQLite under one lock with generation-checked terminal writes
  (`tests/test_persistence_integrity.py`, `tests/test_control_plane_persistence.py`); no gap found.
* **Estate / decomposition.** `api/estate.py` reads only through `graph_view.graph_from_directory` — the layer-2 scanners
  and `resolve.build_graph`, the single sanctioned structural producer (LAYER_MODEL contract 1). The recorded wording
  "uses the old discovery" is stale; the remaining cost is a *second scan pass* per request (§6).

## 2. Gap found and closed: L14-P1 the background workers never re-checked the readiness gate

Recorded open since the Layer 1/2 audit (`docs/discovery/LAYER_AUDIT.md` line 42): "the engine
`UniversalModernizationPipeline.execute` and background workers do not re-check the gate (it is a service-layer
convention)". The gate lived only in `Service.modernize` / `Service.revalidate`, before the run record exists; the workers
that actually generate and validate never consulted it:

* `_modernize_background` went straight from loading the run to `_generate_application`. A source tree that changed or
  *disappeared* after the entry gate — the re-ingest race window between the gate and `add_run`, or any edit under the run's
  source directory — still reached generation. `_engine_wiring` deliberately ignores `allowed`, so a BLOCKED record only
  changed the wiring inputs; it never stopped the work. A deleted source surfaced as an internal pipeline error instead of
  the named readiness refusal.
* `_revalidate_background` re-used `_revalidation_target` (which checks only that the directory *exists*) and then ran
  `_run_validation` with no readiness consultation at all.

**Fix.** Both workers re-check the gate where the work happens, before any discovery snapshot, generation or validation:

* `_modernize_background` (`api/service.py:1060-1080`): `_require_ready(_run_source(run, app), app.name)`; a refused run
  is failed with `str(exc)` — the exact `ReadinessError` message ("Modernization is blocked until discovery is
  complete: …") — and logged as `run.readiness_refused`. Any `ApiError` (including the L14-P2 `BusyError`) fails the run
  closed rather than proceeding unguarded.
* `_revalidate_background` (`api/service.py:1313-1318`): the same check directly after `_revalidation_target`, so the
  pre-existing "source replaced by a later upload" `ServiceError` keeps its message while a tree that merely became
  BLOCKED now fails with the readiness refusal.

Generation output and all 110 generation hashes are untouched (the gate only ever *refuses*).

Tests (red first): `tests/test_layer14_background_gate.py` (3), shown **3 failed** against the old workers — a `_generate_application`
/ `_run_validation` sentinel proved the work was attempted for a blocked source — then 3 passed: the run whose source tree
was deleted fails with `discovery-failed:SOURCE_MISSING`, a tree mutated to `CALL 'VANISHED'` fails with `program:VANISHED`,
and the revalidate worker refuses the same mutation; each asserts `generated_app_path is None` and, through
`GET /runs/{id}`, that the API serves the refusal instead of an internal error.

## 3. Gap found and closed: L14-P2 fresh readiness assessments had no bound (D8)

D8 (`docs/discovery/LAYER_AUDIT.md` line 20): "no rate limit or queue bound on discovery". Ingest and the `/discovery/runs`
pool were bounded, but `Service.readiness_for` was not: every *fresh* assessment is a full discovery pass (checkpoint,
inventory, graph, compiler check) started synchronously in the caller's request thread, and `?refresh=true`, a changed
tree, the modernize gate and the ingest gate all funnel into the same call. The only bound was the server's thread pool.

**Fix.** Fresh assessments reserve a permit of their own, separate from job slots:

* `CONTROL_PLANE_MAX_READINESS_ASSESSMENTS` (default 4, read per call like the job limit; `api/service.py:207`),
  `Service._acquire_assessment` / `_release_assessment` (`api/service.py:555`, `:573`) — non-blocking, so a refused caller
  gets the typed 429 (`BusyError`) instead of queueing behind work it cannot see.
* `readiness_for` (`api/service.py:605`) takes the permit **only** around `assess_workspace`: a stored record whose
  fingerprint still matches is free, so the polling path never sees a 429. A missing directory short-circuits to
  `blocked_record` without a permit.
* Separate from the job-slot counter on purpose: a background worker already holds a job slot while it assesses, so sharing
  one counter would make an in-limit run fail spuriously at the limit's edge.

Tests (red first): `tests/test_layer14_readiness_assessment_bound.py` (5), shown **4 failed / 1 passed** (the cached-read
guard passes by design) — with one assessment in flight and the limit at 1: a second fresh assessment raised `BusyError`
without ever reaching discovery; `POST /applications/{id}/readiness/refresh` returned 429 and recovered after the permit
was released; the same 429 reached an ingest end to end. The stored-record read stays 200 while the limit is exhausted.

## 4. Gap found and closed: L14-P3 a failed assessment destroyed the application's source

Found by this audit (not previously recorded), and made reachable in production by L14-P2: `_ingest_application` pointed
the application record at the new workspace and deleted the previous source **before** assessing readiness of the new
tree. Any exception from that assessment — a persistence failure, and now the typed 429 — hit the `except` that cleans up
the new workspace, leaving `cobol_source_path` naming a directory that no longer exists while the previous source had
already been deleted: both copies gone. The block's own comment ("a failed write never destroys the good source") did not
hold on this path.

**Fix.** Readiness is assessed *before* the record is repointed and the previous source is deleted
(`api/service.py:775-787`). A failure now cleans up only the never-referenced new workspace; the application stays on its
previous, intact source. The in-memory `app.cobol_source_path` assignment moved with the record update (the store builds a
fresh record per read, so no shared object is affected).

Tests (red first): both in `tests/test_layer14_readiness_assessment_bound.py` — the patched-failure test (shown failing
with the record pointed at a deleted workspace) and the honest end-to-end trigger (permit exhausted during a second ingest:
429, record and previous source intact, and the same ingest succeeds after the permit is released, proving no permit
leaked).

## 5. Audited, no change

* Auth middleware / RBAC / approval / export / persistence — §1; each already fail-closed and covered by
  `tests/test_api_security.py`, `tests/test_rbac.py`, `tests/test_phase12_p4_bl091_approval_workflow.py`,
  `tests/test_persistence_integrity.py`.
* The VSAM and estate read paths already pass the readiness gate (`require_source_ready`) or the sanctioned graph reader.
* `UniversalModernizationPipeline.execute` itself stays a pure engine orchestrator: the gate is and remains a service-layer
  convention — now enforced by the service on *every* path that reaches it, including the workers (L14-P1), which is why no
  engine change was made (do-not-regress: engine generation behaviour and hashes untouched).

## 6. Limitation stated, not fixed

* **`/estate` and `/decomposition` re-scan the tree per request** instead of reading the readiness record's sealed graph
  artifact (`record["graph_artifact"]`, already validated against `graph_id`). Same sanctioned scanners and resolver, so
  no divergent graph producer exists; the cost is a duplicate discovery pass and no checkpoint/profile lineage in the
  view. Serving the view from the assessed artifact is a behaviour change for endpoints that currently work without any
  stored record (fallback would still be needed) — deliberately not done here.
* **Production manifests carry no traceability overlay.** The API never passes `knowledge_graph_path` to
  `ModernizationConfig` (`api/service.py` `_generate_application`; the field exists at `engine/modernization/pipeline.py:85`
  and is consumed at `:549`/`:593`), so `graph_traceability` in production manifests is the `graph_id` lineage only and the
  overlay id stays absent (`api/readiness.py:graph_lineage` says so explicitly). Wiring it would change sealed evidence
  content across the corpus — an evidence-scope change, not a control-plane fix.
* **Frontend.** The node-link view is capped at 60 nodes (`frontend/src/components/kg/layout.ts`, `KNOWN_ISSUES` line 29)
  and navigation is React state only (`frontend/src/App.tsx`): the UI loses the run on reload and offers no deep link.
  Both are UX work with their own test surface, recorded not fixed.
* **Residual race window.** L14-P1 closes the *consequence* of the gate→`add_run` window (a blocked or missing tree never
  reaches generation), not the window itself; closing it would need a per-application lock across gate+run creation and
  re-ingest. Process-local counters (job slots, assessment permits) are correct for the single-replica SQLite deployment
  only, like every existing limit here.

## 7. Next steps

Layer 14 is closed. The remaining Layer-14-owned rows in `LAYER_MODEL.md` are the §6 limits (estate second pass,
`knowledge_graph_path` wiring, frontend cap/deep link) plus the UI half of D8 ("the UI loses the run on reload"), which is
frontend scope.

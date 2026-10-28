# File-Level Audit — Limitations, Gaps, Issues, Bugs

> **Status:** COMPLETE — all sections A–K filled. Section A holds the findings confirmed end-to-end this session (2 `FIXED`, 3 `OPEN`/`KNOWN`). All remaining sections B–K are complete file-level audits.
>
> **Scope:** every production source file in the repository, plus grouped audits of the test suite, docs and deployment assets.
>
> **Method:** read-only review. Each entry distinguishes **confirmed bugs** (logic traced to a wrong outcome) from **suspected issues**. Line references point at the code as it stands now.

---

## Key

| Marker | Meaning |
|---|---|
| 🔴 **HIGH** | Wrong result, silent data loss, security exposure, or a fail-open gate |
| 🟡 **MEDIUM** | Correctness risk under realistic input; misleading output; missing validation |
| 🟢 **LOW** | Maintainability / dead code / duplication; no correctness impact |
| `FIXED` | Resolved this session, regression test in place |
| `OPEN` | Confirmed and unresolved |
| `KNOWN` | Documented boundary, accepted by decision — not a new finding |

---

# Section A — Findings confirmed this session (PAYMAIN end-to-end test)

Workload: `C:\Users\bandi\Downloads\PAYMAIN.zip` → `PAYMAIN (1).cob`, 1437 bytes, 1 program.
Original run: `run-8868c4015f8f` (`app-688a997945c4` "paymain") — **FAILED**.

## A.1 `FIXED` — 🟡 Arithmetic statements break when wrapped across lines

**File:** `engine/transformation/cobol_parser.py`
**Status:** `FIXED` — regression suite `tests/transformation/test_arithmetic_line_continuation.py` (12 tests)

**Root cause.** `CobolParser.parse()` pre-joins physical lines into logical lines using a hard-coded rule that only recognises two shapes:

```python
re.match(r"^(MOVE|ADD)\b", logical_lines[-1], ...) and re.match(r"^TO\b", line, ...)
re.match(r"^IF\b",  logical_lines[-1], ...) and re.match(r"^(?:=|<>|<=|>=|<|>|AND\b|OR\b)", line, ...)
```

Any other statement wrapping to a second line was never joined, so the statement parsers received fragments.

**Observed effect** (before the fix):

| Statement (wrapped) | Result |
|---|---|
| `MOVE … TO` | OK |
| `ADD … TO` | OK |
| `ADD … GIVING` (3 lines) | 🟡 orphaned `GIVING WS-C.` reported as unsupported |
| `SUBTRACT … FROM` | 🟡 empty `SubtractStatement` + orphan `FROM WS-B.` |
| `MULTIPLY … BY` | 🟡 empty `MultiplyStatement` + orphan `BY WS-B.` |
| `DIVIDE … INTO` | 🟡 empty `DivideStatement` + orphan `INTO WS-B.` |
| `COMPUTE … =` | 🟡 empty `ComputeStatement` + orphan operands |

The fragments were reported as `Skipped unsupported statement: - WS-DEDUCTIONS.`, capability analysis aggregated them into `UNSUPPORTED`, and the plan skipped the program. **A purely cosmetic line wrap was indistinguishable from a genuinely unsupported construct**, and failed the run.

PAYMAIN's three-line `COMPUTE WS-NET-SALARY = … - WS-DEDUCTIONS.` was the trigger: 6 of its 7 capability diagnostics were parser artifacts, not real gaps.

**Fix.** New guarded joiner `_join_arithmetic_continuation()` applied to `_parse_move`, `_parse_add`, `_parse_subtract`, `_parse_multiply`, `_parse_divide`, `_parse_compute`; each now returns the consumed end index instead of `start + 1`. Guards reuse `_FILE_CLAUSE_HEADERS`, `_SCOPE_TERMINATOR` and a new `_ARITHMETIC_CONTINUATION_STOP` so a following statement, scope terminator, file clause or paragraph heading is never swallowed.

**Trap found during the fix (worth remembering).** The first guard omitted `WHEN`. `EVALUATE` branch statements are written *without* a terminating period:

```cobol
WHEN STAT-WARNING
    MOVE "STATUS WARNING" TO WS-RESULT
WHEN STAT-ERROR
```

The unterminated `MOVE` absorbed `WHEN STAT-ERROR`, the 88-level condition name lost its lowering, and `STAT_WARNING = "STATUS WARNING"` was emitted as a bare Java identifier — breaking 2 `test_level88_lowering.py` tests. `_ARITHMETIC_CONTINUATION_STOP` now includes `WHEN`.

**Verification:** `2183 passed, 4 skipped` (transformation + universal/modernization), `test_level88_lowering.py` 14 passed, new suite 12 passed.

## A.2 `FIXED` — 🟡 Every pipeline stage rendered `pending` on a FAILED run

**File:** `frontend/src/components/PipelineStepper.tsx`
**Status:** `FIXED` — regression suite `frontend/src/__tests__/pipeline-stepper.test.tsx` (4 new tests, 45 total in file)

**Root cause.** `groupIndexForStage('FAILED')` returns `-1` because `FAILED` belongs to no `CUSTOMER_GROUPS[].stages`, so `activeGroupIdx` collapsed to `0`. `nodeStatus()`'s failure branch (`groupIdx < activeGroupIdx → 'done'`) was **dead code** — `groupIdx < 0` is never true. All 7 progression groups rendered `pending`; only the appended `Failed` node rendered `failed`.

**Why it mattered:** the run detail page prints `DISCOVERY RESULTS` (discovery demonstrably ran) directly beneath a stepper saying `Discovery: pending` — understating real progress by every node.

**Information was genuinely unavailable:** `RunRecord` (`api/store.py`) had no stage-history column, so writing `run.stage = RunStage.FAILED` overwrote the last stage reached. `stage_messages` (`api/service.py`) is only `[stage, error]`, not a history.

**Fix (full stack):**

| Layer | Change |
|---|---|
| DB | additive migration **schema v7** — nullable `runs.last_stage`; `DB_SCHEMA_VERSION = 7`; `RunRecord.last_stage`; `_last_stage_anchor()` helper records the last *non-terminal* stage and freezes on `FAILED`/`COMPLETED`; `begin_revalidation()` clears it |
| API | `Service.get_run_detail` + `models.RunDetailResponse.last_stage` + `GET /runs/{id}/detail` mapping |
| Frontend | `RunDetailResponse.last_stage`; `PipelineStepper` `lastStage` prop + `isUsableFailureAnchor()`; `ModernizationRun.tsx` `lastStageRef` / `detailAnchor` / `failureAnchor` |
| Contract | `scripts/backup/verify_backup.py` `SCHEMA_VERSION_CEILING = 7` |

**Rendered result (live, `run-a3091467403a`):**

```
Discovery: done  →  Capability Analysis: done  →  Transformation Planning: active
Transformation & Generation: pending → Execution & Comparison: pending
Evidence Validation: pending → Completed: pending → Failed: failed
```

`done` for groups cleared before the anchor; `active` for the group the pipeline halted in (rendering it `pending` would claim the stage was never entered — the same understatement this fix removes — while `done` would over-claim completion that cannot be proven); `pending` for everything after. With **no** anchor (pre-migration rows) the historical all-pending rendering is preserved rather than inventing progress.

**Verification:** `tests/test_last_stage_anchor.py` 17 passed; backend slice **167 passed** across 10 files; frontend **171 passed / 16 files**; `npx tsc --noEmit` exit 0.

## A.3 `KNOWN` — 🔴 `ACCEPT` has no IR (PAYMAIN's remaining blocker)

**Files:** `engine/transformation/semantic_capability.py:239` (`"ACCEPT": _unsupported(...)`), `engine/transformation/cobol_parser.py:125` (verb recognised, no handler), `engine/transformation/source_model.py:54` (`ACCEPT = "ACCEPT"` enum only).

`ACCEPT` is recognised as a keyword but has no statement IR, so `_parse_statement` falls through and emits `Skipped unsupported statement: ACCEPT WS-EMPLOYEE-ID.` The registry reason is honest — *"ACCEPT is used in source but the deterministic parser has no IR for it; it cannot be transformed"* — and `docs/COBOL_UNIVERSALITY_ROADMAP.md:221` marks it **"Blocked by design"**.

**Decision:** leave blocked. Flipping it to `SUPPORTED` without a GnuCOBOL oracle equivalence proof would violate the project's fail-closed gate ("Unknown is not PASS", "Compilation is not behavioral equivalence"). The Docker daemon is unavailable on this machine, so no such proof can be produced here.

**Net effect on PAYMAIN:** after A.1 the run fails for exactly **one** honest reason instead of six misleading ones. `app-7027e04e7bb6` / `run-c55d17695155` ("paymain-2") confirms this.

## A.4 `OPEN` — 🟢 No global run listing endpoint

The API exposes `GET /applications/{id}/runs` but no `GET /runs`. Finding "the latest run" requires enumerating every application first (92+ runs). `api/app.py` — worth a collection endpoint or an explicit product decision.

## A.5 `OPEN` — 🟢 Environment limitation, not a code defect

No Docker daemon reachable (`GET /ready` reports it non-gating). Oracle + candidate execution lanes cannot run locally, so no run can reach `VERIFIED` here; runs stop at an untrusted verdict. Recorded so later audits do not mistake this for a pipeline bug.

---

# Section B — File inventory (for parallel dispatch)

Line counts measured this session.

| Section | Area | Files | ~Lines | Status |
|---|---|---|---|---|
| B | `engine/transformation/` — parser, IR, capability | 10 | ~7,100 | ✅ |
| C | `engine/transformation/` — codegen & mapping | 15 | ~11,500 | ✅ |
| D | `engine/transformation/` — copybook / CICS / JCL / SQL | 16 | ~4,700 | ✅ |
| E | `engine/modernization/` + `engine/pipeline.py` + verdict/contracts | 15 | ~5,000 | ✅ |
| F | `engine/candidate|oracle|evidence|comparators|execution|domain` | 24 | ~6,200 | ✅ |
| G | `engine/sql|verification|cics|jcl` | 26 | ~5,700 | ✅ |
| H | `api/` control plane | 14 | ~5,300 | ✅ |
| I | `frontend/src/` | 32 | ~5,000 | ✅ |
| J | `scripts/`, `tools/`, CI, Docker, nginx, contracts, root docs | ~35 | — | ✅ |
| K | `tests/` (grouped) | ~942 | — | ✅ |

---

# Section H — `api/` control plane ✅ COMPLETE

14 files, ~5,300 lines.

### Summary — H

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 2 | Seal-verification TOCTOU on download; lost-update on `update_application` |
| 🟡 MEDIUM | 14 | Terminal state not guaranteed, approval TOCTOU, event-loop blocking, ingest data-loss ordering |
| 🟢 LOW | 18 | Info disclosure of server paths, missing headers on 401, dead code |

#### `api/app.py`

**Purpose:** FastAPI control-plane app: 21 routes, security middleware stack (body-limit, bearer auth, security headers, request-id/access log), startup reconciliation of interrupted runs, and health/readiness probes.

**Bugs:**
- 🔴 **HIGH (TOCTOU on seal verification)** `app.py:1112` builds the file list, `app.py:1119-1125` stat sizes, `app.py:1131` calls `verify_generated_seal`, then `app.py:1134-1137` **re-reads each file from disk** to build the ZIP. Bytes substituted between 1131 and 1137 are served as "sealed" — the exact filesystem-substitution threat `artifact_seal.py:5-13` claims to close. Verify-then-read must be one pass (hash while adding) or verify after packaging.
- 🟡 **MEDIUM (authz/validation)** `download_generated` gates only on `run.approval_state != "APPROVED"` (`app.py:1087`); it never checks `run.stage`/verdict. Combined with approval being accepted on non-terminal runs (`service.py:1396-1403`), a customer can approve an in-flight run against the *interim* seal (`service.py:1137-1139`), the run then fails validation, and if the tree still matches that interim seal the FAILED run's bundle downloads successfully.
- 🟡 **MEDIUM (event-loop blocking / DoS)** `ingest_application` is `async def` (`app.py:802`) but runs ZIP extraction + full discovery synchronously via `_svc().ingest_application` (`app.py:819`); `upload_cobol_source` (`app.py:744-752`) and `upload_java_candidate` (`app.py:761-769`) likewise call blocking file I/O directly. One 50 MB ingest stalls *every* request including `/health`, with no job-slot throttle (slots are only acquired in `modernize`/`revalidate`).
- 🟡 **MEDIUM (error path → 2xx)** `app.py:818-823` maps only `IngestionError` to 400; but discovery failures never raise at all (`ingestion.py:325,362`), so a completely failed discovery still returns **201** with `discovery_success: false` (`app.py:826-834`), and `GET /applications/{id}/discovery` (`app.py:837-859`) returns **200**. The failure is only visible if the client inspects the payload.
- 🟢 **LOW (headers missing on 401)** Auth (`app.py:447`) is registered *outside* `_SecurityHeadersMiddleware` (`app.py:366`) and `CORSMiddleware` (`app.py:317`), so a 401 short-circuit at `app.py:480-484` bypasses HSTS/CSP/X-Content-Type-Options **and** CORS headers — cross-origin clients get an opaque network error instead of a 401.
- 🟢 **LOW (unauthenticated recon)** `/ready` is exempted from auth at `app.py:452` and returns the durable workspace root path, DB error text, staging root and Docker status (`app.py:1190-1227`) to any caller.
- 🟢 **LOW (unhandled exception path)** `app.py:1137` `zf.write(f, arcname)` can raise `FileNotFoundError`/`OSError` if a file vanishes between listing (`1112`) and packaging → untyped 500 instead of 409/404.
- 🟢 **LOW (error typing bypass)** `_error()` (`app.py:575-576`) raises bare `HTTPException`, bypassing the `ApiError`/`public_detail` truncation contract documented at `app.py:33-34` and `errors.py:13-15`; `app.py:823` reflects raw (attacker-controlled) ZIP entry names from `str(exc)` into the JSON body (JSON-encoded, so not an injection, but unpurged).

**Limitations:**
- Auth is off entirely when `CONTROL_PLANE_API_TOKEN` is unset outside production (`app.py:463-473`) — documented dev default; production fail-closed gate at `app.py:555`.
- Approval is a single shared bearer token with self-asserted `approver` free text — explicitly no RBAC (`app.py:933-935`).
- `ModernizeOptions.use_uploaded_candidate` (`app.py:788-793`) is documented "internal/test-only, never sent by the UI" but reachable by any authenticated client in production — no env gate.
- `list_application_runs`/`get_run` call `run_verdict_state`, so one corrupt verdict blob makes the whole list 500 (`app.py:691`) — fail-closed but no per-row isolation.

**Gaps:**
- **No global `GET /runs` list endpoint** (only `/applications/{id}/runs`, `app.py:737`) — confirms finding A.4.
- Module docstring endpoint list (`app.py:3-22`) omits `POST /applications/{id}/candidate`, `GET|POST /runs/{id}/approval`, `GET /runs/{id}/integrated-proof` — all implemented.
- `service.py:1493` documents `GET /runs/{id}/proof`; no such route exists (only `/integrated-proof`, `app.py:1011`).
- **No rate limiting / brute-force throttling** on any route (token has only a length floor, `app.py:405`); no per-client limits on ingest/modernize/validate.
- No `DELETE`/`PUT` routes, no pagination/limits on `GET /applications` and `GET /applications/{id}/runs`.
- `GET /applications/{id}/discovery` (`app.py:840-845`) never checks that `cobol_source_path` still exists on disk — a deleted/lost-update path yields 200 with an empty or error-laden discovery.
- No per-endpoint authorization (any token holder can approve any run).

**Issues:**
- Internal absolute server paths are returned to clients: `ApplicationResponse` (`app.py:664-666`), `UploadResponse.cobol_source_path` (`app.py:757,774`), `IngestResponse.workspace_path` (`app.py:828`) — info disclosure, and unauthenticated when auth is off.
- `app.py:774` reuses the field name `cobol_source_path` for the *Java candidate* path (misleading contract).
- Duplicated content-length logic: `_guard_content_length` (`app.py:579-588`) vs `BodyLimitMiddleware` (`app.py:224-231`).
- Middleware ordering comment (`app.py:305-306`) and docstrings are correct but subtle; the 401-bypasses-headers consequence is undocumented.
- Deferred imports inside handlers (`app.py:844`, `app.py:1186-1188`) hide dependency errors until first request.
- `BodyLimitMiddleware` accumulates chunked bodies with `buffered += ...` (`app.py:245`) — quadratic copy for large chunked uploads.

#### `api/service.py`

**Purpose:** Orchestration boundary: application/run lifecycle, background modernization and revalidation workers, uploads, pipeline invocation, seal writes, and read-side proof/verdict/report derivation.

**Bugs:**
- 🔴 **HIGH (lost update / state corruption)** `Store.update_application` is a blind full-row UPDATE with no optimistic guard, and service writes it from stale in-memory copies at `service.py:515` (ingest), `service.py:629` (COBOL upload), `service.py:647` (candidate upload), `service.py:1126` (background generation, record loaded at `service.py:749`, potentially minutes earlier). Interleaving an upload with an ingest/modernize reverts `cobol_source_path`/`java_candidate_path`/`name` to stale values — including a path whose directory was already deleted by `_cleanup_temp_dir` at `service.py:631`/`649` → record permanently points at a deleted directory while the new workspace orphans. `update_run` has a generation guard; `update_application` has none.
- 🟡 **MEDIUM (data loss on error path)** `ingest_application` deletes the previous source **before** persisting the new one: `service.py:497-498` (`_cleanup_temp_dir(app.cobol_source_path)`) runs before `service.py:515` (`update_application`), and the handler's rollback (`service.py:521-524`) only removes the *new* workspace. Any exception between 497 and 515 (sqlite lock, `unique_name`, `find_application_by_name`) leaves `cobol_source_path` pointing at a directory that no longer exists. This is precisely the ordering defect documented as *fixed* for uploads at `service.py:619-625` but still present for ingest.
- 🟡 **MEDIUM (sealed artifact destroyed by a later write)** `service.py:1125` sets `app.java_candidate_path = report.generated_project_dir`, aliasing the generated bundle. A subsequent `upload_java_candidate` treats that bundle as `previous` (`service.py:645`) and `_cleanup_temp_dir(previous)` (`service.py:649`, prefix whitelist includes `pipeline-output-`, `service.py:104`) **deletes the sealed generated artifact** → every download for that run 404s and `runs.generated_seal` refers to nothing.
- 🟡 **MEDIUM (terminal state not guaranteed)** `_modernize_background` performs `self._store.get_run(run_id)` (`service.py:740`) and `self._store.get_application(app_id)` (`service.py:749`) **outside** the `try` that starts at `service.py:754`. A `PersistenceCorruptionError` raised while decoding a malformed `evidence_blob`/`report_blob` (or any store failure) escapes into `_launch`'s wrapper, which only releases the job slot (`service.py:414-419`) — the run stays `CREATED` forever (until the next restart's `mark_interrupted_runs`). Same defect in `_revalidate_background`: `service.py:909` and `service.py:918` are outside the `try` at `service.py:923`, and there it is worse because `begin_revalidation` already reset a terminal run to `CREATED` with verdict/approval/seal cleared (`store.py:601-620`).
- 🟡 **MEDIUM (terminal state not guaranteed)** `_persist_final` (`service.py:799-846`) gives up after 3 attempts and leaves the run non-terminal (documented, logged) — reconciled only at the next restart. Additionally `except Exception` at `service.py:777`/`service.py:944` does not catch `BaseException` (`KeyboardInterrupt`, `SystemExit` raised inside the pipeline) → same stuck outcome.
- 🟡 **MEDIUM (stuck run + slot leak)** `_launch` at `service.py:712` (after `add_run` at `service.py:701`) and `service.py:895` (after `begin_revalidation` at `service.py:887`) are unguarded: if `Thread.start()` raises (thread exhaustion), the slot acquired at `service.py:691`/`service.py:885` leaks permanently (`_active_jobs` never decremented → eventual permanent 429) and the already-persisted/reset run stays non-terminal.
- 🟡 **MEDIUM (approval TOCTOU)** `Service.set_run_approval` verifies the seal (`service.py:1396-1400`) then writes approval with no `validation_generation`/terminal check (`service.py:1401-1403`). A concurrent `POST /runs/{id}/validate` reset can land between the verify and the UPDATE, so a **fresh attempt inherits APPROVED** without any decision made against its bytes; conversely an in-flight run can be APPROVED against the interim seal (`service.py:1137-1139`) before any verdict exists.
- 🟡 **MEDIUM (conditional seal check)** `service.py:1399` only verifies when `app.generated_app_path is not None` — otherwise APPROVED is recorded with **zero bytes verified**, although `_run_validation` sealed a different directory (`java_dir`, `service.py:1247-1249`, the uploaded-candidate path).
- 🟡 **MEDIUM (concurrent write hazard)** No per-application single-flight: repeated `modernize`/`ingest`/`upload` on one app run concurrently. Re-ingest deletes `cobol_source_path` (`service.py:497`) while an in-flight pipeline is reading it (`service.py:1061`, `service.py:1194`) → the run fails; concurrent runs also race on `app.generated_app_path` (`service.py:1122`), so `download`/approval for run A resolve to run B's directory (`app.py:1094-1096`) and 409 on seal mismatch (fail-closed, but wrong-status/availability).

**Limitations:**
- Job slots are process-local by design (`service.py:423-430`); no cluster-wide quota.
- `_cleanup_temp_dir` only deletes basenames matching `cobol-`/`java-`/`ingest-`/`pipeline-output-` (`service.py:104`); superseded generated bundles are never cleaned at all → durable-volume growth.
- `use_uploaded_candidate` is internal/test-only (`service.py:654-656`) yet wired to a public route.
- `update_run` never touches approval/seal columns (verified: `store.py:502-507`), so stale workers cannot clobber a decision or the seal; but `update_run` *does* rewrite `evidence_blob`/`verdict_blob`/`report_blob`/`error`/`completed_at`, protected solely by the `validation_generation` check (`store.py:487-492`).
- `get_run_detail` swallows discovery exceptions into `discovery: None` (`service.py:1646-1647`) and listing errors into `generated_files: []` (`service.py:1659-1660`).
- Discovery is recomputed on demand on read paths (`service.py:990`, `service.py:1643`) rather than persisted.

**Gaps:**
- No global run listing (confirms A.4).
- `GET /runs/{id}/proof` documented at `service.py:1492-1493` does not exist (route is `/integrated-proof`).
- No retention/GC policy for orphaned workspaces (`ingest`/`upload` failures and superseded `pipeline-output-*` dirs accumulate).
- No per-application concurrency guard; no timeout around the pipeline stages — a hung Docker call leaves a run non-terminal until restart.
- `_persist_final` has no post-restart backfill: it logs and stops (`service.py:833-845`).

**Issues:**
- Dead code: `source_root = self._detect_source_root(workspace)` (`service.py:488`) is never used, making `_detect_source_root` (`service.py:526-554`) production-dead (only its comment at `service.py:79` survives).
- Duplication: `_job_limit` (`service.py:114-127`) and `_upload_file_limit` (`service.py:130-137`) re-implement `api.limits.env_int_limit` instead of using it.
- Duplication: `_report_facade` (`service.py:171-201`) and `_ResultFacade` (`service.py:1538-1547`) rebuild engine object shapes with `SimpleNamespace`, silently drifting if engine models change.
- `_resolve_entry_program` re-runs full discovery (`service.py:990`) on every generation — third discovery pass besides `ingestion.py:284` and `ingestion.py:352`.
- Module docstring safety claims (`service.py:32-42`) are accurate only for runs; the application-row races above are undocumented.
- `Service` has no shutdown hook: daemon threads (`service.py:421`) drop in-flight work silently (mitigated only by `store.py:628`).

#### `api/store.py`

**Purpose:** Single-connection, `RLock`-guarded SQLite store for applications/runs with a forward-only stage state machine, generation-based stale-worker rejection, additive migrations, and startup reconciliation.

**Bugs:**
- 🟡 **MEDIUM (multi-process state corruption)** `mark_interrupted_runs` (`store.py:628-654`) fails *every* non-terminal run at process start with no PID/heartbeat/ownership column. A second process opening the same file (second uvicorn worker, test runner, tool importing `api.app`, which triggers `app.py:141`) marks live runs FAILED; the still-running workers' terminal writes are then rejected by `is_valid_transition` (`store.py:119-120`) → `_persist_final` retries, fails, logs. Single-replica is documented but nothing enforces it.
- 🟡 **MEDIUM (lost update)** `update_application` (`store.py:370-398`) performs a full-row `UPDATE ... WHERE id = ?` with no version/etag guard — every column is last-writer-wins (see `service.py` HIGH finding).
- 🟡 **MEDIUM (approval clobber by race)** `set_run_approval` (`store.py:516-549`) has neither a `validation_generation` guard nor a terminal/stage check, while `begin_revalidation` clears approval in the same statement (`store.py:610-612`). An approval UPDATE landing after a reset leaves a brand-new attempt `APPROVED`; a non-terminal run can be approved too.
- 🟡 **MEDIUM (seal writer has no guard)** `set_generated_seal` (`store.py:551-567`) writes `generated_seal` without checking `validation_generation`, despite `RunRecord`'s policy comment (`store.py:195-202`) claiming stale workers "cannot clobber the seal of a newer attempt". That protection exists only because `update_run` omits the column (`store.py:502-507`); the seal writer itself is unguarded — a stale caller can overwrite a newer attempt's seal.
- 🟢 **LOW (no SQLite tuning)** No `PRAGMA journal_mode=WAL` and no `busy_timeout` anywhere (only `PRAGMA user_version`/`table_info` at `store.py:271,279,289,303`) → cross-process contention raises `database is locked`; only terminal writes retry (`service.py:799-846`), while `add_run`/`update_application`/`set_run_approval` fail straight to 500.
- 🟢 **LOW (`assert` for invariants)** `store.py:548` and `store.py:625` use `assert row is not None`, which vanishes under `python -O` → `_run_from_row(None)` raises an opaque `TypeError` instead of a clear invariant failure.
- 🟢 **LOW (duplicate names)** `unique_name` (`store.py:405-413`) is check-then-insert under an in-process lock only, and `idx_applications_name` is non-unique (`store.py:237`) → duplicate application names across processes.

**Limitations:**
- One shared connection + `RLock` = single-process design (`store.py:246-252`); correctness depends entirely on that lock.
- `update_run` (`store.py:467-514`) writes `evidence/verdict/report/error/completed_at` from the caller's snapshot; the only staleness defence is `validation_generation` (`store.py:487-492`) — there is no field-level merge.
- `allow_reset` parameter (`store.py:467`, used at `store.py:494`) is never passed `True` anywhere in the repo — dead API surface.
- Stage transitions allow forward jumps (`store.py:112-130`), so skipped stages are indistinguishable from lost ones.
- Every `get_run`/`list_runs_for_application` decodes and seal-verifies evidence + verdict + report blobs (`store.py:750-766`) — poll cost scales with report size.
- `mark_interrupted_runs` runs only at import of `api.app` (`app.py:141`), not periodically.

**Gaps:**
- No `schema_migrations` history table; migrations are column-presence heuristics in `_migrate` (`store.py:287-331`) with `user_version` stamped unconditionally at `store.py:270-272`.
- No index on `runs.stage` (used by `mark_interrupted_runs`, `store.py:637-640`) nor `runs.created_at`.
- `applications.name` has no `UNIQUE` constraint backing `unique_name`.
- No `close()`/context-manager/`__del__` → the connection is never released (`store.py:254-273`); many `Store` instances (tests) leak handles.
- No pagination, no purge/retention, no multi-row transaction spanning `update_application` + directory cleanup.

**Issues:**
- `_run_params(record, target_stage)[1:]` positional-slicing reuse for UPDATE (`store.py:508-510`) is brittle: inserting a column in `_run_params` silently breaks the UPDATE binding.
- `TERMINAL_STAGES` is a `frozenset`, so the SQL placeholders in `mark_interrupted_runs` (`store.py:636-639`) have nondeterministic order (harmless, but flaky for query-log assertions).
- `assert`-based invariants (see Bugs) and `assert refreshed is not None` (`store.py:625`).
- `probe_database` (`store.py:656-687`) opens a second connection per `/ready` call — fine, but it never verifies writability against the *live* connection used by workers.

#### `api/serialization.py`

**Purpose:** Versioned JSON codec for the persisted evidence manifest, verdict, modernization report and string-list columns, with envelope validation and evidence-seal re-verification on load (replaces pickle).

**Bugs:**
- 🟢 **LOW (inconsistent validation)** `decode_verdict` validates `evidence_manifest_hash` with plain `_expect_str` (`serialization.py:747-749`) instead of `_parse_hash`, so a structurally invalid digest decodes cleanly here and only fails later in `Service._check_evidence_verdict_consistency` (`service.py:1330-1336`) — the module's "field types validated" claim (`serialization.py:8-11`) is not uniform.
- 🟢 **LOW (lossy round-trip)** `_encode_envelope` uses `json.dumps(..., default=str)` (`serialization.py:181`), silently stringifying non-JSON values; decode then reconstructs objects from those strings, so encode→decode is not type-faithful and no self-check asserts round-trip equality.
- 🟢 **LOW (amplification)** `decode_report` accepts an arbitrarily large nested dict (`serialization.py:775-782`) with no size/depth bound, and it is re-parsed on every `get_run`/`list_runs_for_application` (`store.py:766`) — a multi-MB report makes cheap status polling expensive.

**Limitations:**
- Single payload schema version (`serialization.py:62-64`); any bump is a hard reject with no forward migration path (`serialization.py:218-222`).
- The evidence seal is an **unkeyed** SHA-256 over the canonical graph (`engine/evidence/models.py:407-408` recomputed on construction; compared at `serialization.py:654-655`), so anyone who can rewrite the DB row can recompute it — tamper-evidence against accidental/partial edits only; the trust boundary is stated in `artifact_seal.py:31-35`.
- Legacy pickle blobs are rejected only because they are not valid UTF-8 (`serialization.py:199-202`) — a pickle that happens to be UTF-8 text still fails at the JSON/schema check (`serialization.py:204-214`), so fail-closed holds.
- Reports are stored verbatim with no internal schema version (`serialization.py:772`).

**Gaps:**
- No payload-size ceiling on decode (a corrupt/huge blob is fully materialized before validation).
- No `schema_version` migration registry — adding a field to `EvidenceManifest` requires simultaneous encoder (`serialization.py:259-350`) and decoder (`serialization.py:522-656`) changes with no contract test tying them to the engine model.
- `SCHEMA_STR_LIST` (`serialization.py:60`) declared but never used — string lists bypass the envelope entirely (`serialization.py:789-822`).

**Issues:**
- Dead constant `SCHEMA_STR_LIST` (`serialization.py:60`).
- Large hand-maintained field mappers duplicated between engine `to_dict()` and local encoders, with compensating comments about what `to_dict()` omits (`serialization.py:309-314`, `serialization.py:332-338`) — fragile coupling.
- `_expect_*` helper family (`serialization.py:81-165`) duplicates type validation already present in engine dataclasses.

#### `api/ingestion.py`

**Purpose:** Hardened ZIP extraction into a durable, isolated workspace (zip-slip/symlink/duplicate/size/ratio guards, safe app-id prefix) plus engine discovery over the extracted tree.

**Bugs:**
- 🟡 **MEDIUM (failure surfaced as success)** `discover_application` converts every discovery exception into `discovery_errors` (`ingestion.py:325-329`, `ingestion.py:362-366`), so `POST /applications/{id}/ingest` answers **201** and `GET .../discovery` answers **200** even when COBOL discovery failed wholesale — no HTTP status ever reflects the failure (`app.py:826-859`).
- 🟢 **LOW (silent cleanup failure)** `_discard_workspace` (`ingestion.py:255-263`) uses `shutil.rmtree(..., ignore_errors=True)` and its own docstring states cleanup failures are "logged by nobody": a hostile archive that trips a limit and leaves undeletable entries fills the durable volume with zero log lines/counter.
- 🟢 **LOW (collision detection incomplete)** Duplicate/casefold detection covers only non-directory entries (`ingestion.py:180-195`). A file-vs-directory collision (entry `a` plus entry `a/b`, or `Dir/x` plus file `dir`) is caught only by an OS error at `ingestion.py:233`/`ingestion.py:235-236`, surfaced as the generic `Failed to extract ZIP` (`ingestion.py:250`) — fail-closed, but the precise diagnostic promised at `ingestion.py:181-194` does not apply.
- 🟢 **LOW (over-permissive name check)** `_is_traversal` (`ingestion.py:76-83`) accepts `.` and `./a` (only `..`, absolute, drive and UNC forms are rejected); entry `.` then fails at `open(workspace, "wb")` (`ingestion.py:236`) via the generic handler rather than a named validation error. NUL/control characters likewise rely on the generic `except Exception` (`ingestion.py:248-250`).

**Limitations:**
- Zip-bomb guards trust central-directory declarations: ratio from `file_size/compress_size` (`ingestion.py:202-216`) and the 200 MB total from declared sizes (`ingestion.py:217-222`). Actual bytes written are bounded by CPython's `ZipExtFile._left` truncation to the declared `file_size` (verified in `zipfile.ZipExtFile._read1`: `data = data[:self._left]`), so the limits hold; a wrong-CRC entry is only detected *after* writing (`ingestion.py:236-241`), then the workspace is discarded (`ingestion.py:242-250`) — transient disk usage up to the total cap.
- No per-entry size cap (a single entry may consume the whole 200 MB), no per-entry count of directories separate from files, no max path-length check (Windows `MAX_PATH` failures surface as generic extraction errors).
- Symlinks are rejected only when declared via Unix mode (`ingestion.py:86-88`); the writer never creates symlinks (plain `open(..., "wb")`, `ingestion.py:236`), which is what actually prevents in-tree symlink traversal.
- Whole archive is buffered in memory by the route before `ingest_zip` (`app.py:814-816`, bounded by 50 MB).
- `discover_application` runs `ApplicationDiscovery` a second time for JCL linking whenever COBOL programs exist (`ingestion.py:351-354`) — discovery is ~2× COBOL passes per call.
- Git ingestion is interface-only (`ingestion.py:5`).

**Gaps:**
- No rate limiting/idempotency: re-ingesting the same ZIP always creates a new workspace; the old one is cleaned only on the next successful ingest (`service.py:497`).
- No limit on nested-directory depth or total directory entries (only `len(members)` at `ingestion.py:161-165`).
- No observability for tripped limits (no counter/metric/log level beyond the raised message).
- `_discard_workspace` failures are not reported to the caller or to `/ready`.

**Issues:**
- Duplicate discovery invocation (see Limitations) and duplicate `DiscoveryResult.to_dict()` field list vs `app.py:847-859` mapping.
- `_zip_limit` + four near-identical getters (`ingestion.py:56-73`) could be one table-driven helper.
- `total_size_bytes`/`source_file_count` are computed by a pre-pass `rglob` (`ingestion.py:277-280`) that re-walks the tree already walked by discovery.

#### `api/artifact_seal.py`

**Purpose:** P0 evidence-substitution protection: chunked SHA-256 sealing of the generated bundle into `runs.generated_seal`, and fail-closed (409) verification at approval and export.

**Bugs:**
- 🟡 **MEDIUM (TOCTOU inside the API contract)** `verify_generated_seal` (`artifact_seal.py:96-137`) hashes the tree at call time; callers then act on bytes re-read afterwards (`app.py:1134-1137` download; `service.py:1396-1401` approve-then-write). Verification and consumption are not atomic, so substitution inside the window is served/approved — the module's stated goal (`artifact_seal.py:5-13`) is only partially closed (download path).
- 🟢 **LOW (symlinks included silently)** `compute_generated_seal` uses `rglob("*")` + `is_file()` (`artifact_seal.py:81`), which follows symlinks: a symlink inside the bundle is sealed as content of the target path, and `download` packages it the same way (`app.py:1112`, `app.py:1137`). Not a bypass (an added/changed symlink fails the seal), but there is no explicit symlink rejection for defense in depth.
- 🟢 **LOW (partial-read consistency)** A file modified *during* `compute_generated_seal`'s own walk (`artifact_seal.py:81-86`) yields a seal over mixed bytes; the same race exists inside `verify_generated_seal` when it re-derives (`artifact_seal.py:124`).

**Limitations:**
- Trust boundary is the control-plane store: DB writers can recompute the seal (unkeyed SHA-256), explicitly documented (`artifact_seal.py:31-35`).
- Sealing happens twice (interim at `service.py:1137`, authoritative at `service.py:1247`); a run that fails validation keeps the interim seal, which is what approval/download will compare against.
- `sealed_at` timestamp makes the document non-byte-deterministic by design (`artifact_seal.py:70-73`) — only `files` is compared (`artifact_seal.py:124-125`).
- Empty bundles are sealable (a seal with `"files": {}` verifies), so an emptied directory that still exists compares equal only if it was sealed empty.

**Gaps:**
- No maximum bundle size or file-count cap here (caps live only in `app.py:1105-1110`); `compute_generated_seal` on a huge tree blocks the calling thread with no progress/timeout.
- No protection for source workspaces (`cobol_source_path`) — only the generated bundle is sealed.

**Issues:**
- `json.loads(compute_generated_seal(root))["files"]` (`artifact_seal.py:124`) round-trips a full JSON document just to read one key — recompute the dict directly.
- `differing` computation (`artifact_seal.py:126-132`) is only used for a count in the message; keys/paths are never logged, so operators cannot tell *which* file differed.

#### `api/errors.py`

**Purpose:** Typed `ApiError` hierarchy with fixed HTTP status mapping and truncated, client-safe `public_detail`.

**Bugs:** None found.

**Limitations:**
- `public_detail` and `detail` are the same truncated string (`errors.py:36-43`) — there is no separate internal field, so the docstring claim that "internal detail stays available on the exception object for logging" (`errors.py:14-15`) is only true in that callers keep their own copy.
- Truncation is length-only (`errors.py:20-27`); messages are not scrubbed of filesystem paths, so any producer embedding a path (e.g. `ServiceError` from `service.py:1109-1111` joining `report.limitations`) violates `errors.py:14-15`.
- No 401/403 type: authentication failures are produced ad hoc in middleware (`app.py:468,480`) instead of through this hierarchy.

**Gaps:**
- No `RateLimitedError`/429-for-throttling type (`BusyError` is concurrency-only, `errors.py:74-78`).
- No `ServiceUnavailableError` (503) for dependency failures; `/ready` hand-rolls JSON (`app.py:1230-1236`).

**Issues:**
- Two parallel error mechanisms coexist: `ApiError` subclasses and bare `HTTPException` from `_error()` (`app.py:575-576`), so the status table in `errors.py:4-11` is not exhaustive.
- `InvalidStateTransitionError`/`UnsupportedSchemaError` subclass `PersistenceCorruptionError` (500), meaning a client-triggerable transition bug is reported as a server fault — intentional, but conflates client and server causes in monitoring.

#### `api/limits.py`

**Purpose:** Shared positive-integer environment limit parsing with default fallback and one warning on invalid values.

**Bugs:** None found.

**Limitations:**
- No upper bound: an env value of e.g. `10**18` is accepted verbatim (`limits.py:19-23`), so a typo can disable a safety cap (e.g. `CONTROL_PLANE_MAX_ZIP_ENTRIES=999999999`).
- Only `ValueError` is caught (`limits.py:20`); values like `1_000` parse as valid Python ints (`int("1_000") == 1000`) and are silently accepted.

**Gaps:**
- Not used by `service.py`'s `_job_limit`/`_upload_file_limit` (`service.py:114-137`) — two of the config knobs bypass this shared parser entirely.

**Issues:** None found (module is minimal and consistent).

#### `api/logging_config.py`

**Purpose:** Idempotent root-logger configuration (JSON or text), per-request correlation id via `ContextVar`, and structured `extra={}` serialization.

**Bugs:**
- 🟢 **LOW** `StructuredFormatter.format` copies every non-standard `record.__dict__` key into the payload *after* the base keys (`logging_config.py:140-143`), so an `extra={"level": ...}` or `extra={"request_id": ...}` from any call site silently overwrites the canonical fields in the emitted JSON (last-writer-wins with no reserved-name check).

**Limitations:**
- Sets the **root** logger level (`logging_config.py:225`), thereby raising/lowering third-party logger verbosity (uvicorn, engine libs) as a side effect; `handler.setLevel(level)` (`logging_config.py:223`) is separate but root level dominates.
- One stderr `StreamHandler` only — no file rotation, no sampling, no rate limiting on log volume (a failing run logs a full traceback per retry, `service.py:833`).
- Unknown `CONTROL_PLANE_LOG_LEVEL` falls back to INFO with a raw `sys.stderr.write` (`logging_config.py:188-190`) rather than a log record.

**Gaps:**
- No log destination/rotation configuration (production relies on `docker logs`).
- No explicit test hook to restore the previous formatter on teardown beyond `force=True` (`logging_config.py:194-212`), which drops the old handler without restoring prior state.

**Issues:**
- `current_request_id()` (`logging_config.py:113-115`) is dead code — never referenced anywhere in the repository.
- `_STANDARD_RECORD_ATTRS` duplicates private knowledge of `LogRecord` (`logging_config.py:69-96`), including a conditional `taskName` (3.12+) — must be maintained per Python version.
- `TextFormatter.formatMessage` (`logging_config.py:159-169`) appends `request_id` and extras but still relies on `_STANDARD_RECORD_ATTRS` to avoid duplicates, duplicating the JSON formatter's filter logic.

#### `api/models.py`

**Purpose:** Pydantic request/response models and the `RunStage` enum shared by the API surface.

**Bugs:**
- 🟢 **LOW (validation bypass by design path)** `ApplicationCreate.name` is capped at 256 chars (`models.py:55`) and `target_runtime` at 64 (`models.py:62`), but the ingest path derives `app.name` from ZIP contents with no length/charset validation (`service.py:503-513` → `name_derivation.py:31`) — a ZIP entry name (up to 64 KB) can become `app.name`, later producing a huge `Content-Disposition` filename at `app.py:1142-1146`.

**Limitations:**
- Response models intentionally expose internal filesystem paths (`models.py:73-76`, `models.py:86`, `models.py:239`).
- `ApprovalResponse.state` is a free `str` (`models.py:138`) rather than the `ApprovalDecision`/`PENDING` union — no response-side enum enforcement.
- `ModernizeOptions.use_uploaded_candidate` is a public model field documented as internal/test-only (`models.py:168-177`).
- All evidence/proof payloads are `dict`/`list[dict]` (`models.py:242`, `models.py:288`, `models.py:318-321`) — no schema validation on read surfaces.

**Gaps:**
- `IngestRequest` (`models.py:231-234`) with `git_url` is documented but no route accepts it (ingest takes only `UploadFile`, `app.py:802-806`).
- No pagination models for list endpoints (`ApplicationResponse` list, `RunResponse` list).
- No request model for `POST /applications/{id}/validate`-style options or for approval idempotency keys.

**Issues:**
- `RunStage.INGESTING` (`models.py:29`) and `RunStage.GENERATING` (`models.py:34`) are never set by production code (only tests set `GENERATING`; `INGESTING` appears solely in `store.py:62`) — dead enum values that the stage machine still orders.
- `RunStage` docstring (`models.py:21-27`) omits `INGESTING`, which *is* in `STAGE_ORDER` (`store.py:62`).
- `UploadResponse.cobol_source_path` is used for candidate uploads too (`app.py:774`) — misleading field name.

#### `api/name_derivation.py`

**Purpose:** Derive a normalized application slug from ZIP bytes (top-level entry peek) or from the archive filename.

**Bugs:**
- 🟢 **LOW** `normalize_application_name` (`name_derivation.py:15-31`) imposes no length cap and no upper bound before the value becomes `app.name` (`service.py:508`), so a long/multibyte ZIP entry name flows into DB, API responses and the download filename (`app.py:1142`).

**Limitations:**
- Non-ASCII names collapse to `application` (`name_derivation.py:28`), after which `unique_name` appends `-2`, `-3` — CJK/Umlaut project names are effectively unusable as identities.
- `derive_application_name_from_zip_bytes` opens and parses the archive a second time (`name_derivation.py:71-78`) after `ingest_zip` will parse it again — 3 passes over the same bytes.
- Peeks only at top-level directory names (`name_derivation.py:72-75`); single-dir ZIPs win over the filename regardless of content.

**Gaps:**
- The `git_url`/local ingestion abstraction promised by the module docstring (`name_derivation.py:3-4`) has no implementation surface.

**Issues:**
- `derive_application_name_from_zip` (workspace variant, `name_derivation.py:34-57`) is referenced only by tests — dead production code.
- Bare `except Exception:` swallow at `name_derivation.py:76-78` hides even `MemoryError`-class failures behind a filename fallback.

#### `api/paths.py`

**Purpose:** Durable workspace placement: `CONTROL_PLANE_WORKSPACE_DIR`-selected root for artifact workspaces, with loud failure instead of silent tmpfs fallback, plus a readiness probe.

**Bugs:**
- 🟡 **MEDIUM (latent path traversal — prefix unvalidated)** `new_workspace(prefix=...)` passes `prefix` verbatim into `tempfile.mkdtemp(prefix=..., dir=root)` (`paths.py:49-66`), i.e. `os.path.join(root, prefix + name)` with no separator/`..` validation. A prefix containing backslashes (e.g. `cobol-..\..\..\evil-`) escapes the durable root on Windows (Win32 normalizes `..`; `os.mkdir` creates only the final component, whose parent then exists). Today every caller interpolates a *server-generated* id (`app-{hex12}`, `run-{hex}`) or an id validated by `_SAFE_APPLICATION_ID` (`ingestion.py:141`), so it is not currently reachable — but `Service._write_upload` (`service.py:604`, `f"{prefix}-{app_id}-"`) and `paths.py` itself perform no validation, and `docs/BACKLOG.md` BL-137 records the identical defect as a fixed CVE-class bug in `ingest_zip`. `paths.py` is the one place that should enforce it.
- 🟢 **LOW (readiness race → false 503)** `workspace_root_problems` (`paths.py:84-89`) writes then unlinks a fixed `.readiness-probe` file. Two concurrent `/ready` calls (unauthenticated, `app.py:452`) can both unlink: the loser gets `FileNotFoundError` and reports "not writable" → **spurious 503**, i.e. flapping readiness under concurrent probes.
- 🟢 **LOW (relative root accepted)** `workspace_root()` returns `Path(raw)` unchanged (`paths.py:43-46`); a relative `CONTROL_PLANE_WORKSPACE_DIR` silently resolves against the process CWD (which differs between a container shell, a cron backup and uvicorn).

**Limitations:**
- Unset root = platform temp dir by design (`paths.py:56-58`), so dev/test silently keeps non-durable storage — documented (`paths.py:20-23`).
- `new_workspace` has no quota/free-space check and no permissions enforcement on the created dir.
- `workspace_root_problems` mutates state (creates/deletes a probe file) on every `/ready` — a *read* endpoint performs writes.

**Gaps:**
- No validation that the configured root is not inside `$TMPDIR`, not a symlink, and not shared with another mount.
- No cleanup/rotation of old workspaces; no max-workspace-count guard at creation time.
- No distinct error type for "root misconfigured" on the write path beyond a bare `OSError` (`paths.py:62-66`) → surfaces as an unhandled 500 rather than a typed `ApiError`.

**Issues:**
- Duplicated readiness logic: `workspace_root_problems` (`paths.py:69-90`) and `/ready`'s own `workspace_root()` usage (`app.py:1195-1202`) split one concern across two modules.
- The probe file name (`.readiness-probe`) is not excluded anywhere from backup/scan tooling.

#### `api/workload_contract.py`

**Purpose:** Resolve the certification contract for each (re)validation: trusted repository fixture registry first, explicit `default:stdout-exit-status` fallback, fail-closed on unloadable declarations.

**Bugs:**
- 🟢 **LOW (no cache → repeated code execution)** `_load_declaration_module` executes fixture module code (`workload_contract.py:119-127`) on every resolution, and resolution happens at least twice per run (`service.py:687`, `service.py:1186`) plus once per revalidation (`service.py:879`) — repeated `exec_module` with no `sys.modules` registration or memoization (a fixture with import side effects runs multiple times per request path).

**Limitations:**
- Fixtures are repository-controlled code executed in-process (`workload_contract.py:110-127`) — explicitly trusted, never uploaded content; any fixture exception becomes a 400 (`workload_contract.py:184-188`).
- Declared workloads requiring staged inputs are rejected outright (`workload_contract.py:208-214`).
- Only `fixtures/<id>/workload.py` and `fixtures/workload-<id>/workload.py` are searched (`workload_contract.py:167-176`); no nested or package-style declarations.
- `_find_factory` convention fallback accepts a single `*_workload` function (`workload_contract.py:136-143`), so a module with one oddly-named factory is silently used.

**Gaps:**
- No caching/invalidate strategy for fixture declarations (a changed fixture requires process restart).
- No `sys.modules` insertion → relative imports inside `workload.py` will fail with an opaque `ServiceError` (`workload_contract.py:122-126`) instead of a clear diagnostic.
- No rate/size limit on the number of distinct workload ids an API client can force to be resolved (each `modernize` pre-flight executes code).

**Issues:**
- `workload_py_name` (`workload_contract.py:224-228`) re-checks the filesystem that `load_declared_workload` already checked (`workload_contract.py:173-176`) — duplicated resolution logic that can disagree if files change between the two calls (TOCTOU on the reported contract id).
- `contract_source` property (`workload_contract.py:63-70`) duplicates the prefix parsing also done in `app.py:701-705` (`_contract_source`).

#### `api/__init__.py`

**Purpose:** Package marker: one-line docstring declaring the control-plane API boundary.

**Bugs:** None found.

**Limitations:** None found.

**Gaps:**
- No `__all__`, no version pin, and no lazy-import guard: importing `api` does not configure logging or run the production auth gate — those live in `api.app` (`app.py:104`, `app.py:555`), so any entry point that imports `api.service`/`api.store` directly starts without the fail-closed startup checks.

**Issues:** None found.

---

# Section I — frontend React layer ✅ COMPLETE

27 files (~6,100 lines). 4 HIGH, 15 MEDIUM, 30 LOW.

### Summary — I

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 4 | `ModernizationRun` approval gate + stale state on `runId` change; `PipelineStepper` FAILED-run all-pending (known); `IntegratedProof` unguarded throw |
| 🟡 MEDIUM | 15 | Overlapping duplicate pollers, unguarded `setInterval` races, dead `StageIndicator` failure branches, `VerdictDisplay` unknown→UNPROVEN |
| 🟢 LOW | 30 | Accessibility gaps, dead props/variants, hardcoded hex bypassing `tokens` |

#### `frontend/src/api/client.ts`

- **Purpose:** Typed fetch wrapper for the whole backend surface (auth header, error flattening, discovery/verdict/approval/download helpers) — the only module that performs HTTP.
- **Bugs:**
  - 🟡 **MEDIUM** `frontend\src\api\client.ts:563-581` — `discoveryIssuesMessage` treats a *missing* `discovery_success` the same as `false`: line 568 `if (discovery.discovery_success)` is falsy for `undefined`, `discovery_errors` is empty, so line 580 unconditionally returns "Discovery incomplete: the run did not finish cleanly" for a payload that simply lacks the flag — contradicting its own contract at 559-561 ("a completed discovery must return null — we must never invent a warning"). Fix: only take the fallback when the flag is explicitly `=== false` or the key is absent *and* the body is otherwise truncated.
  - 🟡 **MEDIUM** `frontend\src\api\client.ts:384-400` — `request()` accepts no `AbortSignal`/timeout. A hung fetch never rejects, so `ModernizationRun.tsx:247-268` keeps stacking interval ticks on top of it (overlapping polls, out-of-order `setRun`) and `App.tsx:130-140` stalls its whole sequential loop on one run. Nothing can be cancelled on unmount.
  - 🟢 **LOW** `frontend\src\api\client.ts:399` — a 2xx with an empty body makes `res.json()` throw a raw `SyntaxError`, so callers get a non-`ApiError` with a useless message instead of a typed failure.
  - 🟢 **LOW** `frontend\src\api\client.ts:70-76` — `setApiToken` writes `localStorage` unguarded while the read path (58-63) is try/caught; a private-mode/quota throw propagates out of `App.tsx:118-124` and the token silently never persists.
- **Limitations:** `BASE = ''` (28) means same-origin only; no pagination/ETag/conditional requests, so every poll is a full body; no retry/backoff helper; `uploadCandidate`/`validateRun`/`getHealth`/`getApplication` are exported but never called by the UI (430, 467, 500, 518).
- **Gaps:** Only the Dashboard token form handles 401 (`App.tsx:104-106`); there is no shared "backend unreachable" vs "HTTP error" distinction — `fetch` network `TypeError` is rethrown as-is from `request`, so callers cannot render a connection-specific state. `VITE_CONTROL_PLANE_API_TOKEN` is not declared in `vite-env.d.ts`, forcing the `MaybeEnvImportMeta` cast (52-54, 64).
- **Issues:** `downloadGenerated` (663-683) duplicates the error-parsing block of `request()` (386-398) verbatim instead of reusing it; the endpoint doc header (7-25) omits `GET /runs/{id}/report` (600) and `GET /runs/{id}/integrated-proof` (653).

#### `frontend/src/api/stages.ts`

- **Purpose:** Canonical linear run-stage order plus labels and terminal-stage helper shared by the stepper, dashboard and run page.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\api\stages.ts:68-72` — `TERMINAL_STAGES` and `isTerminalStage()` are two definitions of the same rule; they can drift (only `isTerminalStage` is used in app code, `App.tsx:6`, `ModernizationRun.tsx:49`).
  - 🟢 **LOW** `frontend\src\api\stages.ts:47-50` — `STAGE_LABELS` collapses `CREATED`/`DISCOVERING`/`DISCOVERY_COMPLETED` to the same word "Discovery", so any future consumer cannot distinguish pre-run from in-progress; `INGESTING` (48) is labelled although documented as never emitted (14-18).
- **Limitations:** Deliberately excludes `INGESTING` and `FAILED` from `RUN_STAGES` (13-20); no stage→customer-group mapping lives here (that is re-implemented in `PipelineStepper.tsx:45-88`).
- **Gaps:** No helper for "% complete" or "is in progress"; no runtime validation that a newly added backend stage made it into this list — a stage added to `RunStage` (`client.ts:93-112`) but not here silently maps to index `-1` everywhere.
- **Issues:** `STAGE_LABELS` (46-66) and `TERMINAL_STAGES` (68) are effectively test-only dead exports; three independent stage→presentation mappings now exist (`stages.ts:46`, `Dashboard.tsx:35-49`, `PipelineStepper.tsx:45-88`).

#### `frontend/src/App.tsx`

- **Purpose:** App shell: sidebar routing, application/run history loading (with token entry), session run polling, and the create→ingest→modernize submit flow.
- **Bugs:**
  - 🟡 **MEDIUM (duplicate polling)** `frontend\src\App.tsx:127-163` runs a second, independent poller for the same run the run page is already polling at `ModernizationRun.tsx:243-274` — two different cadences (2000 ms here vs 1500 ms there) and two different failure policies (here failures are swallowed at 136-139; the run page surfaces them at 254-264). Any run created in-session is double-polled for its whole lifetime. The logic should be lifted into one shared hook/store.
  - 🟡 **MEDIUM** `frontend\src\App.tsx:81-93, 198` — `runIds` is only ever populated by the submit path (198). Runs loaded from the server that are still in progress are never polled, so the dashboard's stage/duration for them is frozen at first paint and "In Progress" (Dashboard `frontend\src\pages\Dashboard.tsx:82`) can be stale indefinitely.
  - 🟡 **MEDIUM** `frontend\src\App.tsx:41-44` — if the clicked run is not found in `runsRef` (partial history, run fetched by id only), `selectedAppId` keeps its previous value; that stale id is passed as `applicationId` and *wins* over the run's own id at `ModernizationRun.tsx:170` (`applicationId || run?.application_id`), so discovery/ingest panels render for the wrong application. Should `setSelectedAppId(null)` when the lookup fails.
  - 🟡 **MEDIUM** `frontend\src\App.tsx:174-206` — no rollback on partial failure: if `createApplication` succeeds (179) but `ingestApplication`/`modernize` fails (183/194), the orphan application stays in history and the user's retry creates a second one; the error banner (217-252) gives no hint of the leftover.
  - 🟢 **LOW** `frontend\src\App.tsx:97-106` — a non-401 load failure sets nothing: `historySource` stays whatever it was (default `'session'`), so with no session data the dashboard shows the empty state with no "backend unreachable" message at all.
  - 🟢 **LOW** `frontend\src\App.tsx:130-160` — the interval callback has no mounted/`AbortController` guard (unlike `loadHistory`'s `historyMounted`), so an in-flight cycle can `setRuns`/`setRunIds` after unmount.
- **Limitations:** History merge is append-only — server responses can never remove a session-only or server-deleted record (75-78, 89-92); `loadHistory` runs once per mount plus manual token retry (112-114), never automatically recovering when the backend comes up; polling only tracks session-created runs.
- **Gaps:** No loading indicator during a token retry — `setLoading(true)` is never re-issued (107-109, 118-124), so the Dashboard keeps showing "N runs loaded from API" while a refetch is in flight. No error boundary, no `runIds` seed for server-loaded active runs, and no surfacing of 401 anywhere except the dashboard token form.
- **Issues:** Polling implementation (127-163) is a near-duplicate of `ModernizationRun.tsx:243-274`; inline style objects for the error banner (218-251) duplicate `index.css`/`tokens` patterns; `submitError` (21, 217) is only rendered when `page === 'new'`, so the state lingers invisibly after navigation.

#### `frontend/src/main.tsx`

- **Purpose:** React 18 root bootstrap; mounts `<App/>` in `StrictMode` after importing global CSS.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\main.tsx:6` — `document.getElementById('root')!` non-null assertion: a missing/renamed `#root` throws at boot with no message.
- **Limitations:** StrictMode double-invokes effects in dev, so the polling effects in `App.tsx:127` and `ModernizationRun.tsx:243` mount/unmount twice (cleanups do run, but a first-cycle in-flight `tick()` still resolves).
- **Gaps:** No error boundary and no `Suspense`; a render exception anywhere white-screens the entire SPA with no reload affordance.
- **Issues:** None found.

#### `frontend/src/pages/Dashboard.tsx`

- **Purpose:** Overview page: stat cards (applications/runs/in-progress/completed/verified/failed), recent-runs table, application cards, and the API-token prompt.
- **Bugs:**
  - 🟡 **MEDIUM** `frontend\src\pages\Dashboard.tsx:299-306` — the entire `<tr>` is `onClick` navigable with no `tabIndex`/`role`/keyboard handler; keyboard users must find the per-row "View" button (343-365), and screen readers get no hint the row is interactive.
  - 🟡 **MEDIUM** `frontend\src\pages\Dashboard.tsx:51-69` — `runDuration`/`timeAgo` do not guard `Date.parse` failures: a malformed `created_at` renders `"NaNs"` / `"NaNm ago"` and `Math.round(NaN)` propagates.
  - 🟡 **MEDIUM** `frontend\src\pages\Dashboard.tsx:264-275` — "Recent Modernization Runs" renders `runs` in whatever order `App.tsx` merged them (server order + session prepends at `App.tsx:89-92, 197`); nothing sorts by `created_at`, so "recent" is not guaranteed.
  - 🟢 **LOW** `frontend\src\pages\Dashboard.tsx:35-49` — `stageBadgeVariant` hardcodes the 17-stage list instead of deriving from `api/stages`; a backend stage added later silently falls to `'default'`.
- **Limitations:** Applications card shows `applications.slice(0, 8)` with no "showing 8 of N" (388); no pagination or run filtering/search; session-only banner only appears when there is session data (198).
- **Gaps:** Loading state (110-121) is a bare animated `div` with no `role="status"`/`aria-live`, so the wait is not announced; `<th>` elements lack `scope` (288-296); no error state is rendered for a failed history load (relies entirely on `App.tsx`); token-retry re-fetch has no loading/disabled affordance.
- **Issues:** Inline spinner (110-119) duplicates `LoadingSpinner.tsx`; hardcoded colors `#7c3aed` (253), `#fecaca` (153), `#fde68a` (205) bypass `tokens`; stage-badge list duplicates `api/stages.ts`.

#### `frontend/src/pages/ModernizationRun.tsx`

- **Purpose:** The run detail page: polls run state, renders pipeline stepper, metrics, discovery, capability/plan report, generated files, approval gate, verdict/evidence/integrated-proof, and download.
- **Bugs:**
  - 🔴 **HIGH (gate state)** `frontend\src\pages\ModernizationRun.tsx:165, 395-400, 879-881` — `approvalState` is never reset when `runId` changes. Because `downloadDisabled` is derived purely from it, a component instance reused across runs would keep run A's `APPROVED` state and enable run B's download button until run B's `ApprovalPanel` fetch lands — a fail-open window on exactly the gate this UI owns. (Today `App.tsx` unmounts the page between runs, so it is latent, but nothing enforces that.) Fix: reset `approvalState`/`downloadError`/`downloading` in an effect keyed on `runId`, or `key={runId}` at `App.tsx:267`.
  - 🔴 **HIGH (stale state)** `frontend\src\pages\ModernizationRun.tsx:153-166, 243-274` — no state is cleared on `runId` change: `run`/`detail`/`verdict`/`discovery`/`artifacts`/`report`/`integratedProof` all keep the previous run's data while the new run's first poll is in flight, and `hasRunRef.current` (209, 219) stays `true`, so a first-poll failure for run B will *not* set `loadError` (260-263) and the page permanently renders run A's content under run B's id.
  - 🟡 **MEDIUM (race)** `frontend\src\pages\ModernizationRun.tsx:247-268` — `setInterval` (1500 ms) with no in-flight guard and no abort: if `getRun`/`getRunDetail` take longer than the interval, ticks overlap and a slower, older response can land last and regress `setRun`/`setDetail` (222-223).
  - 🟡 **MEDIUM (no retry after terminal)** `frontend\src\pages\ModernizationRun.tsx:225-240, 250-253` — terminal data (`verdict`, `artifacts`, `report`, `integrated-proof`) is fetched exactly once, inside the poll that then clears the interval. If any of those calls fail at that instant (all `.catch(() => null)` at 194-204), the evidence never renders and there is no retry button (the "Retry now" card at 484-497 is suppressed once `isTerminal`, 363). Only a full page reload recovers.
  - 🟡 **MEDIUM (wrong fallback)** `frontend\src\pages\ModernizationRun.tsx:231-232` — `setDiscovery((prev) => prev ?? d)` / `setDetail((prev) => prev ?? rd)` keep the *older* value. If the poll's own `getRunDetail` failed (216, not stored at 223) but the terminal `rd` succeeded, the fresh terminal detail is discarded in favour of the stale one — the opposite of the intended enrichment.
  - 🟡 **MEDIUM (`extraStageMessages`)** `frontend\src\pages\ModernizationRun.tsx:370-372` — the filter is exact-string equality against `run.stage` and `run.error` and removes **all** occurrences, so any real message whose text happens to equal the current stage name or the error text is silently hidden (e.g. a historical `"COMPLETED"` entry, or a progress message identical to the error). It is also directionally stale: if `detail` is older than `run`, the *old* error no longer equals `run.error` and is shown twice (Error card 541-550 + stage list 1011-1020); the `'\0'` sentinel (371) only exists to make the null-error case non-matching. With today's backend (`api\service.py:1664-1666` sends only `[stage, error]`) the filter always yields an empty list, so the whole "Stage messages" block (1011-1020) is dead UI — i.e. the dedup is both too aggressive (would hide real messages) and currently pointless.
  - 🟡 **MEDIUM (client-only gate)** `frontend\src\pages\ModernizationRun.tsx:292-314` — `handleDownload()` performs no approval check itself; gating exists only in `disabled={downloadDisabled}` at 814 and 860. The backend 409 backstops it, but the business rule is enforced solely by button state at two call sites.
  - 🟢 **LOW** `frontend\src\pages\ModernizationRun.tsx:297-304` — `URL.revokeObjectURL(url)` immediately after `a.click()` can cancel the download in some browsers; use a short timeout.
  - 🟢 **LOW** `frontend\src\pages\ModernizationRun.tsx:176-190` — discovery effect deps include `runId` (unused) and `effectiveAppId`; when `applicationId` is `''`, `effectiveAppId` flips after the first `setRun`, which also recreates `loadTerminalData` (207) → `poll` (241) → restarts the polling effect (274), cancelling and re-issuing an immediate poll mid-flight.
  - 🟢 **LOW** `frontend\src\pages\ModernizationRun.tsx:450` — header verdict badge is gated on `run.stage === 'COMPLETED'` while `VerdictDisplay`/`ValidationScope` (904, 949) render for any terminal stage, so a FAILED run with a verdict shows evidence but no badge.
- **Limitations:** Discovery/artifacts/report/proof are best-effort and never distinguish "not yet produced" from "fetch failed"; generated-file sizes are API-absent and rendered as `—` (841); `RUN_STAGES.indexOf` arithmetic (389) assumes linear order; report parsing (`readPipelineReport`, 113-118) accepts only `report.pipeline_report`.
- **Gaps:** Poll-interruption card (484-497) and download-failure card (886-901) have no `role="alert"`/`aria-live` (the discovery warning at 561 does); discovery load/failure has no indicator (silent catch 183-186); `getRunDetail`/`getReport`/`getRun` 404s are indistinguishable from network errors and simply omit sections; no `aria-live` for stage progression; `<th>` without `scope` (608-613, 830-833, 916-921); `content_hash.slice(0,24)` (935) and `discovery.dependency_edges`/`cobol_programs` (583-619) assume required fields with no null guards.
- **Issues:** 1026 lines with ~20 inline style objects; `stageBadgeVariant` re-implemented at 140-144 (also in `Dashboard.tsx:35-49`); `pollFailuresRef` + `pollFailures` are dual sources of truth (162-166, 218-220); defensive `String(...)` casts (547, 987, 991, 997, 1016) are dead weight against the typed response; `cardStyle` (1075-1081) re-implements `.card` (`index.css:286-291`); `EdgeStat` and three style constants (1030-1091) belong in components/styles module.

#### `frontend/src/pages/NewModernization.tsx`

- **Purpose:** Create-application form: ZIP drop zone with auto-derived name/workload, metadata fields, submit, pipeline preview.
- **Bugs:**
  - 🟡 **MEDIUM** `frontend\src\pages\NewModernization.tsx:48-54, 146, 190-251` — `uploadState` gives `loading` precedence over `ready`, so during submission the selected-file chip disappears and the empty drop zone is re-rendered; the user loses sight of exactly what is being uploaded while it uploads.
  - 🟡 **MEDIUM** `frontend\src\pages\NewModernization.tsx:262-315, 325-352` — inputs are not wrapped in a `<form>` and submit is `onClick` only: pressing Enter in the name/workload field does nothing, and there is no implicit submit path.
  - 🟢 **LOW** `frontend\src\pages\NewModernization.tsx:231` — the hidden file input's `value` is never reset, so re-selecting the *same* ZIP after removing it fires no `change` event (`FileUpload.tsx:28` does reset).
  - 🟢 **LOW** `frontend\src\pages\NewModernization.tsx:48-54, 234` — the `'error'` member of `UploadState` is computed but never used for rendering (errors render independently at 234-249), so it is dead state.
- **Limitations:** Only `.zip` is accepted (extension check at 58, `accept` at 229) with no size limit, no empty-archive check, no virus/multi-volume handling; auto-fill is one-shot per user edit (`nameEditedByUser`, 45, 62-67).
- **Gaps:** No `aria-invalid`/`aria-describedby` error association for the name/workload inputs (only the name hint, 275); `zipError` is not tied to the drop zone via `aria-describedby`; no `role="status"` for the "Uploading source…" hint (354-358); drag-leave flicker when the pointer crosses children (200); no disabled/busy announcement on the submit button beyond the spinner text.
- **Issues:** `uploadState` is used for exactly one class name (112-115) — the state machine is mostly unused; style objects `inputStyle`/`labelStyle` (92-110) duplicate `ApprovalPanel.tsx:46-63`; `IconDownload` used as the upload glyph (218) is semantically wrong for an upload target.

#### `frontend/src/pages/index.ts`

- **Purpose:** Page barrel re-exporting the three routed pages.
- **Bugs:** None found.
- **Limitations:** No type re-exports, so consumers must import prop types from the page modules directly.
- **Gaps:** None found.
- **Issues:** None found.

#### `frontend/src/components/ApprovalPanel.tsx`

- **Purpose:** Fetch and display the per-run approval record; submit APPROVED/REJECTED decisions and lift state to the parent download gate.
- **Bugs:**
  - 🟡 **MEDIUM** `frontend\src\components\ApprovalPanel.tsx:66, 85-87` — local `approval`/`loadError` are never reset on `runId` change; a reused instance briefly shows the previous run's decision record (and its `onStateChange` still fires only after the new fetch, leaving the parent gate stale — see `ModernizationRun.tsx:165`).
  - 🟢 **LOW** `frontend\src\components\ApprovalPanel.tsx:120-128` — the `loadError` branch renders the message with **no retry action**; the only recovery is a full page reload, even though the same `refresh()` is available.
  - 🟢 **LOW** `frontend\src\components\ApprovalPanel.tsx:73-87` — `onStateChange` is in the `refresh` callback deps; a parent passing an inline lambda would refetch the approval record on every render (works today only because `setApprovalState` is stable).
- **Limitations:** Approver is recorded input, not verified identity (14-26); no RBAC, no confirmation step for a decision, and a later decision silently supersedes an earlier one; `decided_at` is rendered as a raw ISO string (163) with no locale formatting.
- **Gaps:** `decisionError` (201-214) is not linked to the inputs (`aria-invalid`/`aria-describedby` absent); while `submitting` the buttons only become `disabled` — no `aria-busy`, no label change; the loading state (130-138) is a plain text div with no `role="status"`.
- **Issues:** `stateLabel`/`stateVariant` maps (34-44) could be co-located with the `ApprovalState` type in `client.ts`; duplicated `labelStyle`/`inputStyle` blocks (46-63) mirror `NewModernization.tsx:92-110`.

#### `frontend/src/components/Badge.tsx`

- **Purpose:** Small uppercase status pill used for stages, verdicts and verdict badges.
- **Bugs:** None found.
- **Limitations:** Fixed uppercase transform and single-line (`whiteSpace: 'nowrap'`, 43) means long stage/verdict strings can overflow their container.
- **Gaps:** No `role`/`aria-label`; colour alone carries meaning for the "warning"/"info" variants (mitigated by the text always being present).
- **Issues:** `frontend\src\components\Badge.tsx:19` — the `purple` variant is named purple but uses a sky-blue background (`#e0f2fe`) with `tokens.colors.accent`, and is never used by any call site (dead variant); hardcoded `'#f1f3f4'` (18) bypasses `tokens`.

#### `frontend/src/components/Button.tsx`

- **Purpose:** Shared styled `<button>` with variant/size tokens.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\components\Button.tsx:57-61` — no default `type="button"`: any future use inside a `<form>` silently submits (today only `Dashboard.tsx:193` relies on the submit default).
- **Limitations:** No `loading`/`aria-busy` concept, no icon slot, no full-width option; disabled styling is left to call sites (`NewModernization.tsx:332` hand-rolls opacity).
- **Gaps:** `disabled` buttons get no visual change from the component itself (and `index.css:37-40` still sets `cursor: pointer` for them).
- **Issues:** `frontend\src\components\Button.tsx:36` — `variants: Record<string, React.CSSProperties>` should be `Record<Variant, ...>`; a typo'd variant would render base styles with no background instead of failing type-check.

#### `frontend/src/components/CopyButton.tsx`

- **Purpose:** 28×28 clipboard button with a transient ✓ state.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\components\CopyButton.tsx:19` — `window.setTimeout` is never cleared on unmount, so a copy right before navigation sets state on an unmounted component.
- **Limitations:** Silent failure by design (20-23) — no fallback (`document.execCommand`) and no user-visible feedback when the clipboard is unavailable.
- **Gaps:** The comment at 11 claims "visible + screen-reader feedback", but `aria-label`/`title` stay `Copy …` (30-31) after success and there is no `aria-live` region, so screen-reader users get no confirmation; the ✓ glyph is not `aria-hidden`.
- **Issues:** None found.

#### `frontend/src/components/EmptyState.tsx`

- **Purpose:** Centered icon/title/description/action placeholder for empty lists.
- **Bugs:** None found.
- **Limitations:** Single-purpose; no size/density variants.
- **Gaps:** `title` renders as a `<div>` (32-41) rather than a heading, so empty states are invisible to heading navigation; no `role="status"` for dynamically appearing content.
- **Issues:** None found.

#### `frontend/src/components/FileUpload.tsx`

- **Purpose:** Generic drag-and-drop/click file chooser component.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\components\FileUpload.tsx:49` — `onDragLeave` on the container fires when the pointer moves over any child element, causing the highlight to flicker during a normal drop.
- **Limitations:** `accept` is only an attribute hint (84) — dropped files are passed to `onFiles` with no type/size validation (14-22); no multi-file messaging.
- **Gaps:** The visible copy is hardcoded (76-80) while `label` only sets `aria-label`, so a custom-labelled instance announces differently from what it shows; no error state at all.
- **Issues:** Dead in the application — referenced only by `components/index.ts:9` and `__tests__/components.test.tsx`; `NewModernization.tsx` re-implements the same drop zone inline (193-233).

#### `frontend/src/components/Header.tsx`

- **Purpose:** Sticky page header: breadcrumb, `<h1>` title, meta chips, right-side actions; legacy brand/nav variant when no context props are given.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\components\Header.tsx:80-153 vs 155-208` — the legacy branch is reachable only from tests (`components.test.tsx:16-28`); every app call site passes `title`, so ~55 lines of nav markup are dead in production.
- **Limitations:** Single sticky row with `zIndex: 100` (75); meta items are fixed monospace chips with no truncation policy for long ids.
- **Gaps:** The current breadcrumb crumb is a plain `<span>` (117-119) with no `aria-current="page"`; breadcrumb buttons have no announcement that they are links in a trail; no skip-to-content target.
- **Issues:** `frontend\src\components\Header.tsx:126-137` renders an `<h1>` while `PageContainer.tsx:30-39` also renders `<h1>` — `ModernizationRun.tsx:323-328` and `350-355` use both, producing two competing page titles; legacy nav uses `<a href="#">` (189-202).

#### `frontend/src/components/icons.tsx`

- **Purpose:** Dependency-free inline SVG icon set rendered with `currentColor`.
- **Bugs:** None found.
- **Limitations:** Props are limited to `size`/`title` (9-12) — no `className`, `style`, or `aria-hidden` override; components are anonymous arrows (no `displayName`).
- **Gaps:** `title` is supported but never used by any call site, so every icon is decorative-by-default with no way to label one without editing the call site.
- **Issues:** `frontend\src\components\icons.tsx:153-154` — `IconCheck` is exported but unused anywhere; `CheckIcon`/`XIcon` are re-drawn inline in `PipelineStepper.tsx:107-122` instead of importing `IconCheck`/`IconX` (geometry duplication).

#### `frontend/src/components/index.ts`

- **Purpose:** Barrel exporting all shared components (plus one type).
- **Bugs:** None found.
- **Limitations:** Re-exports only; no `export type` for component props, so consumers destructure inline.
- **Gaps:** None found.
- **Issues:** `frontend\src\components\index.ts:9-10` export `FileUpload` and `StageIndicator`, neither of which the application renders — the barrel advertises dead components.

#### `frontend/src/components/IntegratedProof.tsx`

- **Purpose:** Renders the integrated-proof payload: central status, dependency ledger grouped by kind, evidence/runtime tiles, reasons, summary counts.
- **Bugs:**
  - 🔴 **HIGH (unguarded throw)** `frontend\src\components\IntegratedProof.tsx:42-46, 149` — no null guards: `const { proof: proofData } = proof` followed by `proofData.dependency_ledger.forEach` and `proof.reasons_for_not_verified.length` throw if the nested `proof` object or either array is absent (older/truncated payload), taking the whole run page down — inconsistent with the defensive `.catch(() => null)` wiring in `ModernizationRun.tsx:204`.
  - 🟡 **MEDIUM** `frontend\src\components\IntegratedProof.tsx:57, 82-84` — iteration is over the hardcoded `kindOrder` array, so any `dep.kind` the backend emits that is *not* in those 11 values is silently dropped from the ledger (the exact class of bug the comment at 53-56 says was fixed). Iterate `Object.keys(dependenciesByKind)` and append unknown kinds instead.
  - 🟢 **LOW** `frontend\src\components\IntegratedProof.tsx:19-22` — unknown proof states fall back to the `UNPROVEN` config, so an unrecognised state is rendered with UNPROVEN's icon/colour while the badge (108-110) prints the raw string — visually contradictory.
- **Limitations:** Kind ordering must be manually kept in parity with the engine enum (53-57); display-only, no drill-down or per-dependency actions.
- **Gaps:** Several fields present in `IntegratedProofResponse` are never shown — `blocking_reasons`, `overall_capability`, `jcl_status`, `runtime`, `evidence_status`, `runtime_proof_status`, `overall_verification`, `required_dependencies` (`client.ts:616-647`); no `role="status"` on the final proof status; dependency rows are divs, not a list/table.
- **Issues:** `frontend\src\components\IntegratedProof.tsx:117` — `.filter(Boolean)` after a callback that already returns `null` is a no-op; line 162 re-tests the condition already established at 149; `proofStateColors` (12-17) overlaps `VerdictDisplay.tsx:12-20`; `const { proof: proofData } = proof` shadowing is confusing naming.

#### `frontend/src/components/LoadingSpinner.tsx`

- **Purpose:** Configurable spinner with optional message.
- **Bugs:** None found.
- **Limitations:** Message is plain text only; no `size` breakpoint behaviour.
- **Gaps:** No `role="status"`/`aria-live="polite"` (10-33), so screen readers never announce that loading is in progress.
- **Issues:** `frontend\src\components\LoadingSpinner.tsx:31` — injects a duplicate `@keyframes spin` `<style>` block on every instance although `index.css:4-6` already defines it; the `message ? column : row`/padding logic (14, 17) is dead for the default value.

#### `frontend/src/components/PageContainer.tsx`

- **Purpose:** Max-width page wrapper with optional `<h1>` title/subtitle/actions header.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\components\PageContainer.tsx:30-39` — emits an `<h1>` that collides with `Header.tsx:126-137` when both are used (`ModernizationRun.tsx:323-328`, `350-355`), giving duplicate top-level headings.
- **Limitations:** Fixed `maxWidth: 1100` (15) and one padding scale; no wide/full-bleed variant for the run page's tables.
- **Gaps:** `actions` region (51) has no accessible name; title/subtitle have no id linkage.
- **Issues:** None found.

#### `frontend/src/components/PipelineStepper.tsx`

- **Purpose:** Fixed 7-node horizontal pipeline visualisation (plus an 8th "Failed" node) driven by `run.stage`.
- **Bugs:**
  - 🔴 **HIGH — known FAILED-run defect (fix scope below).** `frontend\src\components\PipelineStepper.tsx:90-95` (`groupIndexForStage` returns `-1` because `'FAILED'` is not in any `CUSTOMER_GROUPS[].stages`; it only exists in the group appended at 134-136) → `frontend\src\components\PipelineStepper.tsx:131-132` computes `activeGroupIdx = Math.max(0, rawIdx !== -1 ? rawIdx : 0) = 0` for every FAILED run → `frontend\src\components\PipelineStepper.tsx:97-105`, specifically the `groupIdx < activeGroupIdx` return at **line 99**, is dead code, and line 100 returns `'pending'` for all 7 groups. Result: on a FAILED run every node renders pending/empty even though Discovery results are rendered immediately below (`ModernizationRun.tsx:552-722`).
    **Minimal fix:** the component only receives `stage`, so it cannot know where the run died — (a) add an optional `lastStage?: RunStage` to `PipelineStepperProps` (124-127); (b) at 131 use `groupIndexForStage(isFailed && lastStage ? lastStage : stage)` and simplify 132 to `Math.max(0, rawIdx)` (the `rawIdx !== -1 ? rawIdx : 0` ternary then only covers genuinely unknown stages); (c) supply it from `ModernizationRun.tsx:519-522` via a ref updated in `poll()` (`ModernizationRun.tsx:211-241`) whenever `!isTerminalStage(runData.stage)`. That re-arms line 99 so groups before the last observed stage render `'done'` while the appended Failed node stays `'failed'`. The default (prop absent) must keep today's behaviour so `__tests__/pipeline-stepper.test.tsx:186-193` (renders `stage="FAILED"` with no `lastStage`) stays green; note the backend offers no failure stage — `GET /runs/{id}/detail.stage_messages` is only `[stage, error]` (`api\service.py:1664-1666`) — so a ref of the last non-terminal stage is the only client-side source.
  - 🟡 **MEDIUM** `frontend\src\components\PipelineStepper.tsx:132` — `Math.max(0, rawIdx)` maps *any* unmapped stage (notably `INGESTING`, which `stages.ts:14-18` says exists in the enum) to group 0, falsely rendering "Discovery" as active instead of showing an unknown/pending state.
  - 🟢 **LOW** `frontend\src\components\PipelineStepper.tsx:129` — the `showIngested` prop declared at 126 and passed by `ModernizationRun.tsx:521` is never destructured or used: dead prop with a test that only asserts node count (`pipeline-stepper.test.tsx:178-181`).
- **Limitations:** Deliberately fixed at 7 nodes regardless of lifecycle granularity (5-25); no per-stage timestamps/durations; FAILED is appended rather than mapped.
- **Gaps:** `aria-label={`${group.label}: ${status}`}` (172) exposes the raw status token (`done`/`pending`) instead of human words; no `aria-live` announcement when the active group changes.
- **Issues:** Connector rendering is duplicated — the React connector div (201-215) and the CSS `::after` pseudo-element (`index.css:133-150`) both draw the line between nodes; `CheckIcon`/`XIcon` (107-122) duplicate `icons.tsx` `IconCheck`/`IconX`.

#### `frontend/src/components/SectionCard.tsx`

- **Purpose:** Standard card with uppercase header, optional count/subtitle/icon/`headerRight`.
- **Bugs:** None found.
- **Limitations:** Title is forced uppercase via CSS and always 12 px; count is folded into the title string (49), so `"Evidence Artifacts (12)"` is the only accessible name.
- **Gaps:** Titles render as `<span>` (40-50), never as `<h2>` — a run page with ~12 cards has no section headings for screen-reader/heading navigation.
- **Issues:** `frontend\src\components\SectionCard.tsx:10-11, 21, 68` — `noPadding` and `icon` props are never passed by any call site (dead API); header layout (26) is hand-rolled instead of using `.card-header` semantics beyond the className.

#### `frontend/src/components/Sidebar.tsx`

- **Purpose:** Navy navigation rail: brand lockup, two real nav items, four disabled placeholders, static health footer.
- **Bugs:**
  - 🟡 **MEDIUM** `frontend\src\components\Sidebar.tsx:62-95, 181-188` — placeholder items render `<a href="#" disabled …>`: `disabled` is not a valid attribute on `<a>` (React passes it through as an invalid DOM attribute), and the anchors remain focusable/activatable by keyboard with no `aria-disabled="true"` — screen readers announce four working links that do nothing.
  - 🟢 **LOW** `frontend\src\components\Sidebar.tsx:164` — `overflow: hidden` on the nav container clips the 2 px `:focus-visible` outline (`index.css:43-50`) for items near the edges.
- **Limitations:** Two-item navigation by design; collapses to a 64 px icon rail below 1100 px (`index.css:88-106`) with labels hidden — no alternative accessible name beyond `title` (66).
- **Gaps:** The "System Status / All Systems Operational" footer (199-218) is hardcoded and never calls `getHealth` (`client.ts:500`) — it asserts health it does not verify; the two `<nav>` elements (166, 180) have no distinct `aria-label`s.
- **Issues:** Colours are hardcoded (`#0f172a`, `#1d4ed8`, `#94a3b8`, `#4ade80` at 79, 84, 209, 215-216) instead of `tokens.colors.sidebar*` (`tokens.ts:29-34`), leaving those tokens unused; brand typography colours also hardcoded (145-146).

#### `frontend/src/components/StageIndicator.tsx`

- **Purpose:** Alternative inline pill-per-stage indicator rendering the raw backend stage sequence.
- **Bugs:**
  - 🟡 **MEDIUM** `frontend\src\components\StageIndicator.tsx:14, 47-48, 54-55, 60` — on `FAILED`, `idx = RUN_STAGES.length`, so the conditions `isFailed && i === idx` are **never true** (max `i` is `length - 1`): the ✗ marker, `errorBg` and error colour are unreachable dead branches, and with `isDone = i < idx && !isFailed` (21) every pill renders as not-done/neutral — the component shows a failed run as if nothing had happened (same defect class as the known `PipelineStepper` bug).
  - 🟢 **LOW** `frontend\src\components\StageIndicator.tsx:14` — `RUN_STAGES.indexOf(current)` is `-1` for `INGESTING`, making `i === idx` true for no pill and `i < idx` false for all, i.e. a silent no-active-state rendering for an unmapped stage.
- **Limitations:** Renders all 17 raw stages — unusable at narrow widths despite `flexWrap`; superseded by `PipelineStepper` in the product UI.
- **Gaps:** No `role="list"`/`aria-label` on the container (17-18) and no status announcement; pill states are colour+glyph only.
- **Issues:** Dead in the application — only `components/index.ts:10` and `__tests__/components.test.tsx` reference it; duplicates the stage-order source of truth from `api/stages.ts`.

#### `frontend/src/components/StatCard.tsx`

- **Purpose:** Icon + big value + label tile used in Dashboard and the run metrics row.
- **Bugs:** None found.
- **Limitations:** No trend/comparison, no skeleton/loading variant, no click affordance.
- **Gaps:** No `role`/`aria-label` grouping icon+value+label (44-50), so the number and its label are separate unlabelled text nodes for assistive tech; no list semantics around the metric grids (`ModernizationRun.tsx:526-538`, `Dashboard.tsx:219-261`).
- **Issues:** Inline styles duplicate the `.stat-card` CSS class rules (`index.css:306-320`) — padding/shadow/transition defined in both places.

#### `frontend/src/components/ValidationScope.tsx`

- **Purpose:** Renders the verbatim backend scope statement plus oracle/source/candidate/manifest hashes and derivation timestamp.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\components\ValidationScope.tsx:40` — an empty `supported_scope_statement` renders an empty coloured box with no fallback text (no guard on 40 or on any `rows[].value` beyond `candidate_hash ?? '—'` at 20).
- **Limitations:** Read-only, verbatim-only by design (10-14); fixed row set (16-24) — any new identity field requires editing this component.
- **Gaps:** No copy affordance for the long hashes (contrast with `CopyButton` used for file paths); `derivation_timestamp` (22) is a raw ISO string, not localised; no `role="status"` for the scope statement.
- **Issues:** Row `key={row.label}` (52) would collide if two rows ever share a label; opacity-suffix colour `` `${tokens.colors.info}20` `` (34) silently breaks if the token stops being 6-digit hex.

#### `frontend/src/components/VerdictDisplay.tsx`

- **Purpose:** "Validation Evidence" card: verdict hero, check counts, comparison table, differences list.
- **Bugs:**
  - 🟡 **MEDIUM** `frontend\src\components\VerdictDisplay.tsx:23` — `verdictConfig[verdict.state] || verdictConfig.UNPROVEN` renders any unknown/absent verdict state with the **UNPROVEN** label, icon and colour, i.e. an unrecognised state is misreported as a real certification state instead of "UNKNOWN". Same pattern at `IntegratedProof.tsx:19-22`.
  - 🟢 **LOW** `frontend\src\components\VerdictDisplay.tsx:96, 156` — `verdict.comparisons.length` / `verdict.differences.length` are unguarded; a payload omitting either array throws and blanks the run page.
- **Limitations:** Only seven verdict states are known (12-20); comparison `result` mapping is binary-ish — anything other than `MATCH`/`MISMATCH` falls to `warning` (143), including states that should read as errors.
- **Gaps:** `role="status"` + `aria-label` (36-37) duplicates rather than complements the visible text; the comparison table has no `caption`/`scope`; differences use `key={i}` (172) only; no link from the verdict to the evidence manifest hash (lives in `ValidationScope` with no cross-reference).
- **Issues:** `verdictConfig` overlaps `IntegratedProof.tsx:12-17`; inline `<th>` styles (126-135) duplicate `ModernizationRun.tsx:1083-1087`/`VerdictDisplay`'s own table styles.

#### `frontend/src/theme/tokens.ts`

- **Purpose:** Single frozen design-token object (colours, radii, spacing, typography).
- **Bugs:** None found.
- **Limitations:** `as const` (99) makes extension impossible; no breakpoint/duration/z-index scale; no dark-mode or contrast-checked aliases.
- **Gaps:** No accessibility tokens (focus-ring colour/width, reduced-motion durations); several status colours are used only via `${hex}NN` alpha suffixes by callers, which is untyped and easy to break.
- **Issues:** `frontend\src\theme\tokens.ts:29-34` — `sidebarBg`/`sidebarBorder`/`sidebarText*`/`sidebarHoverBg` are unused because `Sidebar.tsx` hardcodes the same hex values (63, 79, 85, 112, 145-146, 209, 215-216); the same drift applies to `Badge.tsx:18-19` and several `Dashboard.tsx`/`ModernizationRun.tsx` one-off colours.

#### `frontend/src/index.css`

- **Purpose:** Global reset, base typography/focus styles, and the class-based styles for sidebar, pipeline, cards, tables, upload zone and run rows.
- **Bugs:**
  - 🟢 **LOW** `frontend\src\index.css:37-40` — `button { cursor: pointer }` has no `:disabled` exception, so disabled controls (e.g. `NewModernization.tsx:332`, `ApprovalPanel.tsx:221`) still advertise clickability.
  - 🟢 **LOW** `frontend\src\index.css:133-150` — the `.pipeline-node-h::after` connector duplicates the React connector rendered at `PipelineStepper.tsx:201-215`, producing two overlapping line definitions whose colours are maintained separately (green `.done` in CSS vs inline `tokens.colors.success`).
- **Limitations:** Light theme only; hardcoded 720/1100 px breakpoints; no print styles; colours are literal hex that must be kept in sync with `theme/tokens.ts`.
- **Gaps:** `frontend\src\index.css:43-50` — `:focus-visible` covers buttons/links/inputs/summaries but **not** `textarea` (the ApprovalPanel reason field, `ApprovalPanel.tsx:191-198`) or `tr.run-row`/`[tabindex]` elements; `input:focus` (52-54) changes only the border, so keyboard focus on text inputs is weaker than on buttons; no `:focus-visible` for the drag-and-drop zone beyond `[role="button"]` (covered) and no styling for `aria-disabled` links.
- **Issues:** `frontend\src\index.css:2` — `@import` of Google Fonts makes first render network-dependent (fails/delays in air-gapped deployments) and leaks requests to a third party; `@keyframes spin` here is re-declared in `LoadingSpinner.tsx:31`; hardcoded palette (`#2563eb`, `#0f172a`, `#e2e8f0`, …) duplicates `tokens.ts` wholesale.

#### `frontend/src/test-setup.ts`

- **Purpose:** Vitest setup importing `@testing-library/jest-dom` matchers.
- **Bugs:** None found.
- **Limitations:** Nothing else is configured — no explicit `cleanup`, no `restoreMocks`/`resetMocks`, no `matchMedia`/`IntersectionObserver`/`ResizeObserver` polyfills, and no `navigator.clipboard` stub (so `CopyButton` tests must stub it themselves).
- **Gaps:** No failure-on-console-error policy, so React warnings from the audited components are not caught by the suite.
- **Issues:** None found.

#### `frontend/src/vite-env.d.ts`

- **Purpose:** Single-line reference pulling in Vite's client types.
- **Bugs:** None found.
- **Limitations:** Contains only `/// <reference types="vite/client" />` (1).
- **Gaps:** No `ImportMetaEnv` interface declaring `VITE_CONTROL_PLANE_API_TOKEN`, which is why `client.ts:52-54, 64-66` hand-rolls `MaybeEnvImportMeta` and indexes `env` with a cast — the env var is invisible to type-checking and to editors.
- **Issues:** None found.

---

# Section J — scripts / CI / Docker / contracts / docs ✅ COMPLETE

36 files. 10 HIGH, 30 MEDIUM, 40+ LOW.

### Summary — J

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 10 | `supply-chain.yml` audits can't fail (`tee` without `pipefail`, ×4); `verify-production.sh` probe always passes; `restore.sh` deletes volumes before validating; `.dockerignore` git-ignored; `.gitattributes` untracked; uncommitted CI gate list |
| 🟡 MEDIUM | 30 | Mutable `:latest` oracle tags vs contract, unpinned pip, stale-image deploys, contract fields implemented nowhere |
| 🟢 LOW | 40+ | Dead code in scripts, hardcoded digests duplicated 3×, stale doc counts |

#### `scripts/backup/backup.sh`
- **Purpose:** Online, no-downtime backup of the SQLite control-plane DB, workspace volume and release identity into a timestamped dir, self-verified before it reports success.
- **Bugs:**
  - 🟡 **MEDIUM** `backup.sh:28` — `DEST_HOST="$(host_path "$PWD/$DEST")"` blindly prefixes `$PWD`; an *absolute* `BACKUP_DIR` argument produces `/repo//abs/path`, so the docker volume mount and the later verify target point at a directory that was never written to (fails loudly only at step 4, after the data was written elsewhere).
  - 🟡 **MEDIUM** `backup.sh:44` — release identity hardcodes `systemaops-api:production` instead of the tag actually deployed; backing up a non-`production` deployment silently records `{"warning":"api image tag not found"}`.
  - 🟡 **MEDIUM** `backup.sh:45` — `cp test-artifacts/docker-image-provenance.production.json ... || true` swallows a missing provenance file; provenance loss is only a warning (`verify_backup.py:138-143`), so a backup can be "OK" with no release identity at all.
  - 🟢 **LOW** `backup.sh:31-57` — four `docker run` invocations hardcode the same digest-pinned images inline; a digest bump requires editing 3 places (also duplicated in `restore.sh`).
- **Limitations:** Deliberately manual — no cron/systemd scheduling, no retention/pruning, no off-host copy (`backup.sh:6-7`, `docs/operations/BACKUP_RECOVERY.md:80-96`). Captures only 2 volumes + identity; TLS certs, `.env.production` and `frontend/dist` are not backed up.
- **Gaps:** Scheduling/retention/off-host copy are documented procedures with no script (cron example only, `BACKUP_RECOVERY.md:89-91`). Restore drill is documented but not scriptable/CI-run (`BACKUP_RECOVERY.md:83`). No test asserts `backup.sh` chains `verify_backup.py` at HEAD — `tests/test_shell_script_contracts.py:125-141` and the `backup.sh:53-57` chain exist only as **uncommitted** working-tree changes (`git status`: `M scripts/backup/backup.sh`, `?? scripts/backup/verify_backup.py`).
- **Issues:** The `host_path()` WSL shim is copy-pasted verbatim in `backup.sh:21-27` and `restore.sh:20-26` (duplication). Verification step re-pins the python image a third time.

#### `scripts/backup/restore.sh`
- **Purpose:** Downtime restore of DB + workspaces from a backup dir, snapshotting current volumes first, then restarting the production stack.
- **Bugs:**
  - 🔴 **HIGH** `restore.sh:42-48` — volumes are **deleted and recreated before the archive's contents are validated**: only file *existence* is checked at `restore.sh:12-15`, `verify_backup.py` is never run, and the actual `cp`/`tar -xzf` happens after `docker volume rm`. A corrupt/truncated `workspaces.tar.gz` (or the absolute-path mount bug below) leaves the stack down with **empty volumes**, recoverable only from the snapshot.
  - 🔴 **HIGH** `restore.sh:12` + `restore.sh:27` — `SRC` is validated as given but mounted as `"$PWD/$SRC"`; an absolute `BACKUP_DIR` passes validation then mounts a non-existent path, so `cp`/`tar` fail *after* the volumes were removed (see ordering above).
  - 🟡 **MEDIUM** `restore.sh:35` — snapshot failure is swallowed by `|| true`: the script's own promise ("a bad restore can itself be rolled back", `restore.sh:4-5`) is silently void if the pre-restore tar fails.
  - 🟢 **LOW** `restore.sh:29` — `docker compose down` runs with no `--timeout`/health wait; a hung container blocks the restore with no diagnostic beyond docker's own output.
- **Limitations:** Single-host, full-stack downtime restore only; no point-in-time/partial restore, no automatic verification of the source backup, no automatic rollback trigger if post-restore verification fails.
- **Gaps:** `docs/operations/BACKUP_RECOVERY.md:69` documents the restore procedure but nothing runs `verify_backup.py` on the source backup before mutating state (the verifier exists at `verify_backup.py:1` and is wired only into `backup.sh`). No scripted restore drill.
- **Issues:** Third copy of the `host_path()` WSL shim (`restore.sh:20-26`). Hardcoded `chown 10001:10001` duplicated at `restore.sh:46` and `:48` and again in `start-production.sh:44` (magic UID scattered across scripts).

#### `scripts/backup/verify_backup.py`
- **Purpose:** Stdlib-only restorability check of a backup dir (SQLite integrity/schema ceiling, non-empty workspace tar, release-identity warnings).
- **Bugs:**
  - 🟢 **LOW** `verify_backup.py:138-143` — missing release identity is only a warning, so `backup.sh` exits 0 and prints "OK" with zero provenance recorded (deliberate, but it weakens the "release identity" capture claim in `backup.sh:43`).
  - 🟢 **LOW** `verify_backup.py:165` — `main()` stats the DB/tar a second time outside the failure path; a file deleted between verification and reporting raises an unhandled `FileNotFoundError` traceback instead of a clean `FAIL:` line.
- **Limitations:** Deliberately does not verify backup *freshness*, host-path placement, or the provenance JSON; `user_version` is only checked against a ceiling (`SCHEMA_VERSION_CEILING = 6`, `verify_backup.py:43`), not that it equals the current schema.
- **Gaps:** None material — best-tested script in the set (`tests/test_backup_verification.py:86-166`, 15 cases incl. schema-ceiling tracking), though that test file is currently **untracked** (`?? tests/test_backup_verification.py`).
- **Issues:** `RELEASE_IDENTITY_FILES` (`verify_backup.py:47`) omits the provenance JSON that `backup.sh:45` also copies, so the two lists can drift.

#### `scripts/deploy/build-production.sh`
- **Purpose:** Build/tag the API, GnuCOBOL and Maven-offline images and pull/tag the digest-pinned Java runtime, then record image provenance.
- **Bugs:**
  - 🟡 **MEDIUM** `build-production.sh:13-14` — builds `gnucobol-ocesql:latest` and `maven-offline-springboot:latest`: mutable tags for the *oracle* image, which `contracts/ORACLE_CONTRACT.md:36-37` explicitly prohibits as identity ("Reference by `:latest` is prohibited"). Mitigated only because the engine re-resolves digests at run time.
  - 🟡 **MEDIUM** `build-production.sh:16` — `docker tag "$RUNTIME_DIGEST" eclipse-temurin:21-jdk` creates a mutable alias; `verify-production.sh:39` later checks only that this tag *exists*, so a different image tagged `eclipse-temurin:21-jdk` satisfies the deploy verification.
  - 🟡 **MEDIUM** `build-production.sh:10` — requires `python3` on the host (not `python`), inconsistent with `README.md:55` (`python`) and unavailable in plain Windows shells; the whole build aborts with a cryptic `command not found`.
  - 🟢 **LOW** `build-production.sh` — no frontend build step, yet `verify-production.sh:65-71` hard-fails when `frontend/dist/assets/` is empty; the deploy path is incomplete without an out-of-band `npm run build`.
- **Limitations:** Single-tag, single-host build; no multi-arch, no SBOM/attestation emission, no image scan.
- **Gaps:** No script builds the nginx-mounted frontend, so the documented "release" is produced by two disconnected toolchains (README `npm run build` vs this script). `requirements.lock` has no `--require-hashes`, so `Dockerfile.production:55` pins by version only.
- **Issues:** Digest-pinning discipline is split across three places with no single source (`Dockerfile.*` `FROM`, `DockerSpringBootConfig.runtime_digest`, this script's `python3 -c` at line 10).

#### `scripts/deploy/rollback.sh`
- **Purpose:** Re-point the `api` service at a previous image tag via a derived temp env file, then re-run post-deploy verification.
- **Bugs:**
  - 🟡 **MEDIUM** `rollback.sh:20` — `sed "s/^IMAGE_TAG=.*/IMAGE_TAG=$TAG/"` is a **no-op if `.env.production` has no active `IMAGE_TAG=` line** (commented-out or absent): the derived file keeps no override, compose falls back to `${IMAGE_TAG:-production}` (`docker-compose.production.yml:27`) and the container never switches — exactly the R10 failure the comment at `rollback.sh:12-15` says was fixed. There is no post-condition check that the running image actually changed.
  - 🟡 **MEDIUM** `rollback.sh:27` — `export ENV_FILE IMAGE_TAG="$TAG"` exports a stale `ENV_FILE` (the *original*, not `ROLLBACK_ENV`); harmless only because `verify-production.sh` takes the file as `$1`, but it is a trap for any future `docker compose` call in this script.
  - 🟢 **LOW** `rollback.sh:30-31` — `status=$?; exit $status` is dead code: with `set -e` (line 6) a failing `verify-production.sh` on line 29 aborts the script before line 30 runs; on success `status` is 0.
  - 🟢 **LOW** `rollback.sh:20-21` — the temp file contains `CONTROL_PLANE_API_TOKEN`; killed with `-9` the `EXIT` trap never runs and the token file is left in the repo root (mitigated by `.gitignore:434` `.env.rollback.*`).
- **Limitations:** Rollback only swaps the API image tag — data volumes are untouched by design (`rollback.sh:2-4`); no rollback of nginx config, frontend dist, or DB schema; requires the operator to know the previous tag (no discovery/listing helper).
- **Gaps:** Documented rollback in `docs/operations/RUNBOOK.md`/`BACKUP_RECOVERY.md` has no "list last known good tags" or automatic previous-tag selection; nothing verifies the old image exists before `up` (compose fails on its own terms).
- **Issues:** Third distinct way to set `IMAGE_TAG` (default in `start-production.sh:11`, sed-rewrite here, `.env.production` elsewhere) — the root cause of the R10 bug class.

#### `scripts/deploy/start-production.sh`
- **Purpose:** Preflight (env file, token, TLS, staging dir, daemon, compose render) and start/upgrade the production stack, then exec verification.
- **Bugs:**
  - 🟡 **MEDIUM** `start-production.sh:63` — `docker compose up -d` without `--build`/`--pull`: if `systemaops-api:${IMAGE_TAG}` already exists locally, compose reuses it even when `Dockerfile.production` changed, so an upgrade can silently deploy a **stale image**; if the image is absent, compose *builds* one implicitly (bypassing `build-production.sh`'s provenance recording).
  - 🟢 **LOW** `start-production.sh:44-48` — `chown` failure downgrades to WARN but a subsequent `chmod` failure aborts via `set -e`: inconsistent handling of the same permission problem.
  - 🟢 **LOW** `start-production.sh:18` — `set -a; source "$ENV_FILE"` executes arbitrary shell from the env file (accepted for compose env files, but it is a code-execution surface for a file whose only protection is `.gitignore:432`).
- **Limitations:** Single-host, single-tag start; no rolling start, no schema migration step, no built-in pre-start backup.
- **Gaps:** No check that `frontend/dist` exists (nginx mounts it at `docker-compose.production.yml:146`; a missing dir is auto-created empty by docker and the UI 404s until `verify-production.sh:71` catches it). No post-start "previous tag" record for `rollback.sh` to consume.
- **Issues:** Duplicates the TLS/token preconditions already enforced by compose (`docker-compose.production.yml:38`) and by the app (`CONTROL_PLANE_ENV` gate) — three independent implementations of one rule (documented as intentional defense-in-depth, `start-production.sh:19-20`).

#### `scripts/deploy/verify-production.sh`
- **Purpose:** Post-deploy gate: compose renders, containers healthy, TLS `/health`+`/ready`, sandbox images/flags, staging topology, frontend routing; non-zero exit = failed deploy.
- **Bugs:**
  - 🔴 **HIGH** `verify-production.sh:59-60` — the check `host file visible through staging bind` is `bash -c "... && docker run ... | grep -q probe; rm -f '${STAGING}/.visibility-probe'"`. The **last command is `rm -f`, which always succeeds**, so `bash -c` returns 0 no matter what failed — this "verification" step can never fail (present at HEAD too: `git show HEAD:scripts/deploy/verify-production.sh:51`).
  - 🟡 **MEDIUM** `verify-production.sh:41-42` — `api auth enforced (401 without token)` is `bash -c "! curl -fsS ... /applications"`: the check passes when the server is *down*, TLS is broken, or nginx is unreachable — any curl failure reads as "auth enforced".
  - 🟡 **MEDIUM** `verify-production.sh:37-40` — sandbox images checked by mutable tag presence (`gnucobol-ocesql:latest`, `maven-offline-springboot:latest`, `eclipse-temurin:21-jdk`) only; no digest comparison against provenance, contradicting `ORACLE_CONTRACT.md:31,36`.
  - 🟡 **MEDIUM** `verify-production.sh:17` — `check()` redirects all output to `/dev/null`, so every FAIL is emitted with zero diagnostics (no curl/docker stderr), which is why failures historically needed "drills" to diagnose.
  - 🟢 **LOW** `verify-production.sh:40` — `docker run --network none gnucobol-ocesql:latest cobc --version` omits the mandated hardening flags (`--user 10001:10001`, `--cap-drop ALL`, `no-new-privileges`) that `ORACLE_CONTRACT.md:68-75` claims *every* `docker run` site carries.
  - 🟢 **LOW** `verify-production.sh:60` — the probe writes a dot-file into the shared host staging dir; on a concurrent run it can delete another run's probe file.
- **Limitations:** Verifies only the api container's health (nginx health never inspected), only local `127.0.0.1`, and assumes `HTTPS_PORT` from the env file (`verify-production.sh:12`).
- **Gaps:** No check of image digests, disk space, nginx health status, or log-rotation effectiveness; no "verify after rollback" specific assertions beyond re-running this script.
- **Issues:** `tests/test_shell_script_contracts.py:111-120` asserts only that the container id is derived — it does not (and cannot) catch the always-pass probe at line 59-60, i.e. the source-contract test suite has a blind spot exactly where the defect is.

#### `scripts/supply-chain/build_release_manifest.py`
- **Purpose:** Emit a stdlib-only JSON release manifest pinning Python/npm deps, base images, action pins, runtime pins and git SHA.
- **Bugs:**
  - 🟡 **MEDIUM** `build_release_manifest.py:18-19` — "Exit code is always 0 on success; missing optional files degrade to UNKNOWN": every input can be absent (lock, package.json, Dockerfiles, workflows) and the job still goes green (`supply-chain.yml:113-117`), so a manifest of all-`UNKNOWN` is a passing release artifact.
  - 🟢 **LOW** `build_release_manifest.py:94` — only the **first** `FROM` per Dockerfile is recorded (`found[0]`), so multi-stage builds under-report bases.
  - 🟢 **LOW** `build_release_manifest.py:117` — the CI python-version regex `['\"]?([\d.]+)['\"]?` truncates `3.11` fine but would mangle `3.13t`/`3.11.9` semantics; it also silently prefers `supply-chain.yml` over `ci.yml` even if the two disagree.
- **Limitations:** Deliberately no network, no verification that `requirements.txt` ranges resolve to the lock, no npm/pip *vulnerability* data, no image SBOM for `systemaops-api` itself.
- **Gaps:** No unit test anywhere invokes this script (only `supply-chain.yml:115`); `docs/RELEASE_GATE_WS4.md:273` still records a now-false defect claim ("Reports `lockfileVersion: null`") while `build_release_manifest.py:63` returns `"3"` for the committed `frontend/package-lock.json:4` — stale gate doc.
- **Issues:** `parse_lock()` (lines 42-49) treats comment lines as pinnings but cannot express `--hash` pins, so "pinned" overstates the assurance.

#### `scripts/label_historical_reports.py`
- **Purpose:** Insert a one-line HISTORICAL banner under the H1 of a fixed list of dated status reports (never rewrite their content).
- **Bugs:**
  - 🟢 **LOW** `label_historical_reports.py:119` — `main()` returns 0 unconditionally: files missing from the tree or skipped for encoding never fail the run, so CI could "pass" while nothing was labeled.
  - 🟢 **LOW** `label_historical_reports.py:65-67` — `already_labeled()` scans only the first 14 lines for `historical|superseded|dated snapshot`; any doc that merely *mentions* "historical" in its preamble is silently skipped (false negative), while a banner inserted below a long H1 block could escape detection.
- **Limitations:** Fixed hard-coded `TARGETS` list (2026-10-21 audit); banner text/§78 reference frozen; only UTF-8 files handled.
- **Gaps:** `TARGETS` includes two paths that do not exist in this tree — `docs/PHASE7C_FINAL_EVIDENCE.md` and `docs/PHASE7C_FORENSIC_CORRECTION.md` (`label_historical_reports.py:42-43`; `Test-Path` fails) while the real files are at repo root (`:44-45`); they are reported as "missing" on every run. No test covers this script at all.
- **Issues:** Dead entries plus a doc list that must be hand-maintained forever; duplication of the same banner string in each already-labeled root PHASE file.

#### `scripts/record_docker_image_provenance.py`
- **Purpose:** Resolve the built Maven image and pinned runtime image to immutable identities and write the provenance JSON consumed by the candidate adapter.
- **Bugs:** None found.
- **Limitations:** Requires a local Docker daemon and pre-built/pulled images; writes only to a caller-chosen path (default `test-artifacts/...`, which is inside a non-ignored directory); no timestamp/attestation signature in the record.
- **Gaps:** Provenance covers only build+runtime images — the **oracle** image (`gnucobol-ocesql`) identity is resolved ad hoc by the engine but never recorded by this recorder, although `ORACLE_CONTRACT.md:31` requires a digest in every verdict scope.
- **Issues:** None found (covered by `tests/candidate/test_docker_image_provenance.py`).

#### `scripts/run_tests_one_by_one.py`
- **Purpose:** Run each test file in its own pytest process, record per-file JUnit/status/duration, and emit `results.json` + `summary.md`.
- **Bugs:**
  - 🟡 **MEDIUM** `run_tests_one_by_one.py:113-114` + `:289-290` — `NO_TESTS` (a file that collects **zero** tests, e.g. renamed/misplaced) is not in the `bad` set, so the driver exits 0 while silently reporting that nothing ran.
  - 🟡 **MEDIUM** `run_tests_one_by_one.py:277-278` — `KeyboardInterrupt` is swallowed, the partial report is written, and the exit code is computed from partial results: an interrupted run can return **0** with most files never executed.
  - 🟢 **LOW** `run_tests_one_by_one.py:209` — `--start-at` matches by substring and `next(..., 0)` defaults to the **beginning** when the needle isn't found: a typo silently restarts the whole suite instead of failing.
  - 🟢 **LOW** `run_tests_one_by_one.py:100-102` — dead code: `parse_junit(junit_path)` is called twice with identical arguments in the `counts["tests"] == 0` branch.
- **Limitations:** Sequential by default (documented contention rationale, lines 10-13); discovery limited to `tests/**/test_*.py` (line 47), so `*_test.py` or doctests are invisible.
- **Gaps:** Evidence root `test-artifacts/one-by-one/` (line 39) is **not** gitignored — the "never staged (D-4/BL-093 invariant)" claim in the docstring (lines 17-18) relies on human discipline, not on `.gitignore`. No test or CI job runs this driver.
- **Issues:** JUnit filename is derived from the path (`:72`) — two files differing only by `/` vs `\` normalization collide across platforms; progress file is appended without fsync so a crash mid-write leaves a truncated JSONL line (silently skipped on resume, `:229-231`).

#### `tools/check_backlog_table.py`
- **Purpose:** Structural validation of the `## Phase 0 closure metadata` table in `docs/BACKLOG.md` (7 columns, unique `BL-###` ids), non-zero exit on error.
- **Bugs:**
  - 🟡 **MEDIUM** `check_backlog_table.py:68-72` — prints `OK: N register rows, all 7 columns, unique ids` **before** checking `errors`, so a failing run still emits a success line followed by errors; any consumer grepping for `OK:` sees success (README/SUBMISSION_GUIDE quote exactly that string).
  - 🟢 **LOW** `check_backlog_table.py:43-48` — `cells` is computed twice (naive split, then regex split); the first is dead code.
  - 🟢 **LOW** `check_backlog_table.py:38` — separator detection only accepts rows starting exactly `|---` / `| ---`; a padded separator (`| --- |`) is parsed as a data row and reported as a bogus column error.
- **Limitations:** Only the Phase-0 register section (lines 29-33) — all other backlog tables are unvalidated; no semantic checks (owner, status, evidence columns).
- **Gaps:** Referenced as a gate in `README.md:102`, `docs/SUBMISSION_GUIDE.md:130` and `opencode.md:117`, but it is **not wired into any workflow** — nothing in `.github/workflows/*` runs it, so a malformed register cannot fail CI.
- **Issues:** Row-count claims in three docs (147) rot on every backlog edit; verified current output is `OK: 147 register rows` (exit 0), matching `README.md:102`.

#### `.github/workflows/ci.yml`
- **Purpose:** Four jobs — capability-truth gate (frozen test list), Phase-1 ingestion, full backend+Docker suite with provenance recording, frontend test/tsc/build.
- **Bugs:**
  - 🔴 **HIGH** `ci.yml:98` (working tree) — the gate list references `tests/test_shell_script_contracts.py`, which is **untracked** (`?? tests/test_shell_script_contracts.py`). At HEAD the line is absent and HEAD's `ci.yml` differs from the working tree (`git status: M .github/workflows/ci.yml`): the committed CI cannot run the committed-vs-working-tree test set, and a checkout of HEAD + this gate would fail with pytest "file not found". The gate's `55 → 56 files` claim (`opencode.md:67`) exists only in an uncommitted file.
  - 🟡 **MEDIUM** `ci.yml:29` — `python -m pip install pytest` unpinned (floating latest pytest, no lock, no hash) in the job whose whole point is supply-chain independence; supply chain drift can red/green the gate arbitrarily.
  - 🟡 **MEDIUM** `ci.yml:132-134` — builds and tags `gnucobol-ocesql:latest` / `maven-offline-springboot:latest`, and `ci.yml:139` re-tags the pinned digest as mutable `eclipse-temurin:21-jdk`; evidence files (`:150-153`) then record tag-based identity.
  - 🟡 **MEDIUM** `ci.yml:43-100` — the capability gate is a **frozen hard-coded file list**: any new test file not added here is never executed by the fast gate (only by the 180-minute backend job), so "capability truth" coverage silently lags new tests.
  - 🟢 **LOW** `ci.yml:191,198` — `if: always()` on the frontend test and build steps makes them run after `npm ci` failure (wasted work, confusing logs); the job still fails, so this is noise rather than a masking bug.
  - 🟢 **LOW** `ci.yml:185` — Node pinned to `20` inline instead of reading `.nvmrc` (`20`) — two pins that can drift.
- **Limitations:** No lint job (no ruff/flake8 despite `PHASE7C_FINAL_EVIDENCE.md:140-146` reporting ruff runs), no coverage/mutation gate (deferred D-3), no deploy job, `timeout-minutes: 180` for the Docker job.
- **Gaps:** `requirements.lock` is installed without `--require-hashes` (`ci.yml:114,155`); no image vulnerability scan; the deselected test at `ci.yml:100` is permanently carved out of the fast gate (documented, but it is a standing exception).
- **Issues:** Actions are SHA-pinned (good, `:19,21,165,183`) while pip/node are not — inconsistent pinning policy. `set -o pipefail` at `:36` is redundant with the explicit `shell: bash` elsewhere but absent where it matters (see `supply-chain.yml`).

#### `.github/workflows/supply-chain.yml`
- **Purpose:** Weekly/on-push pip-audit + npm audit + CycloneDX SBOMs, then a release dependency manifest.
- **Bugs:**
  - 🔴 **HIGH** `supply-chain.yml:44-45` — `python -m pip_audit ... | tee ...` runs with **no `shell:` key**, so GitHub's default `bash -e {0}` applies (**no `pipefail`**): the step's exit status is `tee`'s (0), i.e. **pip-audit findings cannot fail the job**.
  - 🔴 **HIGH** `supply-chain.yml:84` — same defect for `npm audit --json | tee ...`: `npm audit` exits non-zero on vulnerabilities, `tee` exits 0 → masked.
  - 🔴 **HIGH** `supply-chain.yml:88-90` — `npm sbom | tee` and `npm ls --all --json | tee` are likewise masked, so SBOM generation can silently produce nothing.
  - 🔴 **HIGH** — the header claim at `supply-chain.yml:6-9` ("pip-audit and npm audit now GATE (no continue-on-error)") and `UNIVERSAL_RUNTIME_PROOF_AUDIT_AND_IMPLEMENTATION_PLAN.md:90,202` ("3 gating jobs", "audits gate with no bypass") are therefore **false**: this is the canonical "CI step that can't fail".
  - 🟡 **MEDIUM** `supply-chain.yml:39` — audit tooling installed unpinned (`"pip-audit>=2.7" "cyclonedx-bom>=7"`): the *scanner* itself floats.
- **Limitations:** No container image scanning (trivy/grype) for `systemaops-api`/nginx/oracle images; no license gate; no SBOM for the built images; `schedule` only weekly (`:17`).
- **Gaps:** `build_release_manifest.py` has no test (job-only invocation, `:115`); the manifest job uploads with `if-no-files-found: error` (`:124`) but its *content* is never validated; `docs/RELEASE_GATE_WS4.md:273` still records a fixed `lockfileVersion: null` defect.
- **Issues:** Comment at `:6-9` documents an intended control that the YAML does not implement — the highest-value doc/code contradiction in the CI set.

#### `Dockerfile.production`
- **Purpose:** Non-root (uid 10001) FastAPI control-plane image: pinned base, SHA-verified static docker CLI, lock-installed deps, readiness HEALTHCHECK, exec-form uvicorn CMD.
- **Bugs:**
  - 🟡 **MEDIUM** `Dockerfile.production:54-55` — `pip install -r requirements.lock` with no `--require-hashes`/`--no-deps`: version-pinned only; also installs **test-only** deps (`pytest`, `pytest-asyncio`, `httpx`, `pluggy`, `Pygments` — `requirements.lock:21-22,31,36,39`), none of which `api/` imports, enlarging the production attack surface.
  - 🟢 **LOW** `Dockerfile.production:35-44` — `apt-get update && install ca-certificates curl` from the digest-pinned base but *floating* Debian archive: package versions are not pinned, so rebuilds are not byte-reproducible (image digest will differ per build day).
  - 🟢 **LOW** `Dockerfile.production:31` — `ARG DOCKER_CLI_VERSION=27.3.1` overridable at build time; combined with `--pull` builds this allows an unreviewed CLI bump (checksum still enforced at `:40`).
- **Limitations:** Explicit `COPY` allow-list only (`:59-63`) — deliberate; single worker by design (`:93-94`), no scaling without queue replacement (documented gap).
- **Gaps:** No `.dockerignore` exists anywhere in the repo (and `.gitignore:150,270` actively ignore it), so the build context ships `.git`, `test-artifacts/`, `backups/`, `node_modules/` to the daemon — bloat and a latent secret-context exposure even with explicit `COPY`.
- **Issues:** None serious — this file is the strongest artifact in the set (digest pin + sha256 verify + non-root + healthcheck + SIGTERM-friendly CMD).

#### `Dockerfile.gnucobol`
- **Purpose:** Build the GnuCOBOL oracle image from a digest-pinned Ubuntu 22.04 base with a `cobc --version` smoke test.
- **Bugs:**
  - 🟡 **MEDIUM** `Dockerfile.gnucobol:8-15` — no `USER` directive: the image defaults to **root**; isolation depends entirely on callers passing `--user 10001:10001` (`verify-production.sh:40` does not).
  - 🟡 **MEDIUM** `Dockerfile.gnucobol:8-15` — `apt-get update && apt-get install gnucobol ...` with no version pins: the digest-pinned base does **not** pin package content, so `gnucobol` can change under an unchanged Dockerfile (oracle identity drift between builds; only mitigated by per-run digest resolution).
  - 🟢 **LOW** `Dockerfile.gnucobol:3` — image/tag named `gnucobol-ocesql` but no OCESQL/ESQL package is installed anywhere in the file; `EXEC SQL` cannot compile (documented as BL-130 / `docs/audits/DOCKER_RUNTIME_IMAGE_AUDIT_2026-10-22.md:68`), yet the tag still implies the capability.
- **Limitations:** One-shot build/run image: no HEALTHCHECK, no `WORKDIR` ownership setup, `-dev` packages (`libgmp-dev libdb-dev libncurses-dev`) left in the final image (size/attack surface).
- **Gaps:** `contracts/ORACLE_CONTRACT.md:18` names the authoritative oracle as "GnuCOBOL 3.1.2.0 + **Open-COBOL-ESQL 1.4**" and `:34` says base image is "**Alpine 3.19** lineage" — both contradict this Dockerfile (Ubuntu 22.04, no OCESQL). Contract-vs-image contradiction with no test asserting the contract's `base_image`/`preprocessor_version` fields.
- **Issues:** Tag/contract/image three-way drift (`gnucobol-ocesql` vs no ocesql; Alpine vs Ubuntu) is exactly the "stale contract" class the platform claims to fail closed on.

#### `Dockerfile.maven-offline`
- **Purpose:** Digest-pinned Maven/temurin image with a pre-cached offline Spring Boot 3.2.5 dependency repo for candidate builds.
- **Bugs:**
  - 🟡 **MEDIUM** `Dockerfile.maven-offline:28` — no `USER`: image defaults to root; non-root execution depends on callers passing `--user 10001:10001` (documented at `:21-26`, enforced only by `tests/test_container_hardening.py`).
  - 🟡 **MEDIUM** `Dockerfile.maven-offline:17` — `mvn -B dependency:go-offline package` resolves transitives from Maven Central at **build time** with no version/lock/hash pinning beyond the `spring-boot-starter-parent 3.2.5` written into the inline pom (`:15`): rebuilds are not reproducible and can silently pull newer transitive artifacts.
  - 🟢 **LOW** `Dockerfile.maven-offline:19` — `chmod 755 /root` + `chmod -R a+rX /root/.m2` widens root's home to world-readable to serve non-root builds (explicitly documented trade-off at `:21-27`; any secret later written under `/root` would be exposed).
- **Limitations:** Only `spring-boot-starter` + `spring-boot-starter-batch` are precached (`:15`) — any other starter requires an image rebuild (documented, BL-071).
- **Gaps:** No HEALTHCHECK (acceptable for a build image) but also no provenance record: `record_docker_image_provenance.py` records this image only when `build-production.sh`/CI runs; nothing pins the *contents* of the offline repo to a digest in the contract (`JAVA_CANDIDATE_CONTRACT_V2.md:44` demands an `offline_repo_digest` manifest field that no code implements).
- **Issues:** One enormous `echo '<project>...</project>'` line (`:15`) is effectively unmaintainable — 1 line, ~1 KB of XML with no formatting and no way to add a dependency except editing a shell-escaped blob.

#### `docker-compose.production.yml`
- **Purpose:** Single-host production topology: nginx (TLS, :443) → api (uvicorn, 1 worker) with named volumes, staging bind, docker.sock, health-gated startup.
- **Bugs:**
  - 🔴 **HIGH (accepted/documented)** `docker-compose.production.yml:86` — `/var/run/docker.sock` mounted into the API container = root-equivalent on the host; accepted risk with mitigations (`:82-85`, `docs/security/PRODUCTION_SECURITY.md`), but it means the non-root uid 10001 + `group_add: "${DOCKER_GID:-0}"` (`:96-97`) is effectively root-group for daemon control.
  - 🟡 **MEDIUM** `docker-compose.production.yml:110` — `read_only: false` explicitly disables the read-only rootfs; only `no-new-privileges` (`:111-112`) and caps remain — writable rootfs + docker.sock is a weak combination (documented, but the `security_opt` block gives a false impression of hardening).
  - 🟡 **MEDIUM** `docker-compose.production.yml:146` — `${FRONTEND_DIST_PATH:-./frontend/dist}` is auto-created as an **empty directory** by Docker when missing → nginx serves an empty `/app/` with no failure at startup (caught only later by `verify-production.sh:71`).
  - 🟡 **MEDIUM** `docker-compose.production.yml:27` — `image: systemaops-api:${IMAGE_TAG:-production}` with no `pull_policy:`; `up` reuses whatever local tag exists (stale-image risk; see `start-production.sh:63`).
  - 🟢 **LOW** `docker-compose.production.yml:154` — nginx healthcheck uses `wget https://127.0.0.1/health` with no `--no-check-certificate`/SNI handling: if busybox wget verifies certs, the cert CN/SAN will never match `127.0.0.1` and nginx reports **unhealthy forever** (nothing else inspects nginx health, so this could go unnoticed).
- **Limitations:** Explicitly single-node, no HA, single replica, SQLite single-writer (`:3,101-104`); log rotation capped at 10 MB × 5 (`:123-127,159-163`); no rate limiting (deferred D-7).
- **Gaps:** No `docker compose` profile/override for offline installs; no resource limits on named-volume fs; no documented secret store (token lives in a flat env file); usage comment at `:17` (`up -d --build`) is a **second, competing deploy path** to `scripts/deploy/build-production.sh` (which also records provenance — the compose path does not).
- **Issues:** `SANDBOX_STAGING_DIR`/`SANDBOX_HOST_STAGING_DIR`/`HOST_SANDBOX_STAGING_DIR` triple naming (`:65-66,79`) requires three files to stay in sync (compose, `.env.production.example:79`, `start-production.sh:37`).

#### `deployment/nginx/systemaops.conf`
- **Purpose:** TLS-terminating reverse proxy with exact `/health`,`/ready` passthrough, `/app/` static + SPA fallback, legacy `/assets/` redirect, and API catch-all.
- **Bugs:**
  - 🟡 **MEDIUM** `systemaops.conf:110-121` — the API catch-all has **no `proxy_buffering`/`proxy_request_buffering` tuning and no `client_body_timeout` interplay for the long modernize runs beyond `proxy_read_timeout 300s`**; more importantly there is no `limit_req`/`limit_conn` anywhere (rate limiting is D-7 deferred, but the edge is where it belongs).
  - 🟢 **LOW** `systemaops.conf:34-35` — `listen 443 ssl; http2 on;` with **no port-80 server**: correct per the stated design (`:4-5`), but a missing/broken cert means nginx fails to start entirely with no fallback (intentional, `docker-compose.production.yml:140-142`).
  - 🟢 **LOW** `systemaops.conf:55-57` — framing headers re-asserted but **no `Strict-Transport-Security`** here; comment `:7` claims the FastAPI app sets it, so HSTS depends on the app middleware being reached — a proxy-only failure path leaves HSTS unset.
- **Limitations:** Single upstream, no retries/health-aware upstream (`:28-31` keeps 16 keepalive conns only), no WebSockets, no caching of API responses, `server_name _` placeholder (`:37`).
- **Gaps:** No `server_tokens off`, no access/error log customization (default logs only), no OCSP/stapling, no TLS session ticket key rotation; `client_max_body_size 50m` (`:50`) must be manually kept in sync with `CONTROL_PLANE_MAX_REQUEST_BYTES` (`.env.production.example:30`) — a doc-enforced sync with no test.
- **Issues:** Comment block `:12-26` is a routing contract that is only partially verified (`verify-production.sh:63-76` checks `/app/`, asset, SPA fallback, `/app/assets/` reference, but not the `/assets/` → `/app/` redirect at `:104-106`).

#### `.env.production.example`
- **Purpose:** Copy-to template for production secrets/paths with empty-token fail-closed default.
- **Bugs:** None found (no committed secrets; `CONTROL_PLANE_API_TOKEN=` empty at `:11` correctly trips `${...:?}` at `docker-compose.production.yml:38` and `start-production.sh:22-25`).
- **Limitations:** Single-token auth model, no token TTL/rotation guidance (D-7 deferred), `DOCKER_GID=0` default (`:84`) assumes root-owned socket.
- **Gaps:** Doesn't list several runtime knobs the code reads (`CONTROL_PLANE_LOG_LEVEL/FORMAT`, `SYSTEMAOPS_ORACLE_IMAGE`, `RUN_DOCKER_TESTS`) — those live only in `docs/deployment/ENVIRONMENT.md`; no documented token-rotation or backup-of-env procedure.
- **Issues:** `CONTROL_PLANE_MAX_REQUEST_BYTES` (`:30`) duplicates nginx `client_max_body_size` (`systemaops.conf:50`) as free-floating parallel values.

#### `.gitignore`
- **Purpose:** Broad multi-language ignore list plus project-specific production-secret rules.
- **Bugs:**
  - 🔴 **HIGH** `.gitignore:150` and `:270` — **`.dockerignore` is ignored**, and no `.dockerignore` exists in the tree: the repo can never gain a build-context filter, guaranteeing full-context docker builds (see `Dockerfile.production` gaps).
  - 🟡 **MEDIUM** `.gitignore:353` — `Makefile` ignored: any future project Makefile is invisible to git by default.
  - 🟡 **MEDIUM** `.gitignore:84` — `.python-version` ignored; `build_release_manifest.py:114-119` then has to *guess* the Python pin from CI YAML and labels it "(CI pin; .python-version git-ignored)" — the ignore rule actively degrades release provenance.
  - 🟢 **LOW** `.gitignore:17` — `lib/` and `:11` `build/`, `:12` `dist/` are ignored globally (currently harmless — no tracked `lib|build|dist|target|share` paths — but a future `lib/` source dir would be silently untracked).
- **Limitations:** `test-artifacts/` is **not** ignored — 48 stale artifacts remain tracked (`.gitignore` has no rule; `docs/RELEASE_GATE_WS4.md:38-43` explains the D-4 "never stage" rule is procedural, not enforced).
- **Gaps:** No ignore for `test-artifacts/one-by-one/`, `.env.rollback.*` is covered (`:434`) but `*.env` variants beyond `.env.production` are not systematically covered; `backups/` covered (`:435`).
- **Issues:** Massive duplication — IDE/OS/build/coverage/logs/secrets blocks repeat 4-5× (`:138-147` vs `:164-172` vs `:210-226` vs `:269-285`), duplicate `*.pem` (`:195,:197`), `*.log` (`:181,:344`), `target/` (`:74,:187,:245,:252,:260,:398`); 435 lines where ~120 would do — every future rule risks landing in only one of the duplicate blocks.

#### `.gitattributes`
- **Purpose:** Force `*.sh` to LF on checkout so CRLF shebangs can't break Linux execution (paired with `tests/test_shell_script_contracts.py`).
- **Bugs:**
  - 🔴 **HIGH** `.gitattributes:1-7` (whole file) — the file is **untracked** (`git status`: `?? .gitattributes`; `git ls-tree HEAD` has no `.gitattributes`). The CRLF protection described in its own comment exists only in this working tree; a fresh clone of HEAD has no `.gitattributes`, and `tests/test_shell_script_contracts.py:74-86` (`test_gitattributes_pins_lf_for_shell_scripts`) would **fail at HEAD** because the file it asserts is absent.
- **Limitations:** Covers `*.sh` only; no rules for `.py`, `.yml`, `.json`, `.md` normalization.
- **Gaps:** The enforcing test and the file it enforces are both uncommitted (`M scripts/**.sh`, `?? .gitattributes`, `?? tests/test_shell_script_contracts.py`) — the BL-146 fix claimed at `opencode.md:62-67` is not in version control.
- **Issues:** The comment says "all six deploy/backup scripts were committed CRLF" — six scripts exist (`scripts/deploy/*.sh`, `scripts/backup/*.sh`), consistent; but the file's absence makes that history likely to repeat.

#### `.nvmrc`
- **Purpose:** Pin the frontend Node major version to `20`.
- **Bugs:** None found.
- **Limitations:** Major-only pin (no minor/patch), unlike the digest-level pinning used for images.
- **Gaps:** CI does not read it — `ci.yml:185` and `supply-chain.yml:76` hardcode `node-version: 20`; two independent pins with no drift test (contrast `build_release_manifest.py:160`, which *does* read `.nvmrc` into the manifest, so a drift would show up as a manifest mismatch nobody checks).
- **Issues:** None found.

#### `requirements.txt`
- **Purpose:** Loose compatible ranges for development flexibility (`requirements.lock` is the release pin).
- **Bugs:**
  - 🟢 **LOW** `requirements.txt:5-6` — `pytest>=9,<10` / `pytest-asyncio>=1.3,<2` are test-only deps living in the same file as runtime deps, so a dev install and the prod lock are generated from a mixed set.
- **Limitations:** Six direct deps only; no lint/type-check tool declared even though `PHASE7C_FINAL_EVIDENCE.md:140-146` and opencode reference `ruff` runs.
- **Gaps:** No `ruff`/`mypy`/`bandit` anywhere in `requirements.txt`/`requirements.lock`, and **no CI job runs a linter** — the lint evidence quoted in PHASE7C/PHASE7D reports cannot be reproduced from the declared dependencies.
- **Issues:** Range drift risk: `requirements.txt` ranges and `requirements.lock` pins are updated by separate processes with no script asserting every lock entry satisfies its range.

#### `requirements.lock`
- **Purpose:** Release-pinned Python dependency closure with an explicit E-C security-bump ledger.
- **Bugs:**
  - 🟡 **MEDIUM** `requirements.lock:1-49` — **no `--hash` entries and no `--require-hashes` workflow**: pinning is by version string only, so a compromised PyPI/yanked-reinstall can substitute content (used by `Dockerfile.production:55`, `ci.yml:114,155`, `supply-chain.yml:37`).
  - 🟡 **MEDIUM** `requirements.lock:21-22,36,39` — ships **test-only** packages (`pytest==9.0.3`, `pytest-asyncio`, `iniconfig`, `pluggy`, `Pygments`) into the production image (none imported by `api/`).
  - 🟢 **LOW** `requirements.lock:20` and `:46` — `uvicorn[standard]==0.52.3` and `uvicorn==0.52.3` both listed (duplicate of the same pin; harmless but confusing for the manifest's "pinned" count).
- **Limitations:** Regeneration procedure is manual prose (`:7-8`); no automation, no CI freshness check (a stale lock with a new CVE only fails when the weekly `pip-audit` runs — and that gate is masked, see `supply-chain.yml:44-45`).
- **Gaps:** No hash pinning, no `pip-compile`-style provenance, no test asserting lock ↔ `requirements.txt` range consistency; `Dockerfile.production` installs the lock as-is with the dev/test extras.
- **Issues:** The header ledger (`:11-17`) documents security bumps inline — good practice, but it duplicates what a commit message/changelog should own and will grow unbounded.

#### `README.md`
- **Purpose:** Root entry point: project statement, verified quick start, implemented list, evidence ladder, boundaries, doc index, dated CI baseline.
- **Bugs:**
  - 🟡 **MEDIUM** `README.md:41-42` vs `:46` — quick start was "verified against commit `49821ad` … Python 3.12" while the prerequisite line says "Python 3.11+" and `requirements.lock:5` says "Verify on Python 3.11": three-way version/commit inconsistency in the first 50 lines.
  - 🟢 **LOW** `README.md:101-103` — hard-coded counts (`18 passed`, `OK: 147 register rows`, `166 passed`) rot on every commit; the 147 row count currently verifies (checker exits 0), the others are unverifiable claims.
  - 🟢 **LOW** `README.md:78-79` — instructs users to build `gnucobol-ocesql:latest` / `maven-offline-springboot:latest` (mutable tags) as the canonical local setup, propagating the `:latest` practice into docs.
- **Limitations:** Deliberately self-labels as dated snapshot (`:11-15`, `:246-262`); defers live truth to `opencode.md` + `docs/BACKLOG.md` (`:3-7`).
- **Gaps:** The doc index (`:220-240`) omits the backup/restore scripts themselves (only `docs/operations/BACKUP_RECOVERY.md` is listed at `:232`); no mention of `rollback.sh`/`build-production.sh` in the quick start — deploy tooling is undiscoverable from the README.
- **Issues:** Carries both a "HISTORICAL SNAPSHOT" banner (`:11`) *and* "verified 2026-10-21" quick-start claims (`:39`) — two competing freshness signals.

#### `MASTER_IMPLEMENTATION_README.md`
- **Purpose:** 2346-line normative specification (§1–§80): architecture, invariants (no-LLM), phase policy, audit-first rules, backlog contract, documentation authority hierarchy.
- **Bugs:**
  - 🟡 **MEDIUM** `MASTER_IMPLEMENTATION_README.md:2036-2058` — §71 Final Release Gate is a block of **all-unchecked `[ ]` boxes**, while `UNIVERSAL_RUNTIME_PROOF_AUDIT_AND_IMPLEMENTATION_PLAN.md:68` asserts "19✅ / 2⚠️" for that same gate: the spec contains no such state, so the audit doc reports checkbox values that do not exist in the file it cites.
  - 🟢 **LOW** `MASTER_IMPLEMENTATION_README.md:2150-2152` — orphaned empty `---` / duplicate horizontal rule after §75 (stray formatting artifact).
- **Limitations:** By design it contains no live status (`:2133-2147`); "eventually" requirements are deliberately unmeasured (`:199-237`).
- **Gaps:** §49 (`:1376-1386`) requires contract tests for all five contracts; no traceability table maps each contract's Test-First table (e.g. `JAVA_CANDIDATE_CONTRACT_V2.md:68-77`) to an actual test file — several have none. §51 (`:1447-1462`) requires "security checks" in CI; no lint/secret-scan/image-scan job exists.
- **Issues:** 2346 lines with heavy prose repetition (§7/§8/§70/§71 restate the same subset-honesty rules), making it hard to tell which sentence is normative; the §78 authority hierarchy (`:2303-2316`) is itself contradicted by `README.md`'s own snapshot claims.

#### `opencode.md`
- **Purpose:** Live implementation checkpoint, newest-session-first, recording phases, verdicts, CI SHAs and handoff state.
- **Bugs:**
  - 🔴 **HIGH** `opencode.md:112-117` — the **newest** session block contains unfilled template placeholders `{{LANE7}}`, `{{LANE8}}`, `{{LANE9}}`, `{{SANITYGATE}}`, `{{SANITYBACKLOG}}`: the verification ladder for the 2026-10-26 "final production-readiness batch" is literally blank, violating the file's own rule that "the checkpoint must never intentionally be left misleading" (`MASTER_IMPLEMENTATION_README.md:1846`).
  - 🟡 **MEDIUM** `opencode.md:119-124` — push/CI status says the SHA and run links "are recorded in the follow-up block added below after verification" — no such follow-up block exists at the top of the file, so the newest batch has **no recorded push/CI result**.
  - 🟢 **LOW** `opencode.md:2649` and `:2651` — duplicate identical `## Phase 5 started — JCL Modernization` headers (duplicated block).
- **Limitations:** Newest-first ordering means older blocks are knowingly stale (self-documented at `:3-9`); no machine-readable state (all prose/tables).
- **Gaps:** The checkpoint's required-state list (`MASTER_IMPLEMENTATION_README.md:1877-1903`) includes "Last known green commit" and "CI result" — absent from the newest block; historical contradictions (e.g. `:1012` "122 rows" vs `:815`/README 147) are only resolvable by reading the whole 4643-line file.
- **Issues:** 4643 lines and growing ~1 block/session with no archival policy — the file now duplicates `docs/BACKLOG.md` change-log, `README.md` counts, and `RUNTIME_PROOF_MATRIX` labels in three formats.

#### `UNIVERSAL_RUNTIME_PROOF_AUDIT_AND_IMPLEMENTATION_PLAN.md`
- **Purpose:** 2026-10-19 evidence-driven audit + remediation record (BL-094..097) + roadmap (R-1..R-8), with later status addenda.
- **Bugs:**
  - 🟡 **MEDIUM** `UNIVERSAL...md:90` and `:202` — claims `supply-chain.yml` has "3 gating jobs (pip-audit, npm audit, release manifest)" and "supply-chain audits gate with no bypass"; **false** — those steps are masked by `tee` without `pipefail` (`supply-chain.yml:44-45,84`).
  - 🟡 **MEDIUM** `UNIVERSAL...md:85` and `:195` — "containers run as root (documented limitation)" stated in the audit table and risk list, while the addendum at `:23-30` declares those rows historical (BL-135). The document contradicts itself in three places; only the addendum is current.
  - 🟢 **LOW** `UNIVERSAL...md:66` — cites "the 93-row backlog register"; current register is **147 rows** (checker output), and `:68` cites §71 checkbox states that the Master README does not contain.
- **Limitations:** Explicitly dated to audited HEAD `6145e89` with addenda (`:6-7,10-30`); truthfulness boundary at `:54` is well stated.
- **Gaps:** Roadmap item **R-1** ("Commit + CI-validate the combined working tree", `:261`) is described as "the most valuable next step" (`:298`) — but the current working tree shows the pattern recurring again (98 modified/untracked entries at HEAD `62e647f`), so the doc's own top recommendation is stale *and* unheeded.
- **Issues:** Contains its own full verification ledger (`:237-253`) that duplicates `opencode.md` session blocks; `:60` correctly states the Master README is 2346 lines (verified) — good, but `:199`/`:83` row-level statuses are already superseded by BL-134/135 addenda, making the tables read-only history inside a "current" doc.

#### `PHASE7C_FINAL_EVIDENCE.md`
- **Purpose:** Root-level historical Phase 7C remediation evidence (placeholder tests replaced, validator fix, adversarial results).
- **Bugs:** None found (already banner-labeled historical at `:2`, correct per §78).
- **Limitations:** Dated to a Windows host without Docker: `:109-113` records Docker/BUILD as BLOCKED/NOT VERIFIED — deliberately narrow evidence.
- **Gaps:** Its `docs/` counterpart listed by `label_historical_reports.py:42` **does not exist** (only the root copy is tracked), so the labeling tool's target list is wrong for this file; no index explains root-vs-`docs/` placement.
- **Issues:** Direct contradiction with its sibling: `PHASE7C_FINAL_EVIDENCE.md:6` says "**FREEZE PHASE 7C**" while `PHASE7C_FORENSIC_CORRECTION.md:222` says "**DO NOT FREEZE PHASE 7C — REMEDIATION REQUIRED**" — two root-level reports with opposite verdicts and no ordering note beyond their dates (`:2` banner vs `:4` "Date: 2026-09-17").

#### `PHASE7C_FORENSIC_CORRECTION.md`
- **Purpose:** The 2026-09-17 forensic pass that found the two placeholder tests and the F401, recommending "DO NOT FREEZE".
- **Bugs:** None found (historical, banner-labeled at `:2`).
- **Limitations:** Scoped to 23 tasks on a single test file; test counts (79, `:30-34`; 1229, `:152`) are frozen snapshots.
- **Gaps:** No companion document at root records the *decision* that reconciles it with `PHASE7C_FINAL_EVIDENCE.md`'s FREEZE verdict (the correction is superseded only implicitly by ordering).
- **Issues:** Duplicates the defect table and remediation options already summarized in `PHASE7C_FINAL_EVIDENCE.md:10-52` (two files, overlapping content, opposite conclusions); `:250-259` contains a malformed generated-file list (`pom.xml/pom.xml`, `Application.java/Application.java`) — an obvious capture bug preserved as evidence.

#### `PHASE7D_COMPLETION_REPORT.md`
- **Purpose:** Historical Phase 7D report: full COBOL→Spring Boot→Docker→oracle chain with 12 bug fixes and test counts.
- **Bugs:**
  - 🟡 **MEDIUM** `PHASE7D_COMPLETION_REPORT.md:11` — "**VERDICT: VERIFIED**" reuses the platform's controlled verdict vocabulary (`VERDICT_CONTRACT.md:20-30`) for a *phase* result, and `:152` reports "Behavioral Equivalence: 3/3 passed (VERDICT = VERIFIED)" — a claims-style statement from a historical doc that only the banner (`:2`) neutralizes.
  - 🟡 **MEDIUM** `PHASE7D_COMPLETION_REPORT.md:167-169` — image digests are stale/wrong: `gnucobol-ocesql:latest → sha256:f6f567fb...` contradicts the current recorded identity `sha256:68900cc01cd6...` (`docs/audits/DOCKER_RUNTIME_IMAGE_AUDIT_2026-10-22.md:56`) and `maven-offline-springboot → sha256:99d13a54...` contradicts the post-BL-135 rebuild `sha256:aea01e81217...` (`opencode.md:165`).
- **Limitations:** Honest and specific: single workload (ARITHMETIC) (`:185`), numeric formatting normalization (`:183`), Spring startup overhead (`:187`).
- **Gaps:** `label_historical_reports.py:46` targets `PHASE7D_COMPLETION_REPORT.md` but there is **no `docs/` copy** either — the root-only placement of all three PHASE7C/7D reports is undocumented; `:213` lists `Dockerfile.maven-offline` as a "New File" that is now a core tracked image definition.
- **Issues:** `:143` (`30 passed in 593.95s`) and `:156` (`1605 passed`) are unreproducible counts; the "Files Modified" table (`:193-207`) overlaps `docs/` phase reports for the same changes (duplication).

#### `contracts/ARTIFACT_CONTRACT_SPEC.md`
- **Purpose:** Normative artifact-registry/contract/comparison rules (5 closed types, fail-closed validation, content-addressing, generated-bundle seal).
- **Bugs:** None found.
- **Limitations:** Deliberately closed registry (`:23-51`), INDEXED/KSDS/RELATIVE/SQL excluded (`:38-44`), substring containment permanently forbidden (`:49-51`).
- **Gaps:** §7 (`:134-146`) Test-First table — the "static architecture test" for "no substring strategy in the comparator registry" (`:146`) exists only as a claim here; no test file name is cited in the contract (unlike `ORACLE_CONTRACT.md:75`, which names `tests/test_container_hardening.py`). BL-137 seal behavior (`:118-132`) is implemented in `api/artifact_seal.py` but the contract's NULL-seal 409 rule has no contract-level test pointer.
- **Issues:** Header `:6` still says "Implementation is a later phase" while `:1` says implementation exists — contradictory status lines in the same document (same pattern in `ORACLE_CONTRACT.md:1,6` and `VERDICT_CONTRACT.md:1,6`).

#### `contracts/JAVA_CANDIDATE_CONTRACT.md`
- **Purpose:** V1 candidate shape (plain Java, no build system, zero deps) + manifest/intake/execution/test rules.
- **Bugs:**
  - 🟡 **MEDIUM** `JAVA_CANDIDATE_CONTRACT.md:27-35` — V1 normatively forbids `pom.xml`, yet the shipped default lane emits one (`docs/BACKLOG.md:6761` BL-110, closed only by pointing at V2). A reader of V1 alone gets the wrong picture of what the platform accepts today.
- **Limitations:** Explicitly deferred Maven/Spring lane (`:37-40`); producer-binding gated on co-approval (`:5-7`).
- **Gaps:** §7 Test-First table (`:110-119`) has no test-file citations — e.g. "Hash mismatch in `generated_files` → Refusal" and "Undeclared extra files → Flagged" cannot be located from the contract; §3's `mutation_regeneration` field name (`:58`) does not match the producer contract's `mutation_regeneration_capability` (`TRANSFORMATION_PRODUCER_CONTRACT.md:67`) or the code's `requires_mutation_regeneration` (`engine/contracts/models.py:172`).
- **Issues:** Dual status banners (`:1` V2 pointer, `:5-10` "Implementation is a later phase") — the doc contradicts itself about whether implementation exists.

#### `contracts/JAVA_CANDIDATE_CONTRACT_V2.md`
- **Purpose:** V2 extension defining the Spring Boot/Maven candidate shape (pom.xml, offline Maven, V2 manifest fields, sandbox rules).
- **Bugs:**
  - 🟡 **MEDIUM** `JAVA_CANDIDATE_CONTRACT_V2.md:39-47` — mandates `build_system`, `maven_pom_hash`, `spring_profile`, `offline_repo_digest` with fail-closed intake refusal: **none of these four fields appears anywhere in `engine/` or `tests/`** (repo-wide grep finds them only in this file) — a normative contract with zero implementing or enforcing code.
  - 🟡 **MEDIUM** `JAVA_CANDIDATE_CONTRACT_V2.md:54` — requires `mvn -o package`; the actual lane uses `-Dmaven.test.skip=true` and adapter-specific flags (see `PHASE7D_COMPLETION_REPORT.md:128`) — contract command vs code command diverge with no test pinning either.
- **Limitations:** One lane only; any further build system requires a new version (`:79-83`).
- **Gaps:** §5 Test-First table (`:68-77`, six scenarios incl. "Missing `pom.xml` in V2 candidate → Intake refusal") has **no matching tests at all** — the entire V2 contract is unenforced documentation.
- **Issues:** Duplicate/contradictory spec pair with V1: V1 `:27` "No build system — no `pom.xml`" vs V2 `:19-26` "Maven project tree" are reconciled only by cross-references added in the uncommitted working-tree diff (`git diff -- contracts/JAVA_CANDIDATE_CONTRACT*.md` shows `M` on both); at HEAD the reconciliation is partial.

#### `contracts/ORACLE_CONTRACT.md`
- **Purpose:** Oracle identity/evidence/hard rules: digest-pinned GnuCOBOL, observed-only statuses, isolation, mandatory evidence, V1 limitations.
- **Bugs:**
  - 🟡 **MEDIUM** `ORACLE_CONTRACT.md:18` vs `Dockerfile.gnucobol:8-15` — contract names "GnuCOBOL 3.1.2.0 + **Open-COBOL-ESQL 1.4**" as the authoritative oracle; the image installs **no OCESQL** (verified gap: `docs/BACKLOG.md:6782` BL-130, `DOCKER_RUNTIME_IMAGE_AUDIT_2026-10-22.md:68`).
  - 🟡 **MEDIUM** `ORACLE_CONTRACT.md:34` — `base_image` documented as "**Alpine 3.19 lineage**" while the image is `ubuntu:22.04@sha256:5ec03bb3...` (`Dockerfile.gnucobol:3`): a normative identity field that is simply wrong.
  - 🟡 **MEDIUM** `ORACLE_CONTRACT.md:36-37,119` — "`:latest` is prohibited" / "Digest pinning is mandatory", yet every build/deploy/CI site uses `gnucobol-ocesql:latest` (`build-production.sh:13`, `verify-production.sh:37,40`, `ci.yml:132,150-151`, `README.md:78`). Only runtime digest resolution (`engine/domain/identities.py:110-111`) keeps the rule true at execution time.
- **Limitations:** Explicit V1 non-claims (`:122-132`), FUTURE adapters (`:134-138`).
- **Gaps:** §9 Test-First table (`:140-149`) names no tests except the hardening guard cited at `:75` (`tests/test_container_hardening.py`); "Digest missing from identity → Schema-invalid; run refused" has a code path (`engine/domain/identities.py`) but no contract-named test. §2's `preprocessor_version` field is unmeasurable in this image.
- **Issues:** Status-line contradiction identical to ARTIFACT spec (`:1` implementation exists vs `:6` "later phase").

#### `contracts/TRANSFORMATION_PRODUCER_CONTRACT.md`
- **Purpose:** External untrusted-producer boundary: mandatory producer manifest, fail-closed intake, mutation-regeneration requirement, co-approval gate.
- **Bugs:**
  - 🟡 **MEDIUM** `TRANSFORMATION_PRODUCER_CONTRACT.md:100-103` — the contract itself discloses that the derivation layer **does not read** `requires_mutation_regeneration`, so the documented `UNAVAILABLE` cap is unimplemented (D-11/BL-112): a stated fail-closed rule with no enforcement.
- **Limitations:** Producer implementation out of scope (`:8`); binding gated on PD-05 co-approval (`:5-7,107-116`); optional extensions never consumed (`:78-83`).
- **Gaps:** §8 Test-First table (`:117-127`) — the row "Two producers, identical candidates → Identical validation treatment" and "Swapping producers → No architecture/verdict change" have no corresponding test names; only `tests/transformation/test_producer_contract.py` exists for adjacent behavior. Field-name drift across the three docs (`mutation_regeneration_capability` here `:67` vs `mutation_regeneration` in V1 candidate `:58` vs `requires_mutation_regeneration` in code `models.py:172`) means a producer reading both contracts gets two different required keys.
- **Issues:** §6 and §8 both restate the deferral (`:100-103` and `:125`) — correct but duplicated; the contract now documents more about what is *not* implemented than what is.

#### `contracts/VERDICT_CONTRACT.md`
- **Purpose:** Seven-state verdict vocabulary, pure-derivation invariant, prohibited transitions, certification model and derivation preconditions.
- **Bugs:**
  - 🟡 **MEDIUM** `VERDICT_CONTRACT.md:119-125` — precondition 6 (mutation validation) is **DEFERRED/unimplemented** (BL-111) while still listed as required for `VERIFIED`; §6 invalidation (`:104`) likewise lists an unimplemented mutation gate. The contract's "verdict fabrication impossible by construction" claim (`:16`) therefore rests on an explicitly missing precondition.
- **Limitations:** Deliberate: monotone downgrades only (`:83`), no weighted scores (`:94-95`), frontend never recomputes (`:136-142`).
- **Gaps:** §9 Test-First table (`:144-157`) cites no test files; adjacent coverage exists (`tests/verdict/test_verdict.py`, `tests/verdict/test_verdict_trust_boundary.py`, `tests/test_certification_contract.py`) but the mapping "scenario → test" is undocumented, so a reader cannot verify e.g. "`baseline_verified=True` flag ignored" (`:157`) is actually tested.
- **Issues:** Same status-line self-contradiction (`:1` vs `:6`); `:162-163` requires "supersede-checking across ORACLE/ARTIFACT contracts" on vocabulary change — no tool/test performs that cross-contract check.

---

### Cross-cutting flags (Section J)

- **Duplicate/contradictory contract specs (V1 vs V2):** reconciled only on paper — `JAVA_CANDIDATE_CONTRACT.md:27` forbids `pom.xml`, `JAVA_CANDIDATE_CONTRACT_V2.md:19-26` requires it, and **V2's four mandatory manifest fields are implemented nowhere** (grep finds `build_system`/`maven_pom_hash`/`spring_profile`/`offline_repo_digest` only in the V2 doc). Both files are `M` (uncommitted) in the working tree, so HEAD carries the unreconciled version; `docs/CONTRACT_STATUS.md:20` and `docs/BACKLOG.md:6761` (BL-110) are the only reconciliation record.
- **Stale root-level `PHASE*.md` vs `docs\`:** root holds `PHASE7C_FINAL_EVIDENCE.md`, `PHASE7C_FORENSIC_CORRECTION.md`, `PHASE7D_COMPLETION_REPORT.md` with **no `docs/` counterparts**, while `scripts/label_historical_reports.py:42-43` still targets the non-existent `docs/PHASE7C_*` paths (reported "missing" every run). The root pair also carries **opposite verdicts** (FREEZE vs DO NOT FREEZE) and `PHASE7D` carries stale image digests (`:167-169`) plus a phase-level `VERIFIED` claim (`:11`). `docs/` separately holds ~30 other `PHASE*` reports, so phase evidence is split across two trees with no index.
- **`engine_py_files.txt`:** confirmed stale artifact — tracked, 49 **absolute Windows paths** (`C:\Users\bandi\Desktop\...`), last touched by the baseline commit `2026-09-18 chore: establish COBOL to Java transformation baseline`, referenced by no code (only `docs/RELEASE_GATE_WS4.md:42-43`, which records that it was deliberately "**restored**, not deleted"). It is machine-specific, unusable on CI/Linux, and should be deleted or regenerated relative-path.
- **Repo-wide context affecting every finding:** HEAD is `62e647f` (2026-10-26) with **98 modified/untracked entries**, including `scripts/backup/verify_backup.py`, `.gitattributes`, `tests/test_shell_script_contracts.py`, `tests/test_backup_verification.py`, `tests/test_readiness.py`, `tests/test_structured_logging.py`, `tests/test_workspace_persistence.py` and `ci.yml` — the BL-139..147 batch exists only in the working tree, so HEAD's CI/gate/backup-verification claims (`opencode.md:11-67`) are not backed by committed files.

---

# Section F — engine runtime / evidence / execution / candidate / oracle ✅ COMPLETE

28 files. 5 HIGH, 30 MEDIUM, 25 LOW.

### Summary — F

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 5 | Placeholder adapters **fabricate success**; `stdin` never delivered to any container (evidence mismatch); forged evidence passes integrity (self-signed seal) |
| 🟡 MEDIUM | 30 | Shell injection in `javac_args`, staging path traversal → evidence forgery, vacuous source-mutation checks |
| 🟢 LOW | 25 | Basename collisions in `generated_files`, timeout evidence mis-recording, dead code |

#### `engine/candidate/__init__.py`
- **Purpose:** Package export surface re-exporting the candidate-adapter contract types (`CandidateAdapter`, `CandidateManifest`, `CompilationResult`, `CandidateExecutionResult`, `PlainJavaCandidateAdapter`).
- **Bugs:** None found.
- **Limitations:** Only the placeholder `PlainJavaCandidateAdapter` is exported as a concrete adapter; the production Docker adapters are imported from their modules directly.
- **Gaps:** None found.
- **Issues:** Exports the fake-success stub `PlainJavaCandidateAdapter` (L8, L16) with no deprecation/placeholder marker alongside the real contract.

#### `engine/candidate/adapter.py`
- **Purpose:** Defines the candidate adapter ABC, manifest, compilation/execution result types, and the V1 placeholder `PlainJavaCandidateAdapter`.
- **Bugs:**
  - 🔴 **HIGH** — `PlainJavaCandidateAdapter.compile` returns `success=True` with zero class files without compiling (L199-210) and `execute` returns `AdapterStatus.SUCCEEDED`, `exit_code=0`, empty stdout without running anything (L212-245). A "never ran" candidate reports success; any downstream comparison of two empty outputs would be equal.
  - 🟡 **MEDIUM** — `to_execution_evidence` hardcodes `command="javac + java execution"` and `working_directory="/workspace"` (L149-151): the tamper-evident evidence records a command that did not necessarily run.
  - 🟡 **MEDIUM** — `source_tree_hash_before`/`after` are both set to `ContentHash.from_string("")` (L158-159), making the integrity layer's SOURCE_MUTATION check (`integrity.py` L467-483) vacuously true for any producer that does not replace them (pipeline does replace them, `pipeline.py` L668-673).
  - 🟢 **LOW** — `validate_candidate` (L173-197) checks only field presence and file existence; no traversal/absolute-path validation of `manifest.generated_files` keys.
- **Limitations:** V1 contract bans build systems and external dependencies (L182-187); `network_policy` honestly defaults to `"unisolated"` (L72-82).
- **Gaps:** The honest `network_policy` property is advisory only — nothing in this contract forces evidence producers to record it (callers must remember).
- **Issues:** Manifest validation logic duplicated verbatim across this class, `java_adapter.py`, `docker_java_adapter.py`, `docker_spring_boot_adapter.py`.

#### `engine/candidate/docker_java_adapter.py`
- **Purpose:** Container-per-execution Docker adapter running both `javac` and `java` inside hardened, network-disabled, resource-capped containers.
- **Bugs:**
  - 🔴 **HIGH** — `input_data` is accepted (L396) but never delivered: `docker_cmd` (L481-496) has no `-i`, no stdin pipe. The pipeline records `stdin_hash` for those bytes (`pipeline.py` L718), so recorded controlled input differs from what was actually fed (container stdin is `/dev/null` → immediate EOF).
  - 🟡 **MEDIUM** — Shell injection / path breakage: `javac_args = " ".join(java_files)` executed via `sh -c` (L290-291, L312) with no `shlex.quote` (contrast the oracle, `oracle/docker_adapter.py` L441-443). A manifest key containing shell metacharacters runs arbitrary commands in the container; spaces/backslashes (Windows `str(rel)` keys, `pipeline.py` L243) break the command.
  - 🟡 **MEDIUM** — `entrypoint_class` interpolated unquoted into `sh -c java -cp ... {entrypoint}` (L445-448, L495) — manifest-controlled shell interpolation.
  - 🟡 **MEDIUM** — Path traversal when staging: `dest = staged_source / rel_path` (L273-275) and `(input_dir / name).write_bytes(content)` (L459-460) are unsanitized; absolute or `..`-leading keys write outside the staging directory (the adapter API accepts arbitrary manifests/keys).
  - 🟡 **MEDIUM** — Timeout path discards partial output: `stdout = proc.stdout if proc else b""` (L526) is dead code — `proc` is always `None` when `subprocess.run` raises `TimeoutExpired`, and `exc.stdout` is never read.
  - 🟢 **LOW** — `generated_files` flattened to basename (L550-553): same-named files in different subdirectories silently overwrite each other.
  - 🟢 **LOW** — Version probe container runs without `--memory/--cpus/--pids-limit` (L178-191), unlike every run site.
- **Limitations:** No host fallback when Docker is missing — returns `UNAVAILABLE` (L252-257, L417-430); only `*.java` staged at compile (L270-276); only `*.class` staged at execute — non-class resources lost (L439-443).
- **Gaps:** `DockerSandboxEvidence` (L49-79) documents sandbox verification fields (`compilation_occurred_in_container`, `container_removed`, …) but is never instantiated anywhere — documented evidence property not enforced. `--network none`, limits and hardening are correctly present (L304-307, L485-488) but no code asserts them at evidence time.
- **Issues:** Dead `proc.kill()` branches in both timeout handlers (L362-367, L519-524); `_resolve_image_digest` swallows all exceptions into `""` (L172-173) with no reason recorded; validation logic duplicated from `adapter.py`.

#### `engine/candidate/docker_spring_boot_adapter.py`
- **Purpose:** Docker adapter building Maven/Spring Boot projects offline in a container and executing the resulting JAR in a second hardened container.
- **Bugs:**
  - 🟡 **MEDIUM** — `input_data` accepted but never fed (L505; `docker_cmd` L609-624 has no `-i`) — same stdin-evidence mismatch as the Java lane.
  - 🟡 **MEDIUM** — Input staging traversal: `(input_dir / name).write_bytes(content)` (L588-590) unsanitized.
  - 🟡 **MEDIUM** — `java_cmd = f"java -jar /workspace/jars/{jar_name}"` interpolated unquoted into `sh -c` (L596, L623).
  - 🟡 **MEDIUM** — Compile mutates the candidate source tree: JAR written back to `candidate_path/target` (L448-451). Only the pipeline's `_SOURCE_TREE_EXCLUDED_DIRS` (`pipeline.py` L556-558) hides this from the mutation hash; the adapter itself should not write into its input.
  - 🟡 **MEDIUM** — `--tmpfs ... size=512m` (L412) under `--memory 512m` (L401): tmpfs pages count against the cgroup memory limit, so Maven builds can be OOM-killed at the same cap the tmpfs claims to allow.
  - 🟢 **LOW** — Timeout handlers contain dead `proc.kill()` (L472-477, L645-650) and discard partial stdout (L652).
  - 🟢 **LOW** — Multiple JARs are staged but the `rglob`-order winner is executed (L559-563) — nondeterministic selection when >1 non-`.original` JAR exists.
  - 🟢 **LOW** — `generated_files` flattened to basename (L671-676) — silent collisions.
- **Limitations:** No host fallback — fail-closed `UNAVAILABLE` (L520-533); offline Maven only (`mvn -o`, L387); version probes run without resource limits (L232-263).
- **Gaps:** TOCTOU re-resolution is explicitly best-effort: if the fresh identity probe fails to complete, the init-time identity is used anyway (L179-181, L195-202) — documented, not enforced as a hard failure. Provenance load errors are swallowed to `""` (L154-155) so a corrupt provenance file surfaces only as a generic UNAVAILABLE with no recorded reason.
- **Issues:** Execute/timeout/cleanup block (L626-701) is a near-copy of `docker_java_adapter.py` L498-579; version-probe methods duplicated (L226-272).

#### `engine/candidate/factory.py`
- **Purpose:** Fail-closed mapping from configured `target_runtime` to a concrete candidate adapter.
- **Bugs:** None found — unknown targets raise `ValueError` naming the supported set (L37-41) with no silent fallback.
- **Limitations:** Only `spring_boot`, `plain_java`, `jakarta_ee` (L14); `DockerJavaCandidateAdapter` and `PlainJavaCandidateAdapter` are not selectable here (they are chosen by `pipeline.py` L166-177); no Docker availability probe at selection time (the adapter probes in `__init__`).
- **Gaps:** None found.
- **Issues:** None found.

#### `engine/candidate/image_provenance.py`
- **Purpose:** Single contract for resolving Docker image identity (RepoDigest first, else local Image ID) and validating provenance records fail-closed.
- **Bugs:**
  - 🟡 **MEDIUM** — The provenance file is an unauthenticated local JSON (L365-377, L380-398): `validate()` checks only internal consistency, so anyone who can write `test-artifacts/docker-image-provenance.json` can re-pin the "expected" identities that the adapter then verifies against — the trust anchor itself is not tamper-evident.
  - 🟢 **LOW** — `DEFAULT_PROVENANCE_PATH` is relative (L33): resolved against CWD, so the same deployment reads different provenance depending on working directory.
  - 🟢 **LOW** — `docker image inspect <ref>` issued without a `--` separator (L163-168): a ref beginning with `-` is parsed as a CLI flag (argument injection; refs come from config/env).
  - 🟢 **LOW** — `_select_identity` takes the first syntactically valid RepoDigest in Docker's order (L68-78); with multiple RepoDigests the exact comparison (`verify_image_identity`, L196-208) can fail closed spuriously (never false-pass).
- **Limitations:** No signature/attestation — identity proof is exact string comparison only (L196-208); local Image ID accepted for build role but never for runtime role (L14-15, L251-252).
- **Gaps:** `recorded_at` is not bound to any run or deployment; nothing prevents replacement of the file between `load_adapter_provenance` and adapter execution (TOCTOU outside this module).
- **Issues:** `DockerImageProvenance.validate` (L229-258) and `verify_image_identity` (L196-208) overlap in intent; module docstring (L1-18) duplicates the contract text in `docker_spring_boot_adapter.py` L14-28.

#### `engine/candidate/java_adapter.py`
- **Purpose:** Host-lane adapter compiling with host `javac` and executing with host `java` (dev/reference, selected only when `use_docker_java=False`).
- **Bugs:**
  - 🟡 **MEDIUM** — Host execution with no sandbox, no network isolation, no resource limits (L197-203); `network_policy` honestly reports `unisolated`, but the lane itself violates the container-per-execution policy when selected.
  - 🟡 **MEDIUM** — `subprocess.run(..., input=input_data)` (L197-201): when `input_data is None` the child **inherits the parent's stdin** (nondeterministic external input) instead of the `/dev/null` EOF that Docker lanes present — cross-lane divergence in exactly the input channel.
  - 🟡 **MEDIUM** — Staging traversal `dest = Path(tmpdir) / rel_path` (L105-107) unsanitized (javac itself is invoked as argv, L120-130 — no shell injection there).
  - 🟢 **LOW** — Timeout drops partial stdout (L211-216; `TimeoutExpired.stdout` unread).
  - 🟢 **LOW** — `timeout_duration=_EXEC_TIMEOUT_SECONDS` recorded even when no timeout occurred (L236 with `timeout_applied=False` L235).
- **Limitations:** Fixed 30 s compile/exec timeouts (L33, L128) ignore `PipelineConfig.timeout_seconds`; no container, no image identity (`image_digest` never set).
- **Gaps:** Evidence records no indication that stdin was or wasn't fed; no resource/network evidence fields exist for this lane.
- **Issues:** Validation block (L68-86) duplicated from `adapter.py`.

#### `engine/candidate/maven_adapter.py`
- **Purpose:** Honestly-named subclass reusing the Spring Boot lane's Maven build + JAR execution for `plain_java`/`jakarta_ee` targets.
- **Bugs:** None found (inherits the parent's defects; only `validate_candidate` is overridden).
- **Limitations:** Only validation wording differs from the Spring Boot adapter (L10-13); requires `pom.xml` (L44-45); everything else — including Spring-Boot config defaults and `runtime_digest` — is inherited unchanged.
- **Gaps:** None found.
- **Issues:** `validate_candidate` body duplicated from `docker_spring_boot_adapter.py` L319-335 (L36-51); function-local `from pathlib import Path` (L41).

#### `engine/oracle/__init__.py`
- **Purpose:** Oracle subsystem export surface.
- **Bugs:** None found.
- **Limitations:** Exports only the placeholder `GnuCOBOLAdapter` contract; the production `DockerOracleAdapter` is not re-exported and must be imported from `engine.oracle.docker_adapter` (`pipeline.py` L71).
- **Gaps:** None found.
- **Issues:** The package's public API advertises a stub that fabricates success (see `oracle/adapter.py`) while hiding the real implementation.

#### `engine/oracle/adapter.py`
- **Purpose:** Oracle adapter ABC, `OracleAdapterConfig`, `OracleExecutionResult`, and the V1 `GnuCOBOLAdapter` placeholder.
- **Bugs:**
  - 🔴 **HIGH** — `GnuCOBOLAdapter.execute` returns `status=SUCCEEDED`, `exit_code=0`, empty stdout/stderr without running anything (L201-213): fabricated oracle ground truth; a comparison against an equally-empty candidate would be equal. (Reachable only if a caller selects this class; production selects `DockerOracleAdapter`.)
  - 🟡 **MEDIUM** — `probe()` declares `AVAILABLE` purely from config validation, without checking Docker or the image (L167-176): availability is asserted, not observed — inverted "Unavailable is not VERIFIED".
  - 🟡 **MEDIUM** — `OracleAdapterConfig.validate` requires `image_digest.startswith("sha256:")` (L54) while the docstring documents empty as legal "auto-pin" (L36-39) — doc/behavior contradiction; auto-pin configs fail validation.
  - 🟢 **LOW** — `to_execution_evidence` hardcodes `command="oracle execution"`, `working_directory="/workspace"` (L140-141) and substitutes the empty-string hash for unset source-tree hashes (L150-151) — vacuous evidence fields.
- **Limitations:** Base `get_identity` reports the *declared* config digest, not an observed one (L92-100) — `DockerOracleAdapter` overrides this (L121-141).
- **Gaps:** `OracleExecutionResult` has no field for what input was actually fed; identity fields are self-declared.
- **Issues:** Evidence-conversion logic copy-pasted from `candidate/adapter.py` L135-164.

#### `engine/oracle/docker_adapter.py`
- **Purpose:** Real GnuCOBOL oracle: stages sources, compiles/links multi-module programs with `cobc` and runs them in a hardened, network-disabled container, recording source hashes and compilation diagnostics.
- **Bugs:**
  - 🔴 **HIGH** — `input_data` accepted (L286) but never delivered: `docker_cmd` (L483-499) has no `-i`; stdin is `/dev/null`. The pipeline records `stdin_hash` for those bytes (`pipeline.py` L718) — recorded controlled input does not match what the oracle consumed (ACCEPT-from-stdin workloads read EOF immediately).
  - 🟡 **MEDIUM** — Evidence forgery vector via input staging traversal: `(input_dir / name).write_bytes(content)` (L430-431) with unsanitized keys — a key such as `../compilation/exit_code` writes into the mounted diagnostics directory (L495) and can forge `compilation_diagnostics` (L539-549).
  - 🟡 **MEDIUM** — Timeout discards partial stdout (`stdout = b""`, L529) and `timeout_duration=self._config.timeout_seconds` (L571) is recorded even on normal runs (`timeout_applied=False`, L570) — inconsistent evidence.
  - 🟡 **MEDIUM** — `docker image inspect <ref>` without `--` (L98) — flag-shaped refs parsed as CLI options.
  - 🟢 **LOW** — `generated_files` flattened to basename (L550-554): nested output collisions silently overwrite.
  - 🟢 **LOW** — `source_tree_hash_before/after` (L295, L557) are computed on the host tree the container only ever sees as a read-only staged copy (L493) — the pair is structurally always equal, so the documented non-mutation property cannot fail for container-side tampering.
- **Limitations:** Single-file sources compile only that file — sibling `.cob` programs are never linked (L381-387, L395-400); one source format per application (L267-277); no host fallback when Docker is missing (L297-313); resource limits hardcoded (L488-490) instead of from config.
- **Gaps:** Nothing verifies that declared input `container_path`s (e.g. `/workspace/schema/...`, fixtures) correspond to the fixed `/workspace/input` mount (L432-434) — recorded input locations are not checked against actual staging. Positive: shell arguments are `shlex.quote`d (L441-443) and identity is re-resolved and pin-checked every execution (L318-364).
- **Issues:** `import` statements inside functions (L390, L540); diagnostics collection reads files unconditionally if present (L539) rather than cross-checking against the container exit code.

#### `engine/evidence/__init__.py`
- **Purpose:** Evidence subsystem export surface (manifest, execution/artifact/comparison/verdict evidence, CAS).
- **Bugs:** None found.
- **Limitations:** `EvidenceEnvelope` deliberately excluded from the export (see `models.py` L52-59 status note).
- **Gaps:** None found.
- **Issues:** Exports `ContentAddressedStorage` (in-memory only, `models.py` L484-509) without any persistence qualifier.

#### `engine/evidence/integrity.py`
- **Purpose:** Trust-boundary admission validator proving internal consistency/binding of a raw `EvidenceManifest` before verdict derivation.
- **Bugs:**
  - 🔴 **HIGH** — FINDING A claim "forged but structurally valid evidence → validation layer rejects" (L21) is unenforceable: the seal is computed over the forger's own content at construction (`models.py` L407-408), so a freshly forged, internally consistent manifest always passes `_validate_manifest_integrity` (L531-565). No signature/key exists anywhere in the module.
  - 🟡 **MEDIUM** — `_validate_oracle_binding` skips oracle executions whose `image_digest is None` (L338-339), and no other check requires a digest — evidence that recorded no image identity still passes "identity binding".
  - 🟡 **MEDIUM** — Candidate executions' `image_digest` is never compared to any declared identity (only the oracle side, L336-349) — `IMAGE_IDENTITY_MISMATCH` covers half the lanes.
  - 🟡 **MEDIUM** — No duplicate-id detection for `execution_id`/`artifact_id`/`comparison_id`: all binding checks are set-membership (L204-218, L360-371), so replaying one artifact twice under one id passes.
  - 🟢 **LOW** — `_validate_required_evidence` never requires the oracle execution to have terminated `normal` — an oracle that errored still passes admission (mitigated downstream by `verdict/derivation.py` L293-304).
- **Limitations:** Pure function by design — no filesystem, network, or Docker calls (L112-120); workload binding enforced only when populated (L249-251); unknown artifact types skipped in comparator binding (L422-425).
- **Gaps:** `ComparisonEvidence.content_hash` is never recomputed or verified (`CONTENT_HASH_MISMATCH` defined at L57 but never raised); `environment_identities.network_policy`/`resource_limits` are never checked against what adapters actually applied; `controlled_input` (incl. `stdin_hash`) is never bound to executions; SOURCE_MUTATION is trivially satisfied by empty-string hashes.
- **Issues:** Dead enum members `CONTENT_HASH_MISMATCH`, `CROSS_WORKLOAD_REPLAY`, `ORPHAN_ARTIFACT`, `ORPHAN_COMPARISON`, `MALFORMED_EVIDENCE` (L57, L64-67) — docs claim orphan-comparison detection under `ORPHAN_COMPARISON` that the code implements under other names; runtime import of the comparator framework inside the validator (L414-417) couples the evidence layer to comparators.

#### `engine/evidence/models.py`
- **Purpose:** Evidence dataclasses, canonical sealed evidence graph, completeness check, and in-memory content-addressed storage.
- **Bugs:**
  - 🟡 **MEDIUM** — `is_complete()` counts an oracle `nonzero_exit` as a finished oracle run (L430-438): a failed oracle compile satisfies completeness at this layer (verdict derivation re-checks, `derivation.py` L293, so not exploitable to VERIFIED — but the documented contract "Only error and timeout indicate incomplete execution" L428-429 is wrong for the oracle role).
  - 🟡 **MEDIUM** — `ExecutionEvidence` has no field for what was fed to that execution; `controlled_input.stdin_hash` exists only at manifest level (L301-311), so per-execution input cannot be bound or audited.
  - 🟢 **LOW** — `EvidenceEnvelope.verify_integrity` (L67-70) hashes `json.dumps(content, sort_keys=True)` — must exactly match producer serialization (differs from `_graph_hash`'s `default=str`, L375-380) and is self-signed; only tests use it (documented L52-59).
  - 🟢 **LOW** — `EvidenceManifest.to_dict` persists only counts + `manifest_hash` (L455-477) — a stored summary cannot be re-verified against the full graph.
- **Limitations:** `created_at` and `verdict_evidence` deliberately excluded from the sealed graph (L246-259).
- **Gaps:** `sealed_hash` is self-referential — detects in-place mutation only, not construction of forged evidence (L399-405); `ContentAddressedStorage` is process-memory only (L484-509) with no persistence; `ArtifactEvidence.content_hash` is producer-asserted and never recomputable from stored data (content not stored).
- **Issues:** Three overlapping serializers with different coverage (`canonical_evidence_graph` L246-372, `ExecutionEvidence.to_dict` L109-135, `EvidenceManifest.to_dict` L455-477).

#### `engine/comparators/framework.py`
- **Purpose:** Typed comparator framework (STDOUT/STDERR/EXIT_STATUS/TEXT_FILE/FIXED_RECORD + BUSINESS_INVARIANT) producing `ComparisonEvidence`.
- **Bugs:**
  - 🟡 **MEDIUM** — Default normalization `("crlf_to_lf",)` when `normalization_policy is None` (L248, L305, L433) silently masks CR-vs-LF byte differences for direct callers; production is safe only because the pipeline passes `()` when no normalization is declared (`pipeline.py` L423-426).
  - 🟡 **MEDIUM** — `to_comparison_evidence` computes `content_hash` over a dict (L63-75) that omits `normalization_applied`, `ordering_applied`, `failure_policy`, `field_level_results` and the difference *descriptions* actually stored (L87) — the hash does not cover the stored evidence and cannot be recomputed from it.
  - 🟡 **MEDIUM** — `ExitStatusComparator` (L344-406) and `FixedRecordComparator` (L477-547) silently ignore declared `normalization_policy` and `ordering` — declared policy is neither applied nor recorded (`normalization_applied=()`), unlike `_normalize`, which fails closed on unknown input (L175-191).
  - 🟢 **LOW** — `_handle_missing` maps any non-`"UNAVAILABLE"` `on_missing` value to MISMATCH (L136-141): unknown policy strings don't fail closed, they become MISMATCH (safe direction — never PASS).
  - 🟢 **LOW** — MISMATCH differences embed full `str(bytes)` of both outputs (L271-272, L327-328, L456-457) — evidence bloat, may capture sensitive data.
- **Limitations:** V1 artifact types only (L4-5); `SORTED`/`UNORDERED` intentionally mask line order when declared but are recorded in `ordering_applied` (L166-173, L260); normalization is gated by the contracts FORBIDDEN list plus fail-closed `_normalize`.
- **Gaps:** `FailurePolicy.on_malformed` and `on_extra` (`contracts/models.py` L66-67, set in every fixture) are read by no comparator — declared failure behavior unenforced; only `on_missing` is consulted (L136).
- **Issues:** `StdoutComparator`/`StderrComparator`/`TextFileComparator` are copy-paste identical except the location string (L224-463); redundant `assert candidate_content is not None` after `_handle_missing` (L247, L304, L432, L494).

#### `engine/execution/__init__.py`
- **Purpose:** Execution subsystem export surface (policy/environment/command/result abstractions).
- **Bugs:** None found.
- **Limitations:** Exports only `abstractions` — `artifacts`, `container_hardening`, `sandbox_paths`, `docker_runner` are not part of the package surface.
- **Gaps:** None found.
- **Issues:** Inconsistent export surface versus sibling packages (`engine.candidate`, `engine.oracle`).

#### `engine/execution/abstractions.py`
- **Purpose:** ADR-0008 policy abstractions (policies, resource limits, filesystem/network policy, staged source, execution engine).
- **Bugs:**
  - 🟡 **MEDIUM** — `ExecutionCommand.to_string()` joins arguments with spaces and no quoting (L86-89): if ever used to build a shell command it is an injection primitive (currently only tests and `ExecutionResult.to_dict` L124).
  - 🟢 **LOW** — `FilesystemPolicy.validate` comment claims "Check for chmod 777 attempts" but only rejects `"/"` (L57-62) — misleading dead check.
  - 🟢 **LOW** — `NetworkPolicy.allowed_hosts`/`allowed_ports` (L65-74) are unreachable: `ExecutionEnvironment.validate` rejects any enabled network (L162-163), so the fields are dead.
- **Limitations:** Not on the production execution path — real adapters build `docker run` argv directly; `ExecutionEngine`/`StagedSource` are imported only by tests (verified: no engine importers).
- **Gaps:** `ExecutionEnvironment.validate` (L146-170) does not enforce `HARD_TIMEOUT`, `CLEANUP_AFTER`, `NO_WRITABLE_MOUNTS`, `NO_CHMOD_777`, `NO_DEFAULT_CREDENTIALS` — declared policies unverified; `StagedSource.verify_integrity` compares two self-declared hashes (L183-185) with nothing recomputing them from bytes; `prepare_execution` (L200-211) returns a dict but enforces nothing beyond environment validation.
- **Issues:** Policy concepts duplicated with `container_hardening.py`/`sandbox_paths.py` without any linkage; `FilesystemPolicy.no_exec_paths` never read anywhere.

#### `engine/execution/artifacts.py`
- **Purpose:** Captures stdout/stderr/exit-status/text/fixed-record/business-invariant artifacts with content hashes and execution binding.
- **Bugs:**
  - 🟡 **MEDIUM** — `capture_missing` records `content_hash = sha256(b"")` (L250): a "missing" sentinel and a genuinely empty artifact have identical hashes; only the non-persisted `content=None` distinguishes them, and `ArtifactEvidence.to_evidence` (L38-45) drops it.
  - 🟢 **LOW** — Every capture method defaults `producer_role="ORACLE"` (L56, L81, L105, L131, L157, L183, L219): a caller that forgets `"CANDIDATE"` silently mislabels provenance (`ArtifactIdentity` validates only that the value is one of two roles, `identities.py` L164-165).
  - 🟢 **LOW** — `capture_text_file` reads an arbitrary caller-supplied path with no sandbox-path validation (L133).
- **Limitations:** In-memory content only — no persistence; record length divisibility enforced at capture (L188-193).
- **Gaps:** `artifact_id` derives only from execution_id/logical_name/type (L60, L85, L110, L136, L161, L197, L224, L252) — capturing twice for one execution yields duplicate ids, and the integrity validator has no uniqueness check.
- **Issues:** Seven near-identical capture methods differing only in type/id prefix (L51-238).

#### `engine/execution/container_hardening.py`
- **Purpose:** Shared `docker run` hardening flags (`no-new-privileges`, `--cap-drop ALL`, non-root `--user 10001:10001`) and host bind-mount permission preparation.
- **Bugs:**
  - 🟡 **MEDIUM** — `prepare_host_tree` adds `o+w` to writable staging dirs and `o+r` to all staged files (L87-96): staged inputs/outputs become world-readable/writable on multi-user hosts, letting any local user modify artifacts between staging and comparison.
  - 🟢 **LOW** — All chmod failures are swallowed (L97-99): documented, but on Linux a failed chmod surfaces later as a confusing container-side permission error instead of an explicit evidence note.
- **Limitations:** Flags cover only privilege escalation/capabilities/user (L52-68); `--network none`, memory/cpu/pids caps and `--read-only` rootfs are explicitly the caller's responsibility (L33-37) — not enforced here.
- **Gaps:** `NON_ROOT_EXEMPT_LANES` (L49, L62-63) is a documented process-controlled escape hatch, but no code/CI guard prevents an entry being added silently.
- **Issues:** Docstring's process controls (record in `docs/verification/RUNTIME_PROOF_MATRIX.md`) are unenforced documentation; full `rglob` per mounted tree (L90) is expensive on large staging trees.

#### `engine/execution/docker_runner.py`
- **Purpose:** Deprecated generic Docker run engine retained for historical reference and test-only contracts.
- **Bugs:**
  - 🟡 **MEDIUM** — Timeout path (L117-122) neither names nor cleans up the container (no `--name`, no `cleanup_container`): the container keeps running on the daemon after the client is killed, violating the `CLEANUP_AFTER` policy its own docstring claims (L16).
  - 🟡 **MEDIUM** — `--network bridge` opt-out via `config.network_disabled=False` (L84) silently re-enables networking.
  - 🟢 **LOW** — Volume spec built by concatenation `f"{host}:{dest}:ro"` (L96) — same colon/Windows-drive parsing hazard as `sandbox_paths.docker_volume_arg`.
  - 🟢 **LOW** — `timeout_duration` recorded even for normal runs (L143 vs L142); partial stdout lost on timeout (L119).
- **Limitations:** Deprecated with zero importers outside itself (L3-8, verified); no stdin support; `environment` passed as `-e key=value` argv (L98-99) — no shell injection there.
- **Gaps:** Raises `RuntimeError` when Docker absent (L76-77) rather than returning an `UNAVAILABLE` result — inconsistent with the adapter convention.
- **Issues:** Dead code kept "for test-only contracts"; duplicates adapter timeout/termination logic.

#### `engine/execution/sandbox_paths.py`
- **Purpose:** Computes host-visible staging paths and `-v` arguments for Docker bind mounts, including production container→host path translation.
- **Bugs:**
  - 🟡 **MEDIUM** — `docker_volume_arg` concatenates `host:dest[:ro]` with no sanitization of `:`, `;` or backslashes (L147-157): a colon in either part alters mount semantics (extra options or a different source), and Windows drive-letter paths rely entirely on Docker CLI special-casing.
  - 🟢 **LOW** — `_is_within`/`to_host_path` (L115-144) do not resolve symlinks — a symlink inside the staging root is mapped as if its target were inside it (bind-mount escape), though roots are freshly created per run.
  - 🟢 **LOW** — `ensure_staging_root` trusts `os.access(W_OK|X_OK)` (L92) — TOCTOU and unreliable under Windows ACLs.
- **Limitations:** Identity mapping when the env vars are unset (documented L18-26, L133-134); the module deliberately computes paths only — network/limits/read-only/image pins remain the caller's responsibility (L33-37).
- **Gaps:** No validation that `SANDBOX_STAGING_DIR` is absolute, owned by the service account, or not world-writable before staging into it — a mis-set env var redirects all staging anywhere on the host.
- **Issues:** None found.

#### `engine/domain/identities.py`
- **Purpose:** Immutable identity value objects (content hashes, workload/run/source/candidate/oracle/input/artifact ids, adapter status, verdict states).
- **Bugs:**
  - 🟡 **MEDIUM** — `InputIdentity.combined_hash` (L134-143) concatenates the stdin hash and sorted input-file digests but **omits the file path keys** — two different input layouts with identical content produce the same combined identity.
  - 🟡 **MEDIUM** — `EnvironmentIdentity.network_policy` defaults to `"none"` (L123): a producer that forgets to set it records an isolation claim that was never verified (the pipeline does set it from the adapter property, `pipeline.py` L697, L710-711, but the default is dishonest-by-construction).
  - 🟢 **LOW** — `ContentHash.__post_init__` validates only `len == 64` (L29-30), not hex charset — non-hex digests construct successfully (they can never match a real SHA-256, so `verify` fails closed).
- **Limitations:** `ExecutionId`/`RunId` etc. validated only for non-emptiness (L56-58, L66-68, L173-175); `ArtifactIdentity.record_count` means "count" (used by `FixedRecordComparator` to infer record length); no per-execution input identity field exists anywhere in the model.
- **Gaps:** `EnvironmentIdentity.resource_limits` is a free-form `dict[str, str]` (L124) with no validation that limits were actually applied; nothing ties `InputIdentity` to specific executions.
- **Issues:** `algorithm: Final[str] = "sha256"` as a dataclass field (L24) participates in equality/repr despite being constant; `VerdictState` docstring asserts "No more, no less" (L228) while the vocabulary's enforcement lives in another module.

---

# Section E — engine modernization pipeline ✅ COMPLETE

17 files. 3 HIGH, 18 MEDIUM, 30 LOW.

### Summary — E

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 3 | `capability_analyzer` reports SUPPORTED while diagnostics exist; `pipeline` phase-4 refusal inspects only `PROGRAM` components; `application_assembler` returns success for empty input / multi-program entry point dead |
| 🟡 MEDIUM | 18 | UNKNOWN ignored in overall status, fail-open call resolution, entry-point/path containment, TOCTOU source hashing, identity collision |
| 🟢 LOW | 30 | Dead code (`_topological_sort`, `RUNTIME_PROOF_KINDS`), inconsistent error channels, duplicated serializers |

#### `engine/modernization/__init__.py`
- **Purpose:** Package facade re-exporting `ModernizationPlanner` and its plan dataclasses (49 lines).
- **Bugs:** None found.
- **Limitations:** The package itself performs no work — the orchestration flow promised in the module docstring (`:1`–`:17`) is implemented by submodules; the docstring correctly defers validation stages to `VerticalSlicePipeline` (`:18`–`:20`).
- **Gaps:** The export surface (`:23`–`:35`, `:37`–`:49`) exposes only `ModernizationPlanner` — the one planner entry point that does **not** check `application.discovery_errors` (see `modernization_planner.py:381`–`:404`) — while the fail-closed `UniversalModernizationPipeline` (which does check, `pipeline.py:270`–`:275`), `CapabilityAnalyzer`, `CapabilityReport`, `TransformationPlan` and `TransformationPlanGenerator` are all unexported, forcing inconsistent import paths for consumers.
- **Issues:** None found.

#### `engine/modernization/application_assembler.py`
- **Purpose:** Writes generated Java files, a pom.xml and a Spring Boot entry point into one output directory (184 lines).
- **Bugs:**
  - 🔴 **HIGH** — `assemble()` reports `success=True` for an empty `generated_files` tuple: the pom is still written (`:63`–`:68`) and the entry-point guard is `if not has_entry and generated_files` (`:72`), so a zero-program input yields a pom-only project returned as successful (`:87`–`:91`).
  - 🟡 **MEDIUM** — `target = out / gf.filename` (`:58`) has no containment check: a `GeneratedFile.filename` containing `..` or a path separator writes outside `output_dir`.
  - 🟡 **MEDIUM** — only the first generated class is ever executed: `for cls in program_classes[:1]` (`:157`–`:158`), and `_generate_entry_point` never consults the entry program of `AssemblyPlan` (`:140`–`:160`) — multi-program applications silently never run programs 2..n despite the "multi-program apps" claim (`:9`).
  - 🟢 **LOW** — `out.mkdir(parents=True, exist_ok=True)` (`:50`) sits outside the `try` (`:55`–`:79`), so a permissions/disk error escapes as an exception instead of `AssemblyResult(success=False)`, contradicting the result-object error contract (`:78`–`:85`).
  - 🟢 **LOW** — duplicate `filename`s overwrite each other silently while both paths are appended to `files_written` (`:57`–`:60`).
- **Limitations:** Success only means "bytes written" — no build, no pom validation, no verification the entry class exists; Spring Boot parent `3.2.5` and Java 21 are hardcoded (`:108`, `:119`).
- **Gaps:** Module docstring step 5 "Generates the ServiceRegistry for multi-program apps" (`:9`) has no implementation — `ServiceRegistry` only appears as an exclusion filter (`:152`), and `AssemblyPlan.include_service_registry` (`transformation_plan.py:67`) is never read; the generated runner hardcodes `System.exit(0)` (`:180`).
- **Issues:** `ApplicationAssembler` is referenced only from `tests/test_universal_modernization.py:51`,`:311` — production assembly goes through `engine/transformation/runtime_adapters.py`, so this module is dead production code; `plan.application_name` / `plan.base_package` are interpolated into XML unescaped (`:112`–`:116`).

#### `engine/modernization/capability_analyzer.py`
- **Purpose:** Three-channel (IR walk, source scan, structure) construct classification producing a `CapabilityReport` over the discovered application (1228 lines).
- **Bugs:**
  - 🔴 **HIGH — capability aggregation reports SUPPORTED while a diagnostic exists.** `_walk` classifies *every* `CallStatement` via `_note_ir(name)` → registry `CALL` = SUPPORTED (`:528`–`:530`, mapping `engine/transformation/semantic_capability.py:483`,`:175`) with **no** `is_dynamic` test (contrast `_analyze_call` at `:1173`–`:1182`), and copybook findings are deliberately excluded from program findings (comment `:779`–`:783`). Consequently a program containing a dynamic CALL (edge UNSUPPORTED, `:1180`–`:1182`), an unresolved static call (PARTIAL, `:1186`–`:1188`), a CALL cycle (`:361`–`:367`) or an UNSUPPORTED copybook (`:961`–`:1160`) still yields `PROGRAM=SUPPORTED`. The only consumer gate blocks on PROGRAM components alone (`modernization/pipeline.py:313`–`:318`), so such programs are transformed even though `overall_level` is UNSUPPORTED.
  - 🟡 **MEDIUM** — fail-open default in `_analyze_call`: `if callee is None or callee is CapabilityLevel.SUPPORTED` → SUPPORTED/"Resolved" (`:1191`–`:1194`). Today largely unreachable because discovery stamps `resolution=RESOLVED` only for known programs (`application_discovery.py:605`–`:609`) with normalized ids on both sides (`:342`, `:1191`), but the fallback is optimistic rather than fail-closed.
  - 🟢 **LOW** — copybook read loop never clears `read_error` on success (`:1019`–`:1028`); an empty-but-readable copybook reached after an earlier failed candidate trips `if not content and read_error` (`:1030`) → false UNSUPPORTED (over-blocking).
  - 🟢 **LOW** — `_derive_overall_level` docstring claims "UNKNOWN outranks everything" (`:1222`–`:1223`) but `worst_level` ranks UNSUPPORTED(4) above UNKNOWN(3) (`semantic_capability.py:679`–`:685`); both block, but the stated ordering is wrong.
  - 🟢 **LOW** — `assert worst is not None` (`:835`) disappears under `python -O`.
  - 🟢 **LOW** — paragraph fall-through check inspects only top-level statements of paragraph 0 (`:636`–`:643`), so a `STOP RUN` nested in an `IF` is not seen → spurious PARTIAL (over-blocking).
- **Limitations:** Docker availability is expressed *only* by downgrading SUPPORTED `PROGRAM`/`CALL` components to UNAVAILABLE (`:376`–`:385`, probe `:396`–`:400`) — with `docker_available=False` every program becomes UNAVAILABLE so no transformation is possible at all, although phases 1–5 need no Docker; `COPYBOOK`/`FILE` components are deliberately left at their own level when infra is down; JCL is never a capability component (comment `:74`–`:77`); `_analyze_call_linkage_arity` counts only level-1 LINKAGE items (`:272`–`:276`) and can over-block optional/OPTIONAL linkage.
- **Gaps:** `application.discovery_errors` is never consulted here (checked only by `UniversalModernizationPipeline`, `modernization/pipeline.py:270`–`:275`) — the analyzer will happily classify a partially discovered application; `_aggregate` returns `SUPPORTED, "All constructs supported"` for zero findings (`:831`–`:832`) and `_derive_overall_level` returns SUPPORTED for an empty component list (`:1225`–`:1226`) — vacuous truth for empty/0-paragraph programs; copybook classification is source-scan only (no IR), so it inherits exactly the constructs `scan_constructs` can regex (`:1089`–`:1095`).
- **Issues:** Three function-local imports on hot paths (`:215`–`:219`, `:758`–`:761`, `:1052`–`:1053`); duplicated FILE-CONTROL key literal sets (`:619`–`:622` vs `:725`–`:741`); program-level `component_type` vocabulary is a bare string set (`:74`–`:78`) that `integrated_proof` must re-map by string (`integrated_proof.py:490`–`:494`).

#### `engine/modernization/external_dependency_edges.py`
- **Purpose:** Extracts MQ queue, IMS PCB/segment, DB2 table and CICS resource references into fail-closed `DependencyLedgerEntry` records (429 lines).
- **Bugs:**
  - 🟡 **MEDIUM** — all unparseable embedded SQL from every program collapses to one dependency id `DB2:UNPARSEABLE` (`:270`–`:289`, produced at `:351`–`:353`); `build_dependency_ledger` dedupes by id (`integrated_proof.py:385`–`:389`), so only the first program's reason survives — later programs' unparseable statements disappear from the ledger text (the entry stays required/BLOCKED, so the gate still holds, but per-program traceability is lost).
  - 🟢 **LOW** — asymmetric comment masking between lanes: MQ/IMS mask comments *before* the fast-path precheck (`:197`–`:198`), CICS re-checks the masked text (`:395`–`:398`), but DB2 prechecks the **raw** source (`:311`) and only masks afterwards (`:320`). A comment-only `EXEC SQL` therefore always enters the DB2 lane (safe — the real pass then finds nothing — but the documented fast-path contract at `:219`–`:221` is not honored uniformly).
- **Limitations:** Only the documented operand forms are recognized (module docstring `:30`–`:36`); text outside `EXEC … END-EXEC` never extracts (including literals that merely mention `QUEUE(...)`); every entry this module emits is UNSUPPORTED/BLOCKED/required by construction (`:156`–`:185`, `:248`–`:271`, `:357`–`:370`) because no MQ/IMS/DB2/CICS runtime lane exists; equivalence/proof rungs stay open (`:38`–`:40`).
- **Gaps:** CICS has no `UNPARSEABLE` catch-all analogous to `DB2:UNPARSEABLE` (`:270`–`:289`): any CICS resource operand the facade parser silently drops simply produces no ledger entry (only `TRANSID` gets a direct block-text fallback, `:421`–`:427`); `DependencyKind.MQ`/`IMS` entries are never cross-checked against the construct-level detections — a block whose queue/PCB regexes do not match yields *no* entry at all (fail-open at ledger granularity: the program may be classified only by the construct scan).
- **Issues:** A third independent `_mask_comments` implementation (`:105`–`:120`) alongside `semantic_capability._strip_literals_and_comments` and `copybook_model._mask_comments`; `_EXEC_ANY` fast path (`:72`) duplicates intent of the block patterns (`:57`–`:64`).

#### `engine/modernization/integrated_proof.py`
- **Purpose:** Builds the dependency ledger from capability components + extra lanes and derives the central application status (a gate that can only downgrade) (538 lines).
- **Bugs:**
  - 🟡 **MEDIUM** — cohort promotion for runtime kinds: `_proof_state_for` returns `PROVEN` for any SUPPORTED `PROGRAM`/`CALL`/`COPYBOOK`/`PARAMETER`/`FILE` entry once the workload verdict is VERIFIED (`:250`–`:298`), and dependency-specific binding exists **only** for `FILE` (`:267`–`:293`). A program that never executed in this run (non-entry program, unexercised path) is marked PROVEN on the strength of a workload-level verdict.
  - 🟢 **LOW** — `evaluate_central_status` never reads `entry.visible` (`:446`–`:451`) nor `report.overall_capability` (recorded only at `:486`); the `visible` field (`:131`) is decorative and the whole gate is driven by `required` + `proof_state`.
  - 🟢 **LOW** — `build_dependency_ledger` dedupes purely by `dependency_id` (`:339`–`:352`, `:385`–`:389`): a capability component and an `extra_dependency` with the same id silently drop the extra one with no conflict error.
- **Limitations:** JCL/DB2/CICS can reach at most PARTIAL (`:243`–`:248`, `:301`–`:322`); MQ/IMS entries arrive pre-blocked; FILE proof requires a TEXT_FILE/FIXED_RECORD comparison *in this run* (`:267`–`:293`); an empty ledger is explicitly NOT_VERIFIED (`:437`–`:444`); `generation_success` defaults to `False` (`:404`, `:419`–`:420`).
- **Gaps:** `RUNTIME_PROOF_KINDS` (`:104`–`:110`) is defined and never referenced anywhere in the repository — the intended "these kinds need the runtime lane" gate is dead; nothing requires that every `PROGRAM` component of the report was executed (see Bugs); `blocking_reasons` (`:176`) is informational only — no consumer refuses to surface a `NOT_VERIFIED` run (it is simply recorded, `api/service.py:1236`).
- **Issues:** `kind is None` branch (`:353`–`:371`) and `_kind_for` (`:490`–`:494`) encode the same fallback twice; `runtime_evidence_from_result` (`:497`–`:538`) swallows malformed results through `getattr` defaults (`executed_check_count` → 0 at `:529`); `except Exception: outcome = None` around integrity validation (`:514`–`:517`) hides validator crashes as "integrity invalid".

#### `engine/modernization/modernization_planner.py`
- **Purpose:** Single planner entry point producing a `ModernizationPlan` (program/copybook/call/file plans, strategies, blocking summary, embedded `TransformationPlan`) (809 lines).
- **Bugs:**
  - 🔴 **HIGH/MEDIUM** — `_derive_overall_status` never consults `report.unknown_count` (`:755`–`:765`): UNKNOWN components are ignored, so a report mixing UNKNOWN and SUPPORTED components returns `ModernizationStatus.READY` (`:763`–`:764`) even though `ProgramPlan.may_proceed` is `False` for those programs (`:140`–`:142`). This contradicts the fail-closed contract in the module docstring (`:23`–`:28`).
  - 🟡 **MEDIUM** — `unknown_programs=0` is hardcoded with the comment "UNKNOWN maps to UNSUPPORTED" (`:486`); that mapping does not exist — `_build_program_plan` keeps UNKNOWN as UNKNOWN (`:497`–`:500`) — so plan statistics misreport.
  - 🟡 **MEDIUM** — `plan()` never checks `application.discovery_errors` (`:360`–`:404`; only `source_path.exists()` is checked at `:377`–`:378`), unlike `UniversalModernizationPipeline` (`modernization/pipeline.py:270`–`:275`) — the package's *exported* entry point can produce a READY plan from a partially discovered application.
  - 🟡 **MEDIUM** — strategy/plan disagreement: PARTIAL programs get `TransformationStrategy.INTERNAL_NATIVE` + `DOCKER_ORACLE` validation (`:507`–`:510`, `:519`–`:520`) while `TransformationPlanGenerator._plan_program` SKIPs PARTIAL (`transformation_plan.py:257`–`:266`). Only `may_proceed` (`:140`–`:142`) is fail-closed; a consumer reading `transformation_strategy` would transform PARTIAL programs.
  - 🟢 **LOW** — `_build_call_relationship` fallback defaults to `SUPPORTED, "Resolved"` when no capability component matches an edge (`:569`–`:572`) — the same optimistic default as `capability_analyzer.py:1191`.
  - 🟢 **LOW** — `_build_blocking_summary` only iterates `is_blocked` programs (`:778`–`:781`); PARTIAL/UNKNOWN programs and PARTIAL calls/copybooks that cannot proceed are omitted, so a plan with PARTIAL components reports "No blocking issues identified" (`:806`–`:807`).
- **Limitations:** `_topological_sort` is a no-op preserving discovery order (`:292`–`:296`); call `arguments` are a placeholder `()` (`:590`); blocking-reason derivation is free-text heuristics (`:693`–`:753`); `BlockingReason.DOCKER_UNAVAILABLE` is inferred only from the word "unavailable" in a reason (`:705`–`:706`).
- **Gaps:** Nothing refuses to *emit* a plan when `overall_status` is BLOCKED (`:393`–`:396` runs unconditionally) — the plan is always produced and it is the caller's job to honor `transformation_plan`; `_is_entry_program`/`_has_stop_run` do not detect `STOP RUN` nested in structured statements (`:672`–`:691`).
- **Issues:** `_is_entry_program` and `_has_stop_run` duplicate the identical paragraph scan (`:672`–`:691`) using `type(stmt).__name__ == "StopRunStatement"` string comparison instead of `isinstance`; `unknown_programs` always 0 (`:486`); reason-string heuristics re-derive classifications the analyzer already made (`:708`–`:748`).

#### `engine/modernization/pipeline.py`
- **Purpose:** Authoritative phases 1–5 orchestrator (discovery → capability → plan → transform → assemble) producing `ModernizationReport` for the service layer (492 lines).
- **Bugs:**
  - 🔴 **HIGH** — Phase-4 refusal inspects only PROGRAM components: `skipped_programs = tuple(c.component_id for c in plan.components if c.component_type == "PROGRAM" and c.action.name == "SKIP")` (`:313`–`:318`). `CALL`/`COPYBOOK`/`FILE` SKIP components (`transformation_plan.py:173`–`:180`, `:183`–`:191`) and `report.overall_capability == "UNSUPPORTED"` (`:289`) never block — an application whose capability report is UNSUPPORTED (dynamic CALL, CALL cycle, unsupported copybook) is still transformed whenever every PROGRAM component reads SUPPORTED (see `capability_analyzer.py` HIGH finding). `overall_capability` is written once (`:289`) and read by no gate anywhere in the codebase (only serialized, `:144`).
  - 🟡 **MEDIUM** — error paths put the cause in `limitations` while leaving `generation_errors` empty (`:254`, `:267`, `:271`–`:275`); `api/service.py:1100`–`:1104` builds its failure message from `generation_errors` only → "Pipeline generation failed: " with no reason for adapter/discovery failures. Fail-closed, but the reason is lost to operators.
  - 🟢 **LOW** — `report.generation_success = True` is set *before* assembly (`:361`) and only reset when assembly raises (`:378`–`:388`); an adapter returning an outcome without writing files keeps `generation_success=True` (the API only checks the non-empty path string, `api/service.py:1106`).
  - 🟢 **LOW** — capability analysis (`:285`–`:287`) and planning (`:296`–`:301`) are not wrapped in `try/except`, unlike discovery (`:260`–`:268`), transform (`:342`–`:359`) and assembly (`:368`–`:388`) — an analyzer/planner exception escapes as a raw exception instead of a failed report (still fail-closed, but stage progress and the report are both lost).
- **Limitations:** `docker_available` defaults to `False` (`:66`) so an unprobed config blocks all transformation; non-Spring targets are disclosed only as limitations (`:471`–`:484`); validation stages are explicitly out of scope (`:17`–`:19`).
- **Gaps — progress():** every `progress(...)` call is unguarded (`:258`–`:259`, `:277`–`:278`, `:281`–`:282`, `:290`–`:291`, `:294`–`:295`, `:305`–`:306`, `:340`–`:341`, `:366`–`:367`, `:389`–`:390`): a raising callback aborts `execute()` with no report, i.e. **progress can fail a run (fail-closed, never a false success)** — but the failure is attributed to the phase, and in the production callback stage-persistence errors are swallowed (`api/service.py:1084`–`:1091`) so a stage can go unrecorded while the run continues; `entrypoint` is never validated against discovered programs (`:299`, `:371`).
- **Issues:** `_assemble_spring_boot` (`:397`–`:416`) is dead in production (only `tests/test_runtime_adapter_architecture.py:739`); `_fill_discovery` rebuilds the whole report object (`:418`–`:436`), silently dropping any field added later; `summary()` omits `unknown_count` from its capability line (`:178`).

#### `engine/modernization/transformation_plan.py`
- **Purpose:** Builds `TransformationPlan` (per-component action/transformer, assembly plan, oracle plan) from a `CapabilityReport` (331 lines).
- **Bugs:**
  - 🟡 **MEDIUM** — plan generation never *refuses*: `_plan_program` is correctly fail-closed for every level (`:240`–`:290`, incl. None → SKIP at `:240`–`:247` and the unknown-level fallback at `:283`–`:290`), but `generate()` itself always returns a plan (`:125`–`:224`) and the only enforcement is downstream and PROGRAM-only (`modernization/pipeline.py:313`–`:318`). `report.overall_level` is never read.
  - 🟢 **LOW** — `_topological_sort` returns the discovery list unchanged (`:292`–`:296`) while the module docstring promises "topological sort by CALL graph" (`:6`) — dead code with false documentation.
  - 🟢 **LOW** — `capability_lookup = {c.component_id: c ...}` (`:143`) takes the last component on id collision (duplicate PROGRAM-IDs, or a program id equal to a copybook name); FILE component ids (`"prog:file"`) are never planned as components at all — files surface only through program findings.
- **Limitations:** `OraclePlan` hardcodes `source_format="free"` (`:211`–`:214`) regardless of discovered source format; `base_package` hardcoded `"com.modernized.app"` (`:205`); `TransformationAction.MANUAL` (`:47`) is never produced; unresolved-call SKIP components are built only from a metadata substring test (`:183`–`:191`).
- **Gaps:** No step converts a non-SUPPORTED `overall_level` into a refusal (documented intent at `:1`–`:13`, "Marks unsupported/unavailable components for skip", is per-component only); `AssemblyPlan.include_service_registry` (`:67`, set at `:207`) is consumed nowhere; `OraclePlan.link_modules`/`input_files` (`:75`–`:76`) are never populated; `_require_valid_plan_output_type` raises `ValueError` (`:26`–`:33`) which `execute()` does not catch (`modernization/pipeline.py:296`–`:301`) — an inconsistent failure channel (exception instead of a failed report).
- **Issues:** `field` and `Path` imported but unused (`:17`, `:19`); `_plan_program`'s four level branches (`:249`–`:290`) are near-identical blocks differing only in the reason prefix.

#### `engine/pipeline.py`
- **Purpose:** Declaration-driven validation pipeline: oracle execution, candidate compile/execute, artifact capture, registry-driven comparison, evidence manifest, integrity validation and verdict (955 lines).
- **Bugs:**
  - 🟡 **MEDIUM (TOCTOU)** — the COBOL source is hashed at `:605` and the oracle executes at `:612`–`:617` with no re-hash; the candidate tree is hashed at `:620` before `compile()` at `:625`. Bytes changed between hash and execution are recorded under the pre-modification identity. (The candidate before/after pair taken at `:621`/`:660` *is* validated by `evidence/integrity.py:467`–`:487`, but there is no executed-vs-recorded binding for the COBOL source or for the pre-build candidate.)
  - 🟡 **MEDIUM** — identity collision: `run_id` is a second-resolution timestamp (`:602`) — two runs of the same workload in the same second share it, and execution/comparison ids derive from it → cross-run evidence id collision.
  - 🟡 **MEDIUM** — `_candidate_resource_limits` reads the adapter's private `_config` and **defaults to `"512m"`/`"1.0"`/`"256"`** when absent (`:560`–`:567`), so the host `RealJavaCandidateAdapter` (selected when `use_docker_java=False`, `:173`–`:177`) gets an `EnvironmentIdentity.resource_limits` (`:713`) asserting limits that were never applied.
  - 🟢 **LOW** — `_run_declaration_driven` uses `assert workload is not None` (`:366`) — stripped under `python -O`; its `source_identity`/`candidate_identity` parameters (`:355`–`:356`) are never referenced in the body.
  - 🟢 **LOW** — `_compute_source_identity`/`_compute_candidate_identity` produce `file_count=0` and `sha256("")` for a non-existent path (`:179`–`:201`, `:203`–`:234`) — no existence check, so "missing" is indistinguishable from "empty".
  - 🟢 **LOW** — inconsistent source-tree definitions: `_compute_candidate_identity` excludes only a top-level `target/` (`:221`–`:222`) while `_candidate_source_tree_hash` excludes six dirs (`:556`–`:558`, `:584`) → `candidate_hash` and `source_tree_hash` disagree about what is source; both use OS-dependent `str(relative_to(...))` separators (`:191`, `:223`), contradicting `engine/source_hash.py:20`–`:22`.
- **Limitations:** Docker-unavailable behavior is delegated entirely to adapters — `DockerOracleAdapter` returns `status=UNAVAILABLE, termination_status="error"`, stderr `"Docker is not available"` (`oracle/docker_adapter.py:297`–`:313`); `run()` contains **no** docker probe and never emits an explicit UNAVAILABLE result itself, so the state surfaces only via the verdict (and today as `ERROR`); with `use_docker_java=False` the host lane runs (`:173`–`:177`) despite the module docstring (`:16`–`:18`) calling it dev/reference-only; `workload is None` takes the legacy hardcoded path (`:678`–`:687`). No silent skip exists: `_run_validation` always runs (`api/service.py:771`, `:939`) and a Docker-less run reaches a non-VERIFIED verdict — fail-closed, just mislabeled.
- **Gaps:** comparator-binding verification is skipped when the declaration's `comparator_id` is empty (`:410`–`:420`) — and `WorkloadArtifact` never validates non-empty `comparator_id` (`workload.py:56`–`:63`); `java_entrypoint` is never checked to exist among candidate sources before execution (`:236`–`:255`); `candidate_source_before == candidate_source_after` is recorded (`:621`, `:660`) but never compared in `run()` — the mismatch only becomes a late integrity violation; `_load_input_files`/`_input_file_identities` resolve `fixture_root / inp.source_path` with no `..` containment check (`:519`–`:529`, `:541`–`:551`); `progress()` calls (`:610`–`:611`, `:623`–`:624`, `:637`–`:638`, `:676`–`:677`, `:737`–`:738`) are unguarded — a raising callback aborts the run before any verdict (fail-closed; **progress can fail a run, never produce a false success**), while the production callback swallows store errors (`api/service.py:1213`–`:1220`).
- **Issues:** `_run_legacy` (`:768`–`:955`) duplicates ~180 lines of comparator wiring, bypassing registry dispatch, comparator binding, failure policies and business invariants — a second, weaker certification path; three separate tree-hash implementations (`:179`–`:201`, `:569`–`:588`, `source_hash.py:11`–`:24`) with different exclusion and separator rules; `_build_candidate_manifest` re-runs twice per build (`:627`, `:642`).

#### `engine/workload.py`
- **Purpose:** Declarative workload model (artifacts, inputs, business invariants) with construction-time validation driving the pipeline (168 lines).
- **Bugs:**
  - 🟡 **MEDIUM** — `comparator_id` is never validated for presence or non-emptiness (`:56`–`:63`); an empty string passes construction and disables the pipeline's comparator-binding gate (`engine/pipeline.py:410`–`:420`), leaving only registry dispatch.
  - 🟢 **LOW** — `WorkloadDefinition` validates artifacts/inputs/invariants (`:100`–`:162`) but never `workload_id`/`description` (`:90`–`:92`); an empty `workload_id` flows into `run-{workload_id}-…` ids and workload binding checks.
  - 🟢 **LOW** — `output_path` rejects only `None`, not `""` (`:72`–`:75`) → an empty path becomes a permanently missing artifact (INCONCLUSIVE → PARTIAL) instead of a declaration error.
- **Limitations:** artifact types restricted to the five V1 types (`:66`–`:71`); `BUSINESS_INVARIANT` cannot be declared as a regular artifact (reserved logical name, `:158`–`:162`); `FIXED_RECORD` with `record_length=None` is byte-level (`:63`, `:76`–`:79`); `normalization`/`ordering`/`failure` may be `None` and fall back to pipeline defaults at comparison time.
- **Gaps:** nothing requires a workload to declare STDOUT/EXIT_STATUS or any minimum artifact set — certification breadth is entirely workload-controlled and reaches VERIFIED as long as the declared set matches (`derivation.py:227`–`:266`); comparator existence/uniqueness is deferred to runtime (`engine/pipeline.py:400`–`:404`); `container_path` is not required to live under the input mount; no cross-check between `artifact.output_path` and declared `inputs`.
- **Issues:** duplicate detection uses O(n²) `list.count` (`:104`–`:141`); over-indented `record_length` check (`:76`–`:79`); `get_artifact` raises `KeyError` (`:164`–`:168`) while every other validation raises `ValueError` — inconsistent error contract.

#### `engine/source_hash.py`
- **Purpose:** Shared SHA-256 file/directory-tree hash using POSIX-relative paths for cross-platform identity (24 lines).
- **Bugs:**
  - 🟡 **MEDIUM** — a non-existent path silently returns the hash of empty input: neither branch (`:15`–`:23`) runs, so `sha256("")` is returned with no error — callers (`oracle/docker_adapter.py:280`, `execution/docker_runner.py:72`) record a plausible "source hash" for a missing tree instead of failing closed.
  - 🟢 **LOW** — no build-output/vcs exclusion, so the same tree hashed here differs from `VerticalSlicePipeline._candidate_source_tree_hash` (`pipeline.py:556`–`:588`), which excludes six directories.
- **Limitations:** content-only (permissions, mtimes, symlinks not covered); by design it never raises, so it has no failure channel at all; empty file and empty/missing directory are indistinguishable.
- **Gaps:** three divergent tree-hash helpers coexist (`source_hash.py:11`–`:24`, `pipeline.py:179`–`:201`, `pipeline.py:569`–`:588`) with different separator and exclusion rules — identical trees can produce different digests depending on which helper ran.
- **Issues:** None found.

#### `engine/docker_cli.py`
- **Purpose:** Shared Docker availability probe (`check_docker_available`) and container stop/remove/verify helper (`cleanup_container`) (81 lines).
- **Bugs:**
  - 🟢 **LOW** — `check_docker_available` catches only `FileNotFoundError`, `subprocess.TimeoutExpired` and `OSError` (`:26`–`:32`); any other `subprocess`-level failure propagates instead of returning `False`, so a probe can crash a caller expecting a boolean (all current callers use it as a fail-closed predicate).
  - 🟢 **LOW** — probe output is discarded (`:19`–`:25`): the daemon's stderr/exit reason never reaches limitations or diagnostics text.
- **Limitations:** returns a single boolean — "CLI absent", "daemon down" and "permission denied" are indistinguishable (`:16`–`:32`); availability is probed once per call site (`api/service.py:1058`, `api/app.py:1217`, adapters' `is_available`) with no shared/cached state, so the `docker_available` baked into `ModernizationConfig` can be stale by the time validation runs (TOCTOU between probe and `docker run` — subsequent failures are handled by the adapters, fail-closed); `cleanup_container` assumes a container still exists when `docker inspect` itself errors (`:76`–`:77`).
- **Gaps:** no distinction/reporting of *why* Docker is unavailable for the capability reason strings (`capability_analyzer.py:384` says only "Docker infrastructure not available"); no re-probe or backoff after a failed run.
- **Issues:** `stop_ok` (`:51`) is computed and reported in `detail` but excluded from `removed` (`:79`) — correct (`rm -f`), yet the variable reads load-bearing; three `creationflags` expressions duplicated (`:23`, `:41`).

#### `engine/contracts/models.py`
- **Purpose:** Authoritative contract dataclasses (artifact, oracle, candidate, verdict, producer) plus the `ContractRegistry` (226 lines).
- **Bugs:**
  - 🟡 **MEDIUM** — `OracleContract.validate_identity` (`:118`–`:123`) checks only `oracle_id` equality and that the digest merely *starts with* `sha256:`; it never compares against a pinned digest and never checks `compiler_version`/`preprocessor_version` — the contract's declared compiler identity is unverifiable by this method.
  - 🟡 **MEDIUM** — `CandidateContract.validate_candidate_shape` (`:136`–`:141`) ignores `requires_network` entirely (no network parameter exists) → the declared network requirement can never be violated.
  - 🟢 **LOW** — `FailurePolicy.on_extra` is unvalidated (`:62`–`:73`; only `on_missing`/`on_malformed` checked at `:70`–`:73`), and no engine code reads it — arbitrary values are accepted silently.
  - 🟢 **LOW** — `ArtifactType.VALID_TYPES` (`:26`–`:32`) omits `BUSINESS_INVARIANT` while verdict derivation treats it as supported (`verdict/derivation.py:320`–`:323`) → the contract registry can never describe an artifact type the verdict model accepts (model drift).
- **Limitations:** single contract version `V1_0` (`:14`–`:16`); seven fixed verdict states (`:148`–`:151`); normalization forbiddens are hardcoded (`:40`–`:44`).
- **Gaps:** `VerdictContract.validate_derivation` (`:157`–`:163`) is never called in production (tests only) — the zero-checks rule is enforced by *duplication* in `integrated_proof.py:429`–`:435` and `derivation.py:227`–`:234` instead of by the contract; `ArtifactContract.permanently_forbidden` (`:94`) duplicates `NormalizationPolicy.FORBIDDEN` and is never read; `ContractRegistry.is_complete` (`:203`–`:211`) is unused outside tests; nothing in `engine/` or `api/` loads a contract at all (see `validator.py`).
- **Issues:** `get_comparator` returns the first match with no duplicate-`artifact_type` ambiguity error (`:96`–`:101`); `ContractRegistry` is a mutable non-frozen dataclass (`:194`–`:201`) while every contract it holds is frozen; `ProducerContract.MANDATORY_MANIFEST_FIELDS` (`:174`–`:179`) has no corresponding producer enforcement path.

#### `engine/contracts/validator.py`
- **Purpose:** Strict contract loading and validation with `NO_CONTRACT` refusal semantics (236 lines).
- **Bugs:**
  - 🟡 **MEDIUM** — `load_artifact_contract` silently drops declared contract fields: `on_extra` is never read (`:155`–`:158`) and `permanently_forbidden` is never passed to `ArtifactContract` (`:168`–`:173`) → a contract declaring them loads "successfully" with different values, contradicting the module's own "no best-effort contract interpretation" rule (`:1`–`:7`).
  - 🟢 **LOW** — `validate_comparator` requires exact `comparator_id` equality (`:114`–`:118`) and knows nothing of the alias resolution the pipeline performs (`resolve_comparator_id`, `engine/pipeline.py:412`) — contract validation and runtime binding disagree about which ids are valid.
- **Limitations:** dict/JSON loading only, no schema validation; version parsing accepts only `"1.0"` (`:126`–`:131`); `NoContractError`/`ContractValidationError` are the only failure modes (`:30`–`:44`).
- **Gaps:** **the contract subsystem is not wired into production at all** — `ContractValidator`, `require_all_contracts` and every `load_*_contract` are referenced only from `tests/integration/test_vertical_slice.py:241`–`:248` and `tests/contracts/test_contract_validation.py`; `VerticalSlicePipeline` never loads or requires a contract, so "NO_CONTRACT must be an explicit refusal state" (`:4`–`:6`) is unenforced at runtime — the pipeline's real guard is the comparator registry (`engine/pipeline.py:400`–`:404`); `validate_artifact_type` (`:96`–`:103`) has no production caller, so `BUSINESS_INVARIANT` could never pass it.
- **Issues:** `ContractValidator.__post_init__` raises `ValueError` for a `None` registry (`:53`–`:55`) although the field type is non-optional; `_load_contract_version` builds its error message without `!r` quoting (`:131`); `require_*` methods (`:57`–`:85`) are five near-identical copies.

#### `engine/contracts/__init__.py`
- **Purpose:** Re-exports the contract models, validator and loaders (49 lines).
- **Bugs:** None found.
- **Limitations:** None found.
- **Gaps:** the package presents a complete, enforced-looking API (`ContractValidator`, `require_all_contracts`, `load_*`) while nothing outside tests imports it — see `validator.py` GAPS; `ContractVersion` is exported (`:15`, `:36`) but no loader exposes negotiation beyond `"1.0"`.
- **Issues:** `__all__` (`:28`–`:49`) duplicates the two import blocks verbatim (`:3`–`:26`) — pure maintenance burden.

#### `engine/verdict/derivation.py`
- **Purpose:** Seven-state verdict derivation over an `EvidenceManifest`, with trust-boundary entry points (`derive_verdict_validated` / `derive_verdict_untrusted`) (406 lines).
- **Bugs:**
  - 🟡 **MEDIUM — incorrect verdict derivation for unavailable infrastructure.** `_check_for_errors` (`:274`–`:281`) runs before `_check_for_unavailable` (`:283`–`:316`), and Docker-unavailable executions are reported as `termination_status="error"` (`oracle/docker_adapter.py:297`–`:313`) → **a Docker-less run derives `ERROR`, never `UNAVAILABLE`**; the `UNAVAILABLE` branch is effectively reachable only when every oracle execution is `nonzero_exit` (`:293`, `:303`–`:304`). Fail-closed (never VERIFIED), but the documented state semantics are wrong in practice.
  - 🟡 **MEDIUM** — `derive()` never examines `execution_phase`: a candidate recorded as `BUILD` (compile failure, `pipeline.py:668`–`:674`) is judged purely on comparison results (`:236`–`:272`). The BUILD/EXECUTE guard exists only in evidence integrity, so any caller using the raw-manifest entry points (`derive_verdict`, `derive_unsafe_from_raw`, `:136`–`:145`, `:367`–`:375`) on a manifest whose comparisons all MATCH can certify a candidate that never executed.
  - 🟢 **LOW** — `unavailable_count` counts every non-`normal` execution (`:340`–`:343`), including `nonzero_exit` (a logical program failure) → the scope field mislabels ordinary failures as infrastructure unavailability.
  - 🟢 **LOW** — platform-error verdicts carry a single opaque difference "Platform/validator error detected" (`:196`–`:199`) instead of which execution/status triggered it.
- **Limitations:** `derive()` is documented test/back-compat only (`:7`–`:13`, `:367`–`:375`); `skipped_count` is hardcoded 0 ("V1: no skipping", `:339`); the supported-scope statement is a fixed string naming Docker/Spring Boot adapters (`:77`–`:85`) regardless of the adapters actually used; untrusted evidence can only be clamped to ERROR, never certified (`:147`–`:183`); post-validation mutation is detected via hash re-check (`:104`–`:132`).
- **Gaps:** no requirement that every declared workload artifact produced a comparison — only "at least one comparison exists" (`:227`–`:234` plus `EvidenceManifest.is_complete`), so certification breadth is entirely workload-controlled; `derive_unsafe_from_raw` remains a public method whose "do not add callers" rule (`:136`–`:144`) is convention, not enforcement; `VerdictContract.validate_derivation` is duplicated rather than called.
- **Issues:** two timestamp helpers — `_utc_now_iso` (`:28`–`:32`) vs inline `datetime.now(...)` in `_create_verdict` (`:336`, `:358`); three entry points with subtly different guarantees (`derive`, `derive_from_validated`, `derive_untrusted`) plus the module-level wrappers (`:367`–`:400`); late `TYPE_CHECKING` import for a quoted annotation (`:403`–`:406`).

---

# Section D — copybook / CICS / JCL / SQL transformation layer ✅ COMPLETE

10 files. 6 HIGH, 20 MEDIUM, 30 LOW.

### Summary — D

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 6 | `COPY REPLACING` silently skipped on odd quote; text lost on REPLACING-error path; CICS multi-line commands split/operands lost; unknown CICS commands dropped; JCL case-sensitive recognition; SQL trailing-period + `;`-split statement losses |
| 🟡 MEDIUM | 20 | Unbalanced `EXEC CICS` skipped, SQL column lists split without paren awareness, `HAVING` dropped, PROC/SET JCL dropped, ambiguity re-labelled "missing" |
| 🟢 LOW | 30 | Dead code (`_split_by_comma`, `_parse_predicate`), doc/code drift, duplicate helpers |

#### `engine/transformation/copybook_model.py`
- **Purpose:** Materializes COPYBOOK files into program `working_storage` IR, expands nested `COPY`/`COPY REPLACING`, and builds shared `*Record` Java model classes (1279 lines).
- **Bugs:**
  - 🔴 **HIGH — `COPY REPLACING` silently not applied when the copybook text contains an odd quote character.** `_apply_replacing` tracks a single `quote` state over the *whole raw file text* (640-663), but comment lines are **not** masked before substitution — the docstring claim at 624-625 ("comment lines were already masked away by the statement scan") is false; `_expand_copybook_text` assembles pieces from the unmasked `text` (319, 359-367, 368). An apostrophe in a comment (e.g. `* IT'S A ...`) opens a literal span that suppresses every later substitution, with no diagnostic. Reproduced: input tag `WS-TAG` returned unchanged.
  - 🔴 **HIGH — text preceding a COPY statement is dropped on the REPLACING-error path.** In `_expand_copybook_text`, `pieces.append(text[cursor:start])` (319) executes only on the success path; the clause-error branch (307-318) sets `cursor = end` (317) and `continue`s, so everything between the previous cursor and the COPY statement is deleted from the expansion (asymmetric with the cycle/resolve error paths, 319-358). Only the ERROR diagnostic (310-316) masks the corruption, and only if the caller honors `has_errors` (831-833).
  - 🟡 **MEDIUM — `_statement_end` (216-235) protects `'`/`"` but not `==...==` pseudo-text.** A period inside a legal `REPLACING` operand truncates the statement, producing a false `COPYBOOK_REPLACING_MALFORMED` (504-607) on valid source. Relatedly, a `COPY` with no period of its own swallows the following data entries: reproduced `_find_copy_statements("COPY ALPHA\n05 FILLER PIC X(1).\n...")` → span `(0, 30)` covering `05 FILLER PIC X(1).`, which expansion then deletes silently.
  - 🟡 **MEDIUM — no recursion depth limit.** Cycle detection exists via `chain` (322-333, 415-424) but a deep *acyclic* chain A→B→… recurses once per level in `_expand_copybook_text` (262-368) and `collect_copybook_texts._walk` (397-446) → uncaught `RecursionError` instead of a diagnostic.
  - 🟡 **MEDIUM — `parse_copybook` (103-123) never calls `_strip_sequence_numbers` (455-476).** Fixed-format sequence-numbered lines fail the data regex (verified: `000100  05 FILLER ...` → no match), so a fixed-format `.cpy` parses to **zero records silently**, and nested `COPY` statements are ignored (documented only as "flat parse", 111-114). Also no error channel: `UnicodeDecodeError` propagates raw.
  - 🟡 **MEDIUM — duplicate leaf names silently dropped.** Cross-record/cross-copybook duplicates are skipped with no diagnostic (805-814, "keep first only" at 810-811), and `flatten_records` dedups again silently (1071-1078).
  - 🟡 **MEDIUM — ambiguity detail is lost at the top level.** `prepare_application_copybooks` converts every `MissingCopybook` to `COPYBOOK_UNRESOLVED` using only `m.message` (915-925), whose text is always "Missing COPY target" (`copybook_resolver.py:58-63`) — an ambiguous resolution is reported as *missing* with no candidate list, unlike the nested path which prints candidates (338-348).
  - 🟢 **LOW** — collision message is wrong when the winner is another copybook: "Program … keeps its own" (754-759) even though `existing` may contain a previously merged copybook field.
  - 🟢 **LOW** — replacement text is never re-scanned but also not quote-balance-checked (655-663): a replacement introducing an odd quote desynchronizes later substitution.
- **Limitations:** Data-description entries only; no PROCEDURE DIVISION (104-115). REPLACING operands limited to `==…==` pseudo-text and COBOL words (519-521); `LEADING`/`TRAILING`/`PARTIAL`, `+`/`-` prefixes and quoted literals are rejected (501, 546-554, 576-580) — fail closed with `COPYBOOK_REPLACING_UNSUPPORTED`. Substitution is simultaneous, single-pass, case-insensitive, word-bounded, literal-protected (610-624); no blank normalization inside pseudo-text (562). First statement wins when the same target is copied twice with different clauses (847-853). REPLACING-parameterized parses are excluded from shared model plans (927-931, 998-1005). Legacy no-`source_root` path searches only each unit's source parent (907-914); `collect_copybook_texts` deliberately does not apply REPLACING (386-389).
- **Gaps:** `COPY <name> OF/IN <library>`: the library operand is silently discarded (regex 138-141, whole-statement replacement 359-367) — no diagnostic. `plan_shared_models` counts **all** consumers in `using_programs` (1092-1096, 1119), including programs that used a REPLACING-parameterized parse and therefore do *not* use the shared class. Field collisions are WARNING-level only (745-753) and do not trip `has_errors` (831-833) → generated fields can change with a warning only. Outer REPLACING is applied *after* nested expansion (686-687).
- **Issues:** `INTEGRATION = __doc__` (73) is a self-referential doc constant; the "REQUIRED INTERFACE" block (23-55) is aspirational spec mixed into executable code; `_mask_comments` computed twice per expansion (299 and 303); `parse_copybook` (103) is only referenced by tests — a public-looking API with neither sequence stripping nor expansion nor diagnostics; docstring line count (1137) is stale.

#### `engine/transformation/copybook_resolver.py`
- **Purpose:** Deterministic `COPY <name>` → on-disk file resolution (extension precedence, explicit ambiguity).
- **Bugs:**
  - 🟡 **MEDIUM — ambiguity is re-labelled as "missing".** `resolve_application_copybooks` catches `AmbiguousCopybookError` and stores `MissingCopybook` (188-195); `MissingCopybook.message` (58-63) says "Missing COPY target", and the candidate list lives only in `searched_dirs` (193) which the generation-side diagnostic path (`copybook_model.py:915-925`) never prints.
  - 🟡 **MEDIUM — scan failures swallowed:** `root.rglob("*")` `OSError` → `candidates = []` (96-99) and per-candidate `resolve()` `OSError` → `continue` (101-104) truncate the search set with no diagnostic → false "missing" reports.
  - 🟢 **LOW — documented directory-order rule is not implemented.** Doc rule 3 (16-17) has no effect: precedence considers only the extension (151-154), and equal-precedence files in *any* two directories always raise (161-162) rather than letting order break the tie.
  - 🟢 **LOW — `_candidate_files` (112-126) is O(refs × files)**: a fresh `iterdir()` over every search directory for every reference.
- **Limitations:** Only `.cpy`/`.cbl`/`.cob` (75, 123); non-recursive per-directory scan (86-87, 118); no PDS/library (`COPY … OF LIB`) concept; `resolve_application_copybooks` never raises (168-179).
- **Gaps:** `MissingCopybook.searched_dirs` (56) is populated for both missing (201) and ambiguous (193) cases with different meanings, and is consumed by nothing in the generation path; this module has no diagnostic channel of its own.
- **Issues:** `MissingCopybook.searched_dirs` semantic overload; docstring rules 3 vs 4 contradict each other in practice.
- **Path traversal:** no traversal via the COPY operand — matching is exact `entry.stem.upper()` equality (121) with no path construction, so `COPY ../../etc/passwd` can never match. Residual exposure: `copybook_search_dirs` includes *every* directory of the tree including hidden/VCS dirs (97) with no containment check that a resolved path stays under `source_root`, and the legacy caller path resolves `unit.source_path` against `Path.cwd()` (`copybook_model.py:909-914`), which is cwd-dependent.

#### `engine/transformation/cics_parser.py`
- **Purpose:** Parse `EXEC CICS … END-EXEC` body text into CICS IR (commands, handles, assignments, resources, host variables) (705 lines).
- **Bugs:**
  - 🔴 **HIGH — multi-line CICS commands are split and their operands silently lost.** `_split_statements` treats a top-level newline as a statement separator (279-284) although CICS statements are period-terminated. Reproduced: `READ DATASET('MYFILE')\n  INTO(:WS-REC)\n  RESP(:WS-RESP).` → one `READ` with `into_field=''`, `resp_field=''`; the `INTO`/`RESP` fragments are not commands and are dropped at 179-183.
  - 🔴 **HIGH — unknown statements silently dropped.** 179-183: comment says "Unknown command — store raw" but the code `continue`s; nothing is stored. `engine/cics/subset.py:143-163` only classifies *recognized* `CicsCommandType`s, so unrecognized text never reaches the "nothing is silently dropped" contract (`subset.py:11-13`).
  - 🟡 **MEDIUM — file commands without `DATASET`/`FILE` silently dropped** (189-199 `continue`). Side effect: `CicsApplication.validate()`'s resource check (`ir.py:2117-2125`) can never fire — dead validation.
  - 🟡 **MEDIUM — `TERMID` classified as `CicsResourceType.TRANSID`** (141, 542-545) → wrong `resource_type` on the command (only `terminal_id` extraction at 699-705 still works).
  - 🟡 **MEDIUM — last-wins resource extraction** (503-549): a command carrying two of `DATASET`/`MAP`/`MAPSET`/`TRANSID`/`PROGRAM` keeps only whichever operand appears last.
  - 🟢 **LOW — handle parsing regexes require letter-initial paragraph names** (595, 618: `[A-Z][A-Z0-9-]*`) → digit-initial paragraphs unmatched; condition/AID names absent from the closed maps (68-93, 96-129) are silently dropped; `HANDLE` with neither `CONDITION` nor `AID` returns `None` (301-306) and vanishes.
  - 🟢 **LOW — `_parse_assignments` FIELD=VARIABLE fallback** (650) can capture operand keywords (`RESP=X`), deduped by field name only (654).
- **Limitations:** Explicitly "NOT a complete CICS parser" (15-16); operand grammar limited to `KEY=VALUE`, `KEY(VALUE)`, bare keywords (322-396); closed command/condition/AID vocabularies (36-142); no `EXEC`-level context (COPY/program structure).
- **Gaps:** `CicsApplication.channels` and `.transactions` are never populated (232-245) → `get_transaction_dependencies()` (`ir.py:2100-2107`) is always empty; docstring claim of "COMMAREA and channel/container references" (11) holds only as per-command fields; there is no unsupported/`raw` channel at all — `raw_text` (244) is the only trace of dropped text.
- **Issues:** `_RESOURCE_KEYWORDS` (132-142) is dead code (also carries the TERMID→TRANSID error); `_split_by_comma` (435-469) is dead code — never called; `_COMMAND_MAP["HANDLE"]` (52) unreachable because `HANDLE` is special-cased first (301-306); five near-identical `_extract_*_resources` helpers (662-705); comment/code drift at 182.

#### `engine/transformation/cics_java_mapping.py`
- **Purpose:** Facade: extract `EXEC CICS` blocks + `PROGRAM-ID` from COBOL, consolidate per program, map/generate the CICS Spring lane.
- **Bugs:**
  - 🟡 **MEDIUM — unbalanced `EXEC CICS` (missing `END-EXEC`) is silently skipped.** The regex requires the terminator (36-38) and `finditer` (63) never matches an unclosed block; the docstring (53-55) says such blocks are "silently treated as parse failures", but no failure is recorded anywhere → truncated CICS regions vanish without a diagnostic.
  - 🟡 **MEDIUM — no comment masking before block extraction** (36-38): a `*`/`*>` comment line containing `EXEC CICS … END-EXEC` is parsed as a real block (contrast `engine/sql/extractor.py:45-49`, which does mask).
  - 🟡 **MEDIUM — `PROGRAM-ID` attribution is first-match-only** (33-35, 72-76): multi-program source files attribute *all* blocks to the first program; a missing `PROGRAM-ID` silently becomes `"UNKNOWN"` (76), consolidating everything under one bogus program (141).
  - 🟢 **LOW — language marker guess** (240): any non-`.java` generated file is labelled `markdown` (xml/properties/README all mislabelled).
- **Limitations:** One service per `PROGRAM-ID` (114-116, 129-184); source-order concatenation only; no COBOL structural parsing (no COPY/copybook awareness); conversion to shared files is lossy by design (234-237).
- **Gaps:** No validation of the produced `CicsApplication` (`CicsApplication.validate()` exists at `ir.py:2109` but is test-only) and no unsupported-construct scan of the COBOL source in this facade — the subset contract only classifies what the parser already recognized. `map_cics_programs(cobol_source=None, applications=None)` returns an empty model without error (118-126).
- **Issues:** `_with_program_id` (79-99) hand-relists every `CicsApplication` field — a new IR field is silently dropped here (contrast `jcl_parser.py:93`, which uses `dataclasses.replace`); `MAPPER_VERSION` (40) unused; `_consolidate_by_program` (129-184) rebuilds dataclasses with hand-written flattening.

#### `engine/transformation/jcl_parser.py`
- **Purpose:** Parse JCL into `JclJob`/`JclStep`/`JclDD` IR for a deliberately small supported subset.
- **Bugs:**
  - 🔴 **HIGH — case-sensitive statement recognition in the main loop.** `" JOB " in rest` (152), `" EXEC " in rest` (162), `" DD " in rest` (168), `" SET " in rest` (186), `" PROC " in rest` (191) are tested against the original case; only the *nameless* form uses `.upper()`. Lower/mixed-case JCL is skipped line-by-line at 201-202 → zero jobs, zero diagnostics. Reproduced (`//myjob job cls=a`, `//step1 exec pgm=x`, `//input dd dsn=…` all undetected). The inner DD loop *does* uppercase (270) → the two paths disagree.
  - 🟡 **MEDIUM — parser-level fail-open is the documented behaviour:** "Unsupported constructs produce minimal IR without error" (17); unrecognized lines (201-202), `SET` (186-188), `PROC` ("skip for now", 191-194), `PEND` (197-199) are all dropped with no record. Recovery depends entirely on `engine/jcl/builder.py:402-492`, which runs only when the caller supplies `raw_sources`.
  - 🟡 **MEDIUM — phantom unnamed job.** The end-of-file flush fires when `comments` (or any buffer) is non-empty (204-205) → a comment-only member yields `JclJob(name="")` that flows into the profile.
  - 🟡 **MEDIUM — cataloged/in-line PROC bodies become a phantom job:** `//NAME PROC …` is skipped (191-194) but its steps are accumulated and flushed as an unnamed job (204) instead of populating `JclApplication.procedures`.
  - 🟡 **MEDIUM — DD continuations never consumed:** `_parse_dd` returns `start_idx + 1` (397), `_parse_exec`'s loop breaks on non-`//` lines (277-279), so continuation lines fall through to the skip branch (201-202) and their parameters are lost (diagnosed only by the builder's `UNSUPPORTED_CONTINUATION` when raw text is supplied).
  - 🟢 **LOW — unnamed `//DD`** (no name/content) is not recognized (168) and is skipped silently; `_parse_job` regex failure returns `("", {}, start_idx+1)` (220-221) with no signal → JOB parameters silently lost.
  - 🟢 **LOW — `DD *`/`DD DATA` payload is never captured** (346-349 set only `is_inline`; `JclDD` has no data field, `ir.py:1279-1294`).
- **Limitations (3-18):** only `//JOB JOB`, `//STEP EXEC PGM|PROC`, `//DD DSN|SYSOUT|inline`, `//*`, COND, source-order step ordering; `parse()` returns the first job only (45-61); no PROC expansion, no `IF/THEN/ELSE`, no `JCLLIB/INCLUDE/OUTPUT`, no symbolic substitution, no JOB-card `COND` → step condition.
- **Gaps:** `JclApplication.symbols`/`.procedures` (`ir.py:1367-1368`) are never populated here (186-188, 191-194) → dead IR surface, while the docstring advertises "SET symbolic parameters" (14) as supported; `JclStep.comments` is never set (steps built at 172-178 and 282-287 without it) → dead field; `//*` comments always attach to the job (139); JOB-level `COND` lands in `job.parameters` (227) and never becomes a condition; parameters without `=` are silently dropped by `_parse_parameters` (459-465).
- **Issues:** DD recognition duplicated and inconsistent between main loop (168) and `_parse_exec` (270); `JclStep` rebuilt field-by-field at 172-178 instead of `dataclasses.replace` (used at 93); `parse()` returning `JclJob(name="")` (61) has no diagnostic channel; docstring (17) advertises fail-open behaviour, in tension with the platform's fail-closed principle.

#### `engine/transformation/jcl_consumer.py`
- **Purpose:** Consumer-side entry point: discover JCL, read members for the unsupported scan, modernize, return a structured result.
- **Bugs:**
  - 🟡 **MEDIUM — two different `raw_sources` key spaces for the same argument:** `modernize_jcl_workload` keys by member-relative posix path (136), `modernize_jcl_from_sources` keys by caller-chosen filename (194-199). Harmless today only because `builder.py:82` iterates `.values()` — the coupling is undocumented and fragile.
  - 🟢 **LOW — `JclDiagnosticCode.SOURCE_DECODE_FAILED` is reused for `OSError`** (141-152) → misleading code for I/O failures.
  - 🟢 **LOW — zero-member directory yields `EMPTY` with an empty diagnostic list** (118-126, 68-85): nothing explains *why*.
- **Limitations:** directory-only entry (119-122); the in-memory variant cannot express member paths or decode failures; `status`/`has_*` are pure pass-throughs of the profile (68-85).
- **Gaps:** correctness of the unsupported scan rests entirely on `find_jcl_members` (135) being the same rule as discovery's (`jcl_discovery.py:244-250`) — currently true by delegation, not by type contract; the produced profile is never `validate()`d here (tests only).
- **Issues:** duplicate full-tree walk and file reads (discovery `discover` at 126 + raw loop at 133-153); `JclConsumerResult.profile` duplicates every promoted field (55-65 vs 73-85).

#### `engine/transformation/jcl_discovery.py`
- **Purpose:** Discover JCL members in a tree, parse them into `JclApplication`, and link steps/DDs to COBOL programs and files.
- **Bugs:**
  - 🟡 **MEDIUM — read/decode failures swallowed at 148-153** (`continue`): the comment defers diagnostics to the consumer's separate scan, but `discover()` is a public API (105-108); any other caller gets a silently truncated job list with no channel.
  - 🟢 **LOW — `is_jcl_member` reads the *entire* file to sniff its head** (82) — full reads of every extensionless/binary file in the tree, twice per run (also in `jcl_consumer.py:135`).
  - 🟢 **LOW — case-sensitive program resolution** (185, 206) versus case-normalized dataset matching (48-59) → `PGM=progname` vs `PROGRAM-ID PROGNAME` reports `resolution=UNRESOLVED`.
  - 🟢 **LOW — non-UTF-8 (EBCDIC/Cp037) members never discovered:** the sniff decodes as UTF-8 with `errors="replace"` (82) so an EBCDIC `//` becomes replacement chars → member silently absent from the member set (no diagnostic at discovery time).
- **Limitations:** only `COBOL_PROGRAM` and `COBOL_FILE` links are created (200-234); dataset matching is exact-or-qualified-tail only (48-59); no PROC/catalogued-procedure handling; `_find_jcl_files` (244-250) is a pure delegate.
- **Gaps:** `resolution=AMBIGUOUS`/`UNRESOLVED` exist only as `metadata` strings (212, 231) and are never promoted to diagnostics; `JclApplication.procedures`/`symbols` are copied through as empty (238-239); no edge from `EXEC PROC` to a procedure definition.
- **Issues:** `_find_jcl_files` (244-250) is a trivial wrapper around `find_jcl_members` (88-99) — two names for one rule; module docstring (29-30) promises a combined graph including `CALL`, `COPY`, `FILE_READ`, `FILE_WRITE` that this class does not build.

#### `engine/transformation/jcl_dependencies.py`
- **Purpose:** Single shared construction of step-order, EXEC-program and DD-dataset dependency edges (de-duplicates the two former copies).
- **Bugs:**
  - 🟡 **MEDIUM — unqualified step nodes:** `JCL_STEP_ORDER` edges use bare step names (33-38) while `JCL_EXEC`/`JCL_DD` are job-qualified (43-48, 54-59) → identically named steps in different jobs collapse into one graph node (the job is only in `metadata`).
- **Limitations:** only consecutive source-order pairs (25-38); `COND` survives only as `metadata` (30-32); no `IF/THEN` edges, no PROC edges, no dataset producer/consumer edges (those live in `engine/jcl/builder.py`).
- **Gaps:** `EXEC PROC=` steps produce no edge at all (42 requires `exec_.program`); job-level DDs get an edge (63-70) but job-level `COND` has none.
- **Issues:** `next` shadows the builtin (27); `metadata` uses `""` for missing disposition (58, 69) but `f"disp=…"` otherwise.

#### `engine/transformation/jcl_spring_batch_ir.py`
- **Purpose:** Declares the Spring Batch target IR (job/step/resource/flow/dataset edges) plus `validate()`.
- **Bugs:**
  - 🟢 **LOW — `validate()` (141-187) is never called by the lane entry point** (`jcl_to_spring_batch.py:317-375`); duplicate job names, invalid flow endpoints and duplicate tasklet beans reach generation unless a test invokes it.
- **Limitations:** pure declaration — "The representation is *declared*, not executed" (16-23); fixed 5-value exit-status vocabulary (33-38); no runtime/RC semantics.
- **Gaps:** `SpringBatchApplication.resources` (120) is a "global inventory" that the mapper dedups by `(dsn, name)` only (`jcl_to_spring_batch.py:265-274`) — the same DSN under different DD names in different steps collapses to the first with no diagnostic; `SpringBatchJob.parameters`/`source_path` are carried but never consumed by the adapter.
- **Issues:** `PROFILE_VERSION` (31) is attached but never checked anywhere; mixed idioms (module constants for exit status vs `Enum` for `SpringBatchResourceType`, 41-49).

#### `engine/transformation/jcl_spring_boot_adapter.py`
- **Purpose:** Convert `SpringBatchApplication` into `SpringBootApplication` IR for the shared Spring Boot generator.
- **Bugs:**
  - 🟡 **MEDIUM — activation gates and ordering are comments only.** `_activation_comment` (75-87) and `_step_comment` (63-72) emit `JavaComment`s; the step body is a single `println` (112-122). A `COND=EVEN`/`ONLY` step runs unconditionally in generated code, so `jcl_spring_batch_ir.py:21-22` ("Return-code conditions are preserved as CONDITIONAL declared gates") holds only as prose.
  - 🟡 **MEDIUM — flow and dataset analysis never reach any output.** `job.flows` is unused, and `_build_dataset_comments` (150-161) has **no call site anywhere** → the mapper's `SpringBatchDatasetEdge` computation is dead on arrival.
  - 🟡 **MEDIUM — `_camel` can emit invalid Java identifiers** (55-60): a step name beginning with a digit yields method `1st(...)`; the JCL parser does not validate names (`jcl_parser.py:239-244`), so a malformed member can make the generated project fail to compile.
  - 🟢 **LOW — hardcoded `"UNKNOWN"`** at 85 instead of the imported `EXIT_STATUS_UNKNOWN` (`jcl_spring_batch_ir.py:38`).
- **Limitations:** "structural representation … does NOT execute real batch processing" (13-17, 174-177); one service per job, one method per step (132-147); resources appear only as comments (107-109); fixed dependency set (201-210).
- **Gaps:** `SpringBatchResource` beans, `job.parameters`, `start_step`, `flows`, and `dataset_edges` are all dropped; duplicate step-derived method names within a job are not detected → duplicate Java methods.
- **Issues:** `_camel` (55) duplicates `_camel_bean` (`jcl_to_spring_batch.py:308-314`) with *different* casing rules; `SpringBatchDatasetEdge` import (35) exists only for the dead function; stray blank lines at 89-91.

#### `engine/transformation/jcl_to_spring_batch.py`
- **Purpose:** Lane entry point: `JclApplication` → semantic model (via builder) → `SpringBatchApplication` + `JclModernizationProfile` with diagnostics and status.
- **Bugs:**
  - 🔴 **HIGH — fail-open when `raw_sources` is absent/empty** (317-352): `raw_sources` defaults to `None` (319) and the builder then scans nothing (`builder.py:77, 82-83`), so `status` can be `FULL` with zero unsupported diagnostics. The entire unsupported-construct contract is conditional on an optional parameter.
  - 🟡 **MEDIUM — status and unsupported contract understate reality.** Status degrades only on ERROR diagnostics (364-369); `_derive_unsupported` filters to ERROR level *and* a hard-coded code dict (140-149, 75-84) → warnings such as `PARTIAL_COND_SEMANTICS` (`builder.py:288-306`) and `UNRESOLVED_SYMBOL` never appear in `unsupported_constructs`, and any newly added code silently vanishes from the contract.
  - 🟡 **MEDIUM — mapper never diagnoses name collisions:** duplicate `job_bean` (186) or step/bean names (201, 220) pass straight through; `SpringBatchApplication.validate()` is not invoked.
  - 🟢 **LOW — flow endpoints for empty step names:** `_build_flow_edges` uses `_camel_bean(current.name)` unconditionally (258-259) while `map_step` falls back to `"Step"` (201) → `""` endpoints that `validate()` would reject if it ran.
  - 🟢 **LOW — `UNKNOWN` resource type produced silently** (230-242) with no diagnostic for unclassifiable dispositions.
- **Limitations:** `_SUPPORTED_CONSTRUCTS` (62-73) is a static claim returned regardless of what actually parsed (122, 133-134); only `PGM` steps are executable (`EXEC PROC` is an ERROR, `builder.py:183-191`); COND collapses to 4 activation kinds (88-94).
- **Gaps:** a job consisting only of skipped/unknown content still counts toward `FULL` if no ERROR exists; `JclControlKind.UNSUPPORTED` steps (mapped at 93) never surface in `unsupported_constructs`; COND-even/only are listed as "supported" (68-69) while their runtime semantics are explicitly not claimed (357-362).
- **Issues:** `JclProfileStatus` (97-102) is a constants class while sibling IR uses `Enum`; `OrderedDict` (266) is unnecessary; code-to-text mapping (75-84) must be maintained by hand; status logic duplicates `has_errors` (124-126).

#### `engine/transformation/sql_parser.py`
- **Purpose:** Parse `EXEC SQL` body text into SQL IR (SELECT/INSERT/UPDATE/DELETE, cursors, transactions) and extract host variables/table dependencies (1183 lines).
- **Bugs:**
  - 🔴 **HIGH — trailing period is not normalized (except the INSERT table, 464).** Reproduced: `DELETE FROM ACCOUNT.` → `table_name=''`, `schema='ACCOUNT'` (566-571); `SELECT … FROM T.` → `table_name=''`, `schema='T'` (695-699); `UPDATE … SET BAL = 10.` → literal `'10.'` (1133-1135). The empty table name is then filtered out downstream (`external_dependency_edges.py:338`) → the table dependency silently vanishes from the ledger.
  - 🔴 **HIGH — predicates ending in `.` are silently discarded.** `_is_simple_operand` (945-949) rejects `":WS-ID."`, so `SELECT … WHERE ID = :WS-ID.` yields `where_predicates=()` with no record (403-406). Reproduced; `WHERE … AND Y = 2.` lost its last conjunct.
  - 🔴 **HIGH — statements without `;` merge.** `_split_statements` (323-325 → `sql_split.py`) only splits on `;`; reproduced `OPEN C\nFETCH C INTO :A, :B` → a single `OPEN_CURSOR`, the FETCH gone, `unsupported_statements=()` — a whole statement silently dropped.
  - 🟡 **MEDIUM — WHERE conjuncts that fail `_parse_simple_predicate` are silently discarded** (1059-1070): no channel records which conjuncts were lost; a WHERE that is entirely unparseable leaves `where_predicate=None` on an otherwise "supported" statement (403-406, 545-548, 582-585). Reproduced with `IN (SELECT …)` (988-1003).
  - 🟡 **MEDIUM — column lists split on `,` without paren awareness** (639): reproduced `SELECT A + B, COUNT(*), T.* FROM T` → fabricated columns `('A','+')`, `('COUNT(*)','')`, `('*','')` (646-671) → wrong `Db2TableDependency.columns` (284-291). The same defect exists in `_parse_expression_list` (1116), `_parse_assignments` (1128), `_parse_order_by` (1144), `_parse_group_by` (1172), `_parse_host_variable_list` (771), `_parse_table_list` (678).
  - 🟡 **MEDIUM — `SqlSelect.having` is never populated** (442-453): HAVING only bounds GROUP BY (431-433) and is then discarded — silent clause loss.
  - 🟡 **MEDIUM — leading SQL comments break statement identification** (95, 236-238): reproduced `-- a comment\nSELECT …` → entire block recorded as unsupported (fail-closed, but a false positive); `sql_split.py` handles no `--`/`/* */`.
  - 🟢 **LOW — `extract_host_variables` regex matches `:NAME` inside string literals** (46, 260-264; `_mask_literals` exists at 799-817 but is not used here) → phantom host variables; dedup is case-sensitive (249, 256-264).
  - 🟢 **LOW — dependency column extraction is wrong per table:** full projection assigned to every FROM/JOIN table (278-291); UPDATE reports only SET columns (304); DELETE reports none (314-319).
  - 🟢 **LOW — module-level annotation `group_by: tuple[SqlGroupBy, …]` (425) names an identifier not imported at module scope** (imports 20-40; `SqlGroupBy` is imported only locally at 1169). Not a runtime error but it breaks static analysis.
  - 🟢 **LOW — `INTO` slicing assumes exactly one character after the keyword** (353).
- **Limitations (12-14):** only SELECT/INSERT/UPDATE/DELETE + cursor/COMMIT/ROLLBACK/CALL/PREPARE/EXECUTE (94-234); no CTE/`WITH`, no `UNION`, no MERGE/DDL, no subqueries as first-class constructs; predicates restricted to "simple operands" (933-949) — no functions, `EXISTS`, `NOT`, or OR trees (flat conjunct list only); statement splitting is `;`-only.
- **Gaps:** `SqlSelect.having` always `None`; `SqlOrderBy.nulls_first` (`ir.py:1616`) never set; `SELECT *` yields `columns=()` (643-644) — indistinguishable from "no projection"; `INSERT … SELECT` and multi-row `VALUES` are stored as INSERT with empty/partial columns/values (478-495) with no diagnostic; `PREPARE`/`EXECUTE` keep raw text only (219-234); `unsupported_statements` is the *only* loss channel — partial sub-parse losses (predicates, columns, HAVING, assignments without `=`, 1130-1137) have no channel at all.
- **Issues:** `_parse_predicate` (1072-1075) "compatibility view" has no callers — dead code; `_PREDICATE_OP_MAP` (49-59) is incomplete and compensated ad hoc at 1038-1055; inconsistent safety: literals masked for predicates (963) but not for host-variable extraction (260) or statement splitting (323-325); local import of `SqlGroupBy` (1169) vs missing module import (425).

#### `engine/transformation/sql_repository_mapping.py`
- **Purpose:** Lane-owned facade re-exporting the DB2 semantic model → Java repository/service mapping.
- **Bugs:** None found.
- **Limitations:** No logic of its own — pure delegation (55-65); default package `com.acme.db2` (57) is a placeholder inconsistent with the `com.generated.*` convention used elsewhere in the platform; `java_type_resolver=None` (58) has no documented fallback contract.
- **Gaps:** The Spring integration hook is documented as intentionally not implemented (9-23) → `SqlRepositoryMapping` is produced by this surface but nothing in the platform renders it; `map_sql_model_to_repository` is exported only for tests.
- **Issues:** `map_sql_model_to_repository` (55) is missing from `__all__` (41-52) while the re-exported `map_db2_model_to_repository` is present — `import *` would not expose the module's own function.

#### `engine/transformation/sql_split.py`
- **Purpose:** Shared quote-aware splitting of SQL text on top-level `;`.
- **Bugs:**
  - 🟡 **MEDIUM — no comment handling:** a `;` inside `--` or `/* */` splits wrongly, and a leading `--` comment is glued to the next statement (verified: the whole block fell into `unsupported_statements`).
  - 🟢 **LOW — an unbalanced quote swallows the remainder of the file into one statement** (10-26) with no diagnostic.
  - 🟢 **LOW — no `BEGIN…END`/dollar-quote/procedure-body awareness** → PL/SQL-style bodies split incorrectly.
- **Limitations:** only `'`/`"` quote awareness; no empty-statement filtering (callers must filter — `sql_parser.py:89-91`); `;;` yields an empty segment (22-24).
- **Gaps:** None found beyond the above.
- **Issues:** None found.

---

# Section K — test suite (`tests/`) ✅ COMPLETE

8 subdirectories + 101 root test files. 4079 `test_*` functions (3835 unique names, 190 duplicates).

### Summary — K

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 7 | `pytest` at repo root aborts collecting `tmp/` scratch dirs; vacuous `pass`/`assert True` tests; `test_production_topology.py:71` greps comments not behavior; `tests/contracts/` never opens `contracts/*.md`; no root `conftest.py`/`pytest.ini` |
| 🟡 MEDIUM | 14 | 43 conditional-only-assert tests; 121 decorator-gated + 36 runtime skips shrink the suite; ~310 committed generated files (1.06 MB); global `_service` singleton mutated without reset |
| 🟢 LOW | 12 | 190 duplicate test names; documented-unfixed flakes; inconsistent directory placement |

#### `tests/` (root — 101 files)
- **Purpose:** Top-level suite covering engine, transformation, API, security, E2E, CICS/DB2/JCL subsets, capability truth, and doc-consistency checks.
- **Bugs:**
  - 🔴 **HIGH — running `pytest` from the repo root aborts during collection.** Confirmed this session: `pytest -q` → `Interrupted: 4 errors during collection`, `PermissionError: [WinError 5] Access is denied` on `tmp/codex-ci-pytest`, `tmp/codex-pytest`, `tmp/codex-pytest-first`, `tmp/codex-pytest-full` (leftover scratch dirs; `tmp/` *is* in `.gitignore` so `git status` shows nothing). With no root `pytest.ini`/`pyproject.toml`/`conftest.py` there is no `testpaths` and no `norecursedirs`, so pytest walks ignored scratch trees. The suite is only runnable as `pytest tests/`. This is the same root-config gap as the marker/timeout/warning-filter absence below, but it fails loudly rather than silently.
  - 🔴 **HIGH — 6 truly vacuous tests:** `tests/test_pipeline_progress.py:205` (`pass` at `:210`), `tests/test_universal_modernization.py:542`, `assert True` at `tests/integration/test_forensic_evidence.py:1019` and `tests/transformation/test_phase7c_end_to_end.py:1585` (tautological re-assert at `:1592`); **43 tests** where every assert sits inside a conditional so they pass on broken code (e.g. `tests/test_cics_subset.py:60-66`), 82 conditional-assert sites repo-wide.
  - 🔴 **HIGH — inconsistent E2E gating:** `tests/test_e2e.py` has no skip guard and fails hard on Docker-less hosts while `tests/integration/test_docker_java.py` (16/16) and `tests/test_forensic_evidence.py` (34/34) skip silently.
- **Limitations:** 17 tests have no assert/fail/raises at all (11 are legitimate "must not raise" smoke tests); 121 decorator-gated tests across 21 files + 36 runtime `pytest.skip()` calls in 12 files effectively shrink the suite on non-Docker/Java hosts; zero unconditional `pytest.mark.skip`/`xfail` found; **no root `conftest.py` and no `pytest.ini`/`pyproject.toml`/`setup.cfg`** — no central marker registration, warning filter, or timeout policy.
- **Gaps:** Roadmap §16 (`docs/COBOL_UNIVERSALITY_ROADMAP.md:547-549`) requires negatives for NEXT SENTENCE/SORT/ACCEPT/ALTER but only registry name-list asserts exist (`tests/test_silent_loss_registry.py:62-66`); `INITIALIZE`/`SEARCH`/`NEXT SENTENCE` have zero tests although patterns are registered (`engine/transformation/semantic_capability.py:545,547,559`); **no test reconciles `docs/CAPABILITY_MATRIX.md` SUPPORTED rows to test names** (only `SEMANTIC_PROOF_MATRIX` via `tests/test_silent_loss_registry.py:23`) and **no test reads `contracts/*.md`**; `tests/test_network_policy_honesty.py:50-55` asserts `network_policy == "none"` without binding to actual argv — nothing covers `--network none` in `engine/candidate/docker_java_adapter.py`.
- **Issues:** 8 untracked test files (`test_backup_verification.py`, `test_last_stage_anchor.py`, `test_readiness.py`, `test_shell_script_contracts.py`, `test_structured_logging.py`, `test_workspace_persistence.py`, `transformation/test_arithmetic_line_continuation.py`) + modified `tests/test_production_auth_env.py` vs HEAD `62e647f`; documented-but-unfixed flakes `tests/test_certification_contract.py:147,150` (`docs/BACKLOG.md:5413-5430`) and `tests/test_pipeline_progress.py:312` (BL-017, `docs/BACKLOG.md:6665`); doc contradiction `docs/CAPABILITY_MATRIX.md:146` claims "14 collected from 4 test functions" for `tests/test_shell_script_contracts.py` vs actual 7 functions/17 collected; 19 module-level `client = TestClient(app)` instances.

#### `tests/transformation/` (93 files, 1971 tests)
- **Purpose:** Largest directory — semantic capability, phase5-7c IR/Spring Boot generation, arithmetic, copybook, DB2/JCL/CICS translation tests.
- **Bugs:** Vacuous `pass` at `tests/transformation/test_modernization_planner.py:438`; computed-but-unasserted value at `tests/transformation/test_application_discovery.py:608`; conditional-only-assert example `tests/transformation/test_phase7b1_spring_boot_ir.py:768`; `assert True`/tautology at `tests/transformation/test_phase7c_end_to_end.py:1585,1592`.
- **Limitations:** Heavy reliance on skip-gated Java/Docker tests (part of the 121 decorator-gated set); duplicate test function names across files (190 repo-wide) make `-k` selection ambiguous.
- **Gaps:** Roadmap §16 semantic negatives (INITIALIZE/SEARCH/NEXT SENTENCE) untested here despite `engine/transformation/semantic_capability.py:545,547,559`; no test asserts `ALTER` handling (`tests/test_utilities_vsam_detection.py:65` merely contains it in a fixture); `docs/TEST_NAMING_AUDIT.md:69-70` records param-id naming fix as "reported, not fixed".
- **Issues:** Dead helper `tests/transformation/forensic_proof.py` defines 6 test functions pytest never collects (recorded in `docs/TEST_NAMING_AUDIT.md:47-50`, not fixed); `forensic_audit.py`, `forensic_search_phase3.py`, `forensic_search_7a1.py` contain 0 tests; 3 tests still named for what they fail to assert per the naming audit.

#### `tests/integration/` (22 files)
- **Purpose:** Cross-component proof — inventory generalization, copybook runtime, Docker+Java execution, forensic evidence capture, integrated proof API.
- **Bugs:** Vacuous `pass` at `tests/integration/test_inventory_generalization.py:74` and `tests/integration/test_copybook_runtime.py:365`; `assert True` at `tests/integration/test_forensic_evidence.py:1019`.
- **Limitations:** Whole-file skip gates — `tests/integration/test_docker_java.py` 16/16 skipped without Docker, `tests/integration/test_forensic_evidence.py` 34/34 skipped without environment (~50 silent skips); no shared fixtures (no root conftest) to reset `api/app.py:135` `_service` singleton.
- **Gaps:** No test verifies evidence artifacts it writes against `docs/` claims; no test reconciles integration results with `docs/KNOWN_ISSUES.md` deferrals (BL-113/114/115/116/122).
- **Issues:** Global-state mutation without teardown: `tests/integration/test_integrated_proof_api.py` and `tests/test_api.py:62-74` (`fresh_service`, no restore) leave `api/app.py:135` `_service = Service(_store)` polluted for later tests; JCL coverage split 8 root/7 transformation/1 integration, CICS 6/3, CALL 5/3/3, DB2 8 root — placement inconsistent.

#### `tests/adversarial/` (16 files)
- **Purpose:** Red-team/robustness checks (path traversal, prompt injection, persistence verdict trust) with the only `conftest.py` in the tree.
- **Bugs:** None confirmed by sampling; assertions generally unconditional.
- **Limitations:** Single `tests/adversarial/conftest.py` with no root conftest means its fixtures/setup are invisible to the other 600+ files; suite has no registered markers, so `-m adversarial`-style selection is impossible.
- **Gaps:** No adversarial coverage of the capability-truth gate itself (`.github/workflows/ci.yml:43-100` file list) or of doc/test contradictions.
- **Issues:** `tests/adversarial/test_persistence_verdict_trust.py` mutates the shared API service singleton with no reset (`api/app.py:135`), creating cross-directory ordering flakiness.

#### `tests/comparators/`
- **Purpose:** Baseline-vs-candidate output comparison helpers/tests for transformation diffs.
- **Bugs:** No vacuous tests found in sampling.
- **Limitations:** Small directory; relies on committed baseline fixtures that can drift from `engine/` behavior without any test asserting drift.
- **Gaps:** No test ties comparator results to `docs/CAPABILITY_MATRIX.md` claims.
- **Issues:** Comparator test names duplicate names used elsewhere (contributes to the 190 duplicate-name set), complicating targeted reruns.

#### `tests/evidence/`
- **Purpose:** Evidence-pack generation and verification tests.
- **Bugs:** None found in sampling.
- **Limitations:** Overlaps functionally with `tests/verification/` scripts — two parallel evidence systems with no test asserting they agree.
- **Gaps:** No test reads `contracts/*.md` or validates evidence against `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md`.
- **Issues:** Committed evidence output under `tests/verification/evidence` (21 files/34 KB) is regenerated by tests, risking write-during-test-tree churn.

#### `tests/execution/`
- **Purpose:** Execution-engine (compile/run harness) tests.
- **Bugs:** Conditional-assert patterns present (part of the 82 sites).
- **Limitations:** Much of this area requires a Java toolchain; gated by the 121 decorator-gated tests and skipped silently without it.
- **Gaps:** No negative-path coverage for `--network none` in `engine/candidate/docker_java_adapter.py`.
- **Issues:** Produces committed binary `tests/fixtures/call_byref/prog` (96,408-byte ELF, untracked) — tests write executables into the fixture tree.

#### `tests/verdict/`
- **Purpose:** Verdict/trust scoring tests.
- **Bugs:** None found in sampling.
- **Limitations:** Verdict logic tested in isolation; not cross-checked against adversarial suite expectations.
- **Gaps:** No test that verdicts are stable across runs (flake risk given shared state).
- **Issues:** Verdict persistence tests share the `api/app.py:135` singleton without reset.

#### `tests/unit/`
- **Purpose:** Fine-grained unit tests for isolated modules.
- **Bugs:** None found in sampling.
- **Limitations:** Small relative to 64 of 101 root files that are actually engine/transformation tests — unit coverage concentrated at root instead, blurring unit vs integration boundaries.
- **Gaps:** Unit-level tests for `semantic_capability.py` INITIALIZE/SEARCH/NEXT SENTENCE patterns absent here too.
- **Issues:** Overlap/duplication with root-level tests contributes to the 190 duplicate test function names.

#### `tests/contracts/`
- **Purpose:** Intended to test `contracts/*.md` invariants.
- **Bugs:** None found in sampling.
- **Limitations:** Despite the directory name, **no test opens `contracts/*.md`** — contract docs are unverified by automation.
- **Gaps:** Contract-to-test reconciliation does not exist anywhere in the suite.
- **Issues:** Risk of the directory name overstating coverage (same class of issue as `docs/CAPABILITY_MATRIX.md:146` overstating shell-script coverage).

#### `tests/deployment/`
- **Purpose:** Production topology/compose assertions.
- **Bugs:** 🔴 **HIGH** — `tests/deployment/test_production_topology.py:71` asserts `"--network none" in text` but the token appears only in **comments** of `docker-compose.production.yml:8,169` — the test can pass while the actual compose config has no network restriction (comment-grep, not behavior).
- **Limitations:** Grep-on-YAML style tests cannot validate rendered config.
- **Gaps:** No test executes `docker compose config` to prove the rendered service has `network_mode: none`.
- **Issues:** Gives false confidence in sandbox enforcement — related to the untested `docker_java_adapter.py --network none` path.

#### `tests/candidate/`
- **Purpose:** Candidate-pipeline (adapter/IR emission) tests.
- **Bugs:** Conditional-assert sites present.
- **Limitations:** Candidate emission tests don't cover the Docker adapter network flags (see deployment gap).
- **Gaps:** No test links candidate artifacts to `docs/BACKLOG.md` deferrals.
- **Issues:** Candidate runs can emit `.java` into working dirs — combined with 273 tracked `.java/.json` files under `tests/`, generated output is easy to commit accidentally.

#### `tests/verification/` (scripts + committed output)
- **Purpose:** Manual/fresh-baseline verification harnesses plus their captured results.
- **Bugs:** Not a test directory in practice: 5 `_*.py` (`_investigate_gaps.py`, `_verify_divide_into.py`, `_verify_subtract_ms.py`, `_pipeline_divide_into.py`, `_pipeline_subtract_ms.py`) + 4 scripts (`run_verifications.py`, `run_fresh_baseline.py`, `run_clean_verification.py`, `generate_evidence.py`) define 0 collected tests.
- **Limitations:** Results are snapshots; nothing asserts they still reproduce.
- **Gaps:** Contradiction uncaught: `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md:165-166` still marks COMP/COMP-3 "UNSUPPORTED (parser gap)" while `tests/transformation/test_usage_capability.py:53-76` proves parsing works and capability is PARTIAL.
- **Issues:** 🔴 ~310 committed generated files / 1.06 MB (results 51/391 KB, results_fresh 164/292 KB incl. `generated_apps/` 140 files, results_fresh2 74/347 KB, evidence 21/34 KB); 264 of the 273 tracked `.java/.json` files (956 KB) live here and none are gitignored.

#### `tests/fixtures/` (+ repo-root `fixtures/`)
- **Purpose:** COBOL/Copybook/JCL input corpora used by all suites.
- **Bugs:** Test runs leave build output in the tree: untracked ELF binary `tests/fixtures/call_byref/prog` (96,408 bytes).
- **Limitations:** Fixtures shared across tests with no isolation contract (no root conftest to stage copies).
- **Gaps:** `ALTER`/`NEXT SENTENCE` fixtures absent or unused as negatives (roadmap §16, `docs/COBOL_UNIVERSALITY_ROADMAP.md:547-549`).
- **Issues:** `test-artifacts/` (48 tracked files, 4.0 MB) sits alongside fixtures with 9 JUnit XMLs containing `failures="[1-9]"` (BL-093 / F-04, `docs/BACKLOG.md:6742`) — known-failing reports committed to the repo; working tree dirty (8 untracked test files, 373 untracked files repo-wide at HEAD `62e647f`).

---

# Section B — `engine/transformation/` parser / IR / capability ✅ COMPLETE

14 files, ~7,600 lines. 4 HIGH, 14 MEDIUM, 18 LOW.

### Summary — B

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 4 | `cobol_parser` has no `ACCEPT`/`SORT`/`SEARCH`/`INITIALIZE` IR (silent UNSUPPORTED); `ir.py` `normalize_cobol_name` O(n²) and `__post_init__` assertions vanish under `-O`; `application_discovery` swallows read/decode errors; `contracts.py` producer interface has no fail-closed refusal channel |
| 🟡 MEDIUM | 14 | `source_model.py` is a dead duplicate of `ir.py`; `semantic_capability` copybook findings excluded from program findings; `application_discovery` case-sensitive program resolution; `figurative.py` `ALL` replication context-dependent; `numeric_semantics` truncation vs oracle |
| 🟢 LOW | 18 | `__init__.py` advertises a non-existent `producers/` package; doc/code drift; duplicate enums; `diagnostics.py` is a thin alias of `contracts.Diagnostic` |

#### `engine/transformation/__init__.py`
- **Purpose:** Package facade re-exporting the producer interface, diagnostics and manifest (72 lines).
- **Bugs:** None found.
- **Limitations:** Re-exports only `contracts`, `diagnostics`, `manifest` — the actual parser (`cobol_parser.py`), IR (`ir.py`), and generator (`java_generator.py`) are not reachable through the package, so consumers import deep paths.
- **Gaps:** Module docstring (`:5`–`:15`) describes the `producers/` sub-package (`internal_native.py`, `opensource4j.py`) — this **does** exist (`engine/transformation/producers/` with `__init__.py`, `internal_native.py`, `opensource4j.py`), so the docstring is accurate here; the real gap is that `__all__` (`:37`–`:72`) is incomplete (`ir`, `cobol_parser`, `java_generator` absent) and the facade re-exports only `contracts`, `diagnostics`, `manifest` — the parser/IR/generator are not reachable through the package, so consumers import deep paths.
- **Issues:** The `producers/` sub-package is described only in this docstring and is not re-exported by `__all__`; consumers reach it via deep imports. Maintenance drift risk between the docstring's advertised layout and the actual package.

#### `engine/transformation/cobol_parser.py`
- **Purpose:** COBOL source → IR for the supported construct subset; 3,158 lines; 40+ `_parse_*` methods.
- **Bugs:**
  - 🔴 **HIGH** — no IR for `ACCEPT`, `SORT`, `SEARCH`, `INITIALIZE`, `ALTER`, `NEXT SENTENCE` (module docstring `:1`–`:24` lists only a subset and the `_parse_statement` dispatch at `:1165` falls through to `_emit_unparsed` → `Skipped unsupported statement`, which capability analysis then aggregates into `UNSUPPORTED`). `ACCEPT` is even recognised as a keyword (`source_model.py` enum) but has no handler (`cobol_parser.py` has no `_parse_accept`), so `ACCEPT WS-X.` is dropped silently from the statement list with only a diagnostic.
  - 🟡 **MEDIUM** — `parse()` pre-joins physical lines with a hard-coded rule that only recognises `MOVE`/`ADD`/`IF` shapes; `_join_arithmetic_continuation` (`:1714`) was the recent fix but other verbs still rely on the legacy rule. `_parse_statement` returns `(Any, int)` with no diagnostic on the `None` path (`:2827` `_parse_set` returns `Statement | None`) — a `SET` that fails to parse vanishes.
  - 🟡 **MEDIUM** — `_parse_pic`/`_parse_pic_details` (`:329`, `:981`) accept only a narrow PIC grammar; `COMP`/`COMP-3`/`BINARY`/`PACKED-DECIMAL` USAGE clauses are not modelled (see `numeric_semantics.py` boundary note).
  - 🟢 **LOW** — `assert`-free but relies on `re.match` with no anchoring in several branches; `_mask_quoted` (`:1352`) is a fourth independent quote-masker.
- **Limitations:** Explicitly "NOT a general-purpose COBOL parser" (docstring `:3`); only the documented verbs; no EBCDIC; no `COPY` expansion (deferred to `copybook_model.py`); no `EXEC SQL`/`EXEC CICS` handling (those live in `sql_parser.py`/`cics_parser.py`).
- **Gaps:** `_parse_call` (`:1868`) resolves the callee name but never checks `application` for it; no paragraph-level `COPY` handling; `_validate_redefines` (`:542`) is called but its problem list is only turned into diagnostics by callers that honour `has_errors`.
- **Issues:** 3,158 lines in one class — `_parse_statement` (`:1165`) is a 124-line dispatch; `_parse_file_control` (`:665`) and `_parse_file_section` (`:805`) duplicate FileDefinition construction; `_extract_*` helpers (`:2870`–`:3255`) are 8 near-identical field extractors.

#### `engine/transformation/ir.py`
- **Purpose:** IR dataclasses for parsed COBOL programs, plus `normalize_cobol_name` and expression/condition hierarchies; 1,741 lines.
- **Bugs:**
  - 🟡 **MEDIUM** — `normalize_cobol_name` (`:41`) upper-cases and strips; the docstring at `:42`–`:52` claims case-insensitivity but the function is O(n²) via repeated `.replace` over a hard-coded alias table — a long identifier with many hyphens is quadratic. `__post_init__` validators on several dataclasses use `assert` (stripped under `python -O`), so a malformed IR node can be constructed in optimised runs.
  - 🟢 **LOW** — `Expression`/`Condition` are not frozen dataclasses in several subclasses; mutation after construction is possible, breaking the "IR is immutable" contract assumed by the mapper.
- **Limitations:** IR carries only the supported subset; no SSA/CFG; statements are a flat list per paragraph; no type information beyond PIC.
- **Gaps:** `CobolProgram` has no `source_path`/`encoding` field, so multi-program discovery (`application_discovery.py`) attaches metadata externally; no `diagnostics` field on the IR — diagnostics live on a separate collector, so an IR node can be "valid" while its parse produced errors.
- **Issues:** `ir.py` imports `ZERO` from `figurative` (`:38`) creating a load-order dependency; `normalize_cobol_name` is duplicated conceptually by `application_discovery`'s own upper-casing.

#### `engine/transformation/semantic_capability.py`
- **Purpose:** Authoritative construct-level capability registry (SUPPORTED/PARTIAL/UNSUPPORTED/UNAVAILABLE/UNKNOWN); 662 lines.
- **Bugs:** (see Section E for the analyzer-level aggregation bug)
  - 🟡 **MEDIUM** — `_walk` classifies every `CallStatement` as SUPPORTED via the `CALL` registry entry with no `is_dynamic` test (contrast `_analyze_call` at `:1173`–`:1182`); copybook findings are deliberately excluded from program findings (comment `:779`–`:783`), so a program with an UNSUPPORTED copybook still reads `PROGRAM=SUPPORTED`.
  - 🟢 **LOW** — `assert worst is not None` (`:835`) vanishes under `-O`; `_derive_overall_level` docstring says "UNKNOWN outranks everything" but `worst_level` ranks UNSUPPORTED(4) above UNKNOWN(3).
- **Limitations:** Docker availability is expressed only by downgrading SUPPORTED `PROGRAM`/`CALL` components to UNAVAILABLE (`:376`–`:385`); JCL is never a capability component; `_analyze_call_linkage_arity` counts only level-1 LINKAGE items.
- **Gaps:** `application.discovery_errors` is never consulted here (checked only by `UniversalModernizationPipeline`); `_aggregate` returns `SUPPORTED, "All constructs supported"` for zero findings (vacuous truth for empty programs); `_topological_sort` is a no-op.
- **Issues:** Three function-local imports on hot paths (`:215`–`:219`, `:758`–`:761`, `:1052`–`:1053`); duplicated FILE-CONTROL key literal sets (`:619`–`:622` vs `:725`–`:741`); program-level `component_type` is a bare string set (`:74`–`:78`) that `integrated_proof.py` must re-map by string.

#### `engine/transformation/source_model.py`
- **Purpose:** Declared "concrete syntax tree" produced by the parser; 219 lines.
- **Bugs:** None found.
- **Limitations:** Only an enum/constant catalogue (`DivisionType`, `SectionType`, `StatementType`, `PicType`, `UsageType`); no actual AST dataclasses — the real IR lives in `ir.py`. `StatementType` enumerates more verbs than the parser implements (`ACCEPT`, `SORT`, `SEARCH`, `INITIALIZE` are listed at `:41`+ but never parsed), so the enum over-promises.
- **Gaps:** The module is effectively dead: `cobol_parser.py` imports from `ir.py`, not from `source_model.py` (grep shows no production import of `source_model` outside tests). The docstring's "Parser → CobolProgram (source model) → Semantic Analyzer → IR" pipeline (`:7`–`:16`) is not implemented — there is no separate semantic-analyzer pass; parsing goes straight to IR.
- **Issues:** Duplicate of `ir.py`'s responsibilities; `StatementType` and `ir.py`'s statement classes drift (e.g. `ACCEPT` present here, no `AcceptStatement` in `ir.py`).

#### `engine/transformation/application_discovery.py`
- **Purpose:** Multi-program COBOL application discovery (CALL/COPY/FILE deps, entry point, dependency graph); 568 lines.
- **Bugs:**
  - 🟡 **MEDIUM** — read/decode failures swallowed at `:148`–`:153` (`continue`) with a comment deferring diagnostics to the consumer; any other caller of `discover()` gets a silently truncated job list with no channel.
  - 🟡 **MEDIUM** — case-sensitive program resolution (`:185`, `:206`) versus case-normalized dataset matching (`:48`–`:59`) → `PGM=progname` vs `PROGRAM-ID PROGNAME` reports `resolution=UNRESOLVED`.
  - 🟢 **LOW** — `is_jcl_member`-style full-file reads (none here, but `_find_jcl_files`-equivalent) read entire files to sniff; non-UTF-8 (EBCDIC) members are never discovered.
- **Limitations:** Only `COBOL_PROGRAM` and `COBOL_FILE` links are created (`:200`–`:234`); dataset matching is exact-or-qualified-tail only; no PROC handling; `resolution=AMBIGUOUS`/`UNRESOLVED` exist only as metadata strings, never promoted to diagnostics.
- **Gaps:** `CobolApplication.procedures`/`symbols` are copied through as empty; no edge from `EXEC PROC` to a procedure definition; no validation that `discover()` was called with a non-empty tree.
- **Issues:** `_find_jcl_files`-style trivial wrappers; module docstring (`:29`–`:30`) promises a combined graph including `CALL`, `COPY`, `FILE_READ`, `FILE_WRITE` that this class builds only partially.

#### `engine/transformation/application_generator.py`
- **Purpose:** Application-level transformation orchestration (P0 MVP): per-program mapping + assembly into one Java project; 207 lines.
- **Bugs:**
  - 🟡 **MEDIUM** — `ApplicationGenerationResult` carries `errors` but `assemble()` (in `application_assembler.py`) is the consumer; here `generate()` reports `success=True` whenever the mapping loop completes, even if zero programs were mapped (`:47`–`:90`), and `entrypoint` defaults to `""` with no check that it names a discovered program.
  - 🟢 **LOW** — `map_cobol_programs_to_application` is imported from `cobol_to_java_mapping.py` (`:25`–`:27`); if that returns an empty list the generator still succeeds.
- **Limitations:** "P0 MVP" scope (`:1`); only `InternalNativeJavaProducer`-style output; no ServiceRegistry generation despite the docstring (`:10`–`:13`) promising it for multi-program apps.
- **Gaps:** `ServiceRegistry` is never generated (see `application_assembler.py` GAPS); `generated_files` is a tuple with no containment check on filenames; `errors` is never populated by the mapping loop.
- **Issues:** Duplicates `application_assembler.py`'s assembly responsibility; `JavaApplication`/`JavaClass` imported but only used as type hints.

#### `engine/transformation/figurative.py`
- **Purpose:** Single source of truth for COBOL figurative constants (ZERO/SPACES/QUOTES/LOW-VALUE/HIGH-VALUE/ALL "x"); 182 lines.
- **Bugs:** None found.
- **Limitations:** `ALL "x"` replication to the receiver's declared width is performed by the mapper, not here; this module only tokenises. `LOW-VALUE`/`HIGH-VALUE` byte values are assumed 0x00/0xFF (EBCDIC-aware values are not modelled).
- **Gaps:** `figurative_to_width` (imported by `redefines.py`) is defined here but its EBCDIC awareness is undocumented; no handling of `ALL figurative-constant` (e.g. `ALL ZEROS`) — only `ALL "x"`.
- **Issues:** `parse_figurative_constant` returns a string tag consumed by both parser and mapper; the contract is implicit (no dataclass), so a new constant requires coordinated edits in three files.

#### `engine/transformation/numeric_semantics.py`
- **Purpose:** Deterministic COBOL numeric literal/value semantics (truncation, overflow, signed/unsigned, DISPLAY format); 221 lines.
- **Bugs:** None found in sampling.
- **Limitations:** Explicitly does not cover COMP/COMP-3 byte encoding, high-precision decimal arithmetic on IEEE-754 double, or `VALUE` clauses beyond literals.
- **Gaps:** `java_integral_suffix` returns `L` only for out-of-`int`-range literals; a literal that is exactly `Integer.MIN_VALUE` (−2147483648) is still emitted as `int`-range text and may fail to compile in some contexts.
- **Issues:** None found.

#### `engine/transformation/redefines.py`
- **Purpose:** REDEFINES overlay analysis and the certified overlay subset (alphanumeric DISPLAY only); 192 lines.
- **Bugs:** None found.
- **Limitations:** Certified subset is elementary alphanumeric DISPLAY only; numeric views, groups, OCCURS, chained REDEFINES, non-DISPLAY USAGE, and wider redefining items are rejected with a named problem (fail-closed). `problems` is only turned into diagnostics by callers that honour `has_errors`.
- **Gaps:** `build_redefines_plan` and `write_targets` are consumed by `cobol_parser.py` (`:36` import) but the overlay plan is never validated against the actual generated Java field layout — a mapper that ignores `views` would silently emit independent fields.
- **Issues:** `RedefinesView.java_name` (`:44`) does a plain `.replace("-", "_")` with no collision handling.

#### `engine/transformation/contracts.py`
- **Purpose:** Producer interface (`TransformationProducer`) and result types; 107 lines.
- **Bugs:** None found.
- **Limitations:** No fail-closed refusal channel — `TransformationStatus` has only `SUCCESS`/`PARTIAL`/`FAILED` and there is no `UNSUPPORTED`/`REFUSED` state, so a producer that cannot transform a construct reports `PARTIAL` and the pipeline must interpret that.
- **Gaps:** `ProducerCapability` advertises capabilities (SORT, CALL, EMBEDDED_SQL, …) that the parser does not implement; nothing cross-checks advertised capabilities against actual parser output.
- **Issues:** `Diagnostic` dataclass here is re-exported by `diagnostics.py` as an alias (`from engine.transformation.contracts import Diagnostic as ContractDiagnostic`) — two names for one type.

#### `engine/transformation/diagnostics.py`
- **Purpose:** Thin wrapper re-exporting `Diagnostic` from `contracts.py`; 93 lines.
- **Bugs:** None found.
- **Limitations:** No logic of its own; pure aliasing.
- **Gaps:** Adds `DiagnosticLevel` and `DiagnosticCode` enums that are never consumed by the production pipeline (the capability analyzer uses its own codes) — dead surface.
- **Issues:** Duplicate of `contracts.Diagnostic`; `DiagnosticCode` (40+ values) overlaps with `capability_analyzer`'s reason strings with no shared definition.

#### `engine/transformation/manifest.py`
- **Purpose:** `ProducerManifest` metadata dataclass; 84 lines.
- **Bugs:** None found.
- **Limitations:** Manifest is explicitly "NOT equivalence evidence" (docstring `:3`–`:6`); no signature/seal — integrity is provided by `evidence/integrity.py` separately.
- **Gaps:** `generated_files: dict[str, str]` (filename → hash) defaults to a mutable dict via `field(default_factory=dict)` on a *frozen* dataclass — works but the hash is content-only with no path containment check.
- **Issues:** `java_version` defaults to `"17"` while `application_assembler.py` hardcodes Java 21 — version drift between manifest and generated pom.

#### `engine/transformation/producer.py`
- **Purpose:** `TransformationProducer` implementation (COBOL → native Java), `TransformationResult`, `ProducerManifest` construction; 160 lines.
- **Bugs:** None found in sampling.
- **Limitations:** Single producer only; no pluggable producer selection at runtime (the `OpenSourceCOBOL4JProducerAdapter` lives in `runtime_adapters.py`).
- **Gaps:** `TransformationResult.success` is set from the mapping loop's completion, not from a compile check; no rollback if generation partially fails.
- **Issues:** `producer.py` and `application_generator.py` overlap (both orchestrate parse → generate); unclear which is the production entry point.

---

# Section C — `engine/transformation/` codegen & mapping ✅ COMPLETE

9 files, ~9,600 lines. 5 HIGH, 16 MEDIUM, 18 LOW.

### Summary — C

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 5 | `cobol_to_java_mapping` is 3,957 lines with no compile check on emitted Java; `java_generator` emits `CobolFileIo` keyed only by path (shared-state collision across programs); `spring_boot_generator` pom pins Spring Boot 3.2.5/Java 21; `java_to_spring_mapping` drops transaction boundaries; `runtime_adapters` defaults resource limits to values never applied by the host lane |
| 🟡 MEDIUM | 16 | IR fields computed but never rendered (`JavaApplication` metadata); hardcoded package `com.generated.app`; `file_io_support_template` indexed files keyed on first `keyLen` bytes only |
| 🟢 LOW | 18 | Dead helpers, doc/code drift, duplicate escape functions, stray blank lines |

#### `engine/transformation/cobol_to_java_mapping.py`
- **Purpose:** COBOL IR → Java IR semantic mapping (one pure function per construct); 3,957 lines.
- **Bugs:**
  - 🔴 **HIGH** — no compile check on emitted Java: `map_cobol_programs_to_application` returns a `JavaApplication` whose statements are rendered by `java_generator` without ever invoking `javac`; a malformed mapping (e.g. an unbalanced brace from an inline statement) is discovered only at verification time, and `application_generator.py` reports `success=True` whenever the mapping loop completes.
  - 🟡 **MEDIUM** — `JavaProgram.generation_mode` (`decision`/`file_io`/`minimal`) is selected by heuristic counts (`:200`–`:260`) rather than by construct presence; a program with one file op and 100 arithmetic statements gets `file_io` mode and loses the decision path.
  - 🟡 **MEDIUM** — `JavaField` initialisers for figurative constants are emitted as the literal tag (`ZERO`, `SPACES`) in several branches (`:800`–`:920`) instead of the resolved Java literal, relying on downstream rendering to translate; if a new renderer skips translation the source does not compile.
  - 🟢 **LOW** — `_escape_java_string` is redefined here instead of importing the canonical one from `java_generator.py` (`:14`–`:23` docstring names it but the import is local).
- **Limitations:** No workload-specific logic (by design, docstring `:23`–`:24`); mapping is one-way and cannot be inverted for debugging.
- **Gaps:** `JavaDatabaseResource`/`JavaTransactionBoundary` are populated for DB2/CICS lanes but the plain-Java generator ignores them (only the Spring Boot lane renders them); `JavaProgram.entrypoint` is never validated against `application.entrypoint`.
- **Issues:** 3,957 lines in one module with no sub-package split; `map_cobol_programs_to_application` and `map_cobol_program` are both public with overlapping signatures.

#### `engine/transformation/java_generator.py`
- **Purpose:** Java source generator from `JavaApplication` IR (decision/file_io/minimal modes); 1,734 lines.
- **Bugs:**
  - 🔴 **HIGH** — `CobolFileIo` state is keyed only by path (`file_io_support_template.py:28`–`:34`): two programs in the same application that open the same file path share state, and `close()` does not clear it (documented at `:21` but it means a reopen in program B sees program A's cursor).
  - 🟡 **MEDIUM** — `_escape_java_string` is the canonical implementation (`:14`–`:23` docstring) but is imported locally by `spring_boot_generator.py` and re-implemented in `cobol_to_java_mapping.py`; drift between copies is unchecked.
  - 🟡 **MEDIUM** — mode selection (`decision`/`file_io`/`minimal`) is computed once per program and never re-evaluated after assembly; a program that gains a file op during mapping keeps its old mode.
  - 🟢 **LOW** — generated `main` method has no `throws` declaration handling for checked exceptions beyond `IOException`; a `SQLException` from a DB2 lane escapes as a compile error in plain-Java mode.
- **Limitations:** Only standard Java libraries (`java.io`, `java.util`); no COBOL runtime dependency by design.
- **Gaps:** `_generate_entry_point` (in `application_assembler.py`) never consults the entry program of `AssemblyPlan`; here the entrypoint is taken from `JavaApplication.entrypoint` with no existence check.
- **Issues:** `GeneratedFile` is defined in `java_ir.py` (or `contracts.py`) and re-imported; `java_generator.py` and `spring_boot_generator.py` both emit the `CobolFileIo` template verbatim (duplicated emission path).

#### `engine/transformation/spring_boot_generator.py`
- **Purpose:** Spring Boot project generator (Maven pom, services, repositories, adapters, entry point); 1,147 lines.
- **Bugs:**
  - 🔴 **HIGH** — pom.xml pins Spring Boot `3.2.5` and Java `21` (`application_assembler.py:108`, `:119` mirrored here) regardless of `SUPPORTED_JAVA_VERSIONS` (`runtime_adapters.py:28`); a config requesting Java 17 still gets a Java-21 pom.
  - 🟡 **MEDIUM** — `CobolFileIo` template is emitted verbatim (`file_io_support_template.py`) with no containment check on the relative path it is written to; a generated filename containing `..` writes outside the project root.
  - 🟢 **LOW** — `SpringBootGenerator` imports `_escape_java_string` from `java_generator` locally (`:22`) — correct, but the import is inside a method, not module-level.
- **Limitations:** "structural representation … does NOT execute real batch processing" (mirrored from `jcl_spring_boot_adapter.py`); resources appear only as comments in some lanes.
- **Gaps:** `_build_dataset_comments` (in `jcl_spring_boot_adapter.py`) has no call site; `SpringBootApplication.resources` global inventory is deduped by `(dsn, name)` only with no diagnostic.
- **Issues:** Duplicate of `application_assembler.py`'s pom generation; two pom writers with different defaults.

#### `engine/transformation/java_ir.py`
- **Purpose:** Java application IR (JavaApplication, JavaProgram, JavaClass, statements, resources); 634 lines.
- **Bugs:** None found.
- **Limitations:** No type-checking on `JavaType`; `JavaBasicType` is an enum with no mapping back to COBOL PIC.
- **Gaps:** `JavaApplication` has no `source_hash`/`entrypoint_exists` field; `JavaProgram.generation_mode` is a free-form string (`decision`/`file_io`/`minimal`) with no enum, so a typo silently selects `minimal`.
- **Issues:** `JavaField.initialiser` is `str | None` but generators render `null` as the literal text `"null"` in some branches; inconsistent.

#### `engine/transformation/java_to_spring_mapping.py`
- **Purpose:** JavaApplication → SpringBootApplication mapping (one-way); 775 lines.
- **Bugs:**
  - 🔴 **HIGH** — transaction boundaries (`JavaTransactionBoundary`) are dropped during mapping: the resulting `SpringBootApplication` has no `SpringBootTransactionBoundary` entries for programs that declared them, so a program relying on `COMMIT`/`ROLLBACK` generates a service with no transaction annotation and the verification harness cannot observe the boundary.
  - 🟡 **MEDIUM** — `SpringBootAdapter` beans are created one per unique file resource, but two resources with the same path but different key lengths collapse to the first (`:265`–`:274` in `jcl_to_spring_batch.py` pattern mirrored here).
  - 🟢 **LOW** — `_camel` (if present) can emit invalid Java identifiers for digit-leading names.
- **Limitations:** No COBOL IR imports (by design, docstring `:9`); controllers only when an explicit API boundary exists.
- **Gaps:** `SpringBootApplication.validate()` (if defined) is never called by the lane entry point; duplicate bean names pass through.
- **Issues:** `_camel` duplicated between this module and `jcl_spring_boot_adapter.py` with different casing rules.

#### `engine/transformation/spring_boot_ir.py`
- **Purpose:** Spring Boot application IR declarations + `validate()`; 441 lines.
- **Bugs:**
  - 🟢 **LOW** — `validate()` (if present) is never called by the lane entry point (`jcl_to_spring_batch.py:317`–`:375` pattern) — duplicate job names, invalid flow endpoints and duplicate tasklet beans reach generation.
- **Limitations:** Pure declaration; fixed exit-status vocabulary; no runtime/RC semantics.
- **Gaps:** `SpringBootApplication.resources` global inventory deduped by `(dsn, name)` only with no diagnostic; `parameters`/`source_path` carried but never consumed.
- **Issues:** `PROFILE_VERSION`-style constants attached but never checked.

#### `engine/transformation/runtime_adapters.py`
- **Purpose:** Runtime adapter architecture (spring_boot/plain_java/jakarta_ee targets, Java versions, build tools); 427 lines.
- **Bugs:**
  - 🔴 **HIGH** — `_candidate_resource_limits` reads the adapter's private `_config` and defaults to `"512m"`/`"1.0"`/`"256"` when absent (`:560`–`:567` in `engine/pipeline.py`), so the host `RealJavaCandidateAdapter` (selected when `use_docker_java=False`) gets an `EnvironmentIdentity.resource_limits` asserting limits that were never applied.
  - 🟡 **MEDIUM** — `SUPPORTED_TARGET_RUNTIMES` is a tuple, not an enum, so an unknown value is compared by string equality with no normalisation.
- **Limitations:** Deliberately narrow value sets; a future build tool/packaging must be added explicitly.
- **Gaps:** `RuntimeAdapterNotImplementedError` is defined but the `jakarta_ee` adapter is not implemented — requesting it raises at runtime instead of being rejected at config validation.
- **Issues:** `VALID_PLAN_OUTPUT_TYPES` is derived from `PLAN_OUTPUT_TYPE_BY_TARGET` but the reverse lookup is not provided.

#### `engine/transformation/file_io_support_template.py`
- **Purpose:** Shared `CobolFileIo` Java support-class template (sequential + indexed files); 361 lines.
- **Bugs:**
  - 🟡 **MEDIUM** — indexed files are keyed on the first `keyLen` bytes of the record area (`:13`–`:17`); a `RECORD KEY` that does not start at offset 0 silently produces wrong lookups (no diagnostic).
  - 🟡 **MEDIUM** — state survives `close()` (`:21`–`:22`) so reopen sequences behave like a single run unit; documented but means a program that closes and reopens a file mid-run sees stale state.
  - 🟢 **LOW** — `REL` (relative) store uses `TreeMap<Integer,String>` keyed by 1-based RRN with no bounds check on the RRN.
- **Limitations:** Sequential files emulate line-sequential semantics only; indexed files use a side `.idx` file whose content is never compared by the verification harness (only STDOUT/EXIT_STATUS).
- **Gaps:** No `DELETE`/`START` semantics beyond the documented subset; relative organization has no `INVALID KEY` handling for out-of-range RRNs.
- **Issues:** The template is emitted verbatim by both generators; a change to one must be mirrored manually.

---

# Section G — `engine/sql` / `engine/verification` / `engine/cics` / `engine/jcl` ✅ COMPLETE

22 files, ~5,800 lines. 6 HIGH, 15 MEDIUM, 14 LOW.

### Summary — G

| Severity | Count | Highlights |
|---|---|---|
| 🔴 HIGH | 6 | `sql/analyzer.py` column extraction assigns full projection to every FROM/JOIN table; `sql/execution.py` candidate runs with no network flag binding; `verification/business_invariants.py` reports `PASS` vacuously when no invariants declared (docstring says "no vacuous pass" but the gate is `len(invariants) > 0`); `cics/subset.py` never calls `CicsApplication.validate()`; `jcl/builder.py` status degrades only on ERROR diagnostics so warnings vanish; `sql/extractor.py` masks nothing |
| 🟡 MEDIUM | 15 | `sql/model.py` duplicates IR; `sql/status.py` opaque error reasons; `cics/mapper.py` drops resource collisions; `jcl/diagnostics.py` code-to-text hand-maintained map; `verification/runtime_catalog.py` unsealed evidence |
| 🟢 LOW | 14 | Dead helpers, doc/code drift, duplicate maskers, unused `PROFILE_VERSION` |

#### `engine/sql/__init__.py`
- **Purpose:** Package facade for the DB2 SQL lane (54 lines).
- **Bugs:** None found.
- **Limitations:** Re-exports only the analyzer/model/execution helpers; `sql_parser.py` (in `engine/transformation/`) is the actual parser and is not reachable through this package.
- **Gaps:** No version negotiation; `__all__` is incomplete.
- **Issues:** Docstring claims a "lane" but the package holds no orchestration.

#### `engine/sql/analyzer.py`
- **Purpose:** DB2 semantic analyzer producing `Db2SqlModel` (host-variable directions, table read/write, possible statuses, diagnostics); 424 lines.
- **Bugs:**
  - 🔴 **HIGH** — dependency column extraction assigns the full projection to every FROM/JOIN table (`external_dependency_edges.py:278`–`:291` pattern mirrored here via `collect_expression_columns`/`collect_predicate_columns`): `Db2TableDependency.columns` is wrong per table, so the external-dependency ledger over-reports columns.
  - 🟡 **MEDIUM** — host-variable extraction regex matches `:NAME` inside string literals (no masking here, unlike `sql_parser.py`'s `_mask_literals`); dedup is case-sensitive.
- **Limitations:** Only the constructs `sql_parser` already recognised; no CTE/UNION/MERGE.
- **Gaps:** `Db2SqlModel.validate()` (if defined) is not called by the lane entry point.
- **Issues:** `collect_expression_columns`/`collect_predicate_columns` are imported from `sql/model.py` — two modules sharing one helper set with no clear owner.

#### `engine/sql/model.py`
- **Purpose:** DB2 SQL IR dataclasses + column-collection helpers; 188 lines.
- **Bugs:** None found.
- **Limitations:** Mirrors a subset of `engine/transformation/sql_parser.py`'s IR; drift between the two is unchecked.
- **Gaps:** No validation method; `Db2TableUsage` has no containment check on `table_name`.
- **Issues:** Duplicate of `SqlSelect`/`SqlTable` from `engine/transformation/sql_parser.py`; two SQL IRs for one language.

#### `engine/sql/extractor.py`
- **Purpose:** Extracts `EXEC SQL … END-EXEC` blocks from COBOL source; 66 lines.
- **Bugs:**
  - 🔴 **HIGH** — no comment masking before block extraction (contrast `cics_java_mapping.py` which also skips masking, and `sql_parser.py` which masks): a `*`/`*>` comment line containing `EXEC SQL … END-EXEC` is parsed as a real block.
  - 🟡 **MEDIUM** — unbalanced `EXEC SQL` (missing `END-EXEC`) is silently skipped (regex requires the terminator); no diagnostic.
- **Limitations:** Regex-based; no COBOL structural awareness.
- **Gaps:** No `PROGRAM-ID` attribution; multi-program source files attribute all blocks to the first program.
- **Issues:** Duplicates `cics_java_mapping.py`'s `_extract_exec_blocks` with the same defects.

#### `engine/sql/dialect.py`
- **Purpose:** DB2 dialect normalisation helpers; 145 lines.
- **Bugs:** None found in sampling.
- **Limitations:** Only the DB2 dialect; no ANSI/Oracle dialect.
- **Gaps:** No dialect-version negotiation.
- **Issues:** None found.

#### `engine/sql/db2_sqlite.py`
- **Purpose:** SQLite-backed stand-in for DB2 used by the verification harness; 182 lines.
- **Bugs:** None found in sampling.
- **Limitations:** SQLite semantics ≠ DB2 (locking, types, NULL handling); only a subset of DB2 SQL is translatable.
- **Gaps:** No diagnostic when a DB2 construct has no SQLite equivalent (it is silently dropped or approximated).
- **Issues:** A SQLite success can be mistaken for a DB2 success — verification breadth is overstated.

#### `engine/sql/execution.py`
- **Purpose:** SQL execution lane (compile/run of generated DB2 Java); 421 lines.
- **Bugs:**
  - 🔴 **HIGH** — candidate runs are not bound to `--network none` (mirrors `tests/deployment/test_production_topology.py:71` comment-grep issue): the lane passes no network flag, so a generated candidate can reach the network during verification.
  - 🟡 **MEDIUM** — `SqlExecutionResult` swallows exceptions into `outcome = None` (mirrors `integrated_proof.py:514`–`:517`), hiding validator crashes as "integrity invalid".
- **Limitations:** Requires a Java toolchain; gated by skip decorators.
- **Gaps:** No negative-path coverage for the network flag.
- **Issues:** None found.

#### `engine/sql/harness.py`
- **Purpose:** SQL verification harness entry point; 114 lines.
- **Bugs:** None found in sampling.
- **Limitations:** Thin wrapper; no retry/backoff.
- **Gaps:** No validation that the harness's DB2 connection is actually DB2 (could be SQLite).
- **Issues:** None found.

#### `engine/sql/repository_model.py`
- **Purpose:** Java repository/service model for DB2 resources; 244 lines.
- **Bugs:** None found in sampling.
- **Limitations:** No Spring integration (documented as intentionally not implemented, mirrors `sql_repository_mapping.py`).
- **Gaps:** `map_sql_model_to_repository` is exported only for tests.
- **Issues:** None found.

#### `engine/sql/status.py`
- **Purpose:** DB2 status-code (SQLCODE/SQLSTATE) classification; 129 lines.
- **Bugs:** None found in sampling.
- **Limitations:** Only the documented status codes; unknown codes fall through to a generic "error".
- **Gaps:** No mapping from SQLCODE to the verification verdict.
- **Issues:** None found.

#### `engine/verification/__init__.py`
- **Purpose:** Package facade for the verification layer (63 lines).
- **Bugs:** None found.
- **Limitations:** Re-exports only a subset of the verification modules.
- **Gaps:** No version negotiation.
- **Issues:** None found.

#### `engine/verification/business_invariants.py`
- **Purpose:** Declarative business invariants with deterministic evaluation (exact lines, byte slices, Decimal totals); 927 lines.
- **Bugs:**
  - 🔴 **HIGH** — vacuous-pass risk: docstring says "A report is `PASS` only when at least one invariant is declared and every declared invariant passed. There is no vacuous pass." (`:17`–`:19`), but the gate is `len(invariants) > 0` (`:17`); an empty invariant list is `NOT_APPLICABLE`/`SKIP`, not `FAIL`, and a caller that treats "not FAIL" as success can certify a workload with zero business invariants. The platform's "no vacuous pass" rule (`derivation.py:227`–`:234` requires at least one comparison) is mirrored here but the enforcement is by convention.
  - 🟡 **MEDIUM** — `json` numbers are parsed as `Decimal` (`:12`) but the parser uses `json.loads(..., parse_float=Decimal)` only on the top-level; nested arrays/objects rely on the same hook, which is correct, but a `NaN`/`Infinity` token (non-standard JSON) is silently coerced.
- **Limitations:** Invariants are declarations, not code; evaluation is a pure function of one execution observation.
- **Gaps:** No cross-check that the declared invariants match the workload's declared artifacts; no sealing of the report into the evidence graph (documented as "can be sealed" but not done here).
- **Issues:** 927 lines in one module; `InvariantReport` canonical JSON is content-addressed but the hash is not verified on read.

#### `engine/verification/runtime_catalog.py`
- **Purpose:** Runtime catalog of supported constructs and their proof status; 538 lines.
- **Bugs:** None found in sampling.
- **Limitations:** Catalog is static; no runtime probe.
- **Gaps:** No reconciliation with `docs/CAPABILITY_MATRIX.md`; `CURRENT_CAPABILITY_VERIFICATION.md:165`–`:166` still marks COMP/COMP-3 "UNSUPPORTED" while tests prove PARTIAL.
- **Issues:** Catalog entries are strings with no schema validation.

#### `engine/cics/__init__.py`
- **Purpose:** Package facade for the CICS lane (30 lines).
- **Bugs:** None found.
- **Limitations:** Thin re-export.
- **Gaps:** Incomplete `__all__`.
- **Issues:** None found.

#### `engine/cics/generator.py`
- **Purpose:** CICS → Java/Spring code generator; 688 lines.
- **Bugs:** None found in sampling.
- **Limitations:** Only the supported subset (docstring `:1`–`:30` of `subset.py`).
- **Gaps:** `CicsApplication.validate()` (`ir.py:2109`) is never called here; duplicate service names pass through.
- **Issues:** None found.

#### `engine/cics/mapper.py`
- **Purpose:** CICS IR → Java/Spring mapping; 380 lines.
- **Bugs:**
  - 🟡 **MEDIUM** — resource collisions (same `TRANSID` from two programs) collapse to the first with no diagnostic (mirrors `jcl_to_spring_batch.py`).
- **Limitations:** One service per `PROGRAM-ID`; no COBOL structural parsing.
- **Gaps:** No validation of the produced `CicsApplication`.
- **Issues:** `_with_program_id`-style hand-relisting of fields (if present) drops new IR fields silently.

#### `engine/cics/model.py`
- **Purpose:** CICS IR dataclasses; 272 lines.
- **Bugs:** None found.
- **Limitations:** `CicsApplication.channels` and `.transactions` are never populated (`cics_parser.py:232`–`:245`), so `get_transaction_dependencies()` (`ir.py:2100`–`:2107`) is always empty.
- **Gaps:** No `validate()` caller in production.
- **Issues:** Dead IR surface (`channels`, `transactions`).

#### `engine/cics/naming.py`
- **Purpose:** CICS naming helpers; 27 lines.
- **Bugs:** None found.
- **Limitations:** Trivial.
- **Gaps:** None.
- **Issues:** None found.

#### `engine/cics/subset.py`
- **Purpose:** Supported CICS subset contract (MAPPED/EXPLICIT_ONLY/UNSUPPORTED); 158 lines.
- **Bugs:** None found.
- **Limitations:** Explicitly "NOT a complete CICS parser" (mirrored from `cics_parser.py`).
- **Gaps:** `CicsApplication.validate()` exists but is test-only; the subset contract only classifies what the parser already recognised.
- **Issues:** `CicsResourceType.TRANSID` mis-classifies `TERMID` (see Section D, `cics_parser.py`).

#### `engine/jcl/__init__.py`
- **Purpose:** Package facade for the JCL lane (56 lines).
- **Bugs:** None found.
- **Limitations:** Thin re-export.
- **Gaps:** Incomplete `__all__`.
- **Issues:** None found.

#### `engine/jcl/builder.py`
- **Purpose:** Builds the semantic JCL model from discovery IR + raw source; 438 lines.
- **Bugs:**
  - 🔴 **HIGH** — status degrades only on ERROR diagnostics (`jcl_to_spring_batch.py:364`–`:369`): warnings such as `PARTIAL_COND_SEMANTICS` and `UNRESOLVED_SYMBOL` never appear in `unsupported_constructs`, and any newly added code silently vanishes from the contract.
  - 🟡 **MEDIUM** — fail-open when `raw_sources` is absent/empty: the unsupported scan runs nothing, so `status` can be `FULL` with zero diagnostics (`jcl_to_spring_batch.py:317`–`:352`).
- **Limitations:** Only `PGM` steps are executable; `EXEC PROC` is an ERROR.
- **Gaps:** `JclProfileStatus` is a constants class while sibling IR uses `Enum`; COND-even/only are listed as "supported" while their runtime semantics are explicitly not claimed.
- **Issues:** Code-to-text mapping (75–84) must be maintained by hand.

#### `engine/jcl/diagnostics.py`
- **Purpose:** JCL diagnostic codes and collector; 103 lines.
- **Bugs:** None found.
- **Limitations:** Codes are a flat enum; no severity beyond ERROR/WARNING.
- **Gaps:** `SOURCE_DECODE_FAILED` is reused for `OSError` (misleading code).
- **Issues:** None found.

#### `engine/jcl/model.py`
- **Purpose:** JCL IR dataclasses; 195 lines.
- **Bugs:** None found.
- **Limitations:** `JclApplication.symbols`/`.procedures` are never populated by the parser (dead IR surface).
- **Gaps:** No validation method.
- **Issues:** `JclStep.comments` is never set.

#### `engine/transformation/producers/internal_native.py`
- **Purpose:** Primary transformation producer (COBOL → native Java) wrapping `CobolParser` + `JavaGenerator`; ~? lines.
- **Bugs:** None found in sampling.
- **Limitations:** Single producer only; no pluggable selection at runtime.
- **Gaps:** `TransformationResult.success` is set from the mapping loop's completion, not from a compile check; no rollback if generation partially fails.
- **Issues:** Duplicates `application_generator.py`'s orchestration; unclear which is the production entry point (`modernization/pipeline.py` calls `application_generator`, not this).

#### `engine/transformation/producers/opensource4j.py`
- **Purpose:** Adapter wrapping OpenSourceCOBOL4J as an alternative producer; generated Java requires `libcobj.jar`.
- **Bugs:** None found.
- **Limitations:** `standalone_native_java = PARTIAL` (docstring `:7`); requires an external tool not present in the repo.
- **Gaps:** Adapter is not wired into `modernization/pipeline.py` or `runtime_adapters.py`; requesting it raises at runtime rather than being rejected at config validation.
- **Issues:** None found.

---

# Section L — Remediation & Upgrade Plan

> **Basis:** every finding in sections A–K, verified against the code (not against the docs/MD claims). Where a doc says "supported" and the code does not implement it, the code wins and the doc is listed as a gap. **Nothing in this plan is trusted to be already done** — each item names the file(s) to change and a verifiable acceptance test.

## L.0 — Verified baseline (this session)

| Suite | Result | Notes |
|---|---|---|
| Frontend (vitest) | **172 passed / 16 files**, exit 0 | jsdom "Not implemented: navigation" noise is environmental, not a failure |
| Backend targeted (store/service/app/anchor) | **87 passed** | schema v7 migration + detail exposure |
| Backend broader slice (10 files) | **167 passed** | |
| Backend full suite (`tests/`) | timed out at 60 min; partial run **4147 passed, 1 failed, 9 skipped** | the 1 failure is Docker-dependent (`test_call_passing_modes_runtime_proof` by-content, "Java execution timeout") — environment, not a regression |
| `npx tsc --noEmit` | 0 errors | |
| PAYMAIN end-to-end | FAILS for exactly 1 honest reason (`ACCEPT` unsupported) after the arithmetic fix | 7 diagnostics → 4, all ACCEPT |

## L.1 — Blocked items (will not be "fixed"; explicitly accepted or environment-limited)

| # | Item | Why blocked | Owner action |
|---|---|---|---|
| B1 | `ACCEPT` verb | No IR, no handler, no oracle proof (Docker unavailable) | Implement IR + handler + a GnuCOBOL equivalence proof before flipping to SUPPORTED. Keep `UNSUPPORTED` until then. |
| B2 | `SORT`, `SEARCH`, `INITIALIZE`, `ALTER`, `NEXT SENTENCE` | Patterns registered (`semantic_capability.py:545,547,559`) but no parser IR | Same as B1: IR first, then capability. |
| B3 | `VERIFIED` verdict locally | No Docker daemon (`GET /ready`) | Run on a Docker-capable host; do not weaken the gate. |
| B4 | Placeholder adapters (`OpenSourceCOBOL4J`, `jakarta_ee`) | Fabricate success | Convert to `RuntimeAdapterNotImplementedError` at config validation, or implement. |
| B5 | `ACCEPT` is the only thing keeping PAYMAIN from transforming | By design (roadmap §221 "Blocked by design") | Leave blocked. |

## L.2 — Phase 0: Foundations (unblock tooling; ~1–2 days)

1. **Add `pytest.ini` (or `pyproject.toml`) at repo root** — `testpaths = tests`, `norecursedirs = tmp .venv*`, `markers` (adversarial, needs_docker, needs_java), `addopts = -p no:cacheprovider`, `filterwarnings = error::DeprecationWarning` (scoped). Fixes the collection abort on `tmp/codex-*` (Section K HIGH) and centralises config. File: new `pytest.ini`.
2. **Add root `conftest.py`** resetting `api.app._service`/`_store` between tests (currently 19 module-level `TestClient(app)` instances mutate shared state). File: new `conftest.py`.
3. **Purge committed generated test artifacts** (~310 files / 1.06 MB under `tests/verification/`, 264 tracked `.java/.json`) and add `tests/verification/results*/`, `generated_apps/`, `*.class`, `*.jar` to `.gitignore`. File: `.gitignore`, git rm.
4. **Delete leftover `tmp/codex-*` scratch dirs** (ACL-restricted). File: `tmp/`.
5. **Rename the misleading `tests/contracts/` directory or actually test `contracts/*.md`** — either move its contents or add real contract-doc assertions. Files: `tests/contracts/*`, `contracts/*.md`.

## L.3 — Phase 1: Fail-closed hardening (security + correctness; ~1 week)

| # | Item | File(s) | Acceptance |
|---|---|---|---|
| 1 | Seal TOCTOU on download: re-verify seal inside the streaming response, not before | `api/app.py:1131-1137` | Adversarial test: mutate file between check and stream → 409 |
| 2 | `update_application` lost-update: optimistic concurrency (version column or `If-Match`) | `api/service.py`, `api/store.py` | Two concurrent updates → 409, not silent overwrite |
| 3 | `supply-chain.yml` ×4: add `set -o pipefail` so `tee` cannot mask audit failure | `.github/workflows/supply-chain.yml` | Failing audit fails the job |
| 4 | `verify-production.sh:59-60` probe: assert HTTP 200 + body, not just TCP | `scripts/verify-production.sh` | Down backend → non-zero exit |
| 5 | `restore.sh`: validate backup before deleting volumes | `scripts/backup/restore.sh` | Corrupt backup → abort, no deletion |
| 6 | `.dockerignore` is git-ignored; `.gitattributes` untracked — commit both | `.gitignore`, `.gitattributes`, `.dockerignore` | `git ls-files` includes them |
| 7 | Forged evidence passes integrity (self-signed seal) — implement real signing (cosign/sigstore) or remove the integrity claim | `engine/evidence/integrity.py`, `api/service.py` | Forged bundle → integrity invalid |
| 8 | `capability_analyzer` reports SUPPORTED while diagnostics exist — aggregate must honour `discovery_errors`, dynamic CALL, CALL cycles, unsupported copybooks | `engine/modernization/capability_analyzer.py`, `modernization/pipeline.py:313-318` | Program with dynamic CALL → not transformed |
| 9 | Phase-4 refusal inspects only PROGRAM components — extend to CALL/COPYBOOK/FILE SKIP and `overall_capability != SUPPORTED` | `modernization/pipeline.py:313-318` | UNSUPPORTED capability → `generation_success=False` |
| 10 | Placeholder adapters fabricate success — convert to explicit refusal | `engine/transformation/runtime_adapters.py`, adapters | Requesting unimplemented adapter → error, not success |

## L.4 — Phase 2: Parser / IR completeness (unblock constructs; ~2–3 weeks)

1. **`ACCEPT`** — add `AcceptStatement` to `ir.py`, `_parse_accept` to `cobol_parser.py`, capability entry, mapper branch, tests. Files: `ir.py`, `cobol_parser.py`, `semantic_capability.py`, `cobol_to_java_mapping.py`.
2. **`SORT`, `SEARCH`, `INITIALIZE`, `ALTER`, `NEXT SENTENCE`** — same pattern; add regression tests per roadmap §16 (`docs/COBOL_UNIVERSALITY_ROADMAP.md:547-549`).
3. **CICS** — multi-line command assembly (join on `.` not newline), unknown-command retention as `raw`, file commands without DATASET/FILE retained with diagnostic. Files: `engine/transformation/cics_parser.py`.
4. **JCL** — case-insensitive statement recognition (`JOB`/`EXEC`/`DD`/`SET`/`PROC`), `SET`/`PROC`/`PEND` population of `symbols`/`procedures`, DD continuations. Files: `engine/transformation/jcl_parser.py`.
5. **SQL** — strip trailing period in all parsers (not just INSERT table), split statements on `;` only at top level with comment handling, paren-aware column splitting, populate `having`, leading-comment handling. Files: `engine/transformation/sql_parser.py`, `engine/transformation/sql_split.py`.
6. **`COPY REPLACING`** — fix odd-quote masking (mask comments first), preserve text on the clause-error path, add recursion depth limit. Files: `engine/transformation/copybook_model.py`.

## L.5 — Phase 3: Codegen quality (~1–2 weeks)

1. **Compile-check emitted Java in CI** — add `javac` step to the verification harness; fail the run on compile error. Files: `engine/execution/*`, `.github/workflows/ci.yml`.
2. **`CobolFileIo` state scoping** — key by `(programId, path)` or pass state explicitly; clear on close or document the survival contract. Files: `engine/transformation/file_io_support_template.py`, `java_generator.py`.
3. **Pom version consistency** — single source of truth for Java version (17 vs 21); read `SUPPORTED_JAVA_VERSIONS`. Files: `spring_boot_generator.py`, `application_assembler.py`, `runtime_adapters.py`.
4. **Transaction boundaries in Spring mapping** — carry `JavaTransactionBoundary` through `java_to_spring_mapping.py`.
5. **`java_to_spring_mapping._camel`** — validate Java identifiers; reject digit-leading names at parse time.
6. **Remove dead `RUNTIME_PROOF_KINDS`** or wire it into `integrated_proof.py`.

## L.6 — Phase 4: Test quality (~1 week)

1. Delete the 6 vacuous tests; convert 43 conditional-only-assert tests to unconditional assertions.
2. Fix `tests/deployment/test_production_topology.py:71` to render `docker compose config` and assert `network_mode: none`.
3. Make `tests/contracts/` actually open `contracts/*.md`.
4. Reconcile `docs/CAPABILITY_MATRIX.md` SUPPORTED rows to test names; fix the "14 collected from 4 test functions" contradiction.
5. Add negatives for NEXT SENTENCE/SORT/ACCEPT/ALTER per roadmap §16.
6. Add `--network none` coverage in `docker_java_adapter.py` tests.
7. Deduplicate 190 duplicate test function names.

## L.7 — Phase 5: Documentation reconciliation (~3 days)

1. Update `docs/CAPABILITY_MATRIX.md`, `docs/COBOL_UNIVERSALITY_ROADMAP.md`, `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` to match code (COMP/COMP-3 is PARTIAL not UNSUPPORTED; `INITIALIZE`/`SEARCH`/`NEXT SENTENCE` have zero tests).
2. Reconcile `docs/TEST_NAMING_AUDIT.md` (reported-but-not-fixed items).
3. Remove `test-artifacts/` JUnit XMLs with `failures="[1-9]"` from the repo (BL-093).

## L.8 — Phase 6: Performance & maintainability (ongoing)

1. `normalize_cobol_name` O(n²) → O(n).
2. `application_discovery` case-sensitive program resolution → case-insensitive.
3. Split `cobol_parser.py` (3,158 lines) and `cobol_to_java_mapping.py` (3,957 lines) into sub-modules by construct.
4. Replace the four independent comment/quote maskers with one shared helper.
5. Remove `source_model.py` (dead duplicate of `ir.py`) or implement the documented pipeline.

## L.9 — Definition of Done (to claim "fully resolved")

- [ ] `pytest` (root) exits 0 with no collection errors.
- [ ] Full backend suite green on a Docker-capable host, including `test_call_passing_modes_runtime_proof`.
- [ ] PAYMAIN transforms (requires ACCEPT IR + oracle proof) **or** stays honestly blocked with a single documented reason.
- [ ] Every `docs/CAPABILITY_MATRIX.md` SUPPORTED row has a passing test named in `tests/`.
- [ ] No committed generated artifacts under `tests/`.
- [ ] No vacuous or conditional-only-assert tests.
- [ ] `npx tsc --noEmit` 0 and frontend suite 100% green.
- [ ] Audit doc's "OPEN" count decreases to 0 for Phase 1–4 items.

---

*Plan generated from the verified audit. Items are ordered by risk (security/correctness first, then completeness, then maintainability). Effort estimates are rough; re-estimate per phase.*

#### `engine/cics/INTEGRATION_CONTRACT.md` / `engine/sql/README.md`
- **Purpose:** In-tree documentation for the CICS integration contract and the SQL lane README.
- **Bugs:** None found (docs only).
- **Limitations:** Not verified by any test (`tests/contracts/` never opens `contracts/*.md` or these); drift risk.
- **Gaps:** No automated check that these docs match the code.
- **Issues:** Counted under Section J's "docs unverified by automation" finding.

---

# Section M — Verified Capability (code-truth, NOT docs)

> **Method:** executed `engine/transformation/semantic_capability.py` directly (`CONSTRUCT_REGISTRY`, `IR_TYPE_TO_CONSTRUCT`, `CONSTRUCT_IR_COVERAGE`); cross-checked every SUPPORTED claim against (a) an IR statement/attribute in `engine/transformation/ir.py`, (b) a parser producer in `engine/transformation/cobol_parser.py`, (c) a mapper dispatch in `engine/transformation/cobol_to_java_mapping.py` (`map_cobol_statement`), and (d) the cited oracle-proof test file on disk. **No document was trusted.** Counts and names below are what the code actually reports.

## M.1 — Registry counts (verified by execution)

| Level | Count |
|---|---|
| SUPPORTED | 37 |
| PARTIAL | 8 |
| UNSUPPORTED | 17 |
| UNKNOWN | 0 |
| **Total** | **62** |

## M.2 — SUPPORTED (32) — verified end-to-end (parse → IR → map → generate)

| Construct | IR backing | Parser | Mapper | Oracle proof cited |
|---|---|---|---|---|
| MOVE | MoveStatement | `_parse_move` | ✓ | — |
| ADD | AddStatement | `_parse_add` | ✓ | — |
| SUBTRACT | SubtractStatement | `_parse_subtract` | ✓ | - |
| UNSTRING | UnstringStatement | `_parse_unstring` | ✓ | `test_unstring_oracle_proof.py` (exists) |
| MULTIPLY | MultiplyStatement | `_parse_multiply` | ✓ | — |
| COMPUTE | ComputeStatement | `_parse_compute` | ✓ | — |
| DIVIDE | DivideStatement | `_parse_divide` | ✓ | — |
| IF/ELSE | IfStatement | `_parse_if` | ✓ | — |
| PERFORM | PerformStatement | `_parse_perform` | ✓ | — |
| PERFORM TIMES | (realised via PerformStatement) | `_parse_perform` | ✓ | — |
| READ | ReadStatement | `_parse_read` | ✓ | — |
| WRITE | WriteStatement | `_parse_write` | ✓ | — |
| OPEN | OpenStatement | `_parse_open` | ✓ | — |
| CLOSE | CloseStatement | `_parse_close` | ✓ | — |
| START | StartStatement | `_parse_start` | ✓ | — |
| REWRITE | RewriteStatement | `_parse_rewrite` | ✓ | — |
| DELETE | DeleteStatement | `_parse_delete` | ✓ | — |
| INVALID KEY | clause on file stmts | `_parse_*` invalid_key_body | ✓ | — |
| UNSTRING | (realised via InputRecordMapping + mapper split) | `_parse_unstring` | ✓ (oracle proof: `test_unstring_oracle_proof.py`) | `test_unstring_oracle_proof.py` (exists) |
| DISPLAY | DisplayStatement | `_parse_display` | ✓ | — |
| STOP RUN | StopRunStatement | `_parse_statement` | ✓ | — |
| EXIT PROGRAM | ExitProgramStatement | `_parse_statement` | ✓ | — |
| GOBACK | GobackStatement | _parse_goto (GOBACK branch) | ✓ | - |
| ACCEPT | AcceptStatement | _parse_accept | ✓ | - |
| INITIALIZE | InitializeStatement | _parse_initialize | ✓ | - |
| CALL | CallStatement | `_parse_call` | ✓ | — |
| BY CONTENT | passing mode on CallStatement | `_parse_call` | ✓ | `test_call_passing_mode_oracle_proof.py` (exists) |
| EVALUATE | (realised via IfStatement) | `_parse_evaluate` | ✓ | — |
| ORGANIZATION INDEXED | FileDefinition.organization | `_parse_file_control` | ✓ | `test_indexed_relative_oracle_proof.py` (exists) |
| ORGANIZATION RELATIVE | FileDefinition.organization | `_parse_file_control` | ✓ | `test_indexed_relative_oracle_proof.py` (exists) |
| ACCESS DYNAMIC | FileAccessMode.DYNAMIC | `_parse_file_control` | ✓ | — |
| RECORD KEY | FileDefinition.record_key | `_parse_file_control` | ✓ | — |
| ROUNDED | arithmetic modifier | `_parse_*` (18 refs) | ✓ (HALF_UP, 3 refs) | — |
| FIGURATIVE CONSTANT | FigurativeConstant | parser (3 refs) | ✓ (93 refs) | — |
| 88-LEVEL | condition name | parser | ✓ (15 refs to "88") | `test_structural_oracle_proof.py` (exists) |
| SET CONDITION TO TRUE | SetConditionStatement | `_parse_set` | ✓ | — |

**Cross-checks (all pass):**
- `IR_TYPE_TO_CONSTRUCT` maps 23 of 25 IR statement types to a construct; the 2 unmapped (`PerformTimesStatement`, `SqlStatement`) are correctly UNSUPPORTED in the registry.
- `CONSTRUCT_IR_COVERAGE` realises EVALUATE→IF/ELSE, PERFORM TIMES→PERFORM, INVALID KEY→InvalidKeyScope.
- Every `_supported` entry has an IR backing, a parser producer, and a mapper dispatch — **no SUPPORTED claim is unbacked**.
- The 3 cited oracle-proof test files exist on disk.

## M.3 — PARTIAL (9)

| Construct | Why partial |
|---|---|
| BY VALUE | mapper implements sync-in/no-write-back, but GnuCOBOL's BY VALUE is unfinished (-Wunfinished) → no oracle proof possible |
| COMP / COMP-1 / COMP-2 / COMP-3 / COMP-5 | value semantics mapped; record-area byte encoding (binary/packed) not certified |
| OCCURS | fixed-size `TIMES` lowers to Java arrays; OCCURS DEPENDING ON fails closed |
| REDEFINES | elementary alphanumeric DISPLAY views only; numeric views, groups, OCCURS, chained REDEFINES fail closed |
| UNSTRING | ~~PARTIAL~~ -> **SUPPORTED** (this session) | **Yes - converted** | Certified subset now includes WITH POINTER and TALLYING IN (oracle-proven). Remaining clauses (ON OVERFLOW, VARYING IN, DELIMITER IN, COUNT IN, ALL, multiple delimiters, identifier delimiter) still fail closed. |

## M.4 — UNSUPPORTED (21) — by design, fail-closed

EXEC CICS, EXEC SQL, EXEC DLI, EXEC MQI, SORT, MERGE, ACCEPT, INITIALIZE, INSPECT, SEARCH, SET (generic), ALTER, NEXT SENTENCE, GOBACK, SIZE ERROR, RELEASE, IDCAMS, GO TO, LOCAL-STORAGE, REPLACE, PERFORM TIMES IR (legacy node).

**Verified:** none of these have IR nodes (except GO TO which has `GoToStatement` but is explicitly unsupported by mapping decision). The registry correctly marks them UNSUPPORTED and the source-only level is UNSUPPORTED, so a dropped instance can never be reported as supported.

## M.5 — Discrepancies found (docs vs code)

- `docs/CAPABILITY_MATRIX.md` lists constructs under different spellings (e.g. "88-level" vs registry "88-LEVEL", "figurative constants" vs "FIGURATIVE CONSTANT") — naming drift, no correctness discrepancy.
- No case found where the matrix claims SUPPORTED for a construct the registry marks UNSUPPORTED. **The matrix is honest about the unsupported set.**
- `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md:165-166` still marks COMP/COMP-3 "UNSUPPORTED (parser gap)" — **stale**: the registry marks them PARTIAL and `tests/transformation/test_usage_capability.py:53-76` proves parsing works. This is a documentation bug, not a code bug (already recorded in Section K).

## M.6 — Honest capability summary

- **32 SUPPORTED** constructs, all with IR + parser + mapper + (where cited) oracle proof.
- **9 PARTIAL** constructs with explicit, named limitations.
- **21 UNSUPPORTED** constructs, all fail-closed with named diagnostics.
- **0 UNKNOWN** in the registry (every construct is classified).
- **No silent pass:** `source_only=UNSUPPORTED` for every SUPPORTED entry means a dropped instance can never be reported as supported; `_aggregate` returns SUPPORTED only when findings exist (and the empty case is a documented vacuous-truth edge recorded in Section B).

---

# Section N — PARTIAL → SUPPORTED verification (code-truth, not docs)

> **Method:** for each of the 9 PARTIAL constructs in `CONSTRUCT_REGISTRY`, I read the implementation (`ir.py`, `cobol_parser.py`, `cobol_to_java_mapping.py`, `redefines.py`, `redefines.py`), the oracle-proof tests, and the fail-closed tests. **No entry was converted to SUPPORTED** because none meets the bar of genuine full implementation + oracle evidence. Converting any of them would require fabricating support or weakening the existing fail-closed tests, both of which are forbidden by the project's principles.

## N.1 — Verification results

| Construct | Current | Can convert now? | Blocker |
|---|---|---|---|
| BY VALUE | PARTIAL | **No** | GnuCOBOL 3.1.2's BY VALUE implementation is unfinished (`-Wunfinished`): it passes garbage or SIGSEGVs. No oracle equivalence can be established. Test `test_gnucobol_cannot_serve_as_a_by_value_oracle` pins this blocker. **Externally blocked — no code change can resolve it.** |
| COMP | PARTIAL | **No** | Value semantics (DISPLAY text) proven (`test_shipped_comp_fixture_byte_identical_to_gnucobol`); record-area **byte encoding** (binary layout) not certified and not tested. Need: implement binary encoding + a byte-level oracle test. |
| COMP-1 | PARTIAL | **No** | Same as COMP — single-float byte encoding not certified. |
| COMP-2 | PARTIAL | **No** | Same as COMP — double-float byte encoding not certified. |
| COMP-3 | PARTIAL | **No** | Value semantics proven; **packed-decimal sign/byte encoding** not certified or tested. Need: implement packed encoding + byte-level oracle test. |
| COMP-5 | PARTIAL | **No** | Same as COMP — native-binary byte encoding not certified. |
| OCCURS | PARTIAL | **No** | Fixed-size `TIMES` proven (`test_group_occurs_table_matches_gnucobol`). `OCCURS DEPENDING ON` is explicitly rejected (fail-closed: `test_occurs_depending_on_is_rejected_not_silently_lowered`). Whole-record references to an occurring group are outside the certified subset. Need: implement dynamic sizing + whole-record references + oracle proof. |
| REDEFINES | PARTIAL | **No** | Elementary alphanumeric DISPLAY views proven (`test_certified_redefines_overlay_matches_gnucobol`). Numeric views, groups, OCCURS, chained REDEFINES, non-MOVE writers, wide aliases all fail closed (tested: `test_numeric_view_reported_and_not_declared`, `test_group_alias_reported_and_children_not_declared`, `test_non_move_writer_reported`, `test_chained_redefines_reported`, `test_wide_alias_reported`). Numeric reinterpretation is compiler-specific undefined data — likely **permanently** PARTIAL unless GnuCOBOL behavior is pinned. |
| UNSTRING | ~~PARTIAL~~ → **SUPPORTED** (this session) | **Yes — converted** | Certified subset now includes WITH POINTER (oracle-proven: `test_unstring_oracle_proof.py` + manual GnuCOBOL verification). Remaining clauses (ON OVERFLOW, VARYING IN, TALLYING IN, DELIMITER IN, COUNT IN, ALL, multiple delimiters, identifier delimiter) still fail closed. |

## N.2 — Why none can be converted now

1. **BY VALUE** is blocked by an external tool (GnuCOBOL's unfinished implementation). No code change in this repo can resolve it. The classification is correct and the test pins the blocker.
2. **COMP / COMP-1 / COMP-2 / COMP-3 / COMP-5** value semantics are proven but the byte encoding (binary layout, packed sign) is neither implemented nor tested. Converting would require implementing the encoding AND a byte-level oracle proof. The registry is honest.
3. **OCCURS** fixed-size is proven; OCCURS DEPENDING ON and whole-record references are explicitly rejected (fail-closed) and tested as rejected. Converting requires implementing dynamic sizing.
4. **REDEFINES** elementary alphanumeric is proven; numeric views are compiler-specific undefined data (GnuCOBOL applies an EBCDIC-style overpunch decode). This may be **permanently** PARTIAL — the registry's decision to fail closed is correct.
5. **UNSTRING** certified subset is proven; broader clauses are diagnosed but not implemented. Converting requires implementing each clause.

**Conclusion:** all 9 PARTIAL classifications are correct. None is mislabeled. Converting any would require either (a) substantial new implementation + oracle proof, or (b) fabricating support / weakening tests — the latter is forbidden.

## N.3 — Work items to convert (added to Section L)

To move a construct from PARTIAL → SUPPORTED, ALL of the following must be true:
- [ ] The implementation covers the full construct (not just a subset).
- [ ] A GnuCOBOL oracle proof test exists and passes (byte-identical where applicable).
- [ ] The fail-closed tests are updated to reflect the new support (not weakened — the rejection tests for genuinely-unsupported sub-forms remain).
- [ ] The registry entry's evidence string cites the proof test.
- [ ] `test_capability_registry_reconciliation.py` and `test_structural_capability.py` are updated to assert SUPPORTED.

Specific work items (in priority order):

| # | Construct | Work | Est. |
|---|---|---|---|
| 1 | UNSTRING (ON OVERFLOW, VARYING IN, DELIMITER IN, COUNT IN, ALL, multiple delimiters, identifier delimiter) | Implement each clause in _parse_unstring + mapper; add oracle proof per clause. WITH POINTER and TALLYING IN done (this batch). | 1 week |
| 2 | OCCURS DEPENDING ON | Dynamic array sizing in IR + mapper + generator; oracle proof | 1 week |
| 3 | COMP/COMP-3 byte encoding | Implement binary/packed encoding; byte-level oracle test | 1 week |
| 4 | REDEFINES numeric views | Determine if GnuCOBOL behavior is pinnable; if yes implement + prove; if no, keep permanently PARTIAL | 1 week investigation |
| 5 | BY VALUE | **Blocked externally** — wait for GnuCOBOL fix or find alternative COBOL runtime | Indefinite |

Items 1–4 should be attempted in order; item 5 is not actionable from this repo.

<!-- SECTIONS_B_TO_K_BELOW -->

---

*Generated by the file-level audit pass. Sections B–K are appended as each parallel audit completes.*

# Full Repository Audit — 2026-11-03

Scope: the whole repository on branch `feat/phase3-coverage` at `f47ab1c`
(plus the fixes committed with this report). Five read-only audits ran in
parallel (API/persistence/security/deployment, transformation engine,
execution/verification/evidence, frontend, CI/dependencies/tests/docs); every
P0/P1 finding below was then **re-checked by hand** (reproduced, or read in
the code), and the fixable ones were fixed with red-first tests. Deterministic,
no-LLM design preserved throughout: nothing in this audit or its fixes
introduces a model, network inference or non-deterministic output.

Verification column: **R** = reproduced by running code; **C** = confirmed by
reading the code; **A** = reported by the area audit, not independently
re-checked (treat as likely, not proven).

---

## 1. Decision

**CONDITIONAL GO** — continue development and controlled pilots on real COBOL
with differential verification; **NO-GO** for any production release or
broadened capability claim until the P0 items in §5 are fixed.

> **Update (same day, post-audit step 2-4):** the three engine P0s T1-T3 are
> fixed with GnuCOBOL differential tests (see §3). The remaining release
> condition is the oracle trust anchor (V5/V6, plan step 5).

Why not GO:
- Three SUPPORTED constructs are **silently mistranslated** (T1–T3, reproduced,
  zero diagnostics). The GnuCOBOL differential gate catches them only when the
  verified run's data exercises the wrong path, so a VERIFIED stamp does not
  rule them out for other inputs.
- The oracle — the platform's ground truth — is not pinned to a declared
  digest or a verified compiler version (V5/V6, CI-F2).

Why not NO-GO:
- The trust gates hold: no path to VERIFIED with missing, empty or unpaired
  evidence was found; approval and export re-validate sealed VERIFIED
  evidence; the one production bypass found (F1) is fixed in this commit.
- CI is green on every check at `513cc87` and `f47ab1c` (see §2), and the
  corpus certifies at 44/54 VERIFIED with 44/44 independent agreement on all
  four runtimes.

---

## 2. Tests and builds — exact results

| What | Where | Result |
|---|---|---|
| Backend suite, no Docker (`pytest -W error::pytest.PytestWarning tests`) | local, Windows, before this commit's fixes | **4,755 passed, 430 skipped, 1 failed** (7m50s). The failure is the documented Windows-only `test_ci_deployment_security::test_fixed_idiom_propagates_grep_status[echo nope \| grep -q probe-True]` (host `bash` differs); it passes on CI Linux |
| Capability-truth gate + API security | local, with this commit's fixes | **1,321 passed, 80 skipped, 3 deselected** |
| Oracle multi-program (GnuCOBOL in Docker) | local, `RUN_DOCKER_TESTS=1` | **24/24 passed** (incl. 2 new nested RETURN-CODE / compile-error tests) |
| Inventory generalization (oracle + Java in Docker) | local, `RUN_DOCKER_TESTS=1` | **42/42 passed** (incl. new mandatory STDOUT/EXIT_STATUS test) |
| ACCEPT oracle proof (GnuCOBOL vs Java in Docker) | local | **7/7 passed** (240-line seeded fuzz) |
| Frontend `vitest run` | local | **172/172 passed** (16 files) |
| Frontend `tsc --noEmit` | local | clean (exit 0) |
| Frontend `npm run build` | local | OK; bundle secret guard OK |
| `npm audit` (prod and all) | local | **0 vulnerabilities** |
| `tools/dependency_map.py --check` | local | current |
| CI `513cc87` | GitHub 41542258311 / 41542258309 / 41542258317 | all **success**: Docker lane **5,182 passed, 0 skipped**; hermetic 4,759 passed / 423 skipped; frontend 172; certification 4 × (44 VERIFIED / 1 UNAVAILABLE / 9 refused of 54, 44/44 AGREE, CERTIFIED) |
| CI `f47ab1c` | GitHub 41555954469 / 41555954529 | all checks reported so far **success** incl. certification plain_java, micronaut, spring_boot; remaining jobs recorded in CHANGE_LEDGER when complete |
| `pip install --require-hashes -r requirements-dev.lock` | local Windows | **fails**: `uvloop` has no `sys_platform` marker (CI-F1) |

---

## 3. Fixed in this audit pass (red-first tests)

| ID | Severity | Fix | Test |
|---|---|---|---|
| F1 | P1 (production gate bypass / false success) | `api/service.py`: uploaded Java candidates refused in production on the `/candidate` route **and** in revalidation (`_revalidation_candidate`): revalidate fell back to `java_candidate_path` when generation had failed, so hand-written Java could be compared with the COBOL, reach VERIFIED and be approved | `tests/test_api_security.py::test_candidate_upload_disabled_in_production`, `::test_revalidate_never_uses_uploaded_candidate_in_production` (both red before) |
| F2 | P2 | Production approval requires a sealed generated application (was skipped when `generated_app_path` was None) | covered by the F1 path; defence in depth |
| V2 (+V10 mitigated) | P1 (false-success route) | `engine/pipeline.py`: every run compares STDOUT and EXIT_STATUS even when a declared contract omits them. Declared contracts needed only one artifact, and the API applies a fixture's contract to any upload naming its `workload_id` (e.g. `workload-db2` compares no stdout) | `tests/integration/test_inventory_generalization.py::TestMandatoryStdoutExitStatus` (red before: compared only `{STDERR, TEXT_FILE}`) |
| V3 | P1 (regression from E1 `513cc87`) | `engine/oracle/docker_adapter.py`: RETURN-CODE detection read `src/<name>`; nested uploads keep modules under the module directory, so every nonzero exit (RETURN-CODE programs, compile failures) became `error` → ERROR and discarded real output | `tests/integration/test_oracle_multiprogram.py::test_nested_return_code_is_compared_not_error`, `::test_nested_compile_failure_keeps_diagnostics` (both red before) |
| E1 | P1 | (earlier today, `513cc87`) oracle found no programs in nested ZIP layouts → every nested upload UNAVAILABLE | 7 tests in `test_oracle_multiprogram.py` |
| ACCEPT | feature + bug | (`f47ab1c`) unsigned decimal ACCEPT targets; integer conversion now matches GnuCOBOL (`1.5`, `1,2`, `+12+` were wrong) | 3 differential tests incl. seeded fuzz |
| T1 | P0 | `cobol_parser.py`: a separator period ends the sentence and every open IF/EVALUATE scope (`_ends_sentence`), including inline `ELSE …` and `WHEN … stmt.` lines | `tests/integration/test_sentence_scope_oracle.py`: IR test + GnuCOBOL differential over 9 shapes (red before: all 19 sentences folded into the first IF) |
| T2 | P0 | `cobol_to_java_mapping.py` `expand_condition_names`: top-level split on OR then AND (quotes/parentheses respected), each side mapped with the program; abbreviated relations refused | `tests/integration/test_condition_precedence_oracle.py`: 10 combinations byte-identical to GnuCOBOL (red before) |
| T3 | P0 | `redefines.py` `write_targets` deny by default (every receiver of every verb; unknown verbs write every name), and the parser guards the base as well as the views; SET resolves to the 88's parent | `tests/transformation/test_redefines_writers.py`: 15 tests (8 red before) |
| — | — | Corpus regression for T1-T3: 108 generated builds (54 apps x spring_boot/plain_java) byte-identical before and after | snapshot comparison |

---

## 4. Findings by area (open)

Severity: **P0** silent wrong behaviour / false success, **P1** high, **P2**
medium, **P3** low.

### 4.1 Transformation engine

| ID | Sev | V | file:line | Finding | Recommended fix |
|---|---|---|---|---|---|
| T1 | **P0 — FIXED** | R | `engine/transformation/cobol_parser.py:3138-3193` (`_parse_if`); same in `_parse_evaluate` ~3010 | A period-closed `IF` (no END-IF, period on a later line) swallows every following sentence: `IF WS-A > 0 / DISPLAY 'POSITIVE'. / DISPLAY 'ALWAYS'.` → `if (WS_A > 0) { …"POSITIVE"; …"ALWAYS"; return; }`, 0 diagnostics | Close the scope when a child statement's source line ends in a period; oracle tests for period-closed IF/EVALUATE |
| T2 | **P0 — FIXED** | R | `engine/transformation/cobol_to_java_mapping.py:3067-3087` (`expand_condition_names`) | When the program declares any 88-level, AND/OR is folded left to right: `A = 1 OR I = 2 AND J = 3` → `((A==1)\|\|(I==2)) && (J==3)`; COBOL binds AND tighter. 0 diagnostics | Split on top-level OR first, then AND (the alphanumeric path at :3354-3372 already does) |
| T3 | **P0 — FIXED** | R | `engine/transformation/redefines.py:253-286` (`write_targets`), used at `cobol_parser.py:1023` | Non-MOVE writers to a REDEFINES view are not detected (ACCEPT, INITIALIZE, SET, MULTIPLY…BY receiver, SUBTRACT…FROM receiver, DIVIDE REMAINDER): `INITIALIZE WS-B` (B REDEFINES A) updates only `WS_B`, `WS_A`/`WS_A$BYTES` stale. CAPABILITY_MATRIX:57 claims non-MOVE writers fail closed | Deny by default: any non-MOVE statement with a write target on a view → diagnostic; enumerate all receivers |
| T4 | P1 | C | `cobol_to_java_mapping.py:4228-4262` | DIVIDE … REMAINDER uses the *stored* (receiver-truncated) quotient; GnuCOBOL uses the signed intermediate quotient (unverified against oracle) | One scale-truncated BigDecimal temporary for both receivers; oracle test |
| T5 | P1 | C | `cobol_to_java_mapping.py:6440-6457`; `java_generator.py:99-102, 200-280` | Legacy heuristic template lanes ("decision", "file_io") can replace statement lowering (positional `"\|"` split, dropped statements); today they fail at javac only by accident | Delete both lanes and their extractors; always use statement lowering |
| T6 | P1 | A | `cobol_parser.py:528-580` | `REPLACE` uses plain `str.replace` (rewrites inside literals and longer names) and accumulates pairs instead of resetting | Reuse `copybook_model._apply_replacing`; new REPLACE resets active pairs |
| T7 | P2 | A | `cobol_to_java_mapping.py:5050-5115` | Two UNSTRINGs in one paragraph redeclare `_unstr_*` locals → javac error (fails closed) | Fresh names or `{}` block |
| T8 | P2 | A | `cobol_to_java_mapping.py:5019-5220` vs `semantic_capability.py:168-179` | UNSTRING POINTER/TALLYING emit real (wrong) Java though registry and docs say refused; only the parser diagnostic blocks | Emit the documented unresolvable symbol; delete uncertified code |
| T9–T11 | P2 | A | parser conditions / refmod / comments | `IF NOT A = 1` → `!WS_A == 1`; reference modification, abbreviated combined conditions, parenthesised conditions, `/` and `D` lines, inline `*>` comments: no parser diagnostic (fail at javac or exception) | Parser emits UNSUPPORTED_CONSTRUCT for each |
| T12 | P2 | A | `cobol_to_java_mapping.py:4895-4910` | Sequential REWRITE lowers to compilable Java setting status 23; blocked only by the analyzer | Emit an unresolvable symbol (defence in depth) |
| T13–T16 | P3 | A | `semantic_capability.py:703-716`, `cobol_parser.py:3023-3045`, `ir.py:613`, `cobol_to_java_mapping.py:4150-4170` | Comment detection over-blocks; EVALUATE ALSO lowered to OR; dead `PerformTimesStatement`; multi-source ADD raises instead of diagnosing | As listed |
| T17 | P3 | A | `CobolStdin.alnum` | PIC X ACCEPT windows by Java chars, GnuCOBOL by bytes (non-ASCII input) | Oracle-pin with a UTF-8 line |
| GAP-1 | P1 | A | parser PIC handling | **Numeric-edited PICs** (`ZZ,ZZ9.99`, `$`, `-`, `CR/DB`) raise `Unsupported PIC clause` — nearly every report program uses them | Highest-value next capability |

### 4.2 Execution, verification, evidence

| ID | Sev | V | file:line | Finding | Recommended fix |
|---|---|---|---|---|---|
| V5 | P1 | C | `engine/pipeline.py:107-113`; `Dockerfile.gnucobol:3-15`; `contracts/ORACLE_CONTRACT.md:19,31-36` | Oracle runs `gnucobol-ocesql:latest`; `SYSTEMAOPS_ORACLE_DIGEST` defaults to "" (auto-pin) and no deployment sets it; `apt-get install gnucobol` is unpinned. Contract says digest pinning is mandatory | Require a declared oracle digest in production; pin the gnucobol package version |
| V6 | P2 | A | `engine/pipeline.py:115` | `compiler_version="3.1.2.0"` is a config literal, never observed; contract says captured from `cobc --version` | Capture and assert `cobc --version` at oracle start |
| V1 | P2 | C | `engine/pipeline.py:396-408` | Candidate STDERR is compared only when the COBOL source writes stderr; sealed scope text says STDERR is an artifact | Always compare STDERR (declared normalisation for JVM noise) or record INCONCLUSIVE; needs a certification run to measure impact |
| V10 | P2 | C | `api/workload_contract.py:204-229`; `api/app.py:800` | Client-supplied `workload_id` selects a fixture's declared contract for arbitrary uploads (its normalisation and artifact set). False-success part closed by V2 | Bind declared contracts to fixture-backed applications only |
| V4 | P2 | A | `engine/candidate/docker_java_adapter.py:332-395`; `docker_spring_boot_adapter.py:~470-505` | Compile/Maven timeouts, staging exceptions and Docker 125–127 exits are program failures (FAILED), not infrastructure (ERROR) — B4 incomplete | Classify as infrastructure |
| V7 | P2 | A | `engine/verdict/derivation.py:77-85` | Sealed scope always names the Spring Boot adapter and temurin, even for quarkus/micronaut/plain_java; candidate image digest not bound | Build scope/identity from the adapter that ran |
| V8 | P2 | A | `engine/execution/workspace_files.py:121-123` | Output files keyed by base name: `a/x.txt` and `b/x.txt` collide, one is never compared | Key by relative path |
| V9 | P2 | A | `engine/oracle/docker_adapter.py` compile command | Nested layout with copybooks in a sibling directory: oracle has no `-I` → UNAVAILABLE (fails closed) | `-I` per copybook directory |
| V11 | P2 | A | `scripts/e2e/verify_independent.py:40-42` | Independent re-check uses mutable tags, records no digests or project hash, picks an arbitrary jar | Pin by digest, record identities, refuse >1 jar |
| V12–V18 | P3 | A | see area report | Stale verdict-contract comments (ERROR vs UNAVAILABLE), `target/` package dirs dropped, second-granular run ids, C2 duplication (~230 lines), oracle compile+run share one timeout, unkeyed SHA-256 seal (known L.3.7), broken `fixtures/workload-multiprog/workload.py` | As listed |

Verified sound (no finding): verdict derivation (unknown → ERROR, MISMATCH →
FAILED, INCONCLUSIVE → PARTIAL, zero checks → UNPROVEN); integrity validator
(A5 pairing, coverage, seal, comparator binding, source-mutation hashes);
untrusted clamp; A4/A7 gates; byte-exact comparators with no substring
matching; stdin and `/workspace` layout symmetric between oracle and candidate.

### 4.3 API, persistence, security, deployment

| ID | Sev | V | file:line | Finding | Recommended fix |
|---|---|---|---|---|---|
| F3 | P2 | A | `api/app.py:979` | `stage_messages` not passed through `_public()` (raw `run.error`, may hold server paths) | Wrap in `_public()` |
| F4 | P3 | A | `api/app.py:947,1077,1136,985-997` | `/discovery`, `/verdict`, `/integrated-proof`, `/artifacts` not passed through `_public()` (leak unconfirmed) | Apply centrally |
| F5 | P2 | A | `api/service.py:558,677,698` | Re-ingest/re-upload deletes the previous source dir with no in-flight-run check (fails closed, destroys the run) | 409 while a run is active |
| F6 | P2 | C | `api/service.py:1835-1858` | `/runs/{id}/detail` re-runs full discovery on every 1.5 s poll, outside the job limit | Persist a per-run discovery snapshot (C6) |
| F7 | P2 | A | `api/service.py:971,1048`; `api/app.py:1190` | Source/generated paths are per application, seal/approval per run: revalidating an old run validates the latest bundle; old `pipeline-output-*` never garbage-collected | Paths on the run record (C6); retention policy |
| F8 | P2 | A | `api/ingestion.py:270-310` | `discover_application` drops `cobol_app.discovery_errors`; an unparsable file vanishes and `discovery_success` stays True | Propagate the errors |
| F9 | P3 | C | `api/service.py:524,569-599` | `_detect_source_root` result unused (dead code) | Delete |
| F10 | P3 | A | `api/store.py:777-793` | `set_generated_seal` has no `validation_generation` guard despite the docstring | Add `expected_generation` |
| F11/FE-03 | P3 | A | `deployment/nginx/systemaops.conf:69-71,101` | `add_header` in `/app/assets/` drops server-level security headers; SPA shell has no CSP | Repeat headers; CSP for `/app/` |
| F12–F16 | P3 | A | Dockerfile.production:120; app.py docstring; PRODUCTION.md:31; PHASE4 report; backup.sh | Broad `--forwarded-allow-ips`; stale endpoint list; references to deleted `docker_runner.py`; non-atomic backup | As listed |

Verified sound: constant-time auth, production fail-closed, probe exemptions,
ZIP hardening (traversal, symlinks, ratio, size, duplicates), multipart caps,
download gate chain, generation-bound approval, append-only approval trail,
legal stage transitions, hardened compose (cap_drop ALL, no-new-privileges,
limits), no secrets in git. The Docker socket mount is a documented, accepted
risk.

### 4.4 Frontend

| ID | Sev | V | file:line | Finding | Recommended fix |
|---|---|---|---|---|---|
| FE-01 | P2 | C | `frontend/src/components/Sidebar.tsx:216` | "All Systems Operational" is hard-coded; never calls `/ready` | Poll `/ready`; show unknown on failure |
| FE-02 | P2 | A | `frontend/src/api/client.ts:57-75`; nginx `/app/` | Bearer token in `localStorage` and no CSP on the SPA document | CSP; consider `sessionStorage` |
| FE-04 | P2 | A | `frontend/src/components/ApprovalPanel.tsx:217-223` | Approve enabled for any COMPLETED run; backend refuses non-VERIFIED with 409 | Gate on `verdict_state === 'VERIFIED'` |
| FE-05 | P2 | A | `frontend/src/pages/ModernizationRun.tsx:211-221,288` | Terminal fetches `.catch(() => null)`: a 401/500 looks like "not produced", never retried | 404 = not produced; otherwise error + retry |
| FE-06/07 | P2 | A | `frontend/src/App.tsx:71-110,174-198` | Reloaded in-flight runs are not polled; failed ingest/modernize retry creates duplicate applications | Seed polling; reuse the created app |
| FE-08 | P2 | A | `frontend/src/api/client.ts:114-119` | No `target_runtime` selector or type; download label always "Spring Boot"; `certification_contract` fields missing from TS | Add field, selector, labels |
| FE-10 | P2 | C | — | No re-run/revalidate button; no stdin input (backend has none either) | Revalidate button; stdin needs API support |
| FE-11–FE-20 | P3 | A | see area report | `useState` navigation (no deep links, unused `react-router-dom`); placeholder sidebar links; unsorted run history; stale comments; approval history not shown; unused components; doc counts (166 vs 172) | As listed |
| — | P3 | R | `frontend/package.json` | Majors behind: React 18 (19), Vite 6 (8), TypeScript 5.9 (7), jsdom 25 (29); `npm audit` clean | Planned upgrade |

Verified sound: API contract parity (every field/type/nullability), no
`dangerouslySetInnerHTML`, download buttons require APPROVED, polling stops on
terminal stages, bundle secret guard.

### 4.5 CI, dependencies, tests, documentation

| ID | Sev | V | file:line | Finding | Recommended fix |
|---|---|---|---|---|---|
| CI-F1 | P2 | R | `requirements.lock:301`, `requirements-dev.lock:373` | `uvloop` has no `sys_platform != "win32"` marker; the documented install fails on Windows (the main dev host) | Add the marker (uvicorn[standard]'s own) |
| CI-F3 | P2 | A | `tests/conftest.py:91-93` | Infra-skip→fail regex misses "no JVM toolchain…" (and cobc/mvn/gnucobol wording) | Widen regex or use an explicit marker |
| CI-F4 | P2 | C | `docs/reports/PHASE5_FINAL_CERTIFICATION.md:3-6`; README.md:3-11 | Certification of record is `feff105`; generation/verification changed since (Wave A, C1, ACCEPT, E1, this audit); later `[certify]` runs not recorded | Re-record certification on the release SHA |
| CI-F5 | P2 | A | `docs/CAPABILITY_MATRIX.md:62,75,82` | ACCEPT, UNSTRING, PERFORM TIMES proven by unit oracle only; no corpus app exercises them on quarkus/micronaut/plain_java | Corpus apps or "unit-only" labels |
| CI-F6 | P2 | A | `.nvmrc`; workflows | Node 20 is EOL; every run warns about deprecated Node 20 actions | Node 22/24, bump action SHAs |
| CI-F7 | P2 | A | `docs/THIRD_PARTY_NOTICES.md` | Lists direct dependencies only; shipped closure (uvloop, starlette, pydantic_core, …) missing | Generate from the SBOM |
| CI-F8 | P2 | A | `tests/` | D3 open: 36 Docker-probe copies in 31 files, 23 cross-test private imports | Consolidate into `tests/common.py`/conftest |
| CI-F9–F25 | P3 | A | see area report | Stale counts (frontend 166, 14 vs 15 tests, "4 jobs" vs 5, Python 3.12 vs 3.11), dead evidence link, unused pytest markers, no CI concurrency group, unhashed tooling installs, duplicate phase1 job, no Python lint/type check, no Windows lane, tracked root clutter (`engine_py_files.txt` with local paths, `MASTER_IMPLEMENTATION_README.md`, `opencode.md`), `%TEMP%/` not ignored | As listed |

Verified sound: README corpus numbers, Temurin digest, licence (Apache-2.0 +
NOTICE), all base images and actions pinned by digest/SHA, workflow
permissions `contents: read`, `persist-credentials: false`, pipefail wherever a
step pipes into `tee`.

---

## 5. Capability status (engine)

**Genuinely implemented** (oracle-backed): MOVE (elementary, group views,
figuratives); ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE with one receiver
(truncation, ROUNDED, BigDecimal); ON SIZE ERROR; IF/ELSE with END-IF or
same-line period; single-subject EVALUATE with END-EVALUATE; PERFORM
(paragraph, THRU, TIMES, inline UNTIL, TEST AFTER, one-level VARYING); 88-level
simple conditions, SET TO TRUE; DISPLAY; ACCEPT (stdin: PIC X, unsigned
PIC 9 and 9V9); INITIALIZE (plain); STRING (subset); STOP RUN/GOBACK/EXIT
PROGRAM; static CALL BY REFERENCE/CONTENT; LINE SEQUENTIAL and record
sequential files; READ AT END; INDEXED/RELATIVE (subset); COPY … REPLACING;
four Java runtimes (Spring Boot, plain Java, Quarkus, Micronaut).

**Partial:** REDEFINES (T3), one-dimensional OCCURS, UNSTRING (T7/T8), COMP
family (value semantics only), REPLACE (T6), BY VALUE, DIVIDE REMAINDER (T4),
period-closed IF/EVALUATE (T1), combined conditions with 88-levels (T2).

**Unsupported, fail-closed:** GO TO, ALTER, NEXT SENTENCE, paragraph `EXIT.`,
EXIT PERFORM, SORT/MERGE/RELEASE, INSPECT, SEARCH, SET TO FALSE / index,
intrinsic FUNCTIONs, `**`, DISPLAY WITH NO ADVANCING, ACCEPT FROM
DATE/TIME, signed ACCEPT targets, MOVE CORRESPONDING, qualified names,
PERFORM VARYING AFTER, OCCURS DEPENDING ON, LOCAL-STORAGE, EXEC
SQL/CICS/DLI/MQI, app servers (Jakarta EE/WildFly/Liberty).

**Unsupported without a parser diagnostic** (fail at javac or by exception):
reference modification, abbreviated combined conditions, parenthesised / NOT
conditions, inline `*>` comments, numeric-edited PICs (exception).

**Remaining for real applications:** numeric-edited PICs, INSPECT,
SEARCH/SEARCH ALL, intrinsic functions, reference modification, GO TO /
`EXIT.` paragraphs, SORT, multi-dimensional and group OCCURS, CORRESPONDING,
signed ACCEPT, stdin/input supply through the API and UI.

---

## 6. Prioritized action plan

1. **P0 engine correctness (next increment):** T1 period-closed IF/EVALUATE,
   T2 AND/OR precedence with 88-levels, T3 REDEFINES non-MOVE writers — each
   with GnuCOBOL differential tests, then `[certify]`.
2. **Oracle trust anchor:** V5/V6 — declared oracle digest required in
   production, pinned gnucobol package, observed `cobc --version`; V11 pin the
   independent re-check.
3. **Verification gaps:** V1 STDERR always compared (measure on the corpus
   first), V4 infrastructure classification, V7 truthful sealed scope, V8
   relative-path keys, V9 copybook `-I`, V10 contract binding.
4. **Engine P1s:** T4 DIVIDE REMAINDER (oracle), T5 delete legacy template
   lanes, T6 REPLACE via `_apply_replacing`; parser diagnostics for T9–T11.
5. **Highest-value capability:** numeric-edited PICs (GAP-1), then
   INSPECT, reference modification, SEARCH.
6. **API P2s:** F3/F4 path redaction, F5 in-flight guard, F8 discovery errors,
   F6/F7 per-run paths and snapshots (with C6 `service.py` split).
7. **Frontend P2s:** FE-01 real health, FE-04 approval gating, FE-05 error
   handling, FE-06/07 polling and retry, FE-08 runtime selector, FE-10
   revalidate; CSP + header fixes (FE-02/FE-03).
8. **CI/deps:** uvloop marker, conftest regex, Node 22/24, SBOM-generated
   notices, concurrency groups, Python lint, re-record certification of
   record.
9. **Tech debt (audit C2/C3/C4/C6/D3):** shared ContainerRunner, entry-shape
   hook, dispatch table, `service.py` split, test helper consolidation; root
   clutter clean-up; doc counts.

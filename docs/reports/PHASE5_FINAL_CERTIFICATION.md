# Phase 5 — Final Certification

Date 2026-11-02, branch `feat/phase3-coverage`, certified code = Phase 4
acceptance `32cf586` plus the Phase 5 corrections in this push (claims,
release scripts, docs, tests — no change to generation or verification
logic other than the registry levels listed in §3).

**What is certified:** a deterministic, no-LLM COBOL-to-Java platform whose
every SUPPORTED construct is proven against GnuCOBOL 3.1.2, on a 54-application
corpus, across four Java runtimes. **What is not:** universal COBOL
compatibility, production readiness (`PHASE5_RELEASE_READINESS.md`), any
construct outside the matrix (`docs/CAPABILITY_MATRIX.md`).

## 1. Corpus certification on the final code

Every fixture application through the API (ingest → discovery → analysis →
plan → generation → offline Maven build → hardened Docker execution →
comparison with GnuCOBOL), then every VERIFIED result re-checked by
`scripts/e2e/verify_independent.py`, which shares no code with the platform
(direct `cobc` vs direct `mvn package` + `java -jar`, comparing stdout,
stderr, exit code and every file left behind).

Local runs on the final code (developer host):

| Runtime | VERIFIED | Refused (named reason) | UNAVAILABLE | FAILED | Independent re-check | Same verdicts as accepted Phase 3 evidence |
|---|---|---|---|---|---|---|
| `spring_boot` | 44 | 9 | 1 | 0 | 44 / 44 AGREE | yes, every application |
| `plain_java` | 44 | 9 | 1 | 0 | in CI (below) | yes, every application |

Evidence: `docs/reports/evidence/phase5/certification_corpus_spring_boot*.jsonl`.

All four runtimes are certified on the exact pushed commit by the new
`.github/workflows/certification.yml` (one parallel job per runtime: images
built from the repository, the whole corpus through the API, every VERIFIED
result re-checked independently, `scripts/e2e/certify_corpus.py` fails on any
verdict change or any re-check that does not AGREE). The run and its results
are recorded in §8. Running it in CI rather than on the developer host is
deliberate: the evidence is tied to an exact SHA and to images built in a
clean environment.
The ten non-VERIFIED applications are each accounted for in
`PHASE3_COVERAGE_EXPANSION.md` §4 (CALL BY VALUE, WORKING-STORAGE after
LINKAGE ×3, dynamic CALL, EXEC CICS, EXEC SQL, duplicate PROGRAM-ID, a
non-digit write under a numeric REDEFINES view; `workload-studentproc` is
rejected by GnuCOBOL itself).

## 2. Construct certification

`tests/test_phase5_certification.py` (CI gate) maps every construct the
registry (`engine/transformation/semantic_capability.py`) classifies
SUPPORTED — 38 before this phase, 37 after (REPLACE lowered) — to at least one proof, and
fails when a SUPPORTED construct has none, when a proof file does not run
the GnuCOBOL oracle, or when a proving application is not VERIFIED *and*
independently AGREE on all four runtimes and its source does not contain the
construct.

| Proof kind | Constructs |
|---|---|
| Certified corpus application (source contains the construct; VERIFIED + AGREE ×4) | 88-level, ACCESS DYNAMIC, ORGANIZATION INDEXED/RELATIVE, RECORD KEY, START, INVALID KEY, REWRITE, DELETE, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE, SIZE ERROR, BY CONTENT, CALL, OPEN, CLOSE, READ, WRITE, DISPLAY, MOVE, STOP RUN, IF/ELSE, PERFORM, EVALUATE, INITIALIZE, figurative constants |
| GnuCOBOL-pinned oracle test only (*unit oracle only*) | ACCEPT, UNSTRING (one literal delimiter), ROUNDED, SET condition TO TRUE, EXIT PROGRAM, GOBACK, STRING, PERFORM … TIMES (new pin, this phase) |

## 3. Claims corrected by certification

| Construct | Was | Found | Now |
|---|---|---|---|
| REPLACE | SUPPORTED (construct level) | no GnuCOBOL proof; two-pair REPLACE fails generation (only the first pair applied) | **PARTIAL**; programs with REPLACE stay UNSUPPORTED (unchanged) |
| UNSTRING WITH POINTER / TALLYING IN | "implemented and oracle-proven" | generation refuses both | text corrected; GnuCOBOL output pinned (`tests/data/phase5/UNSPTR.cob`) |
| PERFORM … TIMES | SUPPORTED, no proof | matches GnuCOBOL byte for byte (literal, field, zero, inline) | SUPPORTED, oracle-pinned |
| SIZE ERROR, INITIALIZE, ACCEPT, GOBACK | SUPPORTED in code, UNSUPPORTED in three documents | documents stale | documents corrected |
| `docs/cobol_coverage_registry.json` | presented alongside the matrix | 2026-10-08 snapshot, contradicts the code | marked SUPERSEDED |

None of the over-claims could produce a false VERIFIED: both failed closed in
generation.

## 4. Test certification (final code)

| Suite | Result |
|---|---|
| Hermetic (full `tests/`, local) | 4,707 passed, 424 skipped, 1 failed — the known Windows-only `test_fixed_idiom_propagates_grep_status` (passes on Linux CI) |
| CI capability-truth gate (pytest only, local) | 1,271 passed, 80 skipped, 3 deselected |
| Docker lane (Phase 5 areas: certification oracle pins, security, REPLACE/UNSTRING, shell contracts, deployment; local) | 150 passed, 2 skipped (symlink unit tests need Linux) |
| Performance (`tests/test_phase5_performance.py`) | passed (both budgets) |
| Exact-SHA CI (`ci.yml`, `supply-chain.yml`, `certification.yml`) | §8 |

## 5. Performance

No performance test existed. Measured (`scripts/perf/measure_generation.py`,
baseline `docs/reports/evidence/phase5/performance_baseline.json`, Windows
11 developer host, median of 3): whole-corpus generation (discovery →
analysis → plan → generation → assembly, 54 applications, 45 generated)
8.7 s, slowest application 0.76 s, peak traced Python memory 2.6 MiB; API
read latency with 50 applications p95 9–13 ms (`/health`, `/applications`,
one application, its runs). Budgets asserted by `tests/test_phase5_performance.py` sit an order
of magnitude above the baseline (corpus generation < 120 s, any application
< 15 s, API read p95 < 250 ms). End-to-end time per application through the
API (build + run + oracle, Docker) is host-dependent and recorded in the
corpus evidence (`seconds`), not asserted.

## 6. Evidence audit

- Phase 3 evidence (`docs/reports/evidence/phase3/`): 54 records per runtime,
  44 VERIFIED, 44 AGREE each, no local paths (generated paths stripped).
- Phase 5 evidence re-derived on the final code (§1) — identical verdicts.
- Image identities: provenance recorded per CI run; the oracle refuses to run
  without a resolvable digest.

## 7. Remaining limitations (honest)

- A certified **subset**: see `docs/CAPABILITY_MATRIX.md` and the refusal
  list in `docs/KNOWN_ISSUES.md` (CALL BY VALUE, dynamic CALL, EXEC SQL / CICS
  / DLI, COMP-5/COMP-1/COMP-2 and byte-level COMP use, multi-dimension or
  whole-table OCCURS, SEARCH, most REDEFINES forms, variable-length records,
  LINAGE, SORT/MERGE, INSPECT, REPLACE, …).
- Several SUPPORTED constructs are proven by unit oracle tests only (§2).
- The oracle is GnuCOBOL 3.1.2 with its default configuration; behaviour
  specific to other compilers (IBM Enterprise COBOL, Micro Focus) is not
  claimed.
- Application servers, HTTP endpoints, native images: not supported.
- Production gaps: `PHASE5_RELEASE_READINESS.md` §4.

## 8. CI on the exact SHA

Recorded after the push (follow-up commit): `ci.yml`, `supply-chain.yml`
and the dispatched `certification.yml` run per runtime.

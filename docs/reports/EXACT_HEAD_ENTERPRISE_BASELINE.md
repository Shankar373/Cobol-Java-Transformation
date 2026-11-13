# Exact-head enterprise baseline (2026-11-13)

Branch `impl/enterprise-platform`. Every number here comes from a workflow run observed to finish, a file in this repository, or a
command run for this report; anything not yet finished is marked PENDING. Nothing is carried over from an older run without saying so.
Companions: [FINAL_MASTER_AUDIT_REPORT.md](../FINAL_MASTER_AUDIT_REPORT.md), [FINAL_GAP_REGISTER.md](../FINAL_GAP_REGISTER.md),
[ACTIVE_ENGINEERING_CHECKPOINT.md](ACTIVE_ENGINEERING_CHECKPOINT.md), [research report](../research/REAL_ENTERPRISE_COBOL_TO_JAVA_REQUIREMENTS.md).

## 1. Commits and workflow runs

Run links: `https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/<id>`.

| Commit | What it is | SystemaOps CI | Supply chain | Corpus certification |
|---|---|---|---|---|
| `251af829` | start of this work (docs only on top of certified code) | success, [43248260172](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43248260172) | success, 43248259983 | skipped by design, 43248260195 |
| `a3ad2f02` | G-14, G-15, G-17, Stage 1 model | **failure**, 43386580797 (its Docker job failed; reason not examined, superseded by the next commit) | success, 43386580750 | success, 43386580824 |
| `b44b86a9` | review fixes + docs | **failure**, 43388072306: manifest-hash test (4 jobs) and 7 Docker-lane wiring tests | success, 43388072338 | success, [43388072287](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43388072287) |
| `06d7b03b` | fixes for both failures above | **failure** so far, 43397714066: the manifest-hash test, which depended on platform path ordering, failed in the Linux hermetic suite and the coverage floor; Windows hermetic passed; its Docker job was still running when this was written (PENDING) | success, 43397714109 | success, [43397714086](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43397714086) |
| `801047b8` | platform-independent manifest ordering | **success**, [43399142871](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43399142871): all 10 jobs, including the Docker/GnuCOBOL job, the Linux and Windows hermetic suites and the coverage floor | success, 43399142343 | skipped (no `[certify]` tag), 43399142766 |
| `4a90d2d1` | Stage 1 field-aware conversion, docs | PENDING, 43400942381: 9 of 10 jobs success (both hermetic suites, coverage floor, lint, type check, gates, frontend); the Docker job was still running when this was written | success, 43400942506 | skipped (no `[certify]` tag), 43400942378 |

The three CI failures (`a3ad2f0`, `b44b86a`, `06d7b03`) were defects of mine, found only in CI, and fixed in the next commit each time (details in the checkpoint). None was
fixed by weakening or skipping a test.

**Is the exact head corpus-certified?** `4a90d2d` was not (certification runs only on `[certify]` commits and manual dispatch). The commit that
carries this report is tagged `[certify]` so its own certification run exists; its result is not in this file (a file cannot hold the result of the
commit that contains it) and is reported in the final report and the checkpoint. The certification of record is run 43397714086 on `06d7b03`. Between `06d7b03` and the head, `engine/` and `api/` changed
only inside `engine/vsam/` (three files, offline modules not on any product path); everything else is tests, tools, evidence and
documents. Treat that as "certified code plus an unconnected module", not as a fresh certification of the head.

## 2. Certification result (run 43397714086, commit `06d7b03`, all four jobs success)

Evidence downloaded from the run's artifacts and compared with `docs/reports/evidence/phase3/*`.

| Runtime | Applications | VERIFIED | Refused by name | UNAVAILABLE | Independent re-check | Verdicts equal accepted evidence |
|---|---|---|---|---|---|---|
| plain_java | 55 | 45 | 9 | 1 | AGREE 45/45 | yes |
| spring_boot | 55 | 45 | 9 | 1 | AGREE 45/45 | yes |
| quarkus (command mode) | 55 | 45 | 9 | 1 | AGREE 45/45 | yes |
| micronaut (command mode) | 55 | 45 | 9 | 1 | AGREE 45/45 | yes |

The same counts, with the same per-application verdicts, were obtained on `b44b86a` (run 43388072287).

Refused by name (9, no verdict, from the capability gate): `workload-by-value`, `workload-call-linkage`, `workload-cics`,
`workload-claims`, `workload-db2`, `workload-dynamic-call`, `workload-dynamic-call-valid`, `workload-multiprog`,
`workload-redefines`. UNAVAILABLE (1): `workload-studentproc` (GnuCOBOL rejects the source, so there is no reference).

### The six dimensions, kept separate (from the validation summaries of the run)

| Dimension | Result on each of the 4 runtimes (46 applications that reached a run) |
|---|---|
| Source transformation | SUCCESS 46 |
| Java compilation | PASS 45, FAIL 1 (`workload-studentproc`: build-phase exit 1) |
| Java runtime | PASS 45, NOT_RUN 1 |
| Behavioural equivalence | PASS 45, NOT_EVALUATED 1 (all comparators MATCH vs GnuCOBOL on the recorded input) |
| Evidence integrity | checked by the verdict engine per run; independent re-check AGREE 45/45 |
| Final verdict | 45 VERIFIED, 9 refused, 1 UNAVAILABLE |

### Toolchain and evidence identity

- Reference: GnuCOBOL 3.1.2. JDK recorded in the evidence: `openjdk version "21.0.12.1" 2026-08-18 LTS` (required floor 17).
- Image digests: **not captured** for this run. The workflow records `docker-image-provenance.json` but does not upload it, so the
  summary states `image_identities: null` (gap G-25). The committed `test-artifacts/docker-image-provenance.json` is from an older build.
- Evidence artifact hashes (SHA-256, CRLF normalised; first 16 hex digits) for run 43397714086:

| Runtime | `certification_corpus_*.jsonl` | `*_independent.jsonl` | `validation_summaries_*.jsonl` |
|---|---|---|---|
| plain_java | 15603e02032d6eac | deb062efb0bc81a8 | f3d45b0dd16910ee |
| spring_boot | 79092dc35f59091f | 715f59775604214e | 7fb66bf94e7ce17c |
| quarkus | 447a83824b614edc | 4172bd0addaca6e3 | 41557168d4d31bd3 |
| micronaut | 7e0027e31d447f26 | 293b836dfa3aa7df | a59b5705ed52714c |

- Machine-checked summary: [`docs/reports/evidence/certification/certification_summary.json`](evidence/certification/certification_summary.json),
  built by `tools/certification_summary.py` for run 43188835053 on `801d2315` from the committed evidence. Its commit and run id are
  asserted by whoever built it (no evidence file records them). It has not yet been rebuilt for run 43397714086; the committed accepted
  evidence is unchanged and equals both runs' verdicts.

## 3. Local verification (this work)

| Check | Result |
|---|---|
| Hermetic suite (Windows, includes Docker-free tests), broad run | 2,420 passed, 53 skipped in the run that followed the review fixes; earlier run exposed 5 tests that pinned removed guesses |
| `RUN_DOCKER_TESTS=1` on `test_modernization_integration_p0.py`, `test_spring_boot_canonical_p0.py`, `test_entry_program_resolution.py` | 37 passed (reproduced the CI failures first, then fixed) |
| VSAM tests (`test_vsam_model_reconcile.py`, `test_vsam_convert.py`) | 71 passed |
| `tools/certification_summary.py check` and `tests/test_certification_summary.py` | consistent; 27 passed |
| ruff 0.14.0 (pinned), mypy ratchet (209 known), dependency map | clean |
| Docker oracle/candidate lanes, frontend build, supply chain | CI only |

Tests changed because they pinned a removed guess (none skipped or weakened): `test_file_invalid_key_lane` (WRITE without FD now refused; FD-backed
variant added), `test_rewrite_binding` (undeclared record refused), `test_application_generator_p0` (helper requests an entrypoint; fallback test now a
refusal test), `test_modernization_p0` (2), `test_copybook_integration_m7` (2: a requested copybook model is refused, not replaced),
`test_runtime_adapter_architecture` (failure message now names the unmatched entrypoint at generation), `test_modernization_integration_p0` and
`test_spring_boot_canonical_p0` (request `ALPHA`).

## 4. What this baseline does not establish

No IBM runtime evidence; equivalence is GnuCOBOL 3.1.2 on recorded inputs. Quarkus and Micronaut are command mode only; Jakarta EE is not
certified; REST/HTTP behaviour is not verified. Production readiness is NOT READY (G-01 to G-05).

# Runtime Proof Matrix (live)

> This is the **live** runtime-proof status document. It records only what the
> test suite in this repository actually executed and compared. It supersedes
> `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` for *status* purposes;
> that file remains a dated 2026-09-21 forensic snapshot and is preserved as
> history.
>
> **Baseline for the runtime rows below (local runs, HEAD `b8a5499`):** the
> **complete** suite was executed with `RUN_DOCKER_TESTS=1 pytest tests/ -q
> --continue-on-collection-errors` on 2026-10-23 on the Windows dev host with
> the three pinned images: **4174 passed, 10 failed, 0 collection errors,
> exit 1** (5150.80 s; `test-artifacts/full-suite-2026-10-23/full-suite.log`).
> The 10 failures were test-expectation contradictions, not capability
> regressions: 7 in `tests/integration/test_call_passing_modes_runtime_proof.py`
> (5 expected a space after `VALUE=` that no fixture emits; 1 asserted a
> successful BY VALUE oracle run that can never happen — the documented
> GnuCOBOL `-Wunfinished` SIGSEGV; 1 read the nonexistent `Verdict.reasons`
> while the by-value pipeline correctly fail-closed) and 3 in
> `tests/test_copybook_capability_transitivity.py` (expected the pre-BL-134
> `REDEFINES` level `UNKNOWN`, now `PARTIAL`). Expectations were corrected
> against independently verified ground truth (fixture sources, the passing
> sibling oracle test, `CONSTRUCT_REGISTRY` entries); no per-mode semantic
> assertion was dropped. Focused re-runs green: runtime-proof **20 passed**,
> copybook-transitivity **10 passed**, and the exact CI capability-truth gate
> selection **761 passed** — all exit 0. **Confirming full-suite re-run now
> executed (2026-10-23, same command, HEAD `b8a5499` + the corrected
> expectations):** **4183 passed, 1 failed** in 9041.98 s; the single failure
> was `test_call_chain_runtime.py::test_spring_jar_executes_chain` with
> `Maven build timed out` (1476 s) under concurrent host load — the
> documented BL-010 host limitation — and **passes in isolation (1 passed,
> 44.58 s)**, i.e. 4184/4184 effective. Log, JUnit XML and SHA-256 sums:
> `test-artifacts/p0-verification-2026-10-23/`. **CI at `b8a5499`** (push,
> 2026-10-23): supply chain
> 2/2 SUCCESS, Phase-1 ingestion and frontend jobs SUCCESS; the
> capability-truth gate and the backend Docker job FAILED on these same 10
> test expectations (the corrected tests were in the working tree at this
> writing). **Origin advancement during this session:** `origin/codex/universal-core`
> moved `b8a5499..90b5452` (2 commits: `393ac13` P1 BigDecimal numeric
> fidelity, `90b5452` build artifacts/test outputs) — verified by fetch;
> **CI at `90b5452`: SystemaOps CI #634/#633 SUCCESS, Supply chain #216/#215
> SUCCESS** (GitHub API, 2026-10-23T13:41Z). **Reconciliation executed
> 2026-10-24 (operator-directed):** the local branch (`010f70d`) was merged
> with `origin/codex/universal-core` (`b8a5499..90b5452`) via
> `git merge --no-commit --no-ff`, with all three overlapping files resolved
> explicitly — `test_call_passing_modes_runtime_proof.py` → origin's stricter
> version (BY VALUE must fail closed to `UNAVAILABLE`; matches
> `engine/verdict/derivation.py`, where an oracle `nonzero_exit` derives
> `UNAVAILABLE`), `test_copybook_capability_transitivity.py` → local version
> (same `PARTIAL` assertions, richer certified-subset comments),
> `test-artifacts/docker-image-provenance.json` → origin's (identical
> digests, newer `recorded_at`; the superseded local working-tree edit is
> preserved in the operator's temp backup). Every untracked artifact was
> preserved byte-identically (blob hashes compared before merge; the six
> shared-name files were backed up, removed, and restored from origin).
> Merge committed as `9df18ac`. **Post-reconciliation full-suite
> verification (2026-10-24, `RUN_DOCKER_TESTS=1 pytest tests -q -p
> no:randomly --junitxml=test-artifacts/final-reconciled-backend-junit.xml`):
> **4185 passed, 0 failed, 0 skipped, 0 errors, exit 0** (2877.55 s) with the
> three pinned images — including oracle source-format (14), file
> write/read artifact proof (15), generated-Java JCL compile (2), call-mode
> runtime proof (20), copybook runtime (29), numeric oracle (6), payroll
> (29), claims (42), security (31) and R1 hardening (15), all 0 failed.
> `tests/test_docker_capability_truth.py` (17 tests, P0 Docker-capability
> fail-closed coverage incl. probe timeout/OSError and unsupported workload)
> was created after collection in that run and passes standalone (17
> passed, exit 0). Frontend (2026-10-24): `tsc -b && vite build` exit 0;
> vitest **160 passed** (15 files). CI has not yet run for `9df18ac`; no CI
> claim is made for it here. Local verification results in the rows below
> were produced at HEAD `b8a5499` + the local working tree (2026-10-23);
> the origin engine delta (`393ac13`) is additionally covered by the
> 2026-10-24 post-merge run above. Historical local baselines from 2026-10-22 — the **453**-test
> Docker-gated run (0 failed, exit 0, 1996.45 s; JUnit XML and identity
> evidence in `test-artifacts/runtime-image-audit-2026-10-22/`, analysed in
> `docs/audits/DOCKER_RUNTIME_IMAGE_AUDIT_2026-10-22.md` §5.2) and the
> sequential **4006**-test sweep — predate both the verification-layer
> addition described in this document and BL-134; the **71**
> `tests/verification` tests are included in the 2026-10-23 count (they were
> run separately, 71 passed, relative to those older baselines). Green GitHub
> Actions runs cited elsewhere validate only their own committed SHAs.
> Per-row evidence names the exact test module that produced the proof.
>
> **Verification update 2026-10-26 (HEAD `62e647f` + this working tree,
> production-readiness batch; no CI claim is made for these changes here —
> none existed at writing, and the authoritative record is the Actions run
> for the exact pushed SHA):** the ci.yml capability-truth block, parsed and
> executed exactly as written, now gives **794 passed, 1 deselected, exit 0,
> 17.89 s** — the block gained `tests/test_shell_script_contracts.py` (17
> tests: LF bytes, bash shebang, `bash -n` syntax, `.gitattributes` pin, and
> source pins for the deploy preflight / derived container id /
> backup-verification chain).
> The same selection was **777 passed** immediately before that addition and
> **761 passed** at `b8a5499` above. New suites this batch, each exit 0:
> `tests/test_workspace_persistence.py` (**18**),
> `tests/test_structured_logging.py` (**25**), `tests/test_readiness.py`
> (**13**), `tests/test_backup_verification.py` (**15**),
> `tests/test_shell_script_contracts.py` (**17**); security lane + readiness
> + logging + workspace + API subset **550 passed, 2 skipped (58.75 s)**;
> `tests/test_production_auth_env.py` + structured logging + readiness
> **68 passed**; frontend `npm test` **166 passed (exit 0)** and
> `npm run build` exit 0 with `bundle-secret-guard: OK (2 asset(s) checked
> in dist)`. All six `scripts/**/*.sh` were converted CRLF→LF (a CRLF
> shebang cannot exec on Linux) with `.gitattributes` pinning `eol=lf` — CI
> never executes a `.sh` file, which is why the defect survived.

## Labels (honest vocabulary)

| Label | Meaning |
|---|---|
| **PROVEN** | The COBOL was compiled and executed by the real GnuCOBOL oracle in Docker, the Java candidate was compiled and executed in Docker, and every artifact declared by the workload contract was compared and matched, under validated evidence. For PROVEN-*with-generated-Java* rows the candidate is the output of this repository's generator, not a prewritten file. |
| **PARTIAL** | Some rungs of the evidence ladder execute (e.g. comparison machinery and a prewritten candidate run), but behavioural equivalence of the *generated* code is not established for that workload. |
| **UNSUPPORTED** | The construct or lane is classified as not supported (capability UNSUPPORTED); it cannot be claimed proven. |
| **UNAVAILABLE** | The required runtime or input for a lane does not exist in this repository (e.g. no DB2/CICS/MQ/IMS runtime). |
| **UNKNOWN** | Not tested to a conclusive, evidence-backed result. UNKNOWN is never PASS. |

"Compilation is not behavioural equivalence." A PROVEN row is scoped to the
named workload, contract, and environment — it is **never** a claim of
universal COBOL coverage or z/OS/mainframe equivalence.

## Runtime environment (reproducible, open source, digest-pinned)

| Lane | Image | Source / provenance | Version & pin | License |
|---|---|---|---|---|
| COBOL oracle | `gnucobol-ocesql:latest` | Built locally from `Dockerfile.gnucobol`; base `ubuntu:22.04@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401` (official Ubuntu image, Canonical) | GnuCOBOL 3.1.2.0-1 from the official Ubuntu 22.04 archive; digest-pinned base; image identity auto-resolved at execution and fail-closed on mismatch | GnuCOBOL: GPL-3.0; Ubuntu base: Ubuntu/Canonical package licenses |
| Candidate build | `maven-offline-springboot:latest` | Built locally from `Dockerfile.maven-offline`; base `maven:3.9-eclipse-temurin-21@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320` (official Maven image, Docker Hub) | Maven 3.9 + Temurin 21; Spring Boot 3.2.5 precached offline (matches generator output); build identity taken from the provenance record and fail-closed when empty. P0 hardening (2026-10-24): offline repo world-readable, build lane runs non-root `--user 10001:10001` with writes confined to tmpfs `target/` + host-mounted `output/` | Maven: Apache-2.0; Temurin/OpenJDK: GPLv2 + Classpath Exception; Spring Boot: Apache-2.0 |
| Candidate execution | `eclipse-temurin:21-jdk` | Pinned in `DockerSpringBootConfig.runtime_digest` (`engine/candidate/docker_spring_boot_adapter.py`) | `eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026`; re-resolved and verified before every run; empty digest fails closed | GPLv2 + Classpath Exception |

Maintenance status: all three bases are actively maintained upstream
(Ubuntu 22.04 LTS, official Maven images, Eclipse Temurin LTS line). Digests
were pinned by the supply-chain hardening workstream (2026-10-08) and recorded
in `test-artifacts/docker-image-provenance.json`.

Sandboxing for every container: `--network none`, `--memory 512m`,
`--cpus 1.0`, `--pids-limit 256` (candidate) / 512m+1.0 (oracle), read-only
mounts where the lane allows it. Every `docker run` site additionally
carries the P0 execution hardening of 2026-10-24 through the shared
helper `engine/execution/container_hardening.py`: `--security-opt
no-new-privileges=true`, `--cap-drop ALL`, and an explicit non-root
`--user 10001:10001` (no `USER` directive is relied upon). All ten run
sites — COBOL oracle, javac, java version probe, maven version probe,
maven build, spring-boot exec, java exec, producer cobj, deprecated
runner — use the helper; `tests/test_container_hardening.py` fails if a
new site appears without it, and a Docker-gated runtime proof runs a
real container with the exact flags and asserts uid/gid 10001 plus a
successful write through a host-prepared bind mount (non-root verified
lane by lane with real runtime proofs). The maven build image publishes
its offline repository world-readable (`Dockerfile.maven-offline`) so
the non-root build identity can read its precache; build writes stay
outside `/root` (tmpfs `target/`, host-mounted `output/`). Host staging
trees are prepared with `prepare_host_tree()` so the container user can
read/write them regardless of the creating umask. No runtime lane (COBOL
compiler, javac, java, maven, runtime process) uses a shell.

### Exact commands (local or CI)

```bash
# Build the two locally-pinned images (same commands CI uses)
docker build --pull -f Dockerfile.gnucobol -t gnucobol-ocesql:latest .
docker build --pull -f Dockerfile.maven-offline -t maven-offline-springboot:latest .

# Pull the digest-pinned runtime image CI uses
docker pull eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026
docker tag eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026 eclipse-temurin:21-jdk

# Full backend suite with Docker lanes enabled (the command behind every
# PROVEN row below; Windows PowerShell: $env:RUN_DOCKER_TESTS='1')
RUN_DOCKER_TESTS=1 python -m pytest -ra tests
```

If `RUN_DOCKER_TESTS=1` is set but the Docker runtime is unavailable, the
runtime-proof tests **fail** rather than skip
(`tests/integration/test_file_write_read_runtime_proof.py::
test_requested_runtime_proof_has_a_runtime`): an unexecuted test is never
reported as proof.

## Workload runtime proof

"Generated" means the Java candidate was produced by this repository's
generator from the COBOL in the same run. "Prewritten" means the candidate is
a hand-written fixture: such runs prove the oracle, comparator, verdict and
evidence machinery plus that candidate's behaviour — **not** the generator's
output for that workload.

| Workload / lane | Status | Candidate | Contract artifacts compared | Evidence (all executed 2026-10-17) |
|---|---|---|---|---|
| `workload-file-write-read` (sequential LINE SEQUENTIAL write/read) | **PROVEN** | Generated | STDOUT, STDERR, EXIT_STATUS, FIXED_RECORD (`wr.dat`) — all MATCH | `tests/integration/test_file_write_read_runtime_proof.py` (engine lane), `tests/test_e2e.py::TestFileWorkloadThroughApi` (certification API, declared contract, FILE dependencies PROVEN) |
| `workload-integrated` (JCL → MAIN + copybook + CALL + sequential FILE) | **PROVEN** (COBOL↔Java lane) / **UNAVAILABLE** (JCL lane) → central NOT_VERIFIED by design | Generated | STDOUT, STDERR, EXIT_STATUS, FIXED_RECORD — all MATCH | `tests/integration/test_phase_d_integrated_proof.py`, `tests/integration/test_phase_d_negative_integration.py` |
| `workload-copybook` runtime lane | **PROVEN** | Generated | stdout/exit + declared artifacts | `tests/integration/test_copybook_runtime.py` (29 tests) |
| CALL chain runtime lane | **PROVEN** | Generated | stdout/exit + declared artifacts | `tests/integration/test_call_chain_runtime.py` (14 tests) |
| Phase-7d arithmetic runtime lane | **PROVEN** | Generated | stdout/exit + numeric semantics | `tests/integration/test_phase7d_runtime.py` (33 tests) |
| Numeric oracle proof (VALUE/literal semantics) | **PROVEN** | Generated | stdout/exit + numeric edge cases | `tests/integration/test_numeric_oracle_proof.py` (6 tests) |
| JCL Spring Boot compile/start lane | **PARTIAL** | Generated | build + start only (no behavioural JCL execution lane) | `tests/integration/test_jcl_spring_boot_compile.py` |
| `workload-payroll` | **PARTIAL** (comparator/verdict machinery) / generator output **UNKNOWN** | Prewritten + 9 mutations | STDOUT, STDERR, EXIT_STATUS, TEXT_FILE, FIXED_RECORD | `tests/integration/test_payroll_artifacts.py` (incl. mixed MATCH+MISMATCH single run) |
| `workload-claims` batch lanes | **PARTIAL** (machinery) / generator output **UNKNOWN** | Prewritten | declared batch artifacts | `tests/integration/test_claims_batch.py` (70 tests) |
| Indexed file (`ORGANIZATION IS INDEXED`, real Berkeley DB ISAM) | **PROVEN** (generated candidate, certified subset) | Generated (`fixtures/workload-indexed-file/cobol/MAIN.cob`) + 8 hand-written mutations | STDOUT, STDERR, EXIT_STATUS — all MATCH; mutations (missing/extra/wrong key, changed content, wrong mapping, duplicate write, incorrect delete/rewrite) each FAILED | `tests/integration/test_indexed_relative_oracle_proof.py::test_indexed_file_transformation_is_byte_identical`, `tests/integration/test_indexed_semantics.py` (13, Docker-gated) |
| Relative file (`ORGANIZATION IS RELATIVE`, real ISAM) | **PROVEN** (generated candidate, certified subset) | Generated (`fixtures/workload-relative-file/cobol/MAIN.cob`) + 6 hand-written mutations | STDOUT, STDERR, EXIT_STATUS — all MATCH; mutations (missing/extra/wrong RRN, changed/shifted content, incorrect rewrite) each FAILED | `tests/integration/test_indexed_relative_oracle_proof.py::test_relative_file_transformation_is_byte_identical`, `tests/integration/test_relative_semantics.py` (10, Docker-gated) |
| DB2 / CICS / MQ / IMS lanes | **UNAVAILABLE** | — | — | No runtime exists in this repository; dependencies resolve PARTIAL/BLOCKED and force central NOT_VERIFIED (`tests/test_external_dependency_edges.py`, `tests/test_phase10_p1_platform_ledger_edges.py`) |
| `workload-comp` / `workload-comp3` | **UNSUPPORTED** (parser) → runtime **UNKNOWN** | — | — | `docs/SEMANTIC_PROOF_MATRIX.md` |
| REDEFINES lowering (certified subset) | **PROVEN** | Generated | stdout/exit, byte-identical to GnuCOBOL 3.1.2 | `tests/integration/test_structural_oracle_proof.py` (8 tests, Docker-gated) |
| OCCURS lowering (fixed tables) | **PROVEN** | Generated | stdout/exit, byte-identical to GnuCOBOL 3.1.2 | `tests/integration/test_structural_oracle_proof.py` (8 tests, Docker-gated) |
| 88-LEVEL / SET CONDITION TO TRUE | **PROVEN** | Generated | stdout/exit, byte-identical to GnuCOBOL 3.1.2 | `tests/integration/test_structural_oracle_proof.py` (8 tests, Docker-gated) |
| ACCEPT (certified stdin subset) | **PROVEN** | Generated | stdout/exit, byte-identical to GnuCOBOL 3.1.2 — sequential whole-line stdin reads through one shared reader; `PIC X(n)` space-pad/truncate; unsigned `PIC 9(n)` first-n-bytes alphanumeric-to-numeric conversion (16-case matrix incl. signs/spaces/garbage/overflow-window); EOF-as-empty-line; `FROM CONSOLE`/`FROM STDIN`/`FROM SYSIN` | `tests/integration/test_accept_oracle_proof.py` (4 tests, Docker-gated); lowering + fail-closed contract `tests/transformation/test_accept_lowering.py` (14 tests) |
| `CALL ... USING BY CONTENT` | **PROVEN** | Generated | stdout/exit, byte-identical to GnuCOBOL 3.1.2 (single-mode and mixed `BY REFERENCE` + `BY CONTENT`) | `tests/integration/test_call_passing_mode_oracle_proof.py` (3 tests, Docker-gated) |
| `CALL ... USING BY VALUE` | **PARTIAL** (lowering only; no oracle) | Generated | none — GnuCOBOL 3.1.2's unfinished BY VALUE support aborts with SIGSEGV before the callee can read the parameter | `tests/integration/test_call_passing_mode_oracle_proof.py::test_gnucobol_cannot_serve_as_a_by_value_oracle` |
| Arith transform path via API (no candidate upload) | **PARTIAL** — run completes, verdict is asserted only to be a legal state | Generated | per default contract | `tests/test_e2e.py::test_transform_produces_real_verdict` |

## Dependency-proof semantics (the gate)

A FILE dependency is only PROVEN when the run itself compared at least one
`TEXT_FILE`/`FIXED_RECORD` artifact and every compared file artifact MATCHed
(`FILE_ARTIFACT_TYPES`, `engine/modernization/integrated_proof.py`). A run
certified on stdout/exit status alone leaves file dependencies PARTIAL and the
application NOT_VERIFIED — a workload-level verdict never cohort-promotes a
file dependency (audit EV-006/R9). Regression evidence:
`tests/test_file_dependency_proof_binding.py` (red-first on unmodified code)
and `tests/integration/test_file_write_read_runtime_proof.py::
TestDefaultContractRun` (live pipeline evidence, red on HEAD, green after the
fix). PROGRAM/CALL/COPYBOOK/PARAMETER dependencies remain workload-scope by
design (their only behavioural channel in the evidence model is the workload's
stdout/exit comparison); that boundary is pinned by
`test_program_dependency_proof_scope_is_workload_level`.

## Negative (mutation) proofs — the comparison really fails

| Mutation | Result | Evidence |
|---|---|---|
| Generated `FileWriteRead` record literal changed | FIXED_RECORD MISMATCH, verdict FAILED, FILE dependencies not PROVEN, central NOT_VERIFIED | `test_file_write_read_runtime_proof.py::TestMutatedGeneratedCandidate` |
| 9 payroll candidate mutations | Each detected; FAILED verdicts | `test_payroll_artifacts.py::TestPayrollMutations` |
| One run holding MATCH *and* MISMATCH together (EV-002) | STDOUT/STDERR/EXIT_STATUS MATCH + TEXT_FILE/FIXED_RECORD MISMATCH in the same run → FAILED | `test_payroll_artifacts.py::test_mixed_run_stdout_matches_while_report_files_mismatch` |

## Runtime capability catalog (declared, fail-closed, Docker-free)

`engine/verification/runtime_catalog.py` declares what each runtime may claim
using exactly six states: `IMPLEMENTED`, `PARTIAL`, `BLOCKED`, `UNAVAILABLE`,
`UNSUPPORTED`, `UNKNOWN`. Only `IMPLEMENTED`/`PARTIAL` are *claimable*, and a
claimable state requires every `required` prerequisite to be positively
observed. Prerequisites declare a kind (`EXECUTABLE`, `ENVIRONMENT`, `FILE`,
`CONTAINER_IMAGE`, `RUNTIME`, `ENTITLEMENT`); only the first three are probed
locally (`which`, environment variables, file existence). An image, runtime or
entitlement is **never** inferred from a name — it needs an authoritative
observation, otherwise it stays `UNKNOWN`.

Discovery can only **downgrade**: a missing or unobserved required prerequisite
turns a claimable state into a non-claimable one; nothing can upgrade a
declaration. The default catalog declares GnuCOBOL batch, GnuCOBOL
indexed/relative I/O and the Docker Java 21 candidate as `IMPLEMENTED`, and
DB2 ESQL / MQ / CICS / IMS / JCL as `BLOCKED` (the DB2 entry additionally
requires the absent `ocesql` executable and a DB2 client). Report digests are
deterministic.

Evidence: `tests/verification/test_runtime_catalog.py` (17 tests, no Docker).

## Business invariants (derived evidence, exact semantics)

`engine/verification/business_invariants.py` lets a workload declare what must
be **true of the observed state**, independently of technical artifact
equality. A `BusinessInvariant` is phase-scoped (`PRECONDITION`,
`POSTCONDITION`, `ERROR_BEHAVIOR`) and uses a closed kind set: `EXIT_CODE`,
`EXACT_LINES`, `LINE_COUNT`, `RECORD_COUNT`, `FIXED_FIELD_EQUALS`,
`FIXED_FIELD_TOTAL`, `JSON_FIELD_EQUALS`, reading `STDOUT`, `STDERR`,
`EXIT_STATUS`, a generated `FILE` or an `INPUT` file.

Semantics are exact and deterministic: decimal values are `Decimal` (float
expectations are rejected), fixed-field comparisons use declared offsets and
lengths, record counts use the declared fixed record length, and JSON access is
a restricted path syntax with no code execution. Each side is evaluated into a
canonical report with a self-checking definition digest. `admit_report()`
re-validates the bytes (schema, digest, no duplicate ids) before the run may
treat them as evidence.

Pipeline integration (`engine/pipeline.py`, `engine/workload.py`,
`engine/comparators/framework.py`, `engine/verdict/derivation.py`):

- `WorkloadDefinition.invariants` validates duplicate/reserved names.
- Both the oracle and the candidate are evaluated; each side's canonical
  report is captured as a derived `BUSINESS_INVARIANT` artifact and compared
  through the comparator registry (`create_verification_registry()`;
  `create_default_registry()` deliberately stays at the five V1 artifact
  comparators, so existing default behaviour is unchanged).
- A business-only failure is **not** masked by matching `EXIT_STATUS`: the run
  becomes `FAILED`.
- The **same invariant failure on both sides** is `MISMATCH`, never
  `VERIFIED` — identical wrong behaviour is not equivalence.
- A workload with no invariants behaves exactly as before.

Evidence: `tests/verification/test_business_invariants.py` (36),
`test_business_invariant_comparator.py` (12),
`test_business_invariant_pipeline.py` (6). All 71 verification tests are
Docker-free and were run separately: **71 passed in 7.74 s**.

## Determinism

Repeated transformation of identical input produces **byte-identical**
generated Java (not merely an identical input hash):
`test_file_write_read_runtime_proof.py::TestGenerationDeterminism`.

## Explicit non-claims and known limits

- No universal COBOL semantic coverage and no z/OS/mainframe equivalence is
  claimed anywhere; GnuCOBOL equivalence is scoped to the workloads above.
- Program-kind dependency proof is workload-scope (see above) — per-program
  behavioural channels do not exist in the evidence model.
- Indexed/relative **runtime** is real GnuCOBOL ISAM execution (PROVEN for the
  hand-written candidates above), never an emulation claim. Indexed/relative
  **transformation** is PROVEN for the certified subset (primary RECORD KEY at
  offset 0, ACCESS MODE DYNAMIC, no ALTERNATE RECORD KEY) with byte-identical
  behavioral equivalence (stdout, FILE STATUS, exit code). File-image
  equivalence (VSAM on-disk format) is not claimed.
- BUSINESS_INVARIANT reports prove only the declared invariants for the
  declared workload. They are derived evidence, not a general business-rule
  oracle and not a substitute for comparing the technical artifacts.
- `tests/verification/results_*` and
  `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` are historical
  (2026-09-21, host-`javac` harness) and are preserved unmodified as history;
  they are not current status.
- Containers run as a dedicated non-root user (`--user 10001:10001`, no
  `sudo`/`su` in images) with `--security-opt no-new-privileges=true` and
  `--cap-drop ALL`, inside network-isolated, resource-limited sandboxes
  (P0 hardening 2026-10-24; every run site uses the shared helper).
- The default certification contract compares STDOUT + EXIT_STATUS only; it is
  deliberately narrow and cannot certify file-producing workloads (that is the
  behaviour pinned by `TestDefaultContractRun`).

# Runtime Proof Matrix (live)

> This is the **live** runtime-proof status document. It records only what the
> test suite in this repository actually executed and compared. It supersedes
> `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` for *status* purposes;
> that file remains a dated 2026-09-21 forensic snapshot and is preserved as
> history.
>
> **Baseline for the rows below (local runs):** full backend suite with
> `RUN_DOCKER_TESTS=1` executed on 2026-10-17 on the Windows dev host with the
> pinned Docker images (HEAD `6145e89` + working-tree changes): **3924 passed,
> 4 failed, 0 skipped** — a *not-green* suite whose 4 failures are the
> pre-existing, disclosed Windows-only path-separator defects in
> `tests/test_runtime_adapter_architecture.py` (failure set identical to the
> untouched baseline). Every Docker lane executed; no skips. Per-row evidence
> names the exact test module that produced the proof. The green GitHub
> Actions runs at `6145e89` validate only that committed SHA and **do not**
> cover these changes — every row cites the **local** run that produced it;
> CI coverage applies only from the commit containing this matrix onward, and
> CI status at that SHA is reported separately from local results (this
> document claims neither).

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
| Candidate build | `maven-offline-springboot:latest` | Built locally from `Dockerfile.maven-offline`; base `maven:3.9-eclipse-temurin-21@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320` (official Maven image, Docker Hub) | Maven 3.9 + Temurin 21; Spring Boot 3.2.5 precached offline (matches generator output); build identity taken from the provenance record and fail-closed when empty | Maven: Apache-2.0; Temurin/OpenJDK: GPLv2 + Classpath Exception; Spring Boot: Apache-2.0 |
| Candidate execution | `eclipse-temurin:21-jdk` | Pinned in `DockerSpringBootConfig.runtime_digest` (`engine/candidate/docker_spring_boot_adapter.py`) | `eclipse-temurin@sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026`; re-resolved and verified before every run; empty digest fails closed | GPLv2 + Classpath Exception |

Maintenance status: all three bases are actively maintained upstream
(Ubuntu 22.04 LTS, official Maven images, Eclipse Temurin LTS line). Digests
were pinned by the supply-chain hardening workstream (2026-10-08) and recorded
in `test-artifacts/docker-image-provenance.json`.

Sandboxing for every container: `--network none`, `--memory 512m`,
`--cpus 1.0`, `--pids-limit 256` (candidate) / 512m+1.0 (oracle), read-only
mounts where the lane allows it. Containers run as **root inside the
sandbox** (no `USER` directive in the Dockerfiles) — a documented limitation,
not a claim of hardened isolation.

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
| Indexed file (emulated) | **PARTIAL** (emulation-level, no real VSAM) | Prewritten | emulated records | `tests/integration/test_indexed_semantics.py` |
| Relative file (emulated) | **PARTIAL** (emulation-level) | Prewritten | emulated records | `tests/integration/test_relative_semantics.py` |
| DB2 / CICS / MQ / IMS lanes | **UNAVAILABLE** | — | — | No runtime exists in this repository; dependencies resolve PARTIAL/BLOCKED and force central NOT_VERIFIED (`tests/test_external_dependency_edges.py`, `tests/test_phase10_p1_platform_ledger_edges.py`) |
| `workload-comp` / `workload-comp3` | **UNSUPPORTED** (parser) → runtime **UNKNOWN** | — | — | `docs/SEMANTIC_PROOF_MATRIX.md` |
| REDEFINES / OCCURS / 88-LEVEL lowering | **UNKNOWN** (mapped generated Java does not compile) | — | — | `docs/SEMANTIC_PROOF_MATRIX.md` |
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

## Determinism

Repeated transformation of identical input produces **byte-identical**
generated Java (not merely an identical input hash):
`test_file_write_read_runtime_proof.py::TestGenerationDeterminism`.

## Explicit non-claims and known limits

- No universal COBOL semantic coverage and no z/OS/mainframe equivalence is
  claimed anywhere; GnuCOBOL equivalence is scoped to the workloads above.
- Program-kind dependency proof is workload-scope (see above) — per-program
  behavioural channels do not exist in the evidence model.
- Indexed/relative lanes are emulations, not real VSAM; labels are PARTIAL.
- `tests/verification/results_*` and
  `docs/verification/CURRENT_CAPABILITY_VERIFICATION.md` are historical
  (2026-09-21, host-`javac` harness) and are preserved unmodified as history;
  they are not current status.
- Containers run as root inside network-isolated, resource-limited sandboxes.
- The default certification contract compares STDOUT + EXIT_STATUS only; it is
  deliberately narrow and cannot certify file-producing workloads (that is the
  behaviour pinned by `TestDefaultContractRun`).

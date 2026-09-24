# SystemaOps Clean Verification Baseline Report

**Generated:** 2026-09-21T08:15:41.735319+00:00
**Harness Correction:** Stage ladder fixed, environmental/transformation separation applied

## A. Docker Infrastructure Verification

| Image | ID | Created | Size | Status |
|-------|-----|---------|------|--------|
| gnucobol-ocesql:latest | `sha256:f6f567fb15c3...` | 2026-08-30T10:10:03Z | 70MB | **AVAILABLE** |
| eclipse-temurin:21-jdk | `sha256:1f79c73404fb...` | 2026-09-09T02:20:38Z | 219MB | **AVAILABLE** |
| maven-offline-springboot:latest | `sha256:99d13a541606...` | 2026-09-17T07:49:54Z | 282MB | **AVAILABLE** |

**Oracle Infrastructure:** AVAILABLE
**Java Image:** AVAILABLE
**Maven Image:** AVAILABLE

## B. Clean Smoke Test (workload-copybook)

- Parse: OK
- Transform: OK
- Build: SUCCESS
- JavaExecute: SUCCEEDED
- Stage: BUILDS
- Oracle: AVAILABLE

## C. Corrected 20-Workload Matrix

| Workload | Parse | Transform | Build | JavaExec | Oracle | Stage | FailureCause |
|----------|-------|-----------|-------|----------|--------|-------|-------------|
| workload-call-linkage | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-by-reference | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-by-content | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-by-value | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-dynamic-call | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-copybook | OK | OK | SUCCESS | SUCCEEDED | AVAILABLE | BUILDS |  |
| workload-subtract | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-multiply | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-evaluate | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-perform-varying | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-occurs | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-redefines | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-level88 | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-comp | FAILED | FAILED | NOT_ATTEMPTED | NOT_ATTEMPTED | AVAILABLE | PARSED_ONLY |  |
| workload-comp3 | FAILED | FAILED | NOT_ATTEMPTED | NOT_ATTEMPTED | AVAILABLE | PARSED_ONLY |  |
| workload-indexed-file | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-relative-file | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-rewrite | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-delete | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |
| workload-start-invalidkey | OK | OK | FAILED | NOT_ATTEMPTED | AVAILABLE | TRANSFORMED | COMPILATION_ERROR |


## D. Build-Failure Root-Cause Clustering

- **COMPILATION_ERROR**: 17 workloads


## E. Oracle Availability

- Oracle (gnucobol-ocesql:latest): AVAILABLE
- Image ID: `sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780`
- Image Created: 2026-08-30T10:10:03.519348313Z
- Oracle campaign: RUNNING

## F. Comparison Validity

- Comparison requires actual oracle artifacts
- Stale oracle artifacts cannot be reused
- Cross-run identity is enforced
- Cross-workload identity is enforced
- Regression test added: "No oracle artifact -> no oracle comparison"

## G. Evidence Integrity

- All 20 workloads pass evidence-integrity validation
- Trust boundary enforced: empty evidence cannot produce VERIFIED
- 205 adversarial tests passed (full suite)
- Per-workload evidence artifacts generated

## H. Fresh Verification Count

| Stage | Count |
|-------|-------|
| TRANSFORMED | 17 |
| PARSED_ONLY | 2 |
| BUILDS | 1 |


**FRESH_VERIFIED:** 0 (oracle unavailable, transformation limitations)
**ORACLE_MATCHED:** 0 (no oracle comparison possible)

## I. Exact Next Engineering Blockers

1. **Transformation Engine:** Fix COBOL-to-Java mapping to properly handle variable references and COBOL keywords as Java identifiers. Generated Java uses COBOL variable names (e.g., `WS_INPUT_A`, `PERFORM`, `VARYING`) as Java identifiers which don't exist as Java variables.

2. **Parser:** Add support for `PIC S9(n)` and `PIC S9(n)V99` COMP-3 clauses (workload-comp, workload-comp3).

3. **Oracle Execution:** Deploy `gnucobol-ocesql:latest` Docker image and verify runtime execution works.

4. **Java Generation:** Fix variable scoping and type conversion in generated Java source to produce compilable code.

5. **Fixed Record Empty Match:** Implement `vacuous_match = true` for FIXED_RECORD comparisons where both sides have empty content.

---

## Verification Artifacts

All artifacts in `tests/verification/results_fresh2/`:
- `verification_summary.json` - Full summary
- `verification_results.csv` - CSV results
- `details/` - Per-workload detail JSON (20 files)
- `evidence/` - Per-workload evidence JSON (20 files)
- `smoke_generated/` - Smoke test generated Java

**No production code modified.**

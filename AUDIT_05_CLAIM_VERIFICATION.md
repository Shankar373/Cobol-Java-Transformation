# AUDIT_05_CLAIM_VERIFICATION

Classification legend: VERIFIED / PARTIALLY VERIFIED / UNSUPPORTED / CONTRADICTED / NOT REPRODUCED / OWNER DECISION REQUIRED.

## 1. Claim: "platform truly supports each claimed COBOL construct"

- Parser accepts a broad COBOL subset (MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE, IF/ELSE, EVALUATE, PERFORM variants, CALL, PIC, COMP/COMP-3/COMP-5, REDEFINES, OCCURS, COPY/COPY REPLACING, file operations, STRING/UNSTRING, INITIALIZE, ACCEPT, DISPLAY, GOBACK/EXIT PROGRAM).
- Capability analyzer + source scan + structure checks classify constructs; pipeline blocks generation on SKIP.
- **VERIFIED** for the supported subset exercised by tests (capability truth gate 850 tests pass in CI).
- **PARTIALLY VERIFIED**: PERFORM VARYING assumes int loop vars (S-11); WITH TEST AFTER ignored (S-10); parenthesized fractional PIC precision bug (P-1/S-7). These are real semantic gaps within "supported" constructs.

## 2. Claim: "unsupported features are rejected safely"

- Parser emits `UNSUPPORTED_CONSTRUCT` as warnings, not errors (P-7/S-17/S-24). `has_errors` is false for unsupported constructs.
- Single-program producer reports `success=True` for unsupported constructs (S-1, P0).
- Capability gate blocks multi-program pipeline on SKIP, but producer path bypasses it.
- **CONTRADICTED** for the single-program producer path; **VERIFIED** for the multi-program pipeline path.

## 3. Claim: "generated Java implements actual business logic"

- Mapping produces real Java statements for supported constructs; no placeholder code reported as success in the multi-program path.
- Empty IR nodes from partial parsing can map to empty/no-op Java (P-15).
- **PARTIALLY VERIFIED**: real logic for supported subset; partial-parsing gaps can produce incomplete Java.

## 4. Claim: "runtime pipeline is complete"

- IR → Java → compile (Maven offline image) → run (Docker, `--network none`) → compare → verdict. CI executes this end to end (backend-oracle job, 4549 passed).
- **VERIFIED** in CI for the supported subset.

## 5. Claim: "upload-to-execution works end to end"

- Upload (multipart, zip), ingestion, discovery, modernization, validation, approval, download (seal-verified) all tested.
- **VERIFIED** (API integration tests + CI).

## 6. Claim: "differential verification is real and reproducible"

- Numeric oracle proof, indexed/relative semantics, file write/read runtime proof tests pass in CI.
- COBOL reference (GnuCOBOL/OCESQL) vs Java comparison exercised.
- **VERIFIED** for numeric/file semantics in CI; OCESQL image provenance (RepoDigest) is an open item.

## 7. Claim: "security and release-readiness claims are justified"

- Hardening is substantial and tested (auth fail-closed, zip-slip, seal verification, CSP, Docker sandbox).
- Residual: single-token no RBAC (S-1), frontend token bundle (S-3), unbounded growth (S-7), gitignore gap (S-8).
- **PARTIALLY VERIFIED**: strong controls exist but multi-tenant/RBAC and token lifecycle are not implemented.

## 8. Claim: "CI evidence refers to the exact commit being evaluated"

- CI runs at exact SHA c2725e63 (run 41030405967) tested the exact commit. Supply chain run (41030405749) also at c2725e63 and passed.
- **VERIFIED**.

## 9. Claim: "universal COBOL compatibility"

- Not claimed by the codebase (docs state certified subset). Capability registry explicitly lists unsupported constructs.
- **UNSUPPORTED** as a universal claim (correctly not claimed).

## 10. Documentation corrections applied

- `AUDIT_00_REPOSITORY_BASELINE.md` corrected: untracked count 57 → 328 (accurate).
- Misleading claims in prior reports (e.g., "all tests pass") corrected where they contradicted CI (C-1).
- Historical reports preserved as evidence.
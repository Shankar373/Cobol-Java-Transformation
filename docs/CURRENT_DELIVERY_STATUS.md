# Current delivery status

**Reviewed:** 2026-09-24  
**Repository revision:** `f00aa2881e70b5292588f738269acfcc8d1f6e29` plus pre-existing uncommitted changes in the user's working tree.

This status separates present implementation from the historical phase reports. It does not treat a generated source file, a successful parser pass, or a successful compile as proof of business equivalence.

## Current shape

The checkout contains a parser and semantic IR, per-program Java/Spring generation, application discovery and planning, a FastAPI/SQLite control plane, a React UI, and Docker-backed GnuCOBOL and Java execution adapters. The product no longer has an external-LLM ownership boundary; the deterministic translator is part of this project. The frontend's source-import path is ZIP-only.

## Verification performed in this review

- `tests/unit`, `tests/test_universal_modernization.py`, and `tests/test_control_plane_persistence.py`: **98 passed**.
- Docker image resolution now accepts a locally built image's immutable `sha256` image ID when no registry digest exists, while continuing to prefer registry RepoDigests. Pipeline image identities can be pinned with `SYSTEMAOPS_ORACLE_*` and `SYSTEMAOPS_{MAVEN,JAVA}_*` environment variables; focused regression tests cover ID fallback and registry-digest precedence.
- `.github/workflows/ci.yml` and `requirements-ci.txt` are prepared locally. The workflow builds both Docker images, runs the full backend/oracle pytest suite, runs frontend tests and production build, and uploads logs/JUnit artifacts. It is **not active on GitHub yet**: the GitHub integration denied branch/content writes, and the local Git remote has no available credentials.
- The prior saved `tests/verification/results_fresh2/FINAL_REPORT.md` is from 2026-09-21 and reports **0 ORACLE_MATCHED**, **17 Java compilation failures**, two parse failures, and one copybook smoke workload reaching execution. It is historical and predates `f00aa28` and today's dirty changes.
- The full pytest command initially collected an untracked root-level debug file (`test_code_lines.py`) and failed to parse it. `pytest.ini` now scopes collection to `tests/`; a fail-fast rerun reached 324 passed / 2 skipped before stopping at `TestClaimsOracleE2E.test_oracle_execution`, which could not start because the Docker oracle and candidate images were unavailable. A non-fail-fast run was stopped after entering the same runtime-dependent failures; no complete full-suite result is claimed. The untracked investigation scripts have not been deleted or modified.
- Docker is installed but its engine is not accessible in this session (`permission denied` on the Docker Engine pipe). GitHub Actions has no workflow run associated with `f00aa28`, and the available remote tools provide repository/Actions metadata rather than remote execution.
- The frontend build currently fails TypeScript checking in `frontend/src/pages/ModernizationRun.tsx` with four `unknown`-to-`ReactNode` errors. Vitest could not start because the local execution sandbox denied access while esbuild loaded the Vite config. UI tests therefore remain unverified.

## Delivery blockers

1. **Behavioral proof:** rerun the oracle-versus-generated-app pipeline against the current working tree after Docker is accessible. The saved 20-workload report is not proof for the newer code.
2. **Translator correctness and coverage:** work through real COBOL workloads, fixing each demonstrated parser/mapping/build/runtime defect and preserving evidence. No universal COBOL compatibility claim is supported.
3. **Runtime integration:** DB2, CICS TS, JES/JCL, VSAM/mainframe file semantics, EBCDIC, and site-specific dependencies need explicit adapters or an honest unsupported result; analysis/generation subsets are not those runtimes.
4. **Production packaging:** Python dependencies were previously undeclared. A minimal `requirements.txt` is now present, but a repeatable locked backend install, image supply process, durable workspaces/artifacts, supported deployment topology, backup/restore, authentication, and client handoff package are still needed.
5. **Source import:** Git URL import is declared in an API model but is not implemented. ZIP ingestion is the only implemented source path.
6. **Security/readiness:** there is no production authentication/authorization configuration, no tenant isolation, no retention/cleanup policy for uploaded COBOL and generated artifacts, and no completed dependency license inventory.

## Client information needed for acceptance

The general-purpose project can continue without client assets, but final acceptance for a real client workload needs a representative source bundle and the actual execution contract: COBOL compiler/dialect and options, copybook/search rules, CALL/load behavior, DB2 schema and SQL semantics, CICS/JCL/VSAM usage, encodings, batch inputs, expected outputs/files/return codes, volume and runtime targets, and the intended deployment environment. Credentials or production data are not needed for initial capability analysis; sanitized representative fixtures are preferable.

## Existing working-tree changes

At review start, the user's checkout already had twelve modified engine files and numerous untracked parser-investigation scripts/fixtures. They were preserved. The only new source changes in this review are `pytest.ini`, `requirements.txt`, and the refreshed README; this status report records the audited state. No files were committed or pushed.

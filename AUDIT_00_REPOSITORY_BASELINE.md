# AUDIT_00_REPOSITORY_BASELINE

## Starting state

- Branch: `codex/universal-core`
- HEAD: `c2725e63af8b7e16b533c36da9b2c859115a1989`
- Expected starting HEAD: `c2725e63af8b7e16b533c36da9b2c859115a1989`
- Match: YES
- Remote: origin `https://github.com/Shankar373/Cobol-Java-Transformation.git`
- Remote branch SHA (`origin/codex/universal-core`): `c2725e63af8b7e16b533c36da9b2c859115a1989`
- Ahead/behind local vs remote: 0 / 0
- Commit count on branch: 288
- Working tree: no staged or unstaged tracked modifications. Untracked files: 328 total, of which 322 under `test-artifacts/` and 6 at top level (`AUDIT_00_REPOSITORY_BASELINE.md`, `apply_unsupported_expression_fix.py`, `run_captruth.py`, `stage_backlog_bl155.py`, `data/control-plane.db-shm`, `data/control-plane.db-wal`). These are prior user/generated work and must be preserved (non-negotiable rule 10).
- `git ls-files data/` returns empty: no DB committed; `data/control-plane.db` and its `-shm`/`-wal` are untracked (see AUDIT_04 finding on gitignore gap).

## Environment

- Python 3.11.9, pytest 9.0.3
- OpenJDK 21 (Temurin), Maven 3.9.16
- Node 20.20.2, npm 10.8.2
- Docker 29.8.2 present
- gh CLI not installed; GitHub API access via owner token (valid as of baseline) for CI log retrieval.

## Test baseline

- Test collection: 4550 tests collected (`python -m pytest --collect-only -q`).
- Baseline full-suite run launched in background (PID 25332, started 2026-10-30T18:16:21, writing `C:\Users\bandi\AppData\Local\Temp\opencode\baseline-full.xml`); result recorded in `VALIDATION_08_FINAL_REGRESSION.md` when complete.
- Known CI failure at exact starting SHA c2725e63: `tests/transformation/test_phase7c_end_to_end.py::TestBuildAndExecution::test_docker_status_recorded` (SystemaOps CI run 41030405967) — see REMEDIATION_07_EXECUTION_LOG (fixed by making the environment-dependent assertion conditional on the Docker gate).

## Risks and discrepancies

- Large untracked `test-artifacts/` tree means `git add -A` would stage generated artifacts. Must stage only reviewed files.
- `.gitignore` does not cover `*.db-wal`/`*.db-shm` or `test-artifacts/` (AUDIT_04).
- Many prior audit/report documents claim verified results; all claims must be re-verified (Phase 5).
- Prior reports mention known issues (WSL bash launcher, Docker integration, OCESQL digest, frontend test exit, L.6.1 counts) that require reproduction.
- Baseline full-suite run in progress; do not claim completion until it finishes.

## Safe execution plan

1. Preserve all untracked user work; never reset/clean/stash/rebase/force-push.
2. Establish full-suite baseline (in progress).
3. Complete source-code forensic audit with exact file/line references (audit subagents running).
4. Perform end-to-end semantic traces and test-quality review.
5. Security and documentation claim verification.
6. Consolidate defect register.
7. Fix safely actionable defects with regression tests.
8. Final regression, pre-commit review, normal push, CI investigation.
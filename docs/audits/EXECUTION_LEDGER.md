# Execution ledger

Running record of the enterprise-alignment roadmap (`docs/audits/ENTERPRISE_ALIGNMENT_AUDIT.md`, section 5).
One row per completed unit: what shipped, the exact commit, the test and CI evidence, limitations, and what is
still open. Facts only; a unit is recorded as done only after its full CI gate passed on the pushed commit.

**Rules for every unit:** code, API, UI, documentation and tests are finished together; focused tests run
locally; one commit and one push; then the full CI pipeline runs on that exact SHA and every failure is fixed
before the next unit starts. Corpus certification (4 runtimes) runs for units that change generation,
verification or the oracle (commit message tagged `[certify]`); documentation-only or control-plane-only units
record "not applicable" with the last certified SHA whose engine tree they leave unchanged.

## Baseline

| Item | Value |
|---|---|
| `main` | `b0c1f6bb58be9b61fe0b7b94a59f945c55697ca9` (merge of PR #9; tree identical to certified candidate `967d313`) |
| Backups (pushed) | `backup/feat-phase3-coverage-pre-merge` / tag `backup-feat-phase3-coverage-pre-merge-d68331f` = `d68331f`; `backup/main-pre-merge` / tag `backup-main-pre-merge-f9dd9b9` = `f9dd9b9` |
| Audit branch | `audit/unified-main-baseline` = `b0c1f6b` |
| Implementation branch | `impl/enterprise-platform` |
| CI on `b0c1f6b` | run 41674480967 success: Docker/oracle 5,203 passed (0 skipped), hermetic 4,752 passed, gate 1,297, lint, frontend; supply chain 41674480813 success |
| Certification on `b0c1f6b` | run 41675939896 (dispatch, headSha verified): 4 runtimes x 44/54 VERIFIED, 9 refused, 1 UNAVAILABLE, independent AGREE 44/44, CERTIFIED |

## Operational notes

- Dependabot PRs #10-#27 are open and unmerged (triage in roadmap unit 3). On 2026-11-03 their 67 queued/running
  workflow runs were cancelled (owner-approved) because they starved the baseline certification of runners; they
  can be re-run per PR.
- The numeric-edited PIC work (roadmap unit 9) is held, uncommitted, on `feat/phase3-coverage` until authorized.

## Owner decisions still open

Identity provider and roles; evidence-signing keys and retention/encryption policy; target databases beyond DB2
and PostgreSQL and hosting for decomposed services; IBM CICS/IMS entitlement (or acceptance of
`SIMULATOR_VERIFIED`); whether Python/Java/Ubuntu runtime pins may move; authorization to merge the numeric-edited
PIC work.

## Units

| Unit | Status | Commit | CI / certification | Tests | Limitations / notes |
|---|---|---|---|---|---|
| 0. Enterprise alignment audit, honest README, ledger | in progress | - | - | docs only | README rewritten; previous README archived at `docs/archive/README_2026-11-03.md` |

# Active engineering checkpoint

Durable state so no progress depends on conversational memory. Updated at each milestone; the last update is at the foot.

## Current position

- Branch `impl/enterprise-platform`; first code commit `a3ad2f0230ebea9a24ff3837c7a9aaa61ea48896` (parent `251af829bce92012d25e82856ddf7983ee614133`); review fixes follow in the next commit, which carries the final-code certification.
- `main` untouched at `b0c1f6bb58be9b61fe0b7b94a59f945c55697ca9`. No force-push. The old `feat/phase3-coverage` checkout was discarded on the
  owner's instruction on 2026-11-12 (backup `C:/pwv/backup-phase3-dirty-2026-11-12/`, outside the repo).
- Phase: Milestones 0-3 and 5 done; Milestone 4 (CI, supply chain, exact-commit corpus certification on `a3ad2f0`) running;
  Milestone 6 (independent review, final report) in progress.

## Harness and ECC (Milestone 0)

- Harness: Claude Code. ECC is already installed and exposed through the harness as skills, agents and commands; it was
  not reinstalled and no settings were changed. ECC is a development tool only; no ECC, Claude or other agent package is a
  SystemaOps dependency (re-scan 2026-11-13: none in `engine/`, `api/`, `scripts/`, `tools/`, requirement locks, `frontend/package.json`).
- Available and relevant (from the harness listing): skills `plan`, `tdd-workflow`, `verification-loop`, `git-workflow`,
  `strategic-compact`, `context-budget`, `architecture-decision-records`; agents `planner`, `architect`, `python-reviewer`,
  `java-reviewer`, `security-reviewer`, `tdd-guide`, `database-reviewer`, `docs-lookup`, `code-reviewer`,
  `build-error-resolver`. Not listed in this session: `python-patterns`, `java-coding-standards`, `security-review`
  (skill), `database-migrations`, `documentation-lookup`, `plan-orchestrate`.
- Actually used: two subagents (one research agent for the external sources, one `python-reviewer` for the independent
  review). The TDD discipline (failing test first, then change) was followed by hand; the `tdd-workflow` and
  `verification-loop` skills were **not** loaded and no ECC command was run. No token savings were measured.

## Done in this session (all in `a3ad2f0` unless noted)

- G-14 closed: file ownership from FILE SECTION only; READ/WRITE/REWRITE refusals named (`cobol_parser.py` `_owning_file`).
- G-15 closed: `ApplicationGenerator._select_entrypoint`, no first-program fallback.
- G-17 closed: `tools/certification_summary.py`, committed `docs/reports/evidence/certification/certification_summary.json`.
- Stage 1: `engine/vsam/` (model, collation, reconciliation) with 37 tests.
- Tests that pinned the removed guesses now assert refusals (listed in `EXACT_HEAD_ENTERPRISE_BASELINE.md`); none skipped or weakened.
- Documents: research report, four stage plans, gap matrix, gap register (G-14/15/17 closed; G-22..G-25 opened), capability and semantic proof
  matrix update notes, README pointers, docs index.
- Docs-commit-only change after `a3ad2f0`: one comment in `engine/transformation/contracts.py` (no longer suggests LLM producers).

## Verification so far

- Local: ruff clean (pinned 0.14.0), mypy ratchet clean (209 known), dependency map current, hermetic suite run (5 failures found, all tests
  that pinned the removed guesses, now updated; focused reruns 63 passed), 108 focused gate tests passed. Docker lanes and the full corpus
  are CI-only.
- CI on `a3ad2f0`: see `EXACT_HEAD_ENTERPRISE_BASELINE.md` (filled in only from runs observed to finish).

## Independent review (python-reviewer subagent over 251af82..a3ad2f0)

Reproduced and fixed (regression tests added for each): READ bound a middle 01 of a multi-record FD (now the FD's buffer record, as
elsewhere); the "declared under more than one FD" message matched unrelated names by prefix (now matches only the rename pass's
`NAME-X...` form); a self-CALL hid the real entrypoint root; `reconcile_migration` reported RECONCILED for a reordered sequential
destination, with key checks skipped, and with caller-asserted rejections it could not justify (now FAILED / RECONCILED_PARTIAL);
a rejected first occurrence made a kept same-key record a false failure; a key byte with no counterpart in the other encoding raised
instead of failing; the summary check ignored missing fixture directories, an empty `not_proven` and toolchain edits, and the README
check passed with zero claims.

Not reproducible as stated: "one duplicate keeps the plain name after renaming" (all duplicates are renamed, the first to `NAME-X`).
Not detectable offline by design: edits to the asserted `commit_sha` / `workflow_run_id` (no evidence file records them); the summary
now says to verify them with `gh run view`. Not changed: the plan-level entry metadata (G-24) and the destination key `kind` check.

## Open items

G-22 `EXEC CICS` inner verbs read as file verbs; G-23 discovery owner map; G-24 plan-level entry metadata fallback; G-25 CI does not
emit the summary; G-13 (phase5 evidence files), G-16; owner/external G-01..G-03, G-07; roadmap G-06, G-08, G-09.

## Next exact action

1. When CI, supply chain and certification on `a3ad2f0` finish, record run ids and results in `EXACT_HEAD_ENTERPRISE_BASELINE.md`
   and the final report; apply any real defect from the independent review.
2. Then: field-aware migration converter (Stage 1 next slice), fix G-22, emit the summary from CI (G-25).

Last updated: 2026-11-13, after pushing `a3ad2f0`, before CI completion.

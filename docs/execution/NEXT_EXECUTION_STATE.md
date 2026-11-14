# Next Execution State

Updated 2026-11-14.

## Branches (three lines, do not confuse them)

| Branch | Head | Meaning |
|---|---|---|
| `stage1/vsam-completion` (PR #28, open, unmerged) | `c962efe` | Stage 1 work. CI 43551424171, supply chain 43551424167 and corpus certification 43551424219 all succeeded on this exact SHA. The `exact-run-certification-summary` artifact names `c962efe`, run 43551424219, `certified: true`. |
| `codex/autonomous-stage1-enterprise-completion` | `6522894` | My original line from `d68331f` (streaming VSAM engine, API, runtime disk index, object store). CI 43566449025 on this SHA: capability-truth, hermetic, lint and frontend succeeded; the Docker lane was still running at the last check. |
| `codex/enterprise-on-stage1` | `ce44b09` | `stage1/vsam-completion` plus a merge of my line. One conflict (generated dependency map, regenerated). My ADR was renumbered 0011 to 0012 because Stage 1 already has `ADR-0011`. Test fixtures now send the required `target_runtime`. 245 focused tests pass locally. CI runs 43568065910 (CI), 43568065899 (certification), 43568065926 (supply chain) are in progress; nothing is certified until they finish. |

`main` is untouched. No PR has been merged.

## Next actions

1. Wait for CI on `ce44b09`. Fix any failure at its root.
2. Reconcile Stage 1 docs against the merged state: `docs/FINAL_GAP_REGISTER.md` G-28 (RRDS, ESDS and variable files now have a streaming path with GnuCOBOL parity; alternate index structures and ESDS RBA are still not built), `STAGE_1_FINAL_COMPLETION_REPORT.md` limits (synchronous, in-memory) and the PR #28 description. Only claim what the merged tests prove.
3. Write `docs/vsam/STAGE_1_FINAL_COMPLETION_REPORT.md` equivalent updates and the final report `docs/execution/MASTER_EXECUTION_FINAL_REPORT.md`.
4. Phases 1 to 4 and 7: S3-compatible adapter (no local verification possible; MinIO service container in CI), PostgreSQL store, Redis/Celery workers, GitHub ingestion, multipart ZIP, scalable inventory, hardening.

## Blockers

- No IBM environment: no `IBM_RUNTIME_VERIFIED` claim is possible.
- Local Docker cannot pull MinIO, Redis or PostgreSQL images anonymously; Windows long paths block `pip install moto`. Use CI service containers (free).
- The Windows host has two known local failures (Git Bash grep idiom test, javac cp1252 on a template comment); neither is caused by this work.
- `winget upgrade Anthropic.ClaudeCode` failed (access denied on the running `claude.exe`); rerun it after the session.

## Certification evidence for `codex/enterprise-on-stage1`

Corpus certification run 43603385699 (manual dispatch, no rule changed) on `ce8ce00edca8671c8b9a8bb74579dd3e447f83a3`: four runtime jobs and the summary job succeeded. The `exact-run-certification-summary` artifact says `certified: true`, commit `ce8ce00edca8671c8b9a8bb74579dd3e447f83a3`, run 43603385699, 55 fixture applications. It is self-attested and has no IBM runtime evidence. Supply chain 43603382150 succeeded on the same SHA. The CI run 43603382116 on the same SHA was still in progress when this was written; `413a969` (code identical to `ce8ce00`) had CI 43571365488 fully green.

## Current work

Branch `codex/stage1-alt-key-browsing` (from `ce8ce00`, nothing committed yet): Phase 1 of the Stage 1 prompt, alternate-key `START` and `READ NEXT`. The ledger recorded about 5 percent mismatches against GnuCOBOL at 150 programs; on this branch seeds 501 (40 programs) and 502 (150) had 0 mismatches. Seeds 503 to 505 were killed by the low-memory guard before finishing, so the gate that refuses browsing stays in place until a wider sweep is clean.

# Next enterprise engineering sprint - report (2026-11-13)

Branch `impl/enterprise-platform`; the sprint started at `f39d1a64de88e15bdfb4a9810909ff93518d57cb`. `main` (`b0c1f6bb`) was not touched.
CI and certification fields marked PENDING are filled in by the exact-head baseline report only from runs observed to finish:
[EXACT_HEAD_ENTERPRISE_BASELINE.md](EXACT_HEAD_ENTERPRISE_BASELINE.md). Checkpoint and next action: [ACTIVE_ENGINEERING_CHECKPOINT.md](ACTIVE_ENGINEERING_CHECKPOINT.md).

## 1. ECC

| Question | Answer |
|---|---|
| Harness | Claude Code. ECC is installed there as skills (`~/.claude/skills`, 56 skill directories), agents (`~/.claude/agents`, 71 files) and commands |
| Reinstalled? Duplicate skills? | No and no. Nothing was installed, no settings were changed, no skill directory was created |
| Skills discovered that are relevant | `tdd-workflow`, `verification-loop`, `architecture-decision-records`, `git-workflow`, `strategic-compact`, `context-budget` |
| Skills loaded and used | `tdd-workflow` (RED then GREEN for every fix; compile-time RED accepted only where the module did not yet exist), `architecture-decision-records` (ADR-0009, written as PROPOSED in the repo's existing `docs/decisions/` register instead of creating `docs/adr/`, because the skill asks before creating that directory and the repo already has a convention), `verification-loop` (types, lint, dependency map, full hermetic suite, security grep, diff review - it caught an unused import and three type errors before CI) |
| Skills not loaded | `git-workflow` (git safety was followed by hand), `strategic-compact`, `context-budget` (no compaction was needed; the context meter was not consulted) |
| Not present in this installation | `python-patterns`, `java-coding-standards`, `security-review` (as a skill), `database-migrations`, `documentation-lookup`, `plan-orchestrate` (a `plan` command exists, not a skill directory) |
| Reviewer agents used | `python-reviewer` (independent code review) and `security-reviewer` (security review), read-only, on separate scopes; one `general-purpose` agent earlier for external-source research. `planner`, `architect`, `java-reviewer`, `tdd-guide` and `database-reviewer` were not used |
| Token savings measured? | **Not measured.** Nothing here claims a saving |

## 2. What was fixed or built

| Item | Result |
|---|---|
| G-14, G-15, G-17 (preserved) | regression tests still pass; `-REC`/`-FILE` guess and first-program fallback not reintroduced |
| G-22 `EXEC CICS` parsed as file verbs | RESOLVED: one named refused region; trailing text after `END-EXEC` is an error; an `EXEC CICS` inside an inline `IF` is named; CICS stays UNSUPPORTED |
| G-23 discovery owner map | RESOLVED: shared `file_ownership.py`, every 01 is an owner key, ambiguity named, no last-wins |
| G-24 planner entrypoint | RESOLVED: planner and generator share `entrypoint.py`; unresolved plans carry no entry and the pipeline refuses them; the pipeline also refuses if the generated entry differs from the plan's. A real bug was found on the way: the old planner picked the callee of a MAIN->CALC chain |
| G-25 exact-run certification summary | IMPLEMENTED, first CI proof PENDING: runtime jobs write identity (SHA, run id, **run attempt**) and keep image provenance and the oracle image id; a `summarize` job verifies all four runtimes and uploads the summary as an artifact; identity only from the environment; the summary says its evidence is self-attested |
| G-16 stale comments | RESOLVED (comment-only) |
| G-21 image-pin mismatch | RESOLVED for the Spring Boot lane: the reason is recorded and reported; the pin is unchanged |
| Stage 1 | layout derivation from the COBOL record description (ADR-0009), layout-driven migration with restart and report, GnuCOBOL differential in two dialects; see section 4 |

## 3. Review findings and what was done

Independent code review (`python-reviewer`): group-level `USAGE`/`SIGN` silently ignored by the layout (**fixed: refused**, `GROUP_CLAUSE_INHERITED`);
hyphenated data names read as `SYNC` / `SEPARATE` / `JUST` (**fixed**, boundary-safe regexes); CICS text after `END-EXEC` silently dropped and
CICS inside an inline `IF` unnamed (**fixed**); planner and generator candidate sets could differ (**fixed**: pipeline agreement check); weak
summary checks - `UNCERTIFIED` accepted, run attempt not compared, digests only checked for non-empty, malformed evidence crashing the aggregator
(**fixed**); duplicate `FILLER` paths and repeated diagnostics (**fixed**). Security review (`security-reviewer`): unbounded `OCCURS` expansion
(**fixed**: `MAX_LAYOUT_FIELDS`, `MAX_RECORD_BYTES`, checked before any field exists); `run_attempt` (**fixed**); no finding in the workflow triggers,
permissions, pinning, script injection or artifact path handling. Residual, stated plainly: the certification evidence is produced and consumed by
the same workflow, so it detects mix-ups but is not tamper-proof or signed (G-03).

Two defects of mine were found by verification, not by review: an unused import and three mypy errors (`verification-loop`), and a test
(`test_unavailable_build_image_is_flagged_infrastructure`) that builds the adapter without `__init__` (fixed with a class-level default, not by
touching the test).

## 4. Stage 1 status

| Piece | Status | Evidence |
|---|---|---|
| Semantic model | IMPLEMENTED_NOT_RUNTIME_VERIFIED | deterministic tests |
| Layout derivation | PARTIAL | `GNUCOBOL_DIFFERENTIAL`: records written by GnuCOBOL (`-std=default` and `-std=ibm`) decoded at the derived offsets and lengths, 6 tests |
| REDEFINES | supported only with an explicit selection of the active alternative; otherwise refused (`OVERLAY_UNSELECTED`), never the first by declaration order |
| OCCURS | fixed and nested fixed expanded; `OCCURS DEPENDING ON` refused; expansion capped |
| Conversion and restart | IMPLEMENTED_NOT_RUNTIME_VERIFIED; resume refuses a torn or altered partial output |
| Reconciliation | IMPLEMENTED_NOT_RUNTIME_VERIFIED; `RECONCILED` is the only success; `RECONCILED_PARTIAL`, `FAILED`, `REFUSED`, `INTERRUPTED` are not |
| GnuCOBOL comparison | layout bytes and migration of GnuCOBOL-written records: done. KSDS/ESDS/RRDS runtime behaviour against GnuCOBOL: not part of this sprint |
| Not done | variable-length (RDW) conversion (G-28), RBA/RRN, alternate-index migration, `SYNCHRONIZED`, COMP-5 byte-order conversion (G-27), `COPY` inside an FD (G-26) |
| Still needs IBM | everything above is GnuCOBOL or deterministic evidence; no Enterprise COBOL output has been read; ordering above ASCII keys, VSAM storage behaviour, ESDS/RRDS semantics |

One correction to earlier claims: the byte *encoding* of COMP/COMP-3 fields had been described as covered by the value fixtures. Those compare
values only; the capability row is now PARTIAL and the bytes are covered by the differential above.

## 5. Enterprise scope (unchanged unless stated)

JCL: partial, documented semantics, not JES. Db2: controlled portable SQL, not Db2 for z/OS. CICS, IMS, MQ: simulator-verified only; `EXEC CICS`
refused and now named precisely. Git ingestion: not implemented (G-06). Security: not production-grade (G-01 docker.sock, G-02 static tokens, G-05
open API outside production). Durable jobs: no (SQLite, daemon threads, G-04). Artifacts: hash-sealed, not signed (G-03). LLM dependencies: none
(re-scan this sprint: no LLM or agent package in `engine/`, `api/`, `scripts/`, `tools/`, the requirement locks or `frontend/package.json`).

## 6. Verification

| Check | Result |
|---|---|
| ruff 0.14.0 (pinned), mypy ratchet (209 known), dependency map | clean on the final code |
| Hermetic suite (Windows), final code | see the baseline report (run completed after this text was written) |
| Docker-lane tests relevant to the change, `RUN_DOCKER_TESTS=1` | 49 passed (integration wiring, entry resolution, GnuCOBOL layout differential) |
| CI, supply chain, four-runtime certification on the final head | PENDING - [EXACT_HEAD_ENTERPRISE_BASELINE.md](EXACT_HEAD_ENTERPRISE_BASELINE.md) |

## 7. Verdict

**CONTROLLED_PILOT_READY_WITH_LIMITATIONS.** Not production: G-01 to G-05 stand. The verdict does not change with green CI.

Next highest-value action: run the first real exact-run summary (G-25 proof) and then close G-26 (`COPY` inside an FD), which blocks ownership and
layout for a very common source shape.

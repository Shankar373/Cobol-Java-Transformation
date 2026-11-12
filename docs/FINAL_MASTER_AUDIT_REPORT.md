# Final master audit report (2026-11-12)

Branch `impl/enterprise-platform`, audited base `4c11615269dc8d1fe2b33231d677508278d3d552` (verified as the real HEAD
and equal to `origin/impl/enterprise-platform`; clean tree). Companions:
[FINAL_GAP_REGISTER.md](FINAL_GAP_REGISTER.md), [FINAL_DOCUMENTATION_COVERAGE.md](FINAL_DOCUMENTATION_COVERAGE.md),
[PROTOTYPE_HANDOFF.md](PROTOTYPE_HANDOFF.md).

**Verdict: READY FOR CONTROLLED PILOT - DOCUMENTED LIMITATIONS.** Not "ready for engineering handoff": production
blockers (G-01 to G-04) and open in-scope items remain.

## A. Baseline and repository forensics

- The session's checkout was `feat/phase3-coverage` (`d68331f`) with 23 modified and 10 untracked paths, not the working
  branch. It was left untouched; the audit ran in the `impl/enterprise-platform` worktree (`C:/pwv/impl`).
- That dirty tree's numeric-edited source, tests, oracle truth and fuzz files are **byte-identical** to the copies committed
  on impl (`b756493`), so no work is at risk; one fixture (`EDITED.cob`) differs. The rest is an older line of CI/doc edits,
  regenerated evidence jsonl, a tsbuildinfo cache and three loose helper scripts. The owner approved discarding it on 2026-11-12 after the backup was re-verified; it is now clean (G-18 closed).
- impl worktree: clean and in sync with its remote; ignored files are caches and build output only. 1179 tracked files, 174
  Markdown. A pattern scan for AWS/GitHub/OpenAI-style keys and private-key headers found nothing, and no databases, logs,
  `.env` files or build output are tracked (`.env.production.example` and `test-artifacts/docker-image-provenance.json`
  are deliberate).
- `integration/impl-numeric-edited` is an ancestor of impl; no work is stranded on another branch that impl lacks.

## B-D. Architecture, scope and proof (from code, not from docs)

Full table: [FINAL_DOCUMENTATION_COVERAGE.md](FINAL_DOCUMENTATION_COVERAGE.md).

- **DIFFERENTIALLY VERIFIED against GnuCOBOL 3.1.2 (bounded subset, fail-closed outside it):** parser, transformation, Java
  generation, copybooks, static CALL, sequential/indexed/relative files, comparator, verdict, and the four runtimes
  (plain_java, spring_boot, quarkus and micronaut in command mode). Corpus: 45/55 VERIFIED per runtime, 9 refused by name,
  1 UNAVAILABLE, independent re-check AGREE 45/45 (CI run 43083693133).
- **TESTED only:** ZIP ingestion, discovery, capability analysis, planning, FastAPI, React, Docker execution, evidence
  integrity (hash seal, no signature), deployment, backup, CI/supply chain.
- **PARTIAL:** VSAM (no engine), JCL (step programs only), DB2 (OCESQL + PostgreSQL 14, not DB2), persistence (SQLite),
  background jobs (daemon threads), RBAC and security.
- **SIMULATOR VERIFIED, not wired into the product:** CICS, IMS, MQ.
- **NOT IMPLEMENTED:** Git ingestion.
- **No LLM anywhere:** nothing in code or requirements; three comments mention the word only.
- **Fallbacks:** most "fallback/silently" hits are fail-closed statements. Real heuristics are recorded as G-14 (REC/FILE
  binding) and G-15 (first-program entry); an image-identity fallback fails closed on mismatch.
- Stage status: Stage 1 PARTIAL, Stage 2 PARTIAL, Stage 3 SIMULATOR VERIFIED only, Stage 4 NOT IMPLEMENTED. No stage is
  marked complete because a parser or simulator exists.

## E. Security

HIGH: docker.sock mounted in the API container (G-01); static bearer tokens only (G-02). MEDIUM: no signing (G-03),
SQLite and non-durable jobs (G-04), open API without a token outside production (G-05), parser REC/FILE heuristic (G-14).
Clean: no `shell=True`, `os.system`, `eval`, `pickle`, `yaml.load` or `verify=False` in engine/api/scripts; no hardcoded
credentials; production auth refuses trivial tokens. Every HIGH/MEDIUM item needs owner credentials, an identity provider
or infrastructure, so none was changed here; the blockers are in the register and `docs/audits/OWNER_DECISIONS.md`.

## F-I. Repository and documentation actions

| Action | Detail |
|---|---|
| Contradictions fixed | README rows for JCL, DB2/SQL, CICS/IMS/MQ; superseded-row notes in CAPABILITY_MATRIX (alternate key, JCL, SQL) and SEMANTIC_PROOF_MATRIX (alternate key) |
| Stale pointers fixed | BL-009 note in CONTRACT_STATUS, KNOWN_ISSUES, PROJECT_STATUS, SYSTEMAOPS_PRODUCT_STATUS, VERIFICATION_STATUS now names PROTOTYPE_HANDOFF and EXECUTION_LEDGER |
| Banners added | PHASE5A_FORENSIC_VERIFICATION, PHASE5D1_COMPLETION_REPORT, PHASE5E_OPEN_SOURCE_TRANSFORMER_EVALUATION, PHASE5F1/5F2_HARDCODED_SEMANTICS_AUDIT, PHASE1C_FINAL_VALIDATION_REPORT, opencode.md, MASTER_IMPLEMENTATION_README.md |
| Moved (1) | `SYSTEMAOPS_COMPLETE_READ_ONLY_AUDIT.md` to `docs/archive/`; its one reference in FORENSIC_REMEDIATION_REPORT is annotated |
| Deleted (0) | None. The two proposed duplicates (`docs/reports/archive/EXECUTION_LEDGER.md`, `TRUSTED_ARTIFACT_SIGNING_PROPOSAL.md`) diverge from their live counterparts, so unique content could not be proven preserved. Test-gated docs were not restructured |
| Links | 0 broken relative links across 174 files (scripted) |
| Classification | about 12 current authoritative, 14 operational, 17 contract/spec, 30 audit evidence, 90 historical, 4 duplicate candidates, 3 obsolete candidates, 0 empty |

Not done: `PROJECT_LICENSE_DECISION.md` was not moved (7 references, churn without value); the `docs/PHASE*` reports were
bannered rather than relocated; the README was corrected rather than rewritten, because it already has the requested
structure and its headline claims were verified against CI.

## J. Validation actually run

- Audited code base `4c11615`, all required workflows success: CI 43083693262, corpus certification 43083693133 (four
  runtimes, 45/55 VERIFIED, AGREE 45/45), supply chain 43083693218.
- Audit commit `f0fb581` (docs-only on `4c11615`): SystemaOps CI [43143318343](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43143318343) success, 10/10 jobs (incl.
  the Windows hermetic suite and Windows capability gate); supply chain [43143318364](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43143318364) success; corpus
  certification [43143318348](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43143318348) **skipped by design** - `certification.yml:43` runs only on
  `workflow_dispatch` or a `[certify]` commit message, and this commit carries neither. It was therefore dispatched manually
  on the exact HEAD: [43172901037](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43172901037) success, `quarkus`, `micronaut`, `plain_java`, `spring_boot` each
  55 apps, 45 VERIFIED, 9 refused by name (None), 1 UNAVAILABLE, independent AGREE 45/45, CERTIFIED. That is a fresh
  certification of `f0fb581`'s code (byte-identical engine to `4c11615`), not a carry-over.
- Local: `test_silent_loss_registry`, `test_third_party_notices`, `test_ci_deployment_security`, `test_lint_baseline` -
  21 passed after the documentation edits. A full hermetic local run was started and not awaited (about 14 % per 20
  minutes); the project's convention is CI for full suites.
- Not run locally: ruff, mypy (not installed in the available venvs), frontend build/tests, Docker corpus, production
  compose staging, backup/restore, container scan. For those, the CI results above on `f0fb581` are the evidence (lint, type
  check, coverage floor, frontend build and the Docker suite are CI jobs; backup/restore and staging are covered only by
  their static contract tests and the earlier staging evidence in the handoff, not rerun).

## K-N. Remaining work

Open in scope: G-13, G-14, G-15, G-16, G-17. Owner/external: G-01 to G-03, G-07. Roadmap: G-06, G-08, G-09.
Recommended next phase: owner decisions on G-01 and G-02, then durable jobs and a real identity provider, then Stage 1
VSAM depth.

# Final documentation coverage and completion metrics (2026-11-12 audit)

Source of the module list and statuses: code inspection at `4c11615` (source paths, test file counts by keyword, evidence
files, CI logs). Test counts are keyword upper bounds, not executed counts. The scores below are the auditor's judgement
from that evidence, with the weights stated, and are **not** a measurement; they exist to stop a high documentation score
from hiding missing implementation or security.

## Documentation coverage

Applicable implemented capabilities: 37 modules (38 audited, minus Git ingestion, which is NOT IMPLEMENTED and so not
applicable). "Complete" = a current document states the behaviour, its limits and the proving test/evidence. "Incomplete" =
mentioned in a matrix row or shared document without its own limits/operations description.

| Class | Count | Modules |
|---|---|---|
| Complete | 30 | Parser, IR, copybooks, CALL, capability analysis, planning, transformation, Java generation, plain Java, Spring Boot, sequential/indexed/relative files, VSAM subset, JCL, DB2, CICS, IMS, MQ, Docker execution, GnuCOBOL oracle, comparator, verdict, FastAPI, React frontend, deployment, backup/recovery, CI/supply chain, ZIP ingestion, discovery |
| Incomplete | 7 | Quarkus and Micronaut (shared `RUNTIME_ADAPTERS.md`, command mode only), evidence integrity (its doc is the superseded signing proposal), persistence, background jobs, RBAC (only `OWNER_DECISIONS.md`), security (partial) |
| No documentation | 0 | |

**Documentation coverage = 30 / 37 = 81 % strict; 33.5 / 37 = 90.5 % counting incomplete as half.** Documented but
unimplemented roadmap capabilities: 1 (Git ingestion, docstring only; the UI correctly hides it) plus the Stage 3/4
items, which are labelled roadmap. Contradictory or stale documents found: 5 contradictions (JCL, DB2, alternate key,
corpus counts, SEARCH ALL comments) and 5 stale status pointers (BL-009) plus 6 unbannered historical reports; the doc contradictions
(G-10), pointers (G-11) and banners (G-12) are corrected in this audit; the corpus-evidence refresh (G-13) and the stale
SEARCH ALL code comments (G-16) remain open.

## Completion metrics

Weights (sum 100): implementation 20, automated tests 15, differential verification 20, documentation 5, architecture 10,
integration 10, security readiness 10, production readiness 10.

| Scope | Impl | Tests | Diff | Docs | Arch | Integ | Sec | Prod | Weighted |
|---|---|---|---|---|---|---|---|---|---|
| A. Certified subset (batch COBOL, seq/indexed/relative, 4 runtimes, ZIP, oracle, verdict, API/UI) | .80 | .85 | .80 | .80 | .75 | .80 | .55 | .45 | **74** |
| Stage 1 COBOL/VSAM | .65 | .75 | .60 | .75 | .70 | .65 | .50 | .40 | **62** |
| Stage 2 JCL/DB2 | .50 | .60 | .30 | .60 | .60 | .35 | .50 | .30 | **46** |
| Stage 3 CICS/IMS/MQ | .25 | .50 | .10 | .50 | .40 | .10 | .30 | .05 | **25** |
| Stage 4 dependency elimination | .30 | .50 | .00 | .50 | .40 | .30 | .30 | .10 | **27** |

Full enterprise roadmap, stage weights 40/25/20/15: 0.40x62 + 0.25x46 + 0.20x25 + 0.15x27 = **about 45 %**.

What the numbers mean: 74 describes how complete the product is against what it *claims to certify* (a bounded
GnuCOBOL-verified subset); it is not COBOL coverage. Differential verification in the certified subset is 45 of 55
corpus applications VERIFIED per runtime (9 refused by name, 1 UNAVAILABLE), each independently re-checked (45/45 AGREE)
on four runtimes (CI 43083693133). Security readiness ~55 % and production readiness ~45 % are capped by the docker.sock
mount, static tokens, SQLite, non-durable jobs and the absence of signing. **Production readiness: NOT READY.**

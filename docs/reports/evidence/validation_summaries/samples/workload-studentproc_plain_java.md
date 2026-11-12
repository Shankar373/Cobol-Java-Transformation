# Validation summary - run-0e84775193de

Target runtime: `plain_java` | Verdict: `UNAVAILABLE` | Overall pass: **NO**

| Check | Result | Basis |
|---|---|---|
| Conversion | **SUCCESS** | transformation reported success |
| Compilation | **FAIL** | build did not complete (termination=nonzero_exit, exit=1); a build failure is not execution evidence; JDK: openjdk version "21.0.12.1" 2026-08-18 LTS |
| Runtime | **NOT_RUN** | candidate never executed |
| Business equivalence | **NOT_EVALUATED** | the candidate did not build or run, so there is no behaviour to compare |

Unsupported constructs: **0**

Warnings: **2**
- 1 comparison check(s) unavailable
- evidence integrity validation did not pass for this run

Not proven:
- No IBM runtime evidence: the only reference is GnuCOBOL 3.1.2 (OCESQL + PostgreSQL 14 for SQL).
- Equivalence is shown only for the recorded comparison input, not for all inputs.
- REST/HTTP behaviour of a generated application is not separately verified.

Reference: GnuCOBOL 3.1.2 (deterministic comparison; no LLM, no IBM runtime)

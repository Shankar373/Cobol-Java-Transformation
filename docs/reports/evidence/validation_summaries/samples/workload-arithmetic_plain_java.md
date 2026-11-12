# Validation summary - run-0ad4aeacef35

Target runtime: `plain_java` | Verdict: `VERIFIED` | Overall pass: **YES**

| Check | Result | Basis |
|---|---|---|
| Conversion | **SUCCESS** | transformation reported success |
| Compilation | **PASS** | a built candidate was executed (compile-only evidence is absent); JDK: openjdk version "21.0.12.1" 2026-08-18 LTS |
| Runtime | **PASS** | candidate executed to completion |
| Business equivalence | **PASS** | all comparators MATCH on the recorded input |

Unsupported constructs: **0**

Warnings: **0**

Not proven:
- No IBM runtime evidence: the only reference is GnuCOBOL 3.1.2 (OCESQL + PostgreSQL 14 for SQL).
- Equivalence is shown only for the recorded comparison input, not for all inputs.
- REST/HTTP behaviour of a generated application is not separately verified.

Reference: GnuCOBOL 3.1.2 (deterministic comparison; no LLM, no IBM runtime)

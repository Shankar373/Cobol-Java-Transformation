# Remediation Matrix

Baseline: 90efdca6c9da3e36888c78f8c3b88757dbcc15f3

| Priority | Area | Required action | Exit evidence |
|---|---|---|---|
| P0 | Capability truth | Reconcile classifications with actual semantic/runtime support | No contradictions + targeted tests |
| P0 | Numeric semantics | Harden PIC/sign/V/COMP/COMP-3/scale/rounding/overflow | COBOL-vs-Java differential tests |
| P1 | Planning | Enforce transformable copybooks and executable entrypoint selection | Planner contract tests |
| P1 | CALL | Expand parameter modes and multi-program proof | End-to-end call-chain tests |
| P1 | Evidence | Cover every production verdict route | Route coverage + tamper/replay tests |
| P1 | Persistence | Replace unsafe serialization and add schema/version migration | Security + migration tests |
| P1 | API security | Authentication, authorization, isolation, audit and rate limiting | Security/integration suite |
| P1 | Enterprise runtime | Define/prove JCL/CICS/DB2/file boundaries | Runtime-specific evidence |
| P2 | CI | Add quality, security, mutation and contract gates | CI policy checks |
| P2 | Documentation | Synchronize current docs with executable baseline | Documentation consistency check |

Every remediation must improve implementation or evidence. Do not solve a finding by weakening
tests or capability labels. Preserve the green baseline.

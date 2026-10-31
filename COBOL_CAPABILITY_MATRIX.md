# COBOL_CAPABILITY_MATRIX

- Report date: 2026-10-31
- Branch: codex/universal-core

Capability levels: SUPPORTED, PARTIAL, UNSUPPORTED, UNAVAILABLE, UNKNOWN.

| Construct | Parser | IR | Mapping | Generation | Runtime | Oracle | Notes |
|---|---|---|---|---|---|---|---|
| MOVE | yes | yes | yes | yes | yes | yes | |
| COMPUTE/ADD/SUBTRACT/MULTIPLY/DIVIDE | yes | yes | yes | yes | yes | yes | |
| IF/ELSE | yes | yes | yes | yes | yes | yes | |
| EVALUATE | yes | yes | yes | yes | yes | yes | |
| PERFORM (basic) | yes | yes | yes | yes | yes | yes | PERFORM TEST AFTER / VARYING decimal edge cases partial (S-10, S-11) |
| GO TO | yes | yes | comment-only | n/a | n/a | n/a | Classified UNSUPPORTED (no Java control-flow mapping) |
| CALL | yes | yes | yes | yes | yes | partial | |
| File I/O | yes | yes | yes | yes | yes | yes | |
| SQL/DB2 | yes | yes | partial | partial | yes | partial | |
| CICS | yes | yes | partial | partial | yes | partial | |

Source of truth for exact capability strings: engine/transformation/semantic_capability.py and capability analyzer. This matrix is a summary.
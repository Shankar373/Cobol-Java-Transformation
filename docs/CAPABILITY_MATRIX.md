# Current Capability Matrix

This is an implementation and evidence matrix, not a language-completeness claim.

| Capability | Parsed/Modeled | Transform path | Execution proof | Current claim |
|---|---:|---:|---:|---|
| DISPLAY | Yes | Yes | Tested subset | Supported subset |
| STOP RUN | Yes | Yes | Tested | Supported subset |
| MOVE | Yes | Yes | Tested | Supported subset |
| ADD/SUBTRACT/MULTIPLY | Yes | Yes | Tested | Supported subset |
| DIVIDE/COMPUTE | Yes | Yes | Targeted | Supported subset; precision edges remain |
| IF/ELSE | Yes | Yes | Tested | Supported subset |
| PERFORM | Yes | Yes | Tested | Supported subset |
| PERFORM VARYING | Yes | Partial | Partial | Partial |
| EVALUATE | Yes | Yes/partial | Targeted | Partial pending broader evidence |
| STRING/UNSTRING | Yes | Yes/partial | Targeted | Partial pending broader evidence |
| CALL | Yes | Yes | Partial | Partial |
| Sequential files | Yes | Yes | Tested subset | Partial-to-supported subset |
| Indexed/relative files | Partial | Partial | Limited | Not certified |
| Copybooks | Yes | Yes | Partial | Partial |
| JCL | Modeled | Partial | No broad runtime proof | Not certified |
| CICS | Modeled | Partial | No broad runtime proof | Not certified |
| DB2/SQL | Modeled | Partial | No DB2 runtime proof | Not certified |

## Capability rule

A construct may only be labeled supported when the implementation chain and required runtime
evidence justify that label. Parser recognition alone is insufficient.

The capability analyzer contains manually maintained statement classifications. These must
remain reconciled with parser, IR, mapping, generator, runtime and evidence behavior.

## Evidence ladder

recognized -> parsed -> IR -> capability -> mapped -> generated -> compiled -> executed ->
oracle executed -> compared -> mutation verified -> end-to-end verified

Current proof is strong for a subset, not every row.

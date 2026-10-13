# Current Capability Matrix

This is an implementation and evidence matrix, not a language-completeness claim.

| Capability | Parsed/Modeled | Transform path | Execution proof | Current claim |
|---|---:|---:|---:|---|
| DISPLAY | Yes | Yes | Tested subset | Supported subset |
| STOP RUN | Yes | Yes | Tested | Supported subset |
| MOVE | Yes | Yes | Tested; figurative-fill semantics (`ALL <pattern>`, `ZEROS` on `PIC X`, `VALUE ALL …`) verified byte-identical vs. GnuCOBOL 3.1.2 (BL-030, 11/11) | Supported subset |
| ADD/SUBTRACT/MULTIPLY | Yes | Yes | Tested | Supported subset |
| DIVIDE/COMPUTE | Yes | Yes | Targeted | Supported subset; precision edges remain |
| IF/ELSE | Yes | Yes | Tested | Supported subset |
| PERFORM | Yes | Yes | Tested | Supported subset |
| PERFORM VARYING | Yes | Yes (bounded Java loop) | Verified end-to-end (phase4 oracle) | Supported subset |
| EVALUATE | Yes (lowered to IF/ELSE) | Yes (via IF/ELSE) | Verified end-to-end (phase4 oracle) | Supported subset |
| STRING/UNSTRING | Yes | Yes/partial | STRING certified subset verified end-to-end (BL-027/BL-029: generated Java compiled+executed vs. GnuCOBOL 3.1.2 oracle, byte-identical; identifier delimiters, `DELIMITED BY ALL`, `VARYING IN`, `ON OVERFLOW` fail closed with named markers; **BL-028 fixed**: fixed-width receiver truncation + the oracle-pinned `1..W+1` pointer boundary rule, re-verified byte-identical 8/8 plus a 3/3 boundary probe) | STRING: supported subset (oracle-verified forms; rest fail closed). UNSTRING: partial (certified pipe-delimited subset, disclosed; broadening = roadmap P1-5) |
| CALL (static, resolved) | Yes | Yes | Verified end-to-end (Phase-D A->B->C proof, 6b5a866; unresolved/dynamic/cyclic/arity-mismatch expressly blocked, 90efdca); comment lines, `*>` inline comments and string-literal text never create a phantom CALL edge — literal-aware extraction keeps only real statements (BL-034, 13 focused gate tests) | Supported subset, fail-closed negatives |
| Sequential files (LINE SEQUENTIAL) | Yes | Yes | Verified end-to-end (Phase-D integrated workload `fixtures/workload-integrated`: OPEN OUTPUT/WRITE/CLOSE + READ loop, record-to-FD resolution, 4 artifacts MATCH) | Supported subset |
| Indexed/relative/REWRITE/START files | Yes (detected) | No (rejected) | Fail-closed negatives (Phase-D negative scenario 4: blocked outside the certified file boundary) | Not certified; blocked by design |
| String comparison (`IF X = "LIT"`) | Yes | Yes (`String.equals`, never `==`) | Verified end-to-end (Phase-D: `PERFORM UNTIL WS-EOF = "Y"` loop terminates on the converted candidate) | Supported subset; pre-fix used `==` (defect fixed) |
| Copybooks | Yes | Yes | Verified end-to-end (copybook-runtime VERIFIED; resolution/ambiguity/missing fail-closed); nested `COPY` inside copybooks expanded at materialization with missing/cyclic targets failing closed (BL-031, 12 focused gate tests); `COPY … REPLACING` operands applied for supported forms (pseudo-text `==…==` pairs, word operands, multi-pair, case-insensitive) with unappliable/malformed clauses failing closed naming `REPLACING` (BL-032, 23 focused gate tests); unresolved/ambiguous copybook dependencies classify `UNSUPPORTED` and block the plan with `MISSING_COPYBOOK` matching generation's fail-closed errors (BL-033, 15 focused gate tests); comment lines, `*>` inline comments and string literals never create a phantom COPY reference — only real statements extract, so valid programs are not blocked (BL-034, 13 focused gate tests); discovery and generation share one deterministic search-directory authority (root plus every directory holding a file, sorted), so a copybook found by discovery is found by generation in every layout either lane accepts while ambiguity stays an explicit error in both lanes (BL-035, 13 focused gate tests) | Supported subset (shared Java model); clause-parameterized copybooks have per-program merged IR and no shared model plan; `LEADING`/`TRAILING`/`PARTIAL`/prefixed/literal operand forms unsupported (fail closed, never silently dropped) |
| JCL | Modeled | Partial | No runtime lane; Phase-D negative scenario 6 proves a PARTIAL/unsupported job stream can never open the central gate | Not certified; central status NOT_VERIFIED |
| CICS | Modeled | Partial | No runtime lane; Phase-D negative scenario 8 (`EXEC CICS ALLOCATE`) classified UNSUPPORTED and blocked | Not certified; central status NOT_VERIFIED |
| DB2/SQL | Modeled | Partial | No DB2 runtime proof (`runtime_verified_features()` is empty by construction); Phase-D negative scenario 7 blocks EXEC SQL programs | Not certified; central status NOT_VERIFIED |
| Integrated application status | Yes | Yes | Verified runtime lane + fail-closed central gate (`engine/modernization/integrated_proof.py`) | Runtime lane VERIFIED; application-level status NOT_VERIFIED whenever JCL/DB2/CICS is declared |

## Capability rule

A construct may only be labeled supported when the implementation chain and required runtime
evidence justify that label. Parser recognition alone is insufficient.

Statement classifications are maintained in the authoritative registry
(`engine/transformation/semantic_capability.py`) consumed by the capability analyzer. These
must remain reconciled with parser, IR, mapping, generator, runtime and evidence behavior.
The analyzer's COPYBOOK component classifies the dependency relationship (discovery,
resolution and consumption as program source context), not standalone transformation of
copybook files.

## Evidence ladder

recognized -> parsed -> IR -> capability -> mapped -> generated -> compiled -> executed ->
oracle executed -> compared -> mutation verified -> end-to-end verified

Current proof is strong for a subset, not every row.

## Integrated application status (Phase D)

`engine/modernization/integrated_proof.py` joins the modernization report, the runtime
lane evidence and the non-runtime lanes (JCL/DB2/CICS) into one ledger, then applies a gate
that can only downgrade:

    central VERIFIED <= runtime verdict VERIFIED
                     AND evidence manifest complete
                     AND evidence integrity validated
                     AND every required dependency PROVEN

A dependency is PROVEN only when its capability is SUPPORTED *and* the COBOL/Java runtime
lane executed it under validated evidence. JCL, DB2 and CICS have no runtime lane here, so
they resolve to PARTIAL/BLOCKED and therefore force `CentralStatus.NOT_VERIFIED` even when
the runtime lane itself is VERIFIED. Proven by `tests/integration/test_phase_d_integrated_proof.py`
(positive workload) and `tests/integration/test_phase_d_negative_integration.py` (8 negative
scenarios plus gate invariants).

## Known gaps

- `CALL ... BY VALUE` and `CALL ... BY CONTENT` have no `CONSTRUCT_REGISTRY` key, so they are
  never claimed supported (asserted in `TestUnsupportedParameterContract`).
- `CapabilityAnalyzer._aggregate` reports `UNAVAILABLE` rather than `UNSUPPORTED` when
  `docker_available=False`; consumers must treat anything other than `SUPPORTED`/`PARTIAL`
  as not certified.
- `integrated_proof_from_pipelines` is not yet wired into `api/service.py` (Phase E).

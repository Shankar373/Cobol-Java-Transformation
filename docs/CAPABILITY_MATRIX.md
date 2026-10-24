# Current Capability Matrix

> **Baseline note (Master README §78, updated 2026-10-22):** rows below were
> verified against commit `6145e892e95282a0ca85eb678057a0ea9890389c` (audit
> date 2026-10-21) and then reconciled with the 2026-10-22 working tree
> (`2e2f4ca` + uncommitted changes). The former three-way drift on
> indexed/relative, `REWRITE` and `START` (BL-108/BL-109) is **FIXED**, and
> **BL-134 (2026-10-22)** then reclassified indexed/relative **transformation**
> to a **SUPPORTED certified subset** (primary RECORD KEY at offset 0, ACCESS
> MODE DYNAMIC, no ALTERNATE RECORD KEY) with a generated-Java differential
> proof against the GnuCOBOL oracle; runtime for those files was already PROVEN
> for hand-written candidates. Outside the certified subset the `FILE-CONTROL`
> layer remains UNSUPPORTED and plans stay BLOCKED. Where this matrix,
> `docs/cobol_coverage_registry.json` and the code still disagree, the
> divergence is a filed defect; no row may be quoted as resolved beyond its
> acceptance criteria. Historical phase reports are evidence of their own
> commit only.

This is an implementation and evidence matrix, not a language-completeness claim.

| Capability | Parsed/Modeled | Transform path | Execution proof | Current claim |
|---|---:|---:|---:|---|
| DISPLAY | Yes | Yes | Tested subset | Supported subset |
| STOP RUN | Yes | Yes | Tested | Supported subset |
| MOVE | Yes | Yes | Tested; figurative-fill semantics (`ALL <pattern>`, `ZEROS` on `PIC X`, `VALUE ALL …`) verified byte-identical vs. GnuCOBOL 3.1.2 (BL-030, 11/11) | Supported subset |
| ADD/SUBTRACT/MULTIPLY | Yes | Yes | Tested | Supported subset |
| DIVIDE/COMPUTE | Yes | Yes | Targeted | Supported subset; precision edges remain. `COMPUTE … ON SIZE ERROR` is removed from the expression and named by an `UNSUPPORTED_CONSTRUCT` diagnostic (never silently evaluated as part of the expression; `test_compute_size_error_diagnostic.py`) |
| IF/ELSE | Yes | Yes | Tested | Supported subset |
| PERFORM | Yes | Yes | Tested | Supported subset |
| PERFORM VARYING | Yes | Yes (bounded Java loop) | Verified end-to-end (phase4 oracle) | Supported subset |
| EVALUATE | Yes (lowered to IF/ELSE) | Yes (via IF/ELSE) | Verified end-to-end (phase4 oracle) | Supported subset |
| STRING/UNSTRING | Yes | Yes/partial | STRING certified subset verified end-to-end (BL-027/BL-029: generated Java compiled+executed vs. GnuCOBOL 3.1.2 oracle, byte-identical; identifier delimiters, `DELIMITED BY ALL`, `VARYING IN`, `ON OVERFLOW` fail closed with named markers; **BL-028 fixed**: fixed-width receiver truncation + the oracle-pinned `1..W+1` pointer boundary rule, re-verified byte-identical 8/8 plus a 3/3 boundary probe) | STRING: supported subset (oracle-verified forms; rest fail closed). UNSTRING: partial (certified pipe-delimited subset, disclosed; broadening = roadmap P1-5). UNSTRING clause losses are explicit: `WITH POINTER`/`VARYING IN`/`TALLYING IN`/`ON OVERFLOW`/`DELIMITER IN`/`COUNT IN`/extra delimiters are captured on the IR and each named by an `UNSUPPORTED_CONSTRUCT` diagnostic; clause keywords never become receivers; the generic mapper emits an `UNSUPPORTED_UNSTRING$…` symbol naming the clause (`test_unstring_clause_diagnostics.py`) |
| CALL (static, resolved) | Yes | Yes | Verified end-to-end (Phase-D A->B->C proof, 6b5a866; unresolved/dynamic/cyclic/arity-mismatch expressly blocked, 90efdca); comment lines, `*>` inline comments and string-literal text never create a phantom CALL edge — literal-aware extraction keeps only real statements (BL-034, 13 focused gate tests); multi-line `CALL` (target/USING on following lines) parses to the identical `CallStatement` as the single-line spelling — one extraction truth across discovery, parser and planner, never split "skipped statement" diagnostics (BL-036, in `tests/test_call_statement_parsing.py`); the `ON EXCEPTION`/`ON OVERFLOW` phrase ends the USING argument list — true arity plus an explicit diagnostic naming the phrase, never a false arity claim, and genuine linkage mismatches block as `ARITY_MISMATCH` (never `UNKNOWN_CONSTRUCT`) (BL-037); `ProgramCall.resolution` carries the same resolution decision as its dependency edge for every call — resolved static `RESOLVED`, missing static and dynamic `UNRESOLVED` (BL-038, 4 focused gate tests); `RETURNING` is captured on the IR, excluded from the USING argument list (no fabricated arity), named by an explicit diagnostic, and the mapper emits an `UNSUPPORTED_CALL$RETURNING_…` symbol so the returned value is never silently discarded (`test_call_returning_clause.py`); `BY CONTENT` arguments are sync-in only (callee writes never reach the caller) and are byte-identical to GnuCOBOL 3.1.2 in both a single-mode and a mixed `BY REFERENCE`/`BY CONTENT` workload (`tests/integration/test_call_passing_mode_oracle_proof.py`); `BY VALUE` uses the same no-write-back lowering but stays PARTIAL because GnuCOBOL's BY VALUE implementation is unfinished and cannot serve as an oracle | Supported subset, fail-closed negatives |
| Sequential files (LINE SEQUENTIAL) | Yes | Yes | Verified end-to-end (Phase-D integrated workload `fixtures/workload-integrated`: OPEN OUTPUT/WRITE/CLOSE + READ loop, record-to-FD resolution, 4 artifacts MATCH); a second file name or unsupported OPEN clause is now named by an `UNSUPPORTED_CONSTRUCT` diagnostic and only the first file opens (`test_open_multi_file_diagnostic.py`) | Supported subset |
| Indexed/relative/REWRITE/START files | Yes (detected) | **Yes, certified subset** (primary RECORD KEY at offset 0, ACCESS MODE DYNAMIC, no ALTERNATE RECORD KEY — `ORGANIZATION INDEXED`/`RELATIVE`/`ACCESS DYNAMIC`/`RECORD KEY` classify SUPPORTED in `semantic_capability.py`, plans TRANSFORM; ALTERNATE RECORD KEY and ACCESS MODE RANDOM classify UNSUPPORTED and plans stay BLOCKED) | Transformation proven: `tests/integration/test_indexed_relative_oracle_proof.py` (2, Docker-gated) — generated Java byte-identical to the GnuCOBOL oracle (stdout, FILE STATUS, exit code). Runtime proven: `tests/integration/test_indexed_semantics.py` + `test_relative_semantics.py` (23 tests, Docker-gated) verify a hand-written Java candidate implementing WRITE/READ/REWRITE/DELETE/START against the GnuCOBOL oracle, with mutations failing | Supported subset (certified indexed/relative subset, oracle-proven); runtime lane proven for hand-written candidates; **file-image (VSAM on-disk) equivalence not claimed** |
| String comparison (`IF X = "LIT"`) | Yes | Yes (`String.equals`, never `==`) | Verified end-to-end (Phase-D: `PERFORM UNTIL WS-EOF = "Y"` loop terminates on the converted candidate) | Supported subset; pre-fix used `==` (defect fixed) |
| Copybooks | Yes | Yes | Verified end-to-end (copybook-runtime VERIFIED; resolution/ambiguity/missing fail-closed); nested `COPY` inside copybooks expanded at materialization with missing/cyclic targets failing closed (BL-031, 12 focused gate tests); `COPY … REPLACING` operands applied for supported forms (pseudo-text `==…==` pairs, word operands, multi-pair, case-insensitive) with unappliable/malformed clauses failing closed naming `REPLACING` (BL-032, 23 focused gate tests); unresolved/ambiguous copybook dependencies classify `UNSUPPORTED` and block the plan with `MISSING_COPYBOOK` matching generation's fail-closed errors (BL-033, 15 focused gate tests); comment lines, `*>` inline comments and string literals never create a phantom COPY reference — only real statements extract, so valid programs are not blocked (BL-034, 13 focused gate tests); discovery and generation share one deterministic search-directory authority (root plus every directory holding a file, sorted), so a copybook found by discovery is found by generation in every layout either lane accepts while ambiguity stays an explicit error in both lanes (BL-035, 13 focused gate tests); the capability scan is transitive — every reachable nested `COPY` target is scanned with the same search directories generation merges, so a construct inside a nested copybook lowers the COPYBOOK verdict with a reason naming the nested file and a nested target generation cannot materialize fails the component closed with generation's own message, while flat copybooks keep the exact legacy reason (BL-039, 9 focused gate tests) | Supported subset (shared Java model); clause-parameterized copybooks have per-program merged IR and no shared model plan; `LEADING`/`TRAILING`/`PARTIAL`/prefixed/literal operand forms unsupported (fail closed, never silently dropped) |
| JCL | Modeled | Partial | No runtime lane; Phase-D negative scenario 6 proves a PARTIAL/unsupported job stream can never open the central gate | Not certified; central status NOT_VERIFIED |
| CICS | Modeled | Partial | No runtime lane; Phase-D negative scenario 8 (`EXEC CICS ALLOCATE`) classified UNSUPPORTED and blocked | Not certified; central status NOT_VERIFIED |
| DB2/SQL | Modeled | Partial | No DB2 runtime proof (`runtime_verified_features()` is empty by construction); Phase-D negative scenario 7 blocks EXEC SQL programs | Not certified; central status NOT_VERIFIED |
| IMS (`EXEC DLI`) | Yes (source-scan pattern + registry key, BL-084 / roadmap P3-4) | No (blocked) | No runtime lane; `tests/test_ims_mq_detection.py` (14 focused tests) proves the program is classified UNSUPPORTED with a reason naming `EXEC DLI`, comment/string-literal text never detects, plans stay BLOCKED, and the pre-existing fail-closed `unparsed_statement` diagnostics remain | Not certified; classification only — no IR node, no mapper, no IMS runtime, no PCB/segment dependency edges |
| IBM MQ (`EXEC MQI`) | Yes (source-scan pattern + registry key, BL-085 / roadmap P3-4) | No (blocked) | No runtime lane; same focused gate proves `EXEC MQI` classification UNSUPPORTED with a reason naming `EXEC MQI`, masking/boundary negatives green, plans stay BLOCKED | Not certified; classification only — queue discovery, message format, correlation and retry semantics not modeled |
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
lane evidence and the non-runtime lanes (JCL, DB2, CICS, MQ and IMS) into one ledger, then
applies a gate that can only downgrade:

    central VERIFIED <= runtime verdict VERIFIED
                     AND evidence manifest complete
                     AND evidence integrity validated
                     AND the dependency ledger is non-empty
                     AND every required dependency PROVEN

A dependency is PROVEN only when its capability is SUPPORTED *and* the COBOL/Java runtime
lane executed it under validated evidence. A `FILE` dependency carries one extra,
dependency-specific requirement: at least one `TEXT_FILE`/`FIXED_RECORD` artifact was
compared in this run and every compared file artifact MATCHed
(`FILE_ARTIFACT_TYPES` in `integrated_proof.py`). A run certified on stdout/exit status
alone therefore leaves its file dependencies PARTIAL and the application
NOT_VERIFIED — a workload-level verdict never cohort-promotes a file dependency
(audit EV-006/R9; regression: `tests/test_file_dependency_proof_binding.py`,
`tests/integration/test_file_write_read_runtime_proof.py::TestDefaultContractRun`).
`PROGRAM`/`CALL`/`COPYBOOK`/`PARAMETER` remain workload-scope: their only behavioural
channel in this evidence model is the workload's stdout/exit-status comparison, which
the VERIFIED verdict already gates (pinned by
`test_program_dependency_proof_scope_is_workload_level`). JCL, DB2, CICS, MQ and IMS
have no runtime lane
here, so they resolve to PARTIAL/BLOCKED and therefore force `CentralStatus.NOT_VERIFIED`
even when the runtime lane itself is VERIFIED. Every lane is fed by a product producer:
JCL by the JCL consumer, and DB2 (`extract_db2_dependency_entries`), CICS
(`extract_cics_dependency_entries`), MQ and IMS (`extract_external_dependency_entries`) by
`engine/modernization/external_dependency_edges.py`, all joined via
`extra_dependencies` on both the persist and recompute proof paths. Proven by
`tests/integration/test_phase_d_integrated_proof.py`
(positive workload) and `tests/integration/test_phase_d_negative_integration.py` (8 negative
scenarios plus gate invariants). Per-workload runtime-proof status lives in
`docs/verification/RUNTIME_PROOF_MATRIX.md`.

## Known gaps

- `CALL ... BY CONTENT` is `SUPPORTED` for plain data-item arguments, proven byte-identical
  to GnuCOBOL 3.1.2 on the shipped `workload-by-content` fixture and a mixed
  `BY REFERENCE`/`BY CONTENT` workload. `CALL ... BY VALUE` is `PARTIAL` only: the mapper
  implements sync-in with no write-back, but GnuCOBOL 3.1.2's BY VALUE implementation is
  unfinished (`-Wunfinished`) and aborts with SIGSEGV, so no oracle proof exists
  (`TestUnsupportedParameterContract`, `tests/integration/test_call_passing_mode_oracle_proof.py`).
- `CapabilityAnalyzer._aggregate` reports `UNAVAILABLE` rather than `UNSUPPORTED` when
  `docker_available=False`; consumers must treat anything other than `SUPPORTED`/`PARTIAL`
  as not certified.
- `integrated_proof_from_pipelines` is the engine-side convenience wrapper
  (integration-test consumer); `api/service.py` is wired to the same gate
  through the lower-level `build_dependency_ledger` + `evaluate_central_status`
  calls in `_proof_payload`, on both the persist and the recompute proof paths
  (Phase E wiring verified; note refreshed Phase 10 P2-g).

## Verification layer (runtime capability + business invariants) — 2026-10-22

Status vocabulary for this section: **implemented/tested** = code + green tests
in the working tree; **proposed** = designed/documented but not built;
**blocked** = missing external prerequisite (no bypass attempted).

| Capability | Status | Evidence |
|---|---|---|
| Runtime capability catalog (six states, typed prerequisites, downgrade-only discovery) | **Implemented/tested** | `engine/verification/runtime_catalog.py`; `tests/verification/test_runtime_catalog.py` (17) |
| Business invariants (pre/post/error phase, exact `Decimal`/fixed-field/JSON semantics, canonical self-checking reports, `admit_report`) | **Implemented/tested** | `engine/verification/business_invariants.py`; `tests/verification/test_business_invariants.py` (36) |
| `BUSINESS_INVARIANT` comparator + registry (`create_verification_registry()` opt-in; V1 default registry unchanged) | **Implemented/tested** | `engine/comparators/framework.py`; `tests/verification/test_business_invariant_comparator.py` (12) |
| Pipeline integration (both sides evaluated, derived artifact captured/compared, business-only failure -> FAILED, identical failure -> MISMATCH) | **Implemented/tested** | `engine/pipeline.py`, `engine/workload.py`, `engine/verdict/derivation.py`; `tests/verification/test_business_invariant_pipeline.py` (6) |
| GnuCOBOL batch + indexed/relative runtime | **Implemented/tested (Docker)** | 453-test Docker run, exit 0 (`test-artifacts/runtime-image-audit-2026-10-22/`); real ISAM execution in `test_indexed_semantics.py` / `test_relative_semantics.py` |
| Indexed/relative **transformation** (certified subset: primary RECORD KEY at offset 0, ACCESS MODE DYNAMIC, no ALTERNATE RECORD KEY) | **Implemented/tested (Docker)** | Byte-identical behavioral equivalence (stdout, FILE STATUS, exit code) proven for generated Java vs GnuCOBOL oracle; `tests/integration/test_indexed_relative_oracle_proof.py` (2 tests), mutation tests in `test_indexed_semantics.py` / `test_relative_semantics.py` |
| DB2 ESQL runtime equivalence | **Blocked (BL-130)** | No `ocesql`, no DB2 client, no DB-state comparator |
| MQ runtime lane | **Blocked/proposed (BL-131)** | Free image exists; no execution lane or message comparator |
| CICS / IMS runtime | **Blocked (entitlement, BL-132)** | IBM registries `UNAUTHORIZED`; mapping-only |
| JCL behavioural execution | **Blocked (BL-133)** | No licensed/MVS runtime; build/start only (PARTIAL) |

All 71 verification tests are Docker-free and deterministic (no LLM, no model
API). The catalog can only downgrade a claim; absent prerequisites never raise
one. See `docs/verification/RUNTIME_PROOF_MATRIX.md` for per-workload runtime
proof and `docs/audits/DOCKER_RUNTIME_IMAGE_AUDIT_2026-10-22.md` for the image
provenance audit.

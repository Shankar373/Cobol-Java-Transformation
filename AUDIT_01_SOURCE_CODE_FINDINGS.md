# AUDIT_01_SOURCE_CODE_FINDINGS

Consolidated forensic source-code audit findings. Each finding cites exact file path and line range. Findings are grouped by subsystem and carry severity (P0/P1/P2/P3), status (Confirmed/Suspected), and a pointer to the owning audit subagent report.

Sources:
- Parser/IR audit (subagent `ses_e73166748ffezXrruuL13S8re6`).
- Semantic capability/mapping audit (subagent `ses_e73124887ffeRr0bcKPc63kdC7`).
- API platform audit (subagent `ses_e7320b95dffefZZMfsNL2S0uny`).
- Java generation/runtime audit (subagent `ses_e730e5749ffeLqfPGhvwmq5G2S`) — **pending completion**; findings to be appended.
- Security/CI/Docker audit (subagent `ses_e730de7acffey9kFMZIJ7lfcZR`) — **pending completion**; findings to be appended.
- CI-blocking test defect found directly during Phase 11 (this session).

---

## 1. COBOL Lexer / parser / IR / diagnostics

See parser/IR audit report for full detail. Key findings:

| ID | Severity | File:Lines | Summary |
|---|---|---|---|
| P-1 | P1 | `engine/transformation/cobol_parser.py:1047-1057` | `_parse_pic_details` counts fractional digits by raw `'9'` chars, so `PIC 9(5)V9(2)` yields `decimal_places=1`. Silent precision loss. |
| P-2 | P2 | `engine/transformation/cobol_parser.py:1368-1411,1584-1679,2838-2996` | File verbs (OPEN/READ/WRITE/CLOSE/START/REWRITE/DELETE/DISPLAY/ACCEPT/INITIALIZE) produce empty IR nodes on malformed input with no diagnostic. |
| P-3 | P2 | `engine/transformation/cobol_parser.py:951-1041,871-949,1073-1116,1118-1143` | Data declarations silently dropped: unmatched lines, PIC-less group children, duplicate-named leaves, childless groups. |
| P-4 | P3 | `engine/transformation/cobol_parser.py:698-700` | Dead `pass` in REPLACE diagnostic slot. |
| P-5 | P2 | `engine/transformation/cobol_parser.py:2266-2360,2132-2265` | Empty `IfStatement`/`Evaluate` nodes emitted without diagnostic. |
| P-6 | P2 | `engine/transformation/producer.py:103-143` | Legacy producer reports `success=True` whenever `has_errors` is false; warnings do not downgrade. |
| P-7 | P2 | `engine/transformation/cobol_parser.py:702-722,472-613` | `CobolParseError` almost never raised; `_validate_program_structure` emits ERROR but parse still returns a program. Unsupported constructs become warnings. |
| P-8 | P3 | `engine/transformation/producer.py:101`, `manifest.py:64` | Non-deterministic manifest timestamps (metadata only). |
| P-9 | P3 | `engine/transformation/redefines.py:87-184` | Multiple redefines of same base silently overwrite view. |
| P-10 | P2 | `engine/transformation/ir.py:900-1016` | Capability derivation uses string heuristics (`') ='`, `endswith('=')`). |
| P-11 | P3 | `engine/transformation/source_model.py:78-86` | `PicClause.scale` never populated (dead field). |
| P-12 | P3 | `tests/transformation/test_parser.py:244`, `test_ir.py:181` | Existence-only assertions that cannot catch partial parsing. |
| P-13 | P2 | `engine/transformation/cobol_parser.py:584-589` | `open_statements` collection skips `OPEN` nested in IF/PERFORM/READ bodies. |
| P-14 | P2 | `engine/transformation/cobol_parser.py:1108-1116` | Duplicate-named working-storage leaves silently dropped. |
| P-15 | P2 | `engine/transformation/cobol_parser.py:1856-1857,1883-1884,...` | Many statement parsers return empty-but-typed IR nodes after `_emit_unparsed` warning (partial parsing survives). |
| P-16 | P1 | `engine/transformation/cobol_parser.py:1974-1975` | CALL parse failure hardcodes `is_dynamic=True`. |

## 2. Semantic capability / mapping / numeric / control flow

See semantic capability audit report. Key findings:

| ID | Severity | File:Lines | Summary |
|---|---|---|---|
| S-1 | P0 | `engine/transformation/producer.py:116-142` | Producer `success=True` for unsupported constructs (parser diagnostics are warnings, not errors). |
| S-2 | P0/P1 | `engine/transformation/application_generator.py:131-177` | `generate` returns `success=True` even when statements are silently dropped. |
| S-3 | P2 | `engine/transformation/application_discovery.py:208-213` | Empty `except Exception: pass` skips unreadable extensionless files. |
| S-4 | P1 | `engine/transformation/cobol_to_java_mapping.py:3074-4425` | No branch for `SqlStatement`/`PerformTimesStatement` → returns `[]`. |
| S-5 | P2 | `engine/transformation/cobol_to_java_mapping.py:1347-1348` | Broad `except Exception` hides parse failures (fail-closed, but loses root cause). |
| S-6 | P3 | `engine/transformation/java_generator.py:871-874` | `_java_type_to_string` returns `"void"` on failure. |
| S-7 | P1 | `engine/transformation/cobol_parser.py:1047-1057` | Parenthesized fractional PIC under-counts decimal places (same as P-1). |
| S-8 | P2 | `engine/transformation/cobol_to_java_mapping.py:409-416` | `_numeric_java_literal` swallows `NumericValueError` and falls back to raw text. |
| S-9 | P2 | `engine/transformation/cobol_to_java_mapping.py:1766-1876` | Unsigned integer receiver overflow throws instead of COBOL-style truncation. |
| S-10 | P1 | `engine/transformation/cobol_parser.py:2380-2385` + `cobol_to_java_mapping.py:4264-4287` | `WITH TEST AFTER` parsed but ignored in generated Java (pre-test loop). |
| S-11 | P1 | `engine/transformation/cobol_to_java_mapping.py:4146-4206,2885-3012` | PERFORM VARYING assumes int loop vars and integer stop values; field-valued `by` emitted as raw literal. |
| S-12 | P2 | `engine/transformation/cobol_to_java_mapping.py:3026-3043` | `_expand_thru_range` returns only `[first]` on inverted/unknown range. |
| S-13 | P3 | `engine/transformation/cobol_to_java_mapping.py:4225-4231` | PERFORM TIMES field count not validated. |
| S-14 | P3 | `engine/transformation/copybook_resolver.py:89-109` | Symlinked dirs may be missed. |
| S-15 | P3 | `engine/transformation/semantic_capability.py:603,672` | PERFORM TIMES pattern also matches VARYING. |
| S-16 | P2 | `engine/modernization/capability_analyzer.py:165-178` | `_iter_call_statements` swallows `AttributeError`/`TypeError`. |
| S-17 | P0 | `engine/transformation/cobol_parser.py` (throughout) + `producer.py` | `UNSUPPORTED_CONSTRUCT` emitted as warnings, so `has_errors` false. |

## 3. API platform / persistence / frontend

See API platform audit report. Key findings:

| ID | Severity | File:Lines | Summary |
|---|---|---|---|
| A-1 | P1 | `api/app.py:927-947,447-485` | Single shared token + unverified approver string = self-approve-and-export; no separation of duties. |
| A-2 | P2 | `api/app.py:788-793`, `api/service.py:797-804` | Test-only `use_uploaded_candidate` reachable in production (uploaded Java executed in validation lane). |
| A-3 | P2 | `frontend/src/api/client.ts:57-67`, `frontend/scripts/verify-bundle-secrets.mjs:50-96,125` | Bearer token designed for frontend bundle; `ALLOW_BUNDLED_API_TOKEN=1` bypasses guard. |
| A-4 | P3 | `api/service.py:829-831,1022-1024` | Raw `str(exc)` from workers served to clients (bypasses sanitized error layer). |
| A-5 | P3 | `api/service.py:1723-1724,1736-1737`, `api/name_derivation.py:76-78` | Silent exception swallowing on read paths (unlogged). |
| A-6 | P3 | `api/models.py:73-76`, `api/app.py:1198-1232` | Server filesystem paths + `/ready` details unauthenticated. |
| A-7 | P3 | (no retention code) | Unbounded growth: SQLite, runs, workspace dirs never pruned. |
| A-8 | P3 | `.gitignore` | `*.db-wal`/`*.db-shm` not ignored; live DB in repo tree. |
| A-9 | P3 | `api/app.py:369-372` | Static token, no expiry/rotation/rate limits. |
| A-10 | P3 | `api/app.py:844-845`, `api/service.py:1716-1722` | Discovery recomputed synchronously on GET (incl. 2s polling). |
| A-11 | P3 | `api/ingestion.py:5`, `api/models.py:231-233` | Dead `git_url` ingestion surface. |
| A-12 | P3 | `api/artifact_seal.py:90,199` | Bundle sealing/export follows symlinks (requires prior FS write). |

## 4. CI-blocking test defect (found this session)

| ID | Severity | File:Lines | Summary |
|---|---|---|---|
| C-1 | P1 | `tests/transformation/test_phase7c_end_to_end.py:1604-1631` | `test_docker_status_recorded` unconditionally asserts `status == "BLOCKED / NOT VERIFIED"` at line 1629, but computes `status = "VERIFIED" if (gate and runtime_available)` at line 1627. In CI, `RUN_DOCKER_TESTS=1` (ci.yml:162) and `eclipse-temurin` image is pulled (ci.yml step "Pull pinned Java execution image"), so gate=True and runtime_available=True → status="VERIFIED" → assertion fails. SystemaOps CI failed on runs 41030405967, 41030293376, 41030220369 (all recent pushes) with this single failure. **Fixed** this session by making the assertion conditional on `gate` (default env must never claim VERIFIED; gated env must track availability). Verified passing in both default and gated environments. |

## 5. Java generation / runtime / verification / provenance

See Java generation audit report. Key findings:

| ID | Severity | File:Lines | Summary |
|---|---|---|---|
| J-1 | P0 | `engine/transformation/spring_boot_generator.py:958-959` | JDBC repository methods are `UnsupportedOperationException` stubs. |
| J-2 | P0 | `engine/transformation/java_generator.py:1991-1992` | GO TO silently dropped as a comment. |
| J-3 | P0 | `engine/transformation/java_generator.py:1935-1997` | Unsupported statements return `None` and are omitted silently. |
| J-4 | P1 | `engine/transformation/java_generator.py:151-163` | ServiceRegistry call methods are placeholders. |
| J-5 | P1 | `engine/candidate/java_adapter.py:197-216` | Host Java execution timeout discards partial stdout; `input_data=None` inherits parent stdin. |
| J-6 | P2 | `engine/candidate/docker_java_adapter.py:517-527`, `docker_spring_boot_adapter.py:644-652` | Docker timeout handlers reference `proc` that is always None; partial stdout discarded. |
| J-7 | P2 | `engine/candidate/docker_java_adapter.py:172-200`, `docker_spring_boot_adapter.py:247-272`, `application_discovery.py:212-213`, `java_generator.py:871-874` | Swallowed exceptions in identity/probe paths. |
| J-8 | P2 | `engine/pipeline.py:236-255` | Nondeterministic candidate manifest file ordering (`rglob`). |
| J-9 | P1 | `engine/verdict/derivation.py:279-313` | Verdict unavailability uses `all()` and can mask mixed failures. |
| J-10 | P2 | `engine/transformation/cobol_parser.py:359,3543`, `copybook_resolver.py:94,103` | Empty excepts in parser/copybook resolution. |
| J-11 | P2 | `tests/common.py:12-36` + many tests | Tests inject stub verdicts instead of real derivation. |
| J-12 | P3 | `tests/integration/test_integrated_proof_api.py:493,502` etc. | Existence-only assertions in integration paths. |
| J-13 | P3 | `tests/test_phase12_p2_f03_masking_skips.py:6-72` etc. | Skips masking generation failures. |

Positive: no `shell=True` in engine; no mock comparators on real paths; no LLM/random/network in engine.

## 6. Security / CI / Docker / dependencies / license

See security/CI/Docker audit report. Key findings:

| ID | Severity | File:Lines | Summary |
|---|---|---|---|
| Dk-1 | P1 | `docker-compose.production.yml:82-86,96-97` | Docker socket mount + group_add docker → API user daemon-root-equivalent. |
| Dk-2 | P2 | `docker-compose.production.yml:110` | Root filesystem writable. |
| Dk-3 | P2 | `engine/execution/container_hardening.py:52-68` | No `--read-only` root FS flag emitted. |
| Dk-4 | P3 | `Dockerfile.gnucobol`, `Dockerfile.maven-offline` | No `USER` directive (root-default images). |
| Dk-5 | P2 | `scripts/deploy/verify-production.sh:55-72` | Env-controlled path interpolated into `bash -c` without escaping. |
| Dk-6 | P2 | `engine/oracle/docker_adapter.py:74-87` | Accepts local Image ID (not just RepoDigest) as identity. |
| Dk-7 | P2 | `engine/oracle/adapter.py:47` | Default mutable tag `gnucobol-ocesql:latest`. |
| Dk-8 | P2 | `.gitignore` | No `test-artifacts/` rule. |
| Dk-9 | P2 | `requirements.txt`, `frontend/package.json` | Ranges at manifest level (lockfiles pin). |
| Dk-10 | P2 | `supply-chain.yml:39` | Audit tooling unpinned (`pip-audit>=2.7`). |
| Dk-11 | P3 | `ci.yml:4-5,135,137,154-156,194,201` | All-branch push triggers; version probes omit hardening; frontend `if: always()`. |
| Dk-12 | P3 | `.gitignore:410,419,351,397` | Ignores `*.kt`, `Makefile`, `Cargo.lock` (could hide files). |
| Dk-13 | P3 | `scripts/deploy/verify-production.sh:40,9-11` | Probe omits hardening flags; sources arbitrary env file. |
| Dk-14 | Owner | `PROJECT_LICENSE_DECISION.md`, `TRUSTED_ARTIFACT_SIGNING_PROPOSAL.md` | License/signing blocked on owner decision. |

Positive: container hardening flags present at all five docker run sites; production API non-root; no secrets in tracked files; CI SHA-pinned and least-privilege; supply chain audits fail closed; oracle fails closed on missing pin; no mock-oracle fallback.

---

## Notes

- No LLM, no `random`, no `pickle`, no `shell=True`, no raw SQL on production paths (confirmed by API audit and grep). Determinism rule holds.
- No secrets/credentials/tokens found in production code (only env-var reads). `.env.production.example` values empty.
- The platform is single-tenant by design; cross-tenant isolation does not exist (A-1).
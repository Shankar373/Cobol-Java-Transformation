# AUDIT_06_MASTER_GAP_REGISTER

Consolidated defect register. Columns: ID | Severity | Subsystem | File | Line | Evidence | Reproduction | Root cause | Impact | Fix | Regression test | Dependencies | Owner action | Status.

## P0

| ID | Severity | Subsystem | File | Line | Evidence | Reproduction | Root cause | Impact | Fix | Regression test | Dependencies | Owner action | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S-1 | P0 | Semantic/Producer | `engine/transformation/producer.py` | 116-142 | `success=True` whenever `has_errors` false; warnings don't downgrade | Transform program with `GO TO`/`SORT` via producer | Parser emits `UNSUPPORTED_CONSTRUCT` as warning, so `has_errors` false | False success for untransformable input | Treat `UNSUPPORTED_CONSTRUCT` diagnostics as failure (or reclassify as errors) | Add producer test asserting unsupported construct → success=False | S-17 | None | Open |
| S-17 | P0 | Parser | `engine/transformation/cobol_parser.py` (throughout) | — | `UNSUPPORTED_CONSTRUCT` emitted via `.warning(...)` | Any unsupported statement | Diagnostics severity choice | `has_errors` false for unsupported constructs | Reclassify `UNSUPPORTED_CONSTRUCT` as error, or add `has_unsupported` flag | Parser diagnostic severity tests | S-1 | None | Open |

## P1

| ID | Severity | Subsystem | File | Line | Evidence | Reproduction | Root cause | Impact | Fix | Regression test | Dependencies | Owner action | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P-1/S-7 | P1 | Parser/Numeric | `engine/transformation/cobol_parser.py` | 1047-1057 | `right_len = len(re.findall(r"9", right))` | Parse `PIC 9(5)V9(2)` | Fractional side not paren-aware | Wrong decimal scale in generated Java | Handle `9(n)` on right side | Parser PIC test | None | None | Open |
| S-2 | P1 | Generator | `engine/transformation/application_generator.py` | 131-177 | `success=True` after mapping | Generate app with unsupported stmt | No check for `JavaUnsupportedExpression`/empty results | False success | Fail if any unsupported/empty result | Application generator test | S-4 | None | Open |
| S-4 | P1 | Mapping | `engine/transformation/cobol_to_java_mapping.py` | 3074-4425 | No branch for `SqlStatement`/`PerformTimesStatement` | Map program containing SQL/PERFORM TIMES | Incomplete mapping table | Empty Java output | Add branches or fail-closed | Mapping tests | S-2 | None | Open |
| S-10 | P1 | Mapping/Control flow | `engine/transformation/cobol_parser.py` + `cobol_to_java_mapping.py` | 2380-2385, 4264-4287 | `test_after` parsed but not emitted | PERFORM … WITH TEST AFTER | Mapper ignores `test_after` | Wrong iteration count | Emit do-while when test_after | PERFORM test | None | None | Open |
| S-11 | P1 | Mapping/Control flow | `engine/transformation/cobol_to_java_mapping.py` | 4146-4206, 2885-3012 | `JavaType(basic_type=INT)`, regex `(\d+)` only | PERFORM VARYING over decimal/long/field | Hardcoded int assumption | Compile failure or wrong bounds | Handle field-valued bounds and decimal/long vars | PERFORM VARYING tests | None | None | Open |
| A-1 | P1 | API/Auth | `api/app.py` | 927-947, 447-485 | Single token + free-text approver | Approve own run via API | No separation of duties | Self-certify-and-export | RBAC / per-user identity (owner decision) | Auth tests | None | Owner (design) | Open (owner) |
| C-1 | P1 | Tests/CI | `tests/transformation/test_phase7c_end_to_end.py` | 1604-1631 | CI failure on runs 41030405967/41030293376/41030220369 | `RUN_DOCKER_TESTS=1` + temurin image present | Unconditional assertion contradicts derivation | CI red | Make assertion conditional on gate | Verified passing both envs | None | None | **Fixed** |

## P2

| ID | Severity | Subsystem | File | Line | Evidence | Reproduction | Root cause | Impact | Fix | Regression test | Dependencies | Owner action | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P-2 | P2 | Parser | `engine/transformation/cobol_parser.py` | 1368-1411 etc. | Empty IR nodes on malformed verbs | Malformed OPEN/READ/etc. | No diagnostic on miss | Partial parsing survives | Emit diagnostic on miss | Parser tests | None | None | Open |
| P-3 | P2 | Parser | `engine/transformation/cobol_parser.py` | 951-1041 etc. | Data declarations dropped | Duplicate names, PIC-less groups | Silent skip | Missing data in IR | Emit diagnostics / preserve | Parser tests | None | None | Open |
| P-5 | P2 | Parser | `engine/transformation/cobol_parser.py` | 2266-2360, 2132-2265 | Empty IfStatement/Evaluate | Malformed IF/EVALUATE | No diagnostic on miss | Empty control nodes | Emit diagnostic | Parser tests | None | None | Open |
| P-6 | P2 | Producer | `engine/transformation/producer.py` | 103-143 | success=True on warnings | Transform with warnings | Warnings don't downgrade | Overstated success | Downgrade on warnings | Producer tests | S-1 | None | Open |
| P-7 | P2 | Parser | `engine/transformation/cobol_parser.py` | 702-722 | PARSE_ERROR emitted but parse returns program | Structurally invalid program | No abort | False success possible | Abort or mark failed | Parser tests | None | None | Open |
| P-10 | P2 | IR | `engine/transformation/ir.py` | 900-1016 | String-heuristic capability derivation | Renamed/whitespace variants | Textual substring matching | Wrong capability verdict | Use structured IR | Capability tests | None | None | Open |
| P-13 | P2 | Parser | `engine/transformation/cobol_parser.py` | 584-589 | Nested OPEN skipped | OPEN inside IF/PERFORM | `open_statements` only top-level | Missed file-role capability | Recurse into nested statements | Parser tests | None | None | Open |
| P-14 | P2 | Parser | `engine/transformation/cobol_parser.py` | 1108-1116 | Duplicate-named leaves dropped | Two same-named items | `seen` set dedup | Missing data | Preserve or diagnose | Parser tests | None | None | Open |
| P-15 | P2 | Parser/Mapping | `engine/transformation/cobol_parser.py` | 1856-2130 | Empty typed IR nodes on miss | Malformed statements | `_emit_unparsed` + empty node | Partial parsing survives | Fail-closed or remove node | Parser tests | None | None | Open |
| P-16 | P2 | Parser | `engine/transformation/cobol_parser.py` | 1974-1975 | CALL miss hardcodes is_dynamic=True | Malformed CALL | Default on failure | Wrong call semantics | Diagnose + don't default | Parser tests | None | None | Open |
| S-3 | P2 | API | `engine/transformation/application_discovery.py` | 208-213 | Empty except swallows read errors | Unreadable extensionless file | `except Exception: pass` | Incomplete discovery | Log + record error | Discovery tests | None | None | Open |
| S-5 | P2 | Mapping | `engine/transformation/cobol_to_java_mapping.py` | 1347-1348 | Broad except hides parse failures | Bad arithmetic expr | `except Exception` | Lost root cause | Log exception | Mapping tests | None | None | Open |
| S-8 | P2 | Mapping | `engine/transformation/cobol_to_java_mapping.py` | 409-416 | `_numeric_java_literal` swallows NumericValueError | Invalid numeric literal | `except NumericValueError` | Raw text leaks | Fail-closed | Mapping tests | None | None | Open |
| S-9 | P2 | Mapping/Numeric | `engine/transformation/cobol_to_java_mapping.py` | 1766-1876 | Unsigned integer overflow throws | Unsigned receiver overflow | `Math.*Exact` | Inconsistent truncation | COBOL modulo truncation | Numeric tests | None | None | Open |
| S-12 | P2 | Mapping/Control flow | `engine/transformation/cobol_to_java_mapping.py` | 3026-3043 | `_expand_thru_range` returns [first] on inverted | Inverted THRU | Silent truncation | Wrong execution | Diagnose | PERFORM tests | None | None | Open |
| S-16 | P2 | Capability | `engine/modernization/capability_analyzer.py` | 165-178 | `_iter_call_statements` swallows errors | Malformed IR | `except (AttributeError, TypeError)` | Hidden CallStatement | Log | Capability tests | None | None | Open |
| A-2 | P2 | API | `api/app.py`, `api/service.py` | 788-793, 797-804 | use_uploaded_candidate not env-gated | POST candidate + modernize | Test-only flag in prod | Arbitrary code exec in Docker | Disable in production | API tests | None | None | Open |
| A-3 | P2 | Frontend/Security | `frontend/src/api/client.ts`, `verify-bundle-secrets.mjs` | 57-67, 50-96, 125 | Token in bundle; bypass flag | Build with ALLOW_BUNDLED_API_TOKEN=1 | Escape hatch | Token leakage | Remove bypass / runtime entry | Frontend tests | None | Owner (deploy) | Open |
| S-6 | P2 | Generator | `engine/transformation/java_generator.py` | 871-874 | `_java_type_to_string` returns "void" | Type render failure | Broad except | Wrong type | Surface failure | Generator tests | None | None | Open |

## P3

| ID | Severity | Subsystem | File | Line | Evidence | Reproduction | Root cause | Impact | Fix | Regression test | Dependencies | Owner action | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P-4 | P3 | Parser | `engine/transformation/cobol_parser.py` | 698-700 | Dead `pass` | — | Dead code | Maintainability | Remove | — | None | None | Open |
| P-8 | P3 | Producer | `engine/transformation/producer.py`, `manifest.py` | 101, 64 | Timestamp metadata varies | Re-run | `datetime.now` | Non-reproducible manifest | Freeze or document | — | None | None | Open |
| P-9 | P3 | Redefines | `engine/transformation/redefines.py` | 87-184 | Multiple redefines overwrite | Two items redefine same base | `setdefault` keeps first | Dropped view | Diagnose collision | Redefines tests | None | None | Open |
| P-11 | P3 | Source model | `engine/transformation/source_model.py` | 78-86 | `scale` never populated | — | Dead field | Confusion | Remove or populate | — | None | None | Open |
| P-12 | P3 | Tests | `tests/transformation/test_parser.py`, `test_ir.py` | 244, 181 | Existence-only assertions | — | Weak tests | Missed partial parsing | Strengthen assertions | Test edits | None | None | Open |
| S-13 | P3 | Mapping | `engine/transformation/cobol_to_java_mapping.py` | 4225-4231 | PERFORM TIMES field count not validated | Field-valued TIMES | No validation | Possible bad code | Validate | PERFORM tests | None | None | Open |
| S-14 | P3 | Copybook | `engine/transformation/copybook_resolver.py` | 89-109 | Symlinked dirs may be missed | Symlinked copybook dir | `rglob` semantics | Missed copybooks | Follow symlinks | Copybook tests | None | None | Open |
| S-15 | P3 | Capability | `engine/transformation/semantic_capability.py` | 603, 672 | PERFORM TIMES pattern matches VARYING | — | Regex overlap | Minor misclassification | Tighten pattern | Capability tests | None | None | Open |
| A-4 | P3 | API | `api/service.py` | 829-831, 1022-1024 | Raw str(exc) served | Worker failure | No sanitization | Internal detail leakage | Sanitize | API tests | None | None | Open |
| A-5 | P3 | API | `api/service.py`, `api/name_derivation.py` | 1723-1724, 1736-1737, 76-78 | Silent swallowing | Read path failure | `except Exception` | Harder debugging | Log | API tests | None | None | Open |
| A-6 | P3 | API | `api/models.py`, `api/app.py` | 73-76, 1198-1232 | Paths in responses | GET /applications | Response model | Topology disclosure | Redact | API tests | None | None | Open |
| A-7 | P3 | API | (no retention code) | — | Unbounded growth | Long-running deploy | No reaper | Disk exhaustion | Add retention | API tests | None | None | Open |
| A-8 | P3 | Repo hygiene | `.gitignore` | — | `*.db-wal`/`*.db-shm` not ignored | `git add` of data/ | Missing patterns | Accidental commit of DB WAL | Add patterns | — | None | None | Open |
| A-9 | P3 | API | `api/app.py` | 369-372 | Static token | — | No expiry/rotation | Permanent leak | Token lifecycle | API tests | None | Owner (policy) | Open |
| A-10 | P3 | API | `api/app.py`, `api/service.py` | 844-845, 1716-1722 | Discovery per request | Polling | No cache | CPU amplification | Cache | API tests | None | None | Open |
| A-11 | P3 | API | `api/ingestion.py`, `api/models.py` | 5, 231-233 | Dead git_url | — | Unimplemented | Dead code | Remove or implement | — | None | None | Open |
| A-12 | P3 | API | `api/artifact_seal.py` | 90, 199 | Symlink follow on read | FS write + symlink | `rglob` follows | Marginal | Reject symlinks | API tests | None | None | Open |
| F-9 | P3 | Numeric | `engine/transformation/numeric_semantics.py`, `cobol_to_java_mapping.py` | 128-131, 390-399 | Inconsistent integer/decimal type | — | `rstrip` | Minor type inconsistency | Normalize | Numeric tests | None | None | Open |

## Additional findings (Java generation / runtime / verification)

| ID | Severity | Subsystem | File | Line | Summary | Status |
|---|---|---|---|---|---|---|
| J-1 | P0 | Generator | `engine/transformation/spring_boot_generator.py` | 958-959 | JDBC repository methods throw UnsupportedOperationException. | Open |
| J-2 | P0 | Generator | `engine/transformation/java_generator.py` | 1991-1992 | GO TO silently dropped as comment. | Open |
| J-3 | P0 | Generator | `engine/transformation/java_generator.py` | 1935-1997 | Unsupported statements return None and are omitted. | Open |
| J-4 | P1 | Generator | `engine/transformation/java_generator.py` | 151-163 | ServiceRegistry call methods are placeholders. | Open |
| J-5 | P1 | Runtime | `engine/candidate/java_adapter.py` | 197-216 | Host Java timeout discards partial stdout; inherits parent stdin. | Open |
| J-6 | P2 | Runtime | `engine/candidate/docker_java_adapter.py`, `docker_spring_boot_adapter.py` | 517-527, 644-652 | Docker timeout handlers reference None proc. | Open |
| J-7 | P2 | Runtime/Discovery | multiple | — | Swallowed exceptions in identity/probe paths. | Open |
| J-8 | P2 | Pipeline | `engine/pipeline.py` | 236-255 | Nondeterministic candidate manifest file ordering. | Open |
| J-9 | P1 | Verdict | `engine/verdict/derivation.py` | 279-313 | `all()` masks mixed infrastructure failures. | Open |
| J-10 | P2 | Parser/Copybook | multiple | — | Empty excepts in parser/copybook resolution. | Open |
| J-11 | P2 | Tests | `tests/common.py` + many | — | Tests inject stub verdicts. | Open |
| J-12 | P3 | Tests | integration tests | — | Existence-only assertions. | Open |
| J-13 | P3 | Tests | `tests/test_phase12_p2_f03_masking_skips.py` etc. | — | Skips masking generation failures. | Open |

## Additional findings (security / CI / Docker)

| ID | Severity | Subsystem | File | Line | Summary | Status |
|---|---|---|---|---|---|---|
| Dk-1 | P1 | Deployment | `docker-compose.production.yml` | 82-86, 96-97 | Docker socket mount + group_add → daemon-root-equivalent. | Open (accepted/owner) |
| Dk-2 | P2 | Deployment | `docker-compose.production.yml` | 110 | Root filesystem writable. | Open |
| Dk-3 | P2 | Execution | `engine/execution/container_hardening.py` | 52-68 | No `--read-only` root FS flag. | Open |
| Dk-4 | P3 | Images | `Dockerfile.gnucobol`, `Dockerfile.maven-offline` | — | No USER directive (root-default). | Open |
| Dk-5 | P2 | Scripts | `scripts/deploy/verify-production.sh` | 55-72 | Env-controlled path interpolated into bash -c. | Open |
| Dk-6 | P2 | Oracle | `engine/oracle/docker_adapter.py` | 74-87 | Accepts local Image ID as identity. | Open |
| Dk-7 | P2 | Oracle | `engine/oracle/adapter.py` | 47 | Default mutable tag. | Open |
| Dk-8 | P2 | Repo hygiene | `.gitignore` | — | No test-artifacts/ rule. | Open |
| Dk-9 | P3 | Dependencies | `requirements.txt`, `frontend/package.json` | — | Ranges at manifest level. | Open |
| Dk-10 | P2 | CI | `supply-chain.yml` | 39 | Audit tooling unpinned. | Open |
| Dk-11 | P3 | CI | `ci.yml` | 4-5, 135, 137, 154-156, 194, 201 | All-branch push; version probes omit hardening; frontend if:always(). | Open |
| Dk-12 | P3 | Repo hygiene | `.gitignore` | 410, 419, 351, 397 | Ignores *.kt, Makefile, Cargo.lock. | Open |
| Dk-13 | P3 | Scripts | `scripts/deploy/verify-production.sh` | 40, 9-11 | Probe omits hardening; sources arbitrary env file. | Open |
| Dk-14 | Owner | License/Signing | `PROJECT_LICENSE_DECISION.md`, `TRUSTED_ARTIFACT_SIGNING_PROPOSAL.md` | — | License/signing blocked on owner. | Owner-dependent |

## Updated summary counts

- P0: 5 (S-1, S-17, J-1, J-2, J-3) — all open
- P1: 11 (8 prior + J-4, J-5, J-9; C-1 fixed)
- P2: 36
- P3: 37
- Owner-dependent: 3 (A-1, A-3, Dk-1, Dk-14, license/signing)
- Total: ~90 findings.
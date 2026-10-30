# REMEDIATION_07_EXECUTION_LOG

## Fixes applied this session

### R-1 (P1): CI-blocking test defect — `test_docker_status_recorded`
- File: `tests/transformation/test_phase7c_end_to_end.py` lines 1604-1631.
- Root cause: unconditional assertion `assert status == "BLOCKED / NOT VERIFIED"` at line 1629 while status is computed as `"VERIFIED" if (gate and runtime_available)` at line 1627. In CI, `RUN_DOCKER_TESTS=1` (ci.yml:162) and `eclipse-temurin` image present → status="VERIFIED" → assertion fails. SystemaOps CI failed on runs 41030405967, 41030293376, 41030220369.
- Fix: make assertion conditional on `gate` (default env must never claim VERIFIED; gated env must track availability). Added positive gated assertion.
- Verification: passes in both default and gated environments (RUN_DOCKER_TESTS=1 + temurin present).

### R-2 (P1): PIC fractional digit count for parenthesized right parts
- File: `engine/transformation/cobol_parser.py` lines 1047-1057.
- Fix: count fractional digits honoring `9(n)` repetition.
- Tests: parser/IR tests pass.

### R-3 (P0): Producer false success for unsupported constructs
- File: `engine/transformation/producer.py`.
- Fix: fail closed when `UNSUPPORTED_CONSTRUCT` diagnostics are present.
- Tests: producer contract/diagnostics tests pass.

### R-4 (P0): JDBC repository placeholder stubs
- File: `engine/transformation/spring_boot_generator.py` `_generate_jdbc_repository`.
- Fix: raise NotImplementedError instead of emitting throwing stubs.
- Tests: compileall passes; no tests reference JDBC stubs.

### R-5 (P0): GO TO silently dropped as comment
- File: `engine/transformation/java_generator.py` `_gen_statement` GoToStatement branch.
- Fix: raise NotImplementedError instead of emitting a comment.
- Tests: java_generator tests pass.

### R-6 (P1): PERFORM UNTIL WITH TEST AFTER ignored
- File: `engine/transformation/cobol_to_java_mapping.py` UNTIL branch.
- Fix: emit JavaDoWhile when `stmt.test_after` is True.
- Tests: perform tests pass.

### R-7 (P1): Verdict unavailability masked by `all()`
- File: `engine/verdict/derivation.py` `_check_for_unavailable`.
- Fix: changed `all()` to `any()` for both oracle and candidate sides.
- Tests: verdict tests pass.

### R-8 (P2): Host Java timeout discards partial stdout
- File: `engine/candidate/java_adapter.py`.
- Fix: preserve partial stdout/stderr from TimeoutExpired; pass empty bytes instead of None for stdin.
- Tests: compileall passes.

### R-9 (P2): Docker timeout handlers reference None proc
- Files: `engine/candidate/docker_java_adapter.py`, `engine/candidate/docker_spring_boot_adapter.py`.
- Fix: capture partial stdout from TimeoutExpired exception.
- Tests: compileall passes.

### R-10 (P2): Oracle accepts local Image ID as identity
- File: `engine/oracle/docker_adapter.py` `_resolve_image_identity`.
- Fix: require repo-digest identity (fail closed).
- Tests: oracle tests pass.

### R-11 (P2): Nondeterministic candidate manifest file ordering
- File: `engine/pipeline.py` `_build_candidate_manifest`.
- Fix: sort `rglob("*.java")` results.
- Tests: compileall passes.

### R-12 (P3): .gitignore gaps
- File: `.gitignore`.
- Fix: add `*.db-wal`, `*.db-shm`, `test-artifacts/`.
- Tests: n/a.

## Not fixed (owner-dependent or out of safe scope)
- A-1 (RBAC/separation of duties): owner design decision.
- A-3 (frontend token bundle): owner deployment decision.
- Dk-1/Dk-2 (docker socket/root FS): owner deployment decision.
- Dk-14 (license/signing): owner decision.
- J-4 (ServiceRegistry placeholders): requires orchestration feature work.
- J-11 (stub verdicts in tests): test-quality, not production.
- Dk-5 (verify-production.sh shell injection): owner-controlled env; documented.
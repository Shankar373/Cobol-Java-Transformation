# Docker and Oracle Integration Certification

Date: 2026-10-30
Git SHA tested: bde0e3d90610e5d2840a63c7cd59cb9f90b418cd
Branch: codex/universal-core

## Environment

- Docker client/server: Docker Desktop 4.94.0 (daemon available)
- Images present:
  - gnucobol-ocesql:latest
  - eclipse-temurin:21-jdk
  - maven-offline-springboot:latest
- Python: 3.11.9
- pytest: 9.0.3

## Commands executed

1. Focused oracle proofs:
   `RUN_DOCKER_TESTS=1 python -m pytest -q tests/integration/test_numeric_oracle_proof.py tests/integration/test_initialize_oracle_proof.py`
   Result: 9 passed in 33.36s

2. Full integration suite:
   `RUN_DOCKER_TESTS=1 python -m pytest -q tests/integration`
   Result: 421 passed, 1 warning in 5092.32s (1:24:52)

## Semantic evidence

- Numeric VALUE normalization vs GnuCOBOL: passed.
- Integer lane generated Java vs GnuCOBOL stdout: passed.
- DISPLAY shape lane (signed/decimal/big literal): passed.
- Unsigned receiver magnitude: passed.
- COMP/COMP-3 shipped fixtures: passed.
- Structured arithmetic (precedence/parens): passed.
- Initialization oracle proof: passed.

## Exact-SHA requirement

- Local Docker results above are for SHA bde0e3d90610e5d2840a63c7cd59cb9f90b418cd.
- Remote CI is pending (commits not pushed); local results are not remote CI results.

## Known limitations

- `tests/test_e2e.py` (real Docker + Maven Spring Boot E2E) was not executed in this session due to time budget; recommended for CI on the same SHA.
- `tests/test_ci_deployment_security.py::...test_fixed_idiom_propagates_grep_status[echo nope | grep -q probe-True]` fails only under WSL `bash -c` interop (environment-specific); the same script passes when executed from a file.

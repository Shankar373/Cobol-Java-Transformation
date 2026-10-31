# REPOSITORY_BASELINE_REPORT

- Report date: 2026-10-31
- Branch: codex/universal-core
- Baseline HEAD (pre-change): ee4dd06f3dc6c148d745cff33883dcb133135382
- Remote HEAD verified: origin/codex/universal-core == ee4dd06f3dc6c148d745cff33883dcb133135382
- Working tree: 3 untracked top-level scripts preserved; no tracked modifications discarded.

## Inventory summary
- Python backend: api/, engine/, contracts/, tools/
- Frontend: frontend/ (React + TypeScript, Vite)
- Tests: tests/ (4550 collected locally; transformation suite 2204 passed)
- CI: .github/workflows/ci.yml (capability-truth, phase1-ingestion, backend-oracle, frontend)
- Docker: Dockerfile.gnucobol, Dockerfile.maven-offline, Dockerfile.production, docker-compose.production.yml

## Key modules
- COBOL parser: engine/transformation/cobol_parser.py
- IR: engine/transformation/ir.py
- Mapping: engine/transformation/cobol_to_java_mapping.py
- Java generator: engine/transformation/java_generator.py, spring_boot_generator.py
- Producer: engine/transformation/producer.py
- API: api/app.py, api/service.py, api/store.py
- Verdict: engine/verdict/derivation.py
- Pipeline: engine/pipeline.py

## Baseline test evidence
- Transformation tests: 2204 passed, 4 skipped (Docker-gated)
- API tests: 51 passed
- API security tests: 32 passed
- Capability-truth subset: 355 passed

## Known limitations
- Docker-gated oracle tests not run in this local environment.
- Full 4550-test run not completed locally (process hung on docker/network); capability-truth + transformation + api suites green.
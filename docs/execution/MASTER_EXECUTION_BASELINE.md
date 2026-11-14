# Master Execution Baseline

Branch: `codex/autonomous-stage1-enterprise-completion`
Start HEAD: `d68331f1ed2f6dac9c16da887f0043dde8cf1682` (from `feat/phase3-coverage`, clean tree)
Toolchain (local): Python 3.11.9, Java 21, Maven 3.9.16, Docker 29.8.2, Node 22.
Not available locally: `cobc` (only inside the gnucobol-ocesql image), `redis-server`, `psql`.

Evidence below comes from read-only audits of the code at the start HEAD. Items
marked "not verified" were not opened in full.

| Area | State | Evidence | Remaining work |
|---|---|---|---|
| COBOL parser / IR / Java generator | IMPLEMENTED (certified subset) | `engine/transformation/*`, certification workflow over 4 runtimes | Re-verify Stage 1 subset at the end |
| COPYBOOK / FD / SELECT | IMPLEMENTED | `copybook_resolver.py`, `cobol_parser.py`, `tests/test_copybook_*.py` | Re-check against current code |
| INDEXED / RELATIVE | PARTIAL, emulated | `semantic_capability.py`: "emulated side file, not VSAM"; primary key at offset 0, ACCESS DYNAMIC only | Real KSDS/ESDS/RRDS semantics |
| ALTERNATE KEY | UNSUPPORTED | parsed, reported UNSUPPORTED per instance | Implement or keep explicit refusal |
| ACCESS RANDOM | no oracle proof | `semantic_capability.py` | Oracle proof or refusal |
| VSAM export / API / streaming | MISSING | no VSAM module, route or manifest | Phase 5 (new build) |
| RDW / variable-length | MISSING | only comments in `engine/` | Phase 5 |
| Checkpoint / resume | MISSING | none found | Phase 5 |
| Java consumer streaming | NOT STREAMING | `file_io_support_template.py` loads `.idx` fully; `spring_boot_generator.py:983,988` uses `Files.readAllLines`; `readRecord` re-reads the file per call | Phase 6 |
| GnuCOBOL oracle | IMPLEMENTED | `engine/oracle/*`, GnuCOBOL 3.1.2 pinned in `Dockerfile.gnucobol` | Docker-only locally |
| Runtimes | adapters for spring_boot, plain_java, jakarta_ee, quarkus, micronaut | `runtime_adapters.py:23-29`; Quarkus/Micronaut completeness not verified | Verify each by compile and run |
| API | FastAPI, SQLite, in-process threads (4 jobs) | `api/store.py`, `api/service.py` | Phase 1 |
| Auth | single optional shared bearer token, no RBAC | `api/app.py` | Phase 7 |
| ZIP ingestion | whole archive in RAM | `api/ingestion.py:159` `io.BytesIO(data)`; limits 50 MiB / 1000 entries / 200 MiB / ratio 100 | Phase 3 |
| Request limits | 50 MiB request, 10 MiB file, one global value | `api/app.py:118-123` | Phase 0 re-evaluation |
| Object storage | MISSING (local filesystem only) | `api/paths.py` | Phase 1 |
| PostgreSQL | MISSING | no dependency, SQLite store | Phase 1 |
| Redis / Celery | MISSING | not in requirements or compose | Phase 1 |
| GitHub ingestion | MISSING | no code found | Phase 2 |
| Discovery / capability graph | IMPLEMENTED | `engine/transformation/application_discovery.py`, `engine/modernization/capability_analyzer.py` | Scale to Phase 4 inventory |
| Frontend | React 18 / Vite 6 / Vitest 5 | `frontend/src/pages`: Dashboard, NewModernization, ModernizationRun; no VSAM or discovery page | Phase 3, 4, 5 UI |
| CI | ci.yml (lint, hermetic backend, oracle backend 180m, frontend), certification.yml (`[certify]` marker, 4 runtimes, ~1h each), supply-chain.yml | `.github/workflows/` | Add jobs for new suites |
| Compose / Docker | `api` + `nginx` only | `docker-compose.production.yml` | Add Postgres, Redis, worker, MinIO |
| ADRs | 0001-0008; 0009/0010 reserved | `docs/decisions/` | New ADRs from 0011 |

## Baseline test run
Command: `python -m pytest -q -W error::pytest.PytestWarning tests` (hermetic lane).
Result: recorded in `MASTER_EXECUTION_LEDGER.md` when the run completes.

## Constraint on scope
Stage 1 requires VSAM. The repo has an emulated INDEXED/RELATIVE lowering, not a
VSAM migration engine. Phase 5 and the Stage 1 VSAM closure are new builds.
IBM runtime verification is not possible here and will not be claimed.

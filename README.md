# SystemaOps

**A deterministic, evidence-based platform for modernizing legacy mainframe estates to Java.**

SystemaOps does not use an LLM anywhere in analysis, transformation or verification. Every transformation is
rule-based and reproducible; every claim of behavioural equivalence is backed by a recorded comparison against a
reference run (the GnuCOBOL oracle); everything it cannot prove fails closed and is reported by name.

> **Current baseline:** `main` @ `b0c1f6b` (merge of PR #9). The certified corpus on this tree is
> **44 of 54 applications VERIFIED on each of four Java runtimes** (`spring_boot`, `plain_java`, `quarkus`,
> `micronaut` command mode), 9 refused by name, 1 UNAVAILABLE (GnuCOBOL rejects the source), every VERIFIED
> result independently re-checked (AGREE 44/44). Evidence: [`docs/reports/PHASE5_FINAL_CERTIFICATION.md`](docs/reports/PHASE5_FINAL_CERTIFICATION.md).
> The audit that produced this README: [`docs/audits/ENTERPRISE_ALIGNMENT_AUDIT.md`](docs/audits/ENTERPRISE_ALIGNMENT_AUDIT.md);
> the running record of work: [`docs/audits/EXECUTION_LEDGER.md`](docs/audits/EXECUTION_LEDGER.md).

## What SystemaOps is

The long-term scope is **enterprise-wide legacy modernization**, not a COBOL-to-Java converter alone:
COBOL, JCL, CICS, DB2, VSAM, IMS, MQ, copybooks, data flows, integrations, batch processing and operational
dependencies, modelled as one dependency graph with a proof state on every edge.

The target architecture is a **hybrid Java architecture**: tightly coupled business workflows stay together;
capabilities that decompose cleanly become independently deployable services. Data targets are pluggable:
**DB2/IMS coexistence** and **selective migration to PostgreSQL or other databases**.

## What it is today (and what it is not)

| Area | Status | What that means |
|---|---|---|
| COBOL batch programs | **Certified subset** | Deterministic lowering to Java on 4 runtimes; compared with GnuCOBOL on stdout, stderr, exit status and files |
| Sequential, indexed, relative files | **Proven, narrow** | Emulated side files with FILE STATUS; not real VSAM |
| Static CALL, copybooks, multi-program | **Certified subset** | In-process calls inside one generated application |
| JCL | **Analysis only** | Parsed, linked to programs and datasets, reported; no Java is generated from JCL |
| DB2 / EXEC SQL | **Detected and blocked** | Programs using it are classified UNSUPPORTED; a SQLite-backed experiment exists but is not part of the product |
| CICS, IMS, MQ | **Detected and blocked** | Dependencies are listed in the ledger; no transformation or runtime |
| VSAM utilities (IDCAMS), GDG | **Not supported** | Classified UNSUPPORTED |
| Hybrid / decomposed output, PostgreSQL targets | **Roadmap** | Not implemented; no claim is made |
| Application servers (Jakarta EE server, WildFly, Liberty ...) | **Not supported** | `jakarta_ee` produces a plain jar and is outside the certified four |
| Control plane | **Pilot-grade** | One shared API token, in-process jobs, single node; **not certified for production** (see [`docs/reports/PHASE5_RELEASE_READINESS.md`](docs/reports/PHASE5_RELEASE_READINESS.md)) |

This is a certified *subset*, not universal COBOL compatibility. Unsupported, partial and unproven constructs
are identified explicitly (see [`docs/CAPABILITY_MATRIX.md`](docs/CAPABILITY_MATRIX.md) and
[`docs/SEMANTIC_PROOF_MATRIX.md`](docs/SEMANTIC_PROOF_MATRIX.md)).

## How it works

```
COBOL/JCL ZIP -> secure ingestion -> discovery & dependency graph -> semantic IR -> capability analysis
 -> transformation plan -> deterministic lowering -> Java generation (per runtime)
 -> Docker candidate execution + GnuCOBOL oracle execution -> comparison -> evidence integrity
 -> deterministic verdict -> FastAPI control plane -> React UI
```

Two stages share one control plane: **generation** (`engine/modernization/pipeline.py`) and **validation**
(`engine/pipeline.py`); `api/service.py` runs them as background jobs.

Verdicts are `VERIFIED` only when every declared observable matches, `UNAVAILABLE` when the reference cannot run,
and otherwise fail closed. A build or infrastructure failure is never evidence.

## Enterprise roadmap: what exists and what does not

The 20-unit plan is in [`docs/audits/ENTERPRISE_ALIGNMENT_AUDIT.md`](docs/audits/ENTERPRISE_ALIGNMENT_AUDIT.md);
the per-unit result, with the CI, supply-chain and four-runtime certification run that gated each commit, is in
[`docs/audits/EXECUTION_LEDGER.md`](docs/audits/EXECUTION_LEDGER.md) (a unit is "done" there only when its own
gates passed). Capability claims live in [`docs/CAPABILITY_MATRIX.md`](docs/CAPABILITY_MATRIX.md).

| Area | State |
|---|---|
| JCL | Preprocessor (PROC/symbolics/SET), DD binding and dataset catalogue, a Java job launcher with COND, dispositions, GDGs, inline data and native IEFBR14/IEBGENER/IDCAMS. Utility and GDG behaviour is from documented semantics, **not** an IBM/JES oracle |
| COBOL | ASSIGN ddnames, keyed `ACCESS MODE RANDOM`, `INSPECT` (GnuCOBOL-proven). Not done: `SEARCH`, `SORT`, `MERGE`; numeric-edited PIC is held uncommitted pending authorization |
| DB2 / SQL | `EXEC SQL` kept as IR; a pluggable `DatabaseDialect` (DB2, PostgreSQL); JDBC generation for a certified subset, equal to an OCESQL + PostgreSQL 14 reference; fixed-width record migration with reconciliation. **Not DB2-verified**; indicators, WHENEVER and dynamic SQL are refused |
| MQ / IMS / CICS | Versioned simulators SIMMQ-1, SIMDLI-1, SIMCICS-1 with Java twins and conformance suites, label `SIMULATOR_VERIFIED`. **Not wired** into generated code: `EXEC CICS`, `EXEC DLI` and MQ calls stay unsupported |
| Estate | Dependency graph with a proof state on every edge, read-only API and UI, a decomposition *proposal* for review (no multi-artifact or container generation) |
| Control plane | Role-based access control on bearer tokens. OIDC, signing keys and Docker socket isolation need the owner: see [`docs/audits/OWNER_DECISIONS.md`](docs/audits/OWNER_DECISIONS.md) |

Verdict labels never overstate: `VERIFIED` (GnuCOBOL oracle), `SIMULATOR_VERIFIED` (equal to an in-repo
specification), and nothing here can produce an IBM-verified verdict.

## Quick start

**Prerequisites:** Python 3.11 (`python`), Node 22 + npm (`.nvmrc`), Docker.

```bash
# 1. Backend (FastAPI control plane, port 8000). Auth is OFF by default; set CONTROL_PLANE_API_TOKEN to require a
#    bearer token on every route except /health and /ready. CONTROL_PLANE_ENV=production fails closed without a
#    token of at least 32 characters and without SYSTEMAOPS_ORACLE_DIGEST (see docs/deployment/PRODUCTION.md).
python -m pip install --require-hashes -r requirements-dev.lock
python -m uvicorn api.app:app --port 8000
curl http://localhost:8000/health        # {"status":"ok"}
curl http://localhost:8000/ready         # 200 when database/workspace/staging are usable, else 503

# 2. Frontend (Vite dev server on 5173, proxies the API on 8000)
cd frontend && npm ci && npm run dev     # open http://localhost:5173/app/
```

**Docker execution lanes** (needed for real end-to-end runs; the same commands CI uses):

```bash
docker build --pull -f Dockerfile.gnucobol -t gnucobol-ocesql:latest .
docker build --pull -f Dockerfile.maven-offline -t maven-offline-springboot:latest .
python scripts/record_docker_image_provenance.py     # required whenever the Maven image is rebuilt
RUN_DOCKER_TESTS=1 python -m pytest -q tests/test_e2e.py
```

The full command reference, troubleshooting and the exact pinned image digests are archived with the previous
README in [`docs/archive/README_2026-11-03.md`](docs/archive/README_2026-11-03.md) and maintained in
[`CONTRIBUTING.md`](CONTRIBUTING.md) and [`docs/deployment/`](docs/deployment/).

## Verification and CI

- **CI** (`.github/workflows/ci.yml`): capability-truth gate, lint, hermetic backend suite, the Docker/GnuCOBOL-oracle
  suite, frontend (tests, type check, production build), plus the supply-chain workflow.
- **Corpus certification** (`.github/workflows/certification.yml`): runs every fixture application through the API
  on each runtime, re-checks every VERIFIED application with an independent verifier, and fails unless every verdict
  equals the accepted evidence. It runs for commits tagged `[certify]` and on manual dispatch.
- Test counts and run ids change on every commit; they are recorded per commit in
  [`docs/audits/CHANGE_LEDGER.md`](docs/audits/CHANGE_LEDGER.md) and
  [`docs/audits/EXECUTION_LEDGER.md`](docs/audits/EXECUTION_LEDGER.md), not here.

## Documentation

[`docs/README.md`](docs/README.md) is the index. Start with the [capability matrix](docs/CAPABILITY_MATRIX.md),
[runtime adapters](docs/RUNTIME_ADAPTERS.md), [known issues](docs/KNOWN_ISSUES.md), the
[full audit](docs/audits/FULL_AUDIT_2026-11-03.md) and [production deployment](docs/deployment/PRODUCTION.md).
Historical material (dated snapshots, earlier READMEs, the original master specification) is kept under
[`docs/archive/`](docs/archive/) and is not current.

Licensed under the Apache License 2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)).

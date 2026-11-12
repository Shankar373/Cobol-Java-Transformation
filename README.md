# SystemaOps

**A deterministic, evidence-based platform for modernizing legacy mainframe estates to Java.**

SystemaOps does not use an LLM anywhere in analysis, transformation or verification. Every transformation is
rule-based and reproducible; every claim of behavioural equivalence is backed by a recorded comparison against a
reference run (the GnuCOBOL oracle); everything it cannot prove fails closed and is reported by name.

> **Where things stand.** Work happens on `impl/enterprise-platform` (`main` is at `b0c1f6b`, the Phase 5 baseline, and is
> not touched without the owner's approval). The exact verified commit, its workflow links, test counts, the staging
> deployment, limitations and the open-PR audit are in [`docs/PROTOTYPE_HANDOFF.md`](docs/PROTOTYPE_HANDOFF.md).
> The certified corpus on that branch is **45 of 55 applications VERIFIED on each of four Java runtimes**
> (`spring_boot`, `plain_java`, `quarkus`, `micronaut` command mode), 9 refused by name, 1 UNAVAILABLE (GnuCOBOL rejects
> the source), every VERIFIED result independently re-checked (AGREE 45/45); on `main` it is 44 of 54
> ([`docs/reports/PHASE5_FINAL_CERTIFICATION.md`](docs/reports/PHASE5_FINAL_CERTIFICATION.md) records that earlier baseline).
> The audit behind the roadmap: [`docs/audits/ENTERPRISE_ALIGNMENT_AUDIT.md`](docs/audits/ENTERPRISE_ALIGNMENT_AUDIT.md);
> the running record of work: [`docs/audits/EXECUTION_LEDGER.md`](docs/audits/EXECUTION_LEDGER.md).
>
> **Prototype, not a product.** It is a working deterministic core with documented limits; it is **not certified for
> production** and makes **no IBM equivalence claim** (the only reference runtimes are GnuCOBOL 3.1.2, OCESQL + PostgreSQL 14
> and in-repo simulators).

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
| JCL | **Partial** | Parsed, linked to programs and datasets; a bounded job runner executes the step programs and its verification lane compares them with GnuCOBOL (step programs only; JCL itself has no IBM reference) |
| DB2 / EXEC SQL | **Certified bounded subset, not DB2** | A documented EXEC SQL subset lowers to JDBC and is compared against OCESQL + PostgreSQL 14; DB2 behaviour is unverified and anything outside the subset is blocked by name |
| CICS, IMS, MQ | **Simulator only, blocked in the product** | Python/Java simulator libraries exist (SIMULATOR_VERIFIED against their own specs); `EXEC CICS`, DL/I and MQI programs are classified UNSUPPORTED and no transformation or runtime is wired in |
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
| COBOL | ASSIGN ddnames, keyed `ACCESS MODE RANDOM`, `INSPECT` (literal subset), file-to-file `SORT`/`MERGE`, linear `SEARCH` and `SEARCH ALL`, `GO TO`, reference modification, qualified names, `**`, a few intrinsic functions, numeric-edited PICTURE, VSAM-style keyed files with alternate keys and packed/binary record bytes - GnuCOBOL-proven. **Narrow shapes only**: alternate-key browsing (`START` / `READ NEXT`: ACCESS DYNAMIC, two alternate keys, one duplicate and one unique, `PIC X(2)` fields, FILE STATUS only), `NEXT SENTENCE` (last statement of a branch of a single `IF ... ELSE` sentence), `MOVE` / `ADD` / `SUBTRACT CORRESPONDING` (single-line statement between two groups). Not done: `SORT` INPUT/OUTPUT PROCEDURE with `RELEASE`/`RETURN`, `OCCURS DEPENDING ON`, EBCDIC data, `INSPECT` with data-name operands, VSAM ESDS/RRDS |
| DB2 / SQL | `EXEC SQL` kept as IR; a pluggable `DatabaseDialect` (DB2, PostgreSQL); JDBC generation for a certified subset, equal to an OCESQL + PostgreSQL 14 reference; fixed-width record migration with reconciliation. **Not DB2-verified**; indicators, WHENEVER and dynamic SQL are refused |
| MQ / IMS / CICS | Versioned simulators SIMMQ-1, SIMDLI-1, SIMCICS-1 with Java twins and conformance suites, label `SIMULATOR_VERIFIED`. **Not wired** into generated code: `EXEC CICS`, `EXEC DLI` and MQ calls stay unsupported |
| Estate | Dependency graph with a proof state on every edge, read-only API and UI, a decomposition *proposal* for review (no multi-artifact or container generation) |
| Quality gates | Capability gate, hermetic backend and frontend on Linux **and Windows**, a mypy ratchet (new code type-clean) and a coverage floor (88%, 90% measured); evidence classes per capability in [`docs/audits/CAPABILITY_STATUS.md`](docs/audits/CAPABILITY_STATUS.md) |
| Control plane | One shared bearer token by default; optional role tokens (`viewer` / `operator` / `approver`, `CONTROL_PLANE_ROLE_TOKENS`). The approver name on an approval is caller-supplied text, not a verified identity. OIDC, signing keys and Docker socket isolation need the owner: see [`docs/audits/OWNER_DECISIONS.md`](docs/audits/OWNER_DECISIONS.md) |

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

**Choosing a runtime.** There is no default: `POST /applications` requires `target_runtime` (`plain_java`, `spring_boot`,
`quarkus` or `micronaut`), the UI starts on "Select a runtime" and Start stays disabled until one is chosen, and the chosen
runtime is the one generated and executed (`tests/test_runtime_selection.py`).

**Tests** (verified commands): backend hermetic `python -m pytest -q` (Docker suites skip without `RUN_DOCKER_TESTS=1`);
frontend `cd frontend && npm test && npm run lint && npm run build`; lint `ruff check .`; types `python tools/mypy_gate.py`.

**Docker execution lanes** (needed for real end-to-end runs; the same commands CI uses):

```bash
docker build --pull -f Dockerfile.gnucobol -t gnucobol-ocesql:latest .
docker build --pull -f Dockerfile.maven-offline -t maven-offline-springboot:latest .
python scripts/record_docker_image_provenance.py     # required whenever the Maven image is rebuilt
RUN_DOCKER_TESTS=1 python -m pytest -q tests/test_e2e.py
```

A localhost-only staging deployment (TLS, secrets, restart, backup / restore, rollback, an end-to-end check over HTTPS) is
documented in [`docs/deployment/PRODUCTION.md`](docs/deployment/PRODUCTION.md) and was executed; results are in the handoff.

The full command reference, troubleshooting and the exact pinned image digests are archived with the previous
README in [`docs/archive/README_2026-11-03.md`](docs/archive/README_2026-11-03.md) and maintained in
[`CONTRIBUTING.md`](CONTRIBUTING.md) and [`docs/deployment/`](docs/deployment/).

## Validation summary and what is not proven

`GET /runs/{id}/validation-summary` (JSON, or `?format=markdown`) returns a deterministic per-run summary: Conversion
(SUCCESS/FAIL), Compilation (PASS/FAIL, with the JDK recorded in the evidence; the build and run image uses JDK 21 and the
generated projects target Java 21, above the required 17), Runtime (PASS/FAIL), Business equivalence
(PASS/WARNING/FAIL/NOT_EVALUATED, from the comparator results only), the named unsupported constructs and the warnings.
Every field is derived from stored evidence; a field with no evidence is `NOT_RUN` or `NOT_EVALUATED`, never PASS, and a
build failure is Compilation FAIL, not a verdict. A run whose build could not even start (for example a local Maven image
that does not match the pinned image identity, see `docs/PROTOTYPE_HANDOFF.md`) also shows Compilation FAIL.

**Not proven:** equivalence holds only for the recorded comparison input, against GnuCOBOL 3.1.2 - there is **no IBM runtime
evidence** and no universal COBOL compatibility claim. **Jakarta EE is not certified** (a generation profile only).
**Quarkus and Micronaut are certified in command mode only** (no HTTP, no native image). **REST/HTTP behaviour of a
generated application is not verified.** The product is a prototype; production readiness is NOT READY.

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

# Enterprise modernization gap matrix (2026-11-13)

One row per area. Status uses only: `IMPLEMENTED_AND_VERIFIED`, `IMPLEMENTED_NOT_RUNTIME_VERIFIED`, `PARTIAL`,
`SIMULATOR_VERIFIED`, `UNSUPPORTED`, `NOT_IMPLEMENTED`, `EXTERNAL_DEPENDENCY`, `OWNER_DECISION_REQUIRED`. "Evidence" names
the environment that produced the proof. Nothing is `IBM_RUNTIME_VERIFIED`. Sources: code and tests in this repository
([FINAL_MASTER_AUDIT_REPORT.md](../FINAL_MASTER_AUDIT_REPORT.md), [FINAL_GAP_REGISTER.md](../FINAL_GAP_REGISTER.md),
[CAPABILITY_MATRIX.md](../CAPABILITY_MATRIX.md)) and the [research report](../research/REAL_ENTERPRISE_COBOL_TO_JAVA_REQUIREMENTS.md).

## Language and data

| Area | Status | Evidence | Main gap | Plan |
|---|---|---|---|---|
| COBOL batch subset (arithmetic, control flow, strings, tables, copybooks, static CALL) | IMPLEMENTED_AND_VERIFIED | GnuCOBOL 3.1.2 differential, 45 of 55 corpus applications on 4 runtimes | not universal COBOL; no IBM Enterprise COBOL run | extend by construct with differential tests |
| File ownership and entrypoint selection (G-14, G-15) | IMPLEMENTED_AND_VERIFIED | unit and regression tests; corpus unchanged | residual G-22..G-24 | close residuals |
| Sequential, indexed, relative files | IMPLEMENTED_AND_VERIFIED (bounded) | GnuCOBOL differential | not VSAM; alternate keys one shape | [Stage 1](STAGE_1_VSAM_IMPLEMENTATION_PLAN.md) |
| VSAM KSDS (IBM behaviour) | PARTIAL | GnuCOBOL INDEXED only | ordering above ASCII, RBA, spanned, CI/CA | Stage 1 + IBM |
| VSAM ESDS | NOT_IMPLEMENTED | none | no local reference | Stage 1; EXTERNAL_DEPENDENCY |
| VSAM RRDS | PARTIAL | GnuCOBOL RELATIVE | slot reuse, variable RRDS | Stage 1 |
| IDCAMS | PARTIAL (`DELETE`, `DEFINE GDG`, `REPRO`, `SET MAXCC`); `DEFINE CLUSTER`/`LISTCAT`/`BLDINDEX`/`ALTER` NOT_IMPLEMENTED | documented semantics, no oracle | no cluster catalogue | Stage 1 |
| EBCDIC key collation | IMPLEMENTED_NOT_RUNTIME_VERIFIED | deterministic tests (`engine/vsam/collation.py`) | no EBCDIC run | Stage 1 |
| Migration reconciliation report | IMPLEMENTED_NOT_RUNTIME_VERIFIED | deterministic tests (`engine/vsam/reconcile.py`) | no field-level translation, no restart, no volume test | Stage 1 next slice |
| SQL to fixed-width data migration | IMPLEMENTED_AND_VERIFIED (subset) | `engine/sql/migration.py` tests | not Db2 | Stage 2 |
| Packed and binary numeric data | IMPLEMENTED_AND_VERIFIED | GnuCOBOL differential | EBCDIC data | Stage 1 |

## Subsystems

| Area | Status | Evidence | Main gap | Plan |
|---|---|---|---|---|
| JCL parse, link, job runner | PARTIAL | documented semantics; step programs vs GnuCOBOL | not JES; no `RESTART`, checkpoint restart | [Stage 2](STAGE_2_JCL_DB2_IMPLEMENTATION_PLAN.md) |
| Db2 / `EXEC SQL` | PARTIAL | OCESQL + PostgreSQL 14 (controlled portable) | no Db2 runtime; indicators, `WHENEVER`, dynamic SQL refused | Stage 2; EXTERNAL_DEPENDENCY |
| CICS | SIMULATOR_VERIFIED, refused in product | SIMCICS-1 | no CICS runtime; G-22 | [Stage 3](STAGE_3_CICS_IMS_MQ_IMPLEMENTATION_PLAN.md) |
| IMS TM / IMS DB | SIMULATOR_VERIFIED, refused in product | SIMDLI-1 | no IMS runtime | Stage 3 |
| IBM MQ | SIMULATOR_VERIFIED, refused in product | SIMMQ-1 | no MQ runtime, licence undecided | Stage 3; OWNER_DECISION_REQUIRED |
| Git ingestion | NOT_IMPLEMENTED | none | G-06 | owner priority |
| Four Java runtimes | IMPLEMENTED_AND_VERIFIED (plain_java, spring_boot); quarkus/micronaut command mode only | corpus certification | HTTP/REST unverified; `jakarta_ee` not certified | per runtime |
| Application decomposition | PARTIAL | proposal for review, no multi-artifact output | no generation of services | Stage 4 |

## Platform

| Area | Status | Evidence | Main gap | Owner action |
|---|---|---|---|---|
| Docker isolation | PARTIAL | hardened containers; the API container mounts `docker.sock` (G-01) | worker/API isolation, rootless or remote workers | OWNER_DECISION_REQUIRED |
| Authentication and RBAC | PARTIAL | static bearer tokens, 3 roles | no OIDC, revocation, rotation, per-resource ownership; approver name is caller text (G-02) | EXTERNAL_DEPENDENCY (identity provider) |
| Artifact integrity | PARTIAL | SHA-256 hash seal | not a signature; no key custody (G-03) | EXTERNAL_DEPENDENCY (KMS/HSM, keys) |
| Persistence and jobs | PARTIAL | SQLite; in-process daemon threads | a worker or process restart loses running jobs; no leases, retry or idempotency (G-04) | design and migration plan |
| Observability | PARTIAL | structured evidence per run | no correlation IDs across services, alerts, retention policy | design |
| Performance and DR | NOT_IMPLEMENTED | none | no load, failover or restore test at scale | Stage 4 |
| Certification evidence | IMPLEMENTED_AND_VERIFIED | `certification_summary.json` derived from evidence, README counts checked (G-17) | CI does not emit it per run (G-25) | engineering |

## Dependencies and licences

| Component | Role | In production path | Licence / note |
|---|---|---|---|
| GnuCOBOL 3.1.2 | reference compiler and runtime | test and verification only | LGPL/GPL family; not redistributed in generated output (see `THIRD_PARTY_NOTICES.md`) |
| OCESQL + PostgreSQL 14 | SQL reference | test and verification only | see notices |
| Spring Boot / Quarkus / Micronaut / Maven | generated project targets and build image | generated output and build | permissive; versions pinned in the build image |
| Spring Batch | JCL modernization profile target | generated output | Apache-2.0; check version vs JDK before upgrading |
| ProLeap | optional parser cross-check (not wired) | no | MIT |
| OpenSourceCOBOL4J (`producers/opensource4j.py`) | experimental producer | **not** in the primary path | needs a separate legal, technical and differential evaluation first |
| IBM JCC, JCICS, IMS drivers, IBM MQ classes | real-environment integration | no | proprietary; `OWNER_DECISION_REQUIRED` and licensed access |
| ECC / Claude Code | development tool | **no** | not a runtime dependency; SystemaOps has no LLM dependency |

## LLM-free check

Searched for LLM and agent-framework imports in `engine/`, `api/`, `scripts/` and the requirements locks: none are used by
the product (earlier audit; three comments mention the word only). `OBSERVED_REPOSITORY`.

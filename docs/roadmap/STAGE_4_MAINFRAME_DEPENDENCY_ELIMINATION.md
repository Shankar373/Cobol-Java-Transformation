# Stage 4 - Mainframe dependency elimination: plan (2026-11-13)

Not implemented. A Java application that compiles and runs is not evidence that an enterprise can shut down a mainframe
dependency. The real production case behind this plan (Venerable, [AWS APN blog](https://aws.amazon.com/blogs/apn/how-venerable-accelerated-growth-by-modernizing-its-mainframes-on-aws/))
shows the work that surrounds translation: 110 VSAM files and 25 Db2 tables migrated, 128 KB records, EBCDIC/ASCII sort
differences, month-end peak throughput, an RTO of 4-6 hours and RPO of 15 minutes, and batch redesigned where it competed
with online work. `VERIFIED_EXTERNAL_SOURCE`; the rows below are `ENGINEERING_INFERENCE`.

## Dependency table with measurable exit criteria

| Dependency | What replaces it | Measurable exit criterion (all must hold) |
|---|---|---|
| Db2 data and SQL | target database (PostgreSQL or other), JDBC | row counts, key sets and column checksums equal per table; every SQL statement classified; dual-run query results equal for N days on production-shaped data |
| VSAM data | files or tables by organization ([Stage 1](STAGE_1_VSAM_IMPLEMENTATION_PLAN.md)) | `reconcile_migration` is `RECONCILED` for every dataset; EBCDIC-order behaviour tested; alternate indexes rebuilt and checked |
| JCL / JES scheduler | job runner plus a scheduler chosen by the owner | every job's step order, return codes and output datasets equal in dual run; restart tested after injected failure |
| Batch orchestration | Spring Batch or equivalent with durable job store | restart from a killed worker resumes without duplicate output (durable jobs, [FINAL_GAP_REGISTER G-04](../FINAL_GAP_REGISTER.md)) |
| CICS transactions | services/UI behind an API | per-transaction response and data-state equality in dual run; syncpoint/rollback cases covered; capacity test at the measured peak |
| IMS transactions / data | services and a data model | same as CICS plus hierarchical data migration reconciled |
| IBM MQ | MQ or another broker via an interface | message counts, ordering and delivery guarantees match in dual run; poison-message and backout handling tested |
| External programs and services | documented interfaces | inventory complete; every call has an owner and a replacement or a retained link |
| Encoding and interchange | explicit code-page handling at every boundary | no implicit conversion; field-level conversion tests (DISPLAY, packed, binary) |
| Security and identity | OIDC, per-resource authorisation, signed artifacts, key custody | independent security review passed; no static shared token; audit trail verified |
| Monitoring | structured logs, correlation IDs, run IDs, alerts | alert tested by fault injection; evidence retention policy in force |
| Disaster recovery | backup/restore and failover | restore tested end to end; measured RTO and RPO within the agreed targets |
| Performance | capacity at measured peak | load test at 1.5x the production peak meets the latency and batch-window targets |

## Phases

1. Discover and classify (exists: dependency graph, capability gate, decomposition proposal). Exit: inventory signed off.
2. Migrate data with reconciliation (Stage 1 tooling, Stage 2 SQL). Exit: reconciliation `RECONCILED` per dataset.
3. Run the modernised system in parallel (dual run) with automatic comparison of outputs; keep the mainframe
   authoritative. Exit: N consecutive business cycles with zero unexplained differences, including a month-end.
4. Cutover rehearsal and rollback rehearsal. Exit: rollback restores the mainframe-authoritative state within the agreed
   time.
5. Cutover, then a defined hold period with the mainframe read-only.
6. Decommission only when every row above is met and the owner signs the criteria; data retention and audit obligations
   are settled first.

Everything outside `engine/` and the corpus (customer data, dual-run harness against a real mainframe, scheduler choice,
legal retention) is `REQUIRES_OWNER_OR_CUSTOMER_INPUT`.

# Documentation index

Start with the repository [README](../README.md). For the state of the implementation branch
(`impl/enterprise-platform`): exact verified commit, workflow links, test and certification results, staging
deployment, limitations, the open-PR audit and owner decisions, read [PROTOTYPE_HANDOFF.md](PROTOTYPE_HANDOFF.md) first.

Final audit (2026-11-12): [FINAL_MASTER_AUDIT_REPORT.md](FINAL_MASTER_AUDIT_REPORT.md), [FINAL_GAP_REGISTER.md](FINAL_GAP_REGISTER.md), [FINAL_DOCUMENTATION_COVERAGE.md](FINAL_DOCUMENTATION_COVERAGE.md).
Current truth, in order:

| Question | Document |
|---|---|
| What is certified, and what is not? | [reports/PHASE5_FINAL_CERTIFICATION.md](reports/PHASE5_FINAL_CERTIFICATION.md) |
| Can it be released / what blocks production? | [reports/PHASE5_RELEASE_READINESS.md](reports/PHASE5_RELEASE_READINESS.md) |
| Which COBOL constructs are supported, with which proof? | [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md), [SEMANTIC_PROOF_MATRIX.md](SEMANTIC_PROOF_MATRIX.md) |
| What does a real enterprise modernization need, and what is the staged plan? | [research/REAL_ENTERPRISE_COBOL_TO_JAVA_REQUIREMENTS.md](research/REAL_ENTERPRISE_COBOL_TO_JAVA_REQUIREMENTS.md), [roadmap/ENTERPRISE_MODERNIZATION_GAP_MATRIX.md](roadmap/ENTERPRISE_MODERNIZATION_GAP_MATRIX.md), [roadmap/STAGE_1_VSAM_IMPLEMENTATION_PLAN.md](roadmap/STAGE_1_VSAM_IMPLEMENTATION_PLAN.md), [Stage 2](roadmap/STAGE_2_JCL_DB2_IMPLEMENTATION_PLAN.md), [Stage 3](roadmap/STAGE_3_CICS_IMS_MQ_IMPLEMENTATION_PLAN.md), [Stage 4](roadmap/STAGE_4_MAINFRAME_DEPENDENCY_ELIMINATION.md) |
| What exactly was verified on the current head? | [reports/EXACT_HEAD_ENTERPRISE_BASELINE.md](reports/EXACT_HEAD_ENTERPRISE_BASELINE.md), [reports/ACTIVE_ENGINEERING_CHECKPOINT.md](reports/ACTIVE_ENGINEERING_CHECKPOINT.md), [reports/NEXT_ENTERPRISE_ENGINEERING_SPRINT_REPORT.md](reports/NEXT_ENTERPRISE_ENGINEERING_SPRINT_REPORT.md) |
| What is known to be wrong or missing? | [KNOWN_ISSUES.md](KNOWN_ISSUES.md) |
| How is it built? | [ARCHITECTURE.md](ARCHITECTURE.md), [RUNTIME_ADAPTERS.md](RUNTIME_ADAPTERS.md), [TRUST_BOUNDARY.md](TRUST_BOUNDARY.md) |
| How is it secured? | [security/PRODUCTION_SECURITY.md](security/PRODUCTION_SECURITY.md), [reports/PHASE4_SECURITY_PRODUCTION_READINESS.md](reports/PHASE4_SECURITY_PRODUCTION_READINESS.md) |
| How is it deployed and operated? | [deployment/](deployment/), [operations/](operations/) |
| Dependencies, licences, supply chain | [supply-chain/DEPENDENCY_AUDIT.md](supply-chain/DEPENDENCY_AUDIT.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [../LICENSE](../LICENSE) |
| Architecture audit and its change ledger | [audits/ARCHITECTURE_AUDIT_2026-11-01.md](audits/ARCHITECTURE_AUDIT_2026-11-01.md), [audits/CHANGE_LEDGER.md](audits/CHANGE_LEDGER.md) |
| Full repository audit, findings and action plan (2026-11-03) | [audits/FULL_AUDIT_2026-11-03.md](audits/FULL_AUDIT_2026-11-03.md) |
| Enterprise alignment audit, target architecture and 20-unit roadmap (2026-11-03) | [audits/ENTERPRISE_ALIGNMENT_AUDIT.md](audits/ENTERPRISE_ALIGNMENT_AUDIT.md) |
| Execution ledger (units, commits, CI evidence, open decisions) | [audits/EXECUTION_LEDGER.md](audits/EXECUTION_LEDGER.md) |
| Archived README (dated snapshots, full command reference) | [archive/README_2026-11-03.md](archive/README_2026-11-03.md) |
| Phase reports (coverage, security, certification) | [reports/PHASE3_COVERAGE_EXPANSION.md](reports/PHASE3_COVERAGE_EXPANSION.md), [reports/](reports/) |
| Evidence files | [reports/evidence/](reports/evidence/) |
| Differential-sweep evidence (alternate-key browsing, CORRESPONDING) | [audits/evidence/](audits/evidence/) |
| Deployment recipe, staging drill, backup / restore / rollback | [deployment/PRODUCTION.md](deployment/PRODUCTION.md), [operations/](operations/) |

The status documents `PROJECT_STATUS.md`, `VERIFICATION_STATUS.md`, `CONTRACT_STATUS.md` and
`SYSTEMAOPS_PRODUCT_STATUS.md` are dated snapshots (each carries a banner). Three superseded duplicates
(`CURRENT_DELIVERY_STATUS.md`, `reports/CURRENT_PROJECT_STATE.md`, `reports/EXECUTION_LEDGER.md`) were removed on
2026-11-11; they remain in git history. Do not read commit SHAs or run numbers in the snapshots as current.

Everything else in `docs/` (phase completion reports, feature matrices,
audits from October 2026) is dated history: each says so in a banner, and
older root-level reports live in [reports/archive/](reports/archive/). On 2026-11-12 the dated reports and plans that
nothing referenced were deleted (listed in [FINAL_MASTER_AUDIT_REPORT.md](FINAL_MASTER_AUDIT_REPORT.md)); git history has them.

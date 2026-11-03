# Stage E — Test Naming Audit and Rename Record

**Scope:** all collected tests under `tests/` (3476 collected at baseline).
**Rule:** renames only. No test added, deleted, skipped, or modified in
assertion; no CI test-set change; collection identity stays exactly 3476.

---

## 1. Audit basis

Four per-area naming audits (Stage C, no-LLM):

| Report | Area | Reviewed | Flagged |
|---|---|---|---|
| `N1_names.md` | `tests/transformation/` | 1683 method defs / 394 class contexts / 1848 collected ids | 20 (6 misleading, 4 over-promising, 10 weak) |
| `N2_names.md` | `tests/` root files | 44 | 44 |
| `N3_names.md` | `tests/integration`, `tests/execution`, `tests/unit` | 449 methods / ~471 ids | 36 (+1 parametrize `ids=` finding, reported-not-fixed) |
| `N4_names.md` | `tests/adversarial`, `contracts`, `deployment`, `verdict`, `evidence`, `comparators`, `candidate` | 469 class+method ids | 41 rename rows (+7 param-id rows in the same table) |

Every flagged body was read; the new names describe the scenario **and**
expected outcome actually asserted (decisive assertion lines are quoted in
the per-report reason columns).

## 2. Renames applied

Applied by `stage_e_renames.py` (idempotent, exact-once anchors, class-scoped
where the finding carries `Class::method`):

| Report | Rows parsed | Method renames applied |
|---|---|---|
| N1 | 20 | 20 |
| N2 | 44 | 44 |
| N3 | 36 | 36 |
| N4 | 41 | 36 (+5 param-id-only rows deferred to §3) |
| **Total** | **141** | **136** |

### Audit-report typo corrected during application

N1 row 18 proposed the identifier
`test_roUNDED_key_appears_in_the_silent_loss_matrix` (accidental mixed case).
The applied name is the all-lowercase
`test_rounded_key_appears_in_the_silent_loss_matrix`. This is a correction
of an audit-report typo, not a scope change.

### Findings surfaced during rename application (recorded, not applied)

- **`forensic_proof.py` is never collected** (6 test functions live outside
  pytest's `test_*.py` collection). The file must **not** be renamed to make
  them collect — that would change the CI test set. Recorded as an audit
  finding only.

## 3. Parametrized node-id labels (`ids=`)

Applied by `stage_e_ids.py` — **labels only**: the number of parametrized
cases and their order (hence collection identity) are unchanged; only the
node-id text becomes descriptive.

| Site | Rows | Labels added |
|---|---|---|
| `test_evidence_trust_boundary.py` `test_valid_workload_validates` | 5 | `workload-payroll` … `workload-relative` |
| `test_evidence_trust_boundary.py` `test_valid_workload_verdict_verified` | 5 | same 5 labels |
| `test_infrastructure_attacks.py` infra matrix | 9 | `oracle-error` … `both-nonzero-exit` (derived from the tuples) |
| `test_metamorphic.py` `n_artifacts` | 4 | `artifact-count-0/1/3/10` |
| `test_silent_loss_remediation.py` verb lines | 5 | `verb-CLOSE` … `verb-WRITE-invalid-key` |
| `test_silent_loss_remediation.py` empty-IR bodies | 6 | `stmt-move` … `stmt-compute-missing-target` |
| `test_semantic_mutations.py` record sets | 6 | `missing-record` … `empty-vs-nonempty` |

**Not applied:**
- N3's single `TestGateNeverUpgrades` finding — the N3 report itself scopes
  it as "reported, not fixed" (suggestion to add `ids=` where none exist).
- N4's summary line claims "8 bare parametrized-id findings"; its findings
  table contains **7** param-id rows. The table is the source of truth; the
  count discrepancy is recorded here.

## 4. Identity proof

- **Applied for real on 2026-10-14** (`stage_e_renames.py --apply`):
  136 method renames applied, 0 problems. Before the application the
  renames had only been *audited and dry-run* — this section previously
  described the dry-run as if it were the applied state; that
  over-claim is corrected here.
- `pytest --collect-only -q` before renames: 3476 tests.
- `pytest --collect-only -q` after renames: 3476 tests (identical count;
  only method/node-id text changed).
- Focused capability-truth gate + renamed-file batch (25 files) after
  renames: **592 passed**.
- Full serialized suite after renames: **3460 passed / 4
  `RUN_DOCKER_TESTS`-gated skips / 12 failed** — every failure is in the
  Docker/timeout lanes (`test_forensic_evidence`,
  `test_inventory_generalization`, `test_phase7d_runtime`,
  `test_e2e` verdict rendering), the documented load-sensitive class
  (BL-010/BL-017 environmental baseline); every failing test **passes in
  isolation** (forensic timeout/cleanup 2/2, `TestInventoryMutations` 9/9,
  phase7d + e2e re-run clean). No failure is in a renamed file's
  assertions; the renames cannot change behavior (method-name text only).
  CI's exact-SHA run is the run of record for the Docker-gated tests.

JUnit snapshots under `test-artifacts/` are regenerated outputs; they differ
after renames and need no manual edit (and their churn stays uncommitted).

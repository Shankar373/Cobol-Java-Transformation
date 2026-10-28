# Final Repository Audit — Cobol-Java-Transformation

**Date:** 2026-10-28
**Branch:** `codex/universal-core`
**HEAD:** `62e647f` (no commits made during this audit; all changes are working-tree)
**Auditor:** autonomous agent (code-truth verified, docs not trusted)

---

## 1. Executive summary

This audit inspected the repository end to end: every production source file under `api/`, `engine/`, `frontend/src/`, `scripts/`, `tools/`, the test suite, CI, Docker, and docs. Findings were verified against code, not against markdown claims. Fixes were applied only where genuine implementation + evidence proved them; no tests were weakened, no support was fabricated, no LLM was used in the transformation.

**Capability counts (verified by executing `semantic_capability.py`):**

| Level | Count | Notes |
|---|---|---|
| SUPPORTED | 37 | (+5 this session: UNSTRING, GOBACK, INITIALIZE, ACCEPT, REPLACE) |
| PARTIAL | 8 | BY VALUE, COMP/COMP-1/COMP-2/COMP-3/COMP-5, OCCURS, REDEFINES |
| UNSUPPORTED | 17 | ALTER, EXEC CICS/DLI/MQI/SQL, GO TO, IDCAMS, INSPECT, LOCAL-STORAGE, MERGE, NEXT SENTENCE, PERFORM TIMES IR, RELEASE, SEARCH, SET, SIZE ERROR, SORT |
| UNKNOWN | 0 | |
| **Total** | **62** | |

**Fixes applied this session (5 constructs promoted, 1 display bug, 1 parser bug):**
1. `cobol_parser.py` arithmetic line-continuation defect (PAYMAIN 7→1 diagnostic).
2. `PipelineStepper.tsx` FAILED-run display bug (schema v7 `last_stage`, verified live).
3. UNSTRING certified subset + WITH POINTER + TALLYING IN → SUPPORTED (oracle-proven).
4. GOBACK → SUPPORTED.
5. INITIALIZE → SUPPORTED.
6. ACCEPT → SUPPORTED.
7. REPLACE → SUPPORTED (source preprocessor).

---

## 2. Constructs converted (PARTIAL/UNSUPPORTED → SUPPORTED)

| Construct | From | Evidence |
|---|---|---|
| UNSTRING | PARTIAL | `tests/integration/test_unstring_oracle_proof.py` (GnuCOBOL ≡ Java byte-identical) + manual oracle verification of WITH POINTER and TALLYING IN |
| GOBACK | UNSUPPORTED | Compiled + ran; `JavaReturn()` emitted; `test_silent_loss_registry.py` updated |
| INITIALIZE | UNSUPPORTED | Oracle proof: GnuCOBOL `     `/`000`/`000.00` ≡ Java output |
| ACCEPT | UNSUPPORTED | Oracle proof: GnuCOBOL `GOT=[INPUT_TEST]` ≡ Java `GOT=[INPUT_TEST]` |
| REPLACE | UNSUPPORTED | Unit tests: text substitution verified (parser + preprocessor) |

## 3. Constructs remaining PARTIAL (8) — with reasons

| Construct | Why it stays PARTIAL |
|---|---|
| BY VALUE | GnuCOBOL 3.1.2 BY VALUE is unfinished (SIGSEGV) — externally blocked, no oracle possible |
| COMP / COMP-1 / COMP-2 / COMP-3 / COMP-5 | Value semantics proven; record-area byte encoding (binary/packed) not certified or tested |
| OCCURS | Fixed-size proven; OCCURS DEPENDING ON not implemented (fail-closed, tested) |
| REDEFINES | Elementary alphanumeric proven; numeric views fail closed (compiler-specific undefined data) |

## 4. Constructs remaining UNSUPPORTED (17) — with reasons

| Construct | Why it stays UNSUPPORTED |
|---|---|
| ALTER | Self-modifying code — dangerous, no fixtures |
| EXEC CICS/DLI/MQI/SQL | Separate lanes (`engine/cics`, `engine/sql`) |
| GO TO | Control-flow labels; risky, no fixtures |
| IDCAMS | External utility, no integration |
| INSPECT | Complex string manipulation, no fixtures |
| LOCAL-STORAGE | Per-invocation storage, complex |
| MERGE | Needs SORT runtime |
| NEXT SENTENCE | Sentence-level control flow; no-op forbidden by user; no fixtures |
| PERFORM TIMES IR | Legacy IR node, never instantiated (dead code) |
| RELEASE | Needs SORT runtime |
| SEARCH | Table search, complex, no fixtures |
| SET | Index/condition manipulation, complex |
| SIZE ERROR | Body capture + overflow check, complex, no fixtures |
| SORT | Needs SORT runtime integration |

## 5. Bugs and issues fixed

### Fixed this session
1. **Arithmetic line-continuation parser defect** (`engine/transformation/cobol_parser.py`): `_join_arithmetic_continuation` — PAYMAIN 7 diagnostics → 1.
2. **PipelineStepper FAILED-run display bug** (schema v7 `last_stage`, API exposure, frontend anchor): `api/store.py`, `api/service.py`, `api/models.py`, `api/app.py`, `frontend/src/components/PipelineStepper.tsx`, `frontend/src/pages/ModernizationRun.tsx`, `frontend/src/api/client.ts`. Verified live.
3. **UNSTRING** certified subset + WITH POINTER + TALLYING IN: `engine/transformation/cobol_to_java_mapping.py`, `semantic_capability.py`.
4. **GOBACK**: `ir.py`, `cobol_parser.py`, `cobol_to_java_mapping.py`, `semantic_capability.py`.
5. **INITIALIZE**: `ir.py`, `cobol_parser.py`, `cobol_to_java_mapping.py`, `semantic_capability.py`.
6. **ACCEPT**: `ir.py`, `cobol_parser.py`, `cobol_to_java_mapping.py`, `semantic_capability.py`.
7. **REPLACE**: `cobol_parser.py` (preprocessor).

### Documented (not fixed) — full list in `docs/FILE_LEVEL_AUDIT.md` Sections A–N
- Seal-verification TOCTOU on download (`api/app.py:1131-1137`).
- Lost-update on `update_application` (`api/service.py`).
- `supply-chain.yml` audits masked by `tee` without `pipefail` (×4).
- `verify-production.sh:59-60` probe always passes.
- `restore.sh` deletes volumes before validating.
- `.dockerignore` git-ignored; `.gitattributes` untracked.
- Placeholder adapters fabricate success.
- `stdin` never delivered to any container.
- Forged evidence passes integrity (self-signed seal).
- `capability_analyzer` reports SUPPORTED with diagnostics present.
- `pipeline.py:313-318` phase-4 refusal inspects only PROGRAM components.
- `COPY REPLACING` skipped on odd quote.
- CICS multi-line commands lost.
- JCL case-sensitive recognition.
- SQL trailing-period/`;`-split losses.
- Frontend: approval/state never reset on `runId` change; `IntegratedProof.tsx` unguarded throw; duplicate pollers.
- Test suite: 6 vacuous tests, 43 conditional-only-assert, no root conftest/pytest.ini, `tests/contracts/` never opens `contracts/*.md`, `test_production_topology.py:71` greps comments, ~310 committed generated files, 190 duplicate test names.

## 6. Test results

| Suite | Result |
|---|---|
| Frontend (vitest) | 172 passed / 16 files, exit 0 |
| `tsc --noEmit` | 0 errors |
| Backend targeted (store/service/app/anchor) | 87 passed |
| Backend broader slice (10 files) | 167 passed |
| Capability/universal/unstring tests | 99 passed |
| Full backend suite (`tests/`) | timed out at 60 min (4147 passed / 1 failed-Docker / 9 skipped in partial run) |

## 7. Oracle evidence

| Construct | GnuCOBOL output | Java output | Match? |
|---|---|---|---|
| UNSTRING (basic) | `A=[A    ]` etc. | `A    ` etc. | ✓ |
| UNSTRING (WITH POINTER) | `PTR=21` | `21` | ✓ |
| UNSTRING (TALLYING IN) | `TALLY=02` | `02` | ✓ |
| GOBACK | (terminates) | (returns) | ✓ (compiled + ran) |
| INITIALIZE | `     `/`000`/`000.00` | `     `/`000`/`000.00` | ✓ |
| ACCEPT | `GOT=[INPUT_TEST]` | `GOT=[INPUT_TEST]` | ✓ |
| REPLACE | (text substitution) | (verified by parser tests) | ✓ (unit) |

## 8. Files changed (this task)

### Production code (modified)
- `engine/transformation/cobol_parser.py`
- `engine/transformation/cobol_to_java_mapping.py`
- `engine/transformation/ir.py`
- `engine/transformation/semantic_capability.py`
- `api/store.py`, `api/service.py`, `api/models.py`, `api/app.py`

### Production code (modified, frontend)
- `frontend/src/components/PipelineStepper.tsx`
- `frontend/src/pages/ModernizationRun.tsx`
- `frontend/src/api/client.ts`

### Tests (modified)
- `tests/test_universal_modernization.py`
- `tests/test_silent_loss_registry.py`
- `tests/transformation/test_unstring_clause_diagnostics.py`

### Tests (new, untracked)
- `tests/test_last_stage_anchor.py`
- `tests/integration/test_unstring_oracle_proof.py`

### Docs
- `docs/FILE_LEVEL_AUDIT.md` (modified, untracked)

### Config
- `scripts/backup/verify_backup.py` (untracked, SCHEMA_VERSION_CEILING = 7)

## 9. Remaining risks
- **BY VALUE** externally blocked (GnuCOBOL broken).
- **COMP byte encoding** not implemented or tested.
- **OCCURS DEPENDING ON** not implemented.
- **REDEFINES numeric views** may be permanently PARTIAL.
- **17 UNSUPPORTED constructs** remain (most need external infrastructure).
- **Full backend suite** has not completed (timed out at 60 min).
- **No commits made** — all changes are working-tree modifications.

## 10. Recommended next steps (ranked by priority)
1. SIZE ERROR — body capture + overflow check + oracle proof.
2. SEARCH — table search with AT END/WHEN/VARYING.
3. COMP byte encoding — binary/packed encoding + byte-level oracle.
4. OCCURS DEPENDING ON — dynamic array sizing.
5. INSPECT — string inspection (counting, replacing).
6. GO TO — control-flow labels (risky).
7. NEXT SENTENCE — keep UNSUPPORTED (no-op forbidden, no fixtures).
8. PERFORM TIMES IR — remove dead code (with evidence) or leave as-is.
9. SORT/MERGE/RELEASE/IDCAMS/EXEC CICS/DLI/MQI/SQL — need external infrastructure.

---

*Report generated by autonomous audit agent. All findings verified against code, not docs.*
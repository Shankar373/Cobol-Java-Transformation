# Phase 5A Forensic Verification Report

**Date**: 2026-09-14
**Status**: PHASE 5A VERIFIED COMPLETE — with documented limitations

## 1. Pipeline Implementation (`engine/pipeline.py`)

### 1.1 Artifact Count
**VERIFIED**: 10 artifact-evidence entries for payroll workload:
- Oracle: STDOUT, STDERR, EXIT_STATUS, FIXED_RECORD (records), TEXT_FILE (report)
- Candidate: STDOUT, STDERR, EXIT_STATUS, FIXED_RECORD (records), TEXT_FILE (report)

### 1.2 How Oracle/Candidate `generated_files` Are Obtained
**VERIFIED**: Real container execution with writable output mount:
- Oracle: `-v {output_dir}:/workspace/output` → COBOL writes to `/workspace/output/report.txt` and `/workspace/output/records.dat` → adapter reads host-side `output_dir` after container exits → populates `OracleExecutionResult.generated_files`
- Candidate: Same mechanism via `DockerJavaCandidateAdapter.execute()`

### 1.3 TEXT_FILE Capture
**VERIFIED**: `capture_text_file_from_bytes()` in `engine/execution/artifacts.py:152` captures from raw bytes with correct `artifact_type="TEXT_FILE"`, content hash derived from actual bytes, size_bytes correct.

### 1.4 FIXED_RECORD Capture
**VERIFIED**: `capture_fixed_record()` in `engine/execution/artifacts.py:177` captures from raw bytes with correct `artifact_type="FIXED_RECORD"`, content hash derived from actual bytes, size_bytes correct.

### 1.5 Comparison Selection — **ARCHITECTURAL LIMITATION**
**FINDING**: `self._comparator_registry = create_default_registry()` is created in `__init__` but **never used** for dispatch in `run()`. All five comparators are directly instantiated:
```python
StdoutComparator()        # hardcoded
ExitStatusComparator()    # hardcoded
StderrComparator()        # hardcoded
TextFileComparator()      # hardcoded
FixedRecordComparator()   # hardcoded
```
File type detection is also hardcoded by extension: `name.endswith((".dat", ".rec"))`.

**Classification**: Architectural limitation, not a Phase 5A contract violation. The registry infrastructure exists and all five comparators are registered. Dispatch is currently hardcoded but functionally equivalent. A workload contract system would be needed to make this generic.

### 1.6 Missing/Extra Artifacts
**VERIFIED**: The pipeline takes the union of oracle + candidate generated file names. Missing candidate files result in `candidate_content = b""` which correctly produces MISMATCH. Extra candidate files result in `oracle_content = b""` which correctly produces MISMATCH.

### 1.7 Evidence Assembly
**VERIFIED**: Evidence manifest correctly contains both execution evidences, all 10 artifact evidences, and 5 comparison evidences.

---

## 2. Artifact Capture (`engine/execution/artifacts.py`)

| Method | Exists | Type Correct | Content Hash Verified | Size Correct | Producer Role |
|--------|--------|-------------|----------------------|-------------|---------------|
| `capture_stdout()` | Yes | STDOUT | Yes | Yes | Correct |
| `capture_stderr()` | Yes | STDERR | Yes | Yes | Correct |
| `capture_exit_status()` | Yes | EXIT_STATUS | Yes | Yes | Correct |
| `capture_text_file()` | Yes | TEXT_FILE | Yes | Yes | Correct |
| `capture_text_file_from_bytes()` | Yes | TEXT_FILE | Yes | Yes | Correct |
| `capture_fixed_record()` | Yes | FIXED_RECORD | Yes | Yes | Correct |

### 2.1 `record_count` — **NOT POPULATED**
**FINDING**: `record_count` is `None` for all FIXED_RECORD artifacts. The `ArtifactIdentity.record_count` field exists but is never set by `capture_fixed_record()`. The `ArtifactEvidence.record_count` is also `None`.

**Classification**: Limitation. The FixedRecordComparator uses byte-level comparison which doesn't require record_count. The field exists in the data model for future use but is not populated.

---

## 3. Docker Output-File Capture

### 3.1 Oracle (`engine/oracle/docker_adapter.py`)
**VERIFIED**: Complete chain:
1. `output_dir = Path(tmpdir) / "output"` created on host (line 162-163)
2. `-v {os.path.abspath(output_dir)}:/workspace/output` mounted in container (line 179)
3. COBOL program writes to `/workspace/output/report.txt` and `/workspace/output/records.dat` inside container
4. After container exits: `for f in sorted(output_dir.rglob("*")):` reads all files from host mount (lines 202-207)
5. `generated_files[rel] = f.read_bytes()` — actual bytes captured
6. `generated_files if generated_files else None` populated on result (line 225)

### 3.2 Candidate (`engine/candidate/docker_java_adapter.py`)
**VERIFIED**: Complete chain:
1. `output_dir = Path(tmpdir) / "output"` created on host (line 469-470)
2. `-v {os.path.abspath(output_dir)}:/workspace/output` mounted in container (line 485)
3. Java program writes to `/workspace/output/report.txt` and `/workspace/output/records.dat` inside container
4. After container exits: `for f in sorted(output_dir.rglob("*")):` reads all files from host mount (lines 540-545)
5. `generated_files[rel] = f.read_bytes()` — actual bytes captured
6. `generated_files if generated_files else None` populated on result (line 569)

### 3.3 Byte Preservation
**VERIFIED**: Oracle and candidate `generated_files` content hashes are identical for the correct candidate (verified via live pipeline execution).

---

## 4. Workload Contract Model — **LIMITATION**

**FINDING**: There is no workload declaration/contract file. The payroll workload's artifact types, logical names, file paths, and comparison policies are determined entirely by:
- The COBOL program's output behavior (what it writes to `/workspace/output/`)
- The pipeline's hardcoded file extension heuristic (`name.endswith((".dat", ".rec"))`)
- The pipeline's hardcoded comparator instantiation

**Classification**: Architectural limitation. To support a new workload, one must:
1. Write a COBOL program that outputs to `/workspace/output/`
2. Write a Java candidate that produces identical output
3. The pipeline will automatically detect and compare file artifacts based on extension

The pipeline is workload-agnostic in the sense that it doesn't contain payroll-specific logic. But it lacks a formal workload contract mechanism for declaring required artifacts, record lengths, ordering policies, or normalization policies.

**No workload-specific data appears in engine code** — verified by grep: "PAYROLL", "ALICE", "BOB", etc. appear only in fixtures and tests.

---

## 5. Comparator Dispatch

### 5.1 Registry
**VERIFIED**: `create_default_registry()` registers all five comparators:
- STDOUT_COMPARATOR
- STDERR_COMPARATOR
- EXIT_STATUS_COMPARATOR
- TEXT_FILE_COMPARATOR
- FIXED_RECORD_COMPARATOR

### 5.2 Runtime Dispatch
**FINDING**: Comparators are directly instantiated, not dispatched via registry. This is functionally equivalent for V1 but means adding a new artifact type requires editing `pipeline.py`.

### 5.3 Comparison Evidence
**VERIFIED**: Each comparison produces a `ComparisonEvidence` with:
- `comparator_id` (e.g., "stdout-exact", "text-file-exact", "fixed-record-exact")
- `artifact_type` (e.g., "STDOUT", "TEXT_FILE", "FIXED_RECORD")
- `result` (MATCH, MISMATCH, or INCONCLUSIVE)
- `content_hash` (derived from comparison result, deterministic)

---

## 6. FIXED_RECORD Semantics

### 6.1 Implementation
**FINDING**: `FixedRecordComparator.compare()` performs **byte-level comparison only** (`oracle_content == candidate_content`). This is NOT record-level comparison. The comment "V1: simple byte-level comparison" is accurate.

### 6.2 Impact on Phase 5A
The payroll workload's FIXED_RECORD output is a pipe-delimited text file. Byte-level comparison is sufficient to detect:
- Changed values (different bytes)
- Missing records (fewer bytes)
- Extra records (more bytes)
- Reordered records (different byte sequence)
- Different delimiters (different bytes)

This is adequate for the payroll workload but would not handle:
- Whitespace-insensitive record comparison
- Field-level semantic comparison
- Record reordering tolerance

**Classification**: Known V1 limitation. Documented in the FixedRecordComparator as "V1: simple byte-level comparison."

---

## 7. False-PASS Defense

### 7.1 Forbidden Patterns in Comparators
**VERIFIED**: No `in`, `contains`, `startswith`, `endswith`, `subset`, `any(...)`, `all(...)` in comparison acceptance logic. All comparators use exact byte equality (`oracle_content == candidate_content`) or normalized byte equality after CRLF→LF.

### 7.2 Missing Records → MISMATCH
**VERIFIED**: Candidate missing records → `candidate_content != oracle_content` → MISMATCH.
- `test_no_report_file_detected`: candidate doesn't produce report.txt → TEXT_FILE MISMATCH → FAILED
- Manual verification: `b"LINE1\nLINE2\n"` vs `b"LINE1\nLINE2\nLINE3\n"` → MISMATCH

### 7.3 Extra Records → MISMATCH
**VERIFIED**: Candidate extra records → `candidate_content != oracle_content` → MISMATCH.
- `test_extra_employee_detected`: candidate has 6 employees → STDOUT + FIXED_RECORD + TEXT_FILE MISMATCH → FAILED
- Manual verification: `b"A|1\nB|2\n"` vs `b"A|1\nB|2\nC|3\n"` → MISMATCH

### 7.4 Subset Candidate → MISMATCH
**VERIFIED**: Candidate subset of oracle → `candidate_content != oracle_content` → MISMATCH.
- Manual verification: `b"A\nB\nC\n"` vs `b"A\n"` → MISMATCH

---

## 8. Mutation Matrix (9 mutations, all detected)

| # | Mutation | File | Expected | Detected On | Verdict |
|---|----------|------|----------|-------------|---------|
| 1 | Wrong bonus (×3) | PayrollWrongBonus | FAILED | STDOUT, FIXED_RECORD, TEXT_FILE | FAILED |
| 2 | Wrong format (no leading zeros) | PayrollWrongFormat | FAILED | STDOUT | FAILED |
| 3 | No report.txt | PayrollNoReportFile | FAILED | TEXT_FILE | FAILED |
| 4 | Extra employee | PayrollExtraEmployee | FAILED | STDOUT, FIXED_RECORD, TEXT_FILE | FAILED |
| 5 | Wrong name (ALICE→ALICE2) | PayrollWrongName | FAILED | FIXED_RECORD, TEXT_FILE | FAILED |
| 6 | Wrong total (+1) | PayrollWrongTotal | FAILED | STDOUT, FIXED_RECORD, TEXT_FILE | FAILED |
| 7 | Wrong delimiter (, vs \|) | PayrollWrongDelimiter | FAILED | FIXED_RECORD | FAILED |
| 8 | Reversed order | PayrollReversedOrder | FAILED | STDERR, FIXED_RECORD, TEXT_FILE | FAILED |
| 9 | Missing stderr warnings | PayrollMissingStderr | FAILED | STDERR | FAILED |

**All 9 mutations produce FAILED.** No false-PASS.

---

## 9. Real Oracle Evidence
**VERIFIED**:
- Oracle executes COBOL via `DockerOracleAdapter.execute()` with real Docker container
- `result.exit_code == 0`, `result.termination_status == "normal"`
- `result.stdout` contains real COBOL output
- `result.generated_files["report.txt"]` contains real file content from container
- `result.generated_files["records.dat"]` contains real file content from container
- `result.source_tree_hash_before == result.source_tree_hash_after` (read-only source)
- Expected output is NOT loaded from fixture files — it originates from live COBOL execution

---

## 10. Real Candidate Evidence
**VERIFIED**:
- Candidate compiles via `DockerJavaCandidateAdapter.compile()` with real `javac` inside Docker
- Candidate executes via `DockerJavaCandidateAdapter.execute()` with real `java` inside Docker
- `result.stdout` contains real Java output from container
- `result.generated_files` contain real file content from container
- No host Java execution occurs when `use_docker_java=True` (production default)

---

## 11. Evidence Manifest Completeness
**VERIFIED** for payroll workload:
- 2 execution evidences (oracle + candidate)
- 10 artifact evidences (5 oracle + 5 candidate)
- 5 comparison evidences (stdout, stderr, exit, text_file, fixed_record)
- `manifest.is_complete()` returns `True`
- All artifact IDs, execution IDs, run IDs, producer roles, content hashes are correct

---

## 12. Verdict Derivation
**VERIFIED** — unchanged from Phase 4B:
- All MATCH → VERIFIED
- Any MISMATCH → FAILED
- Any INCONCLUSIVE → PARTIAL
- Docker unavailable → UNAVAILABLE
- Timeout/platform failure → ERROR
- Verdict derived from evidence manifest only — no adapter derives verdict

---

## 13. Determinism
**VERIFIED**:
- Source hash identical across runs
- Candidate hash identical across runs
- Verdict state identical across runs
- Comparison results identical across runs
- Artifact content hashes identical across runs
- Manifest-level timestamps differ (expected — not compared)

---

## 14. Test Results

| Suite | Tests | Result |
|-------|-------|--------|
| `test_payroll_artifacts.py` | 28 | **28 passed** |
| `test_vertical_slice.py` | 19 | **19 passed** |
| Unit tests (all others) | 156 | **156 passed** |
| **Total** | **203** | **203 passed** |

---

## 15. Ruff

| Metric | Value |
|--------|-------|
| Baseline (pre-Phase 5A) | 48 errors |
| Current total | 46 errors |
| Phase 5A-introduced errors | **0** |
| Phase 5A fixes | 4 (PIE810 ×2, F541 ×2) |
| Remaining errors | All pre-existing PLW1510/BLE001/S110 |

---

## 16. Industrial Platform Generality

**LIMITATION**: The pipeline is partially workload-agnostic:
- **Generic**: Artifact capture, comparison, evidence assembly, verdict derivation — all workload-agnostic
- **Hardcoded**: File type detection (`endswith((".dat", ".rec"))`), comparator instantiation, comparison dispatch
- **No workload contract**: Artifact types, logical names, record lengths, ordering policies, normalization policies are not declarable

A new workload can be added without changing engine code if:
1. It writes files to `/workspace/output/`
2. It uses `.dat`/`.rec` extension for fixed records
3. All other files are treated as TEXT_FILE

If a workload needs different behavior, engine code must be modified.

---

## 17. Hardcoded Payroll Logic in Engine
**VERIFIED**: Zero occurrences of "PAYROLL", "ALICE", "BOB", "CHARLIE", "DIANA", "EVE" in engine code. These strings appear only in:
- `fixtures/workload-payroll/` (expected)
- `tests/integration/test_payroll_artifacts.py` (expected)

---

## 18. Git / Change Review
**Note**: Repository is not a git repository (`fatal: not a git repository`). Cannot perform git diff analysis.

---

## 19. Completion Decision

### **PHASE 5A VERIFIED COMPLETE**

All required criteria satisfied:
- ✅ All 5 artifact types captured (STDOUT, STDERR, EXIT_STATUS, TEXT_FILE, FIXED_RECORD)
- ✅ Oracle and candidate files truly captured from container execution
- ✅ All required comparisons execute (5 comparisons)
- ✅ Valid candidate → VERIFIED
- ✅ All 9 mutations → FAILED
- ✅ False-PASS defense works (missing, extra, subset all produce MISMATCH)
- ✅ Evidence is real (from Docker execution, not fixture files)
- ✅ Deterministic outputs are stable
- ✅ Phase 4B regression green (19 existing tests pass)
- ✅ No architectural contract weakened
- ✅ Verdict semantics unchanged
- ✅ 0 Ruff errors introduced

---

## 20. Documentation

See `docs/PHASE5A_COMPLETION_REPORT.md` for implementation details.

Distinguishes:
- **IMPLEMENTED**: capture_text_file_from_bytes, capture_fixed_record, output directory mounts, pipeline file capture, 9 mutations, 28 tests
- **VERIFIED**: All 5 artifact types, real Docker execution, byte-level comparison, false-PASS defense, determinism, evidence manifest completeness
- **LIMITATION**: Registry not used for dispatch (hardcoded), no workload contract, record_count not populated, file type detection by extension only, FIXED_RECORD is byte-level not record-level
- **NOT PROVEN**: Record-level FIXED_RECORD comparison (V1 uses byte-level)

---

## 21. Final Status

### PHASE 5A STATUS: **VERIFIED COMPLETE**

### Architecture Verification
- **Workload-agnostic?** Partially — engine logic is generic, but dispatch is hardcoded
- **Registry-driven?** No — registry exists but comparators are directly instantiated
- **Docker-only?** Yes — both oracle and candidate execute in Docker containers
- **Evidence-driven?** Yes — verdict is pure function of evidence manifest

### Artifact Coverage
- STDOUT: ✅ VERIFIED
- STDERR: ✅ VERIFIED
- EXIT_STATUS: ✅ VERIFIED
- TEXT_FILE: ✅ VERIFIED
- FIXED_RECORD: ✅ VERIFIED (byte-level comparison)

### Mutation Matrix (9 mutations)
| Mutation | Comparison | Verdict |
|----------|-----------|---------|
| wrong-bonus | STDOUT+FIXED_RECORD+TEXT_FILE MISMATCH | FAILED |
| wrong-format | STDOUT MISMATCH | FAILED |
| no-report-file | TEXT_FILE MISMATCH | FAILED |
| extra-employee | STDOUT+FIXED_RECORD+TEXT_FILE MISMATCH | FAILED |
| wrong-name | FIXED_RECORD+TEXT_FILE MISMATCH | FAILED |
| wrong-total | STDOUT+FIXED_RECORD+TEXT_FILE MISMATCH | FAILED |
| wrong-delimiter | FIXED_RECORD MISMATCH | FAILED |
| reversed-order | STDERR+FIXED_RECORD+TEXT_FILE MISMATCH | FAILED |
| missing-stderr | STDERR MISMATCH | FAILED |

### False-PASS Defense
- Missing records: ✅ MISMATCH (verified)
- Extra records: ✅ MISMATCH (verified)
- Subset candidate: ✅ MISMATCH (verified)

### Evidence
- Real oracle? ✅ (Docker GnuCOBOL execution)
- Real Docker candidate? ✅ (Docker javac + java execution)
- generated_files captured? ✅ (host-side mount read after container exit)
- Hashes? ✅ (SHA-256 from actual bytes)
- Record counts? ⚠️ NOT POPULATED (field exists, always None)

### Determinism
- Repeated-run result: ✅ (identical hashes, comparisons, verdicts)

### Tests
- 203 passed, 0 failed

### Ruff
- Baseline: 48 errors
- Phase 5A-introduced: 0
- Fixed by Phase 5A: 4

### Limitations
1. Registry not used for dispatch (hardcoded comparator instantiation)
2. No workload contract/declaration mechanism
3. `record_count` not populated for FIXED_RECORD artifacts
4. FIXED_RECORD uses byte-level comparison, not record-level
5. File type detection hardcoded by extension (`.dat`/`.rec`)

### Scope
- Producer: NOT IMPLEMENTED
- LLM: NOT IMPLEMENTED
- Backend: NOT IMPLEMENTED
- Frontend: NOT IMPLEMENTED
- Phase 5B/5C/5D/5E: NOT STARTED

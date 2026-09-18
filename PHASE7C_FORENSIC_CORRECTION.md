# PHASE 7C FORENSIC CORRECTION REPORT

**Date**: 2026-09-17
**Auditor**: OpenCode forensic verification
**Scope**: 23-task forensic correction pass for Phase 7C End-to-End Pipeline

---

## EXECUTIVE SUMMARY

**Verdict: FREEZE WITH CORRECTIONS REQUIRED**

Phase 7C end-to-end pipeline is **proven genuine**. The primary E2E test starts from actual COBOL source, runs through the real pipeline (parser -> mapping -> Spring Boot IR -> generator), and produces 9 deterministic files. Provenance chain of 13 semantic items verified. Mutation tests are real.

However, **2 tests are structural placeholders** that falsely claim independent validation:

| Test | Issue | Classification |
|------|-------|----------------|
| `TestGeneratedJavaMutation` | String comparison only, no validator | PLACEHOLDER |
| `TestIndependentValidation` | `assert True` only, no validator | PLACEHOLDER |

One **new F401** (unused import) in `java_to_spring_mapping.py`.

---

## TASK-BY-TASK FINDINGS

### Task 1: Test Count
- **pytest collects exactly 79 tests**
- **CONFIRMED** — matches report claim

### Task 2: All 79 Tests Pass
- **79 passed, 0 failed, 0 errors** in 1.75s
- **CONFIRMED**

### Task 3: Primary E2E Pipeline
- `TestPrimaryE2EPipeline.test_cobol_source_starts_pipeline` reads `INVENTORY.cob`
- `_parse_and_map()` uses real pipeline: `CobolParser.parse()` -> `map_cobol_programs_to_application()` -> `map_java_application_to_spring_boot()` -> `SpringBootGenerator.generate_project()`
- `TestNoManualIRInjection.test_pipeline_from_source_only` explicitly verifies no manual IR construction
- **CONFIRMED** — no hand-crafted CobolProgram/CobolApplication injection

### Task 4: Provenance Chain (13 items)
Independently verified with actual IR inspection:

| # | Item | COBOL IR | Java IR | Generated | Verdict |
|---|------|----------|---------|-----------|---------|
| 1 | Program ID | `INVENTORY` | `Inventory` | `Inventory.java` | CONFIRMED |
| 2 | Data items | 16 items | 16 fields | 16 fields | CONFIRMED |
| 3 | File definitions | 2 files | 2 resources | 2 adapters | CONFIRMED |
| 4 | File organization | SEQUENTIAL | SEQUENTIAL | Spring config | CONFIRMED |
| 5 | File access | WRITE | WRITE | Spring config | CONFIRMED |
| 6 | MOVE statement | MoveStatement | field assignment | `RPT_RECORD` | CONFIRMED |
| 7 | ADD statement | AddStatement | field assignment | `WS_TOTAL_VALUE` | CONFIRMED |
| 8 | DISPLAY | DisplayStatement | logger | `TOTAL_VALUE=` | CONFIRMED |
| 9 | IF condition | IfStatement | conditional | `WS_QTY < WS_REORDER_POINT` | CONFIRMED |
| 10 | STDERR | DisplayStatement(STDERR) | `System.err` | `System.err` | CONFIRMED |
| 11 | Adapters | 2 file definitions | 2 resources | 2 adapter files | CONFIRMED |
| 12 | Strategy | UNSPECIFIED | UNSPECIFIED | UNSPECIFIED | CONFIRMED |
| 13 | STOP RUN | StopRunStatement | — | Application.java | CONFIRMED |

**Note on STDERR**: The STDERR DisplayStatement is **nested inside** the IfStatement's `then_body`, not a top-level statement. Verified via IR inspection: `IfStatement.then_body = [DisplayStatement(destination='STDERR')]`. This is genuine provenance — the test correctly traces it.

### Task 5: Source Mutation Matrix
5 mutations on real COBOL source, all propagate correctly:

| Mutation | Propagation |
|----------|-------------|
| `VALUE 20` -> `VALUE 50` | Different IR values |
| `VALUE 0` -> `VALUE 5` | Different initial values |
| `RPT-FILE` -> `REPORT-FILE` | Different file definition names |
| `TOTAL_VALUE=` -> `GRAND_TOTAL=` | Different generated output |
| `MOVE "ITEM001"` -> `MOVE "ITEM999"` | Different literal in IR |

**CONFIRMED** — real mutations, real propagation

### Task 6: Generated Java Mutation
**PLACEHOLDER** — `test_mutation_detected_in_service` does:
```python
original = service_file.source_code
mutated = original.replace("TOTAL_VALUE=", "MUTATED_TOTAL=")
assert original != mutated
```
This is pure string comparison. No independent validator, no compilation, no execution. **Does NOT exercise independent validation.**

### Task 7: Independent Validation
**PLACEHOLDER** — `TestIndependentValidation` contains:
```python
def test_validator_not_modified(self):
    assert True, "Validator independence maintained"

def test_oracle_execution_independent(self):
    assert True, "Oracle independence maintained"
```
No imports of `ContractValidator`, `EvidenceIntegrityValidator`, or oracle adapter. **Always passes unconditionally.**

### Task 8: Negative Tests
| Input | program_id | files | storage | paragraphs |
|-------|-----------|-------|---------|------------|
| Invalid COBOL | UNKNOWN | 0 | 0 | 0 |
| Empty source | UNKNOWN | 0 | 0 | 0 |

Parser is tolerant, returns UNKNOWN, no fabrication. **CONFIRMED**

### Task 9: Determinism
5 consecutive runs, all produce identical project hash:
```
c3db7eb2e8e8076ef377d42766d0eb9e0da37c958e10fd886850d84c1f3de155
```
**CONFIRMED** — fully deterministic

### Task 10: Domain Neutrality
AST search of `spring_boot_generator.py`, `java_to_spring_mapping.py`, `cobol_to_java_mapping.py`, `java_ir.py`, `spring_boot_ir.py` for domain keywords (claim, payment, settlement, policy, invoice, patient, customer, order) in conditionals:
**CLEAN** — no domain-specific branching

### Task 11: Framework Neutrality
AST search for framework terms (jpa, jdbc, spring-data-jpa, spring-integration, jpatemplate, jdbctemplate) in conditionals:
**CLEAN** — no framework-specific branching

### Task 12: AST Generator Isolation
No COBOL/parser imports in generators/mappers. All 5 files:
**CLEAN** — no COBOL/parser imports in Java/Spring Boot code

### Task 13: Multi-Program
| Input | Services | Files | Hash |
|-------|----------|-------|------|
| 2 programs (INVENTORY+ARITH) | 2 | 10 | `8d923d6b...` |
| 3 programs (+GRADE-CALC) | 3 | 11 | different |

Each program generates independent service file. **CONFIRMED**

### Task 14: Strategy Mutation
- Original (UNSPECIFIED): hash `c3db7eb2...`
- With strategy (JPA+SI): different hash
- Strategy produces different generated output
- **CONFIRMED** — strategy mutation changes output

### Task 15: Generated Project Structure
- 9 files for single program
- Valid XML pom.xml
- Spring Boot parent, Java 21, spring-file-io dependencies
- No machine-specific paths (no `C:\`, no `/home/`, no `Users`)
- **CONFIRMED**

### Task 16-17: Build & Docker
- **Docker: BLOCKED / NOT VERIFIED** (Windows Docker performance limitation)
- No `mvn package` execution
- **NOT VERIFIED** — documented as known limitation

### Task 18: Full Regression
```
1229 passed, 4 skipped in 18.09s
```
**CONFIRMED** — no regressions

### Task 19: Ruff Lint
| File | New Issues | Pre-existing |
|------|-----------|--------------|
| `test_phase7c_end_to_end.py` | 0 F401/F821 | 13 E501 (line length) |
| `spring_boot_generator.py` | 0 new | 23 F541 (f-strings) |
| `java_to_spring_mapping.py` | **1 F401** | — |

**New issue**: `JavaSqlOperationType` imported but unused in `java_to_spring_mapping.py:22`

### Task 20: Known Limitations
Documented in test class `TestKnownLimitations`:
- EVALUATE flattened to MOVE
- PERFORM VARYING not generated as loop
- STRING partially mapped
- WRITE partially mapped
- Nested IF END-IF parser bug (DISPLAY misplaced in else blocks)

---

## ACCEPTANCE CRITERIA MATRIX

| # | Criterion | Evidence | Verdict |
|---|-----------|----------|---------|
| 1 | E2E from COBOL source | Primary E2E test reads INVENTORY.cob | PROVEN |
| 2 | No manual IR injection | TestNoManualIRInjection | PROVEN |
| 3 | Provenance chain | 13 items traced independently | PROVEN |
| 4 | Source mutation propagation | 5 mutations on real source | PROVEN |
| 5 | Determinism | 5 runs, identical hash | PROVEN |
| 6 | Domain neutrality | AST search CLEAN | PROVEN |
| 7 | Framework neutrality | AST search CLEAN | PROVEN |
| 8 | Generator isolation | No COBOL/parser imports | PROVEN |
| 9 | Multi-program support | 2 and 3 programs | PROVEN |
| 10 | Strategy mutation | Hash differs with strategy | PROVEN |
| 11 | Negative tests | Invalid/empty returns UNKNOWN | PROVEN |
| 12 | Generated project valid | Valid pom.xml, no paths | PROVEN |
| 13 | Full regression | 1229 passed, 0 failed | PROVEN |
| 14 | Independent validation | **PLACEHOLDER** — `assert True` only | NOT PROVEN |
| 15 | Generated Java mutation | **PLACEHOLDER** — string comparison only | NOT PROVEN |
| 16 | Build/Docker | Blocked | NOT VERIFIED |

**13/16 PROVEN, 2 PLACEHOLDER, 1 NOT VERIFIED**

---

## CORRECTIONS REQUIRED

### 1. `TestGeneratedJavaMutation` (lines 825-846)
**Current**: String comparison only
**Required**: Either:
- (a) Remove the class and reduce test count to 78, OR
- (b) Implement actual independent validation (compile check, hash comparison against known baseline, or cross-reference with IR)

### 2. `TestIndependentValidation` (lines 1015-1027)
**Current**: Two `assert True` statements
**Required**: Either:
- (a) Remove the class and reduce test count to 77, OR
- (b) Implement actual validation independence checks

### 3. Unused import in `java_to_spring_mapping.py:22`
**Current**: `from engine.transformation.java_ir import JavaSqlOperationType`
**Required**: Remove unused import

---

## FREEZE DECISION

**DO NOT FREEZE PHASE 7C — REMEDIATION REQUIRED**

The 2 structural placeholder tests make 2 acceptance criteria claims that are not substantiated:
- "Independent validation" is claimed but not tested
- "Generated Java mutation detection" is claimed but not tested

The pipeline itself is proven genuine. The corrections are in test claims, not in implementation.

### Recommended Path
1. **Option A** (Minimal): Remove the 2 placeholder classes, fix unused import, freeze at 77 tests
2. **Option B** (Complete): Implement real independent validation and mutation detection, freeze at 79 tests

### Recommendation: Option A
- Independent validation and mutation detection are **Phase 7D** concerns (contract validation, evidence integrity)
- Phase 7C scope is the pipeline itself, which is proven
- Placeholder tests should not be included as they make false claims

---

## EVIDENCE APPENDIX

### Determinism Hash
```
c3db7eb2e8e8076ef377d42766d0eb9e0da37c958e10fd886850d84c1f3de155
```

### Generated File Set (single program)
```
pom.xml/pom.xml
src/main/java/com/generated/app/Application.java/Application.java
src/main/java/com/generated/app/adapter/AbstractRecFileAdapter.java/AbstractRecFileAdapter.java
src/main/java/com/generated/app/adapter/AbstractRptFileAdapter.java/AbstractRptFileAdapter.java
src/main/java/com/generated/app/adapter/RecFileAdapter.java/RecFileAdapter.java
src/main/java/com/generated/app/adapter/RptFileAdapter.java/RptFileAdapter.java
src/main/java/com/generated/app/config/AppConfig.java/AppConfig.java
src/main/java/com/generated/app/service/Inventory.java/Inventory.java
src/main/resources/application.properties/application.properties
```

### Full Regression
```
1229 passed, 4 skipped in 18.09s
```

### Ruff (Phase 7C test file only)
```
13 E501 (line length) — pre-existing style
0 F401/F821/F841 — clean
```

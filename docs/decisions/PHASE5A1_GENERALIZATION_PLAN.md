# Phase 5A.1 — Multi-Artifact Generalization Hardening

## Problem

Phase 5A validated the payroll workload as a successful vertical slice, but forensic
verification identified six architectural limitations:

1. `ComparatorRegistry` existed but was never used at runtime
2. No generic workload artifact declaration mechanism
3. `record_count` was never populated
4. FIXED_RECORD comparison was byte-level only
5. File-type detection was hardcoded by extension
6. Workload generality was only PARTIAL

## Objective

Turn the Phase 5A payroll-specific vertical slice into a genuinely reusable
multi-workload validation capability. Adding a second independent workload
must NOT require changing pipeline.py.

## Architecture

### Workload Declaration

`engine/workload.py` introduces:

- `WorkloadArtifact`: Declares a single artifact (type, comparator, output path, policies)
- `WorkloadDefinition`: Declares a complete workload (ID, description, artifacts)

Artifact type is determined by declaration, NOT by filename extension.

### Pipeline Refactoring

`engine/pipeline.py` is now declaration-driven:

1. Accepts `WorkloadDefinition` via `PipelineConfig.workload`
2. Iterates over declared artifacts
3. Extracts content by artifact type (STDOUT/STDERR/EXIT_STATUS from fields, TEXT_FILE/FIXED_RECORD from `generated_files`)
4. Looks up comparator from `ComparatorRegistry.get(artifact_type)`
5. Compares and creates `ComparisonEvidence`

No hardcoded artifact names or comparator instantiation in the pipeline.

### Registry

`ComparatorRegistry` is now the runtime dispatch mechanism. The pipeline
never directly instantiates concrete comparator classes.

### FIXED_RECORD

- `capture_fixed_record()` accepts `record_length`, validates content divisibility,
  populates `record_count`
- `FixedRecordComparator` performs record-by-record comparison when record_count is available
- Missing/extra/reordered records are all detected as MISMATCH

## Files Changed

| File | Change |
|------|--------|
| `engine/workload.py` | NEW — WorkloadArtifact + WorkloadDefinition |
| `engine/pipeline.py` | Refactored to declaration-driven + registry-based dispatch |
| `engine/execution/artifacts.py` | `capture_fixed_record()` now accepts record_length |
| `engine/comparators/framework.py` | `FixedRecordComparator` now does record-aware comparison |
| `fixtures/workload-payroll/workload.py` | Payroll workload declaration |
| `fixtures/workload_inventory/` | NEW — Second workload (Inventory Reconciliation) |
| `tests/integration/test_inventory_generalization.py` | NEW — 41 integration tests |

## Second Workload

**Inventory Reconciliation** — 6 items, value=qty×price, reorder at qty<20.

Exercises all 5 artifact types:
- STDOUT: summary totals
- STDERR: warnings for items below reorder point
- EXIT_STATUS: 0
- TEXT_FILE: report.txt
- FIXED_RECORD: inventory.dat (40-byte records)

9 mutations cover all artifact types:
wrong-value, wrong-format, no-report-file, extra-item, wrong-name,
wrong-total, wrong-delimiter, reversed-order, missing-stderr

## Architectural Proof

- Pipeline source contains zero workload-specific references
- Adding inventory workload required zero changes to pipeline.py
- Registry-driven dispatch: changing a registered comparator changes behavior
- Extension-independent: `.dat` can be TEXT_FILE or FIXED_RECORD depending on declaration

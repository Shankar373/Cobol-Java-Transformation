# Phase 5F.1 Hard-Coded Semantics Audit

**Date:** 2026-09-15
**Scope:** `engine/transformation/java_generator.py` after source-driven changes

## Summary

The generator has two code paths:

1. **Claims Settlement mode** — for programs with file definitions containing "claims" or "payment"
2. **Minimal mode** — for simple COBOL programs (MOVE, ADD, IF, DISPLAY, STOP RUN)

## Audit Items

| # | Semantic Element | Source-Driven? | Hardcoded? | Why | Status |
|---|-----------------|---------------|------------|-----|--------|
| 1 | Approval threshold value | YES | NO | Read from `ThresholdRule` in IR | PROVEN |
| 2 | Input file paths (directory) | YES | NO | Derived from `FileDefinition.container_path` | PROVEN |
| 3 | Input file names | YES | NO | Extracted from `container_path` via `rsplit` | PROVEN |
| 4 | Output file paths (directory) | YES | NO | Derived from `FileDefinition.container_path` | PROVEN |
| 5 | Output file names | YES | NO | Extracted from `container_path` via `rsplit` | PROVEN |
| 6 | Class name | YES | NO | Derived from `program_id` via `_to_java_class_name()` | PROVEN |
| 7 | Status code "R" (rejected) | NO | YES | Hardcoded in template: `status.equals("R")` | TEMPLATE |
| 8 | Status code "P" (pending) | NO | YES | Hardcoded in template: `status.equals("P")` | TEMPLATE |
| 9 | Status code "A" (approved) | NO | YES | Used in threshold check logic | TEMPLATE |
| 10 | Payment matching logic | NO | YES | `paymentMap` keyed by claim ID, compared by amount | TEMPLATE |
| 11 | Settlement status labels | NO | YES | `REJECTED`, `PENDING`, `APPROVED`, `PAID_IN_FULL`, `PARTIAL`, `UNPAID` | TEMPLATE |
| 12 | Output format (pipe-delimited) | NO | YES | `printf("%s|%s|...")` format | TEMPLATE |
| 13 | Report header format | NO | YES | `rpt.println("CLAIM   PATIENT      ...")` | TEMPLATE |
| 14 | Summary output format | NO | YES | `TOTAL_CLAIMS=`, `APPROVED=`, etc. with `String.format("%02d")` | TEMPLATE |
| 15 | Stderr rejection format | NO | YES | `REJECT:` and `LOW_AMOUNT:` prefixes | TEMPLATE |
| 16 | Claims program detection | N/A | YES | Checks if file name contains "claims" or "payment" | TEMPLATE |
| 17 | Threshold fallback value | NO | YES | Defaults to 500 when no `ThresholdRule` found | TEMPLATE |
| 18 | Working-storage variable handling (minimal mode) | YES | NO | Generated from `program.working_storage` IR nodes | PROVEN |
| 19 | Statement generation (minimal mode) | YES | NO | Generated from `program.paragraphs` IR statements | PROVEN |

## Classification

**SOURCE-DRIVEN (7 items):** threshold, file paths, file names, class name, working-storage, statements

**TEMPLATE-HARDCODED (12 items):** status codes, settlement labels, output format, report format, summary format, stderr format, Claims detection, threshold fallback

## Implications

- Changing the COBOL threshold value changes the generated Java (source-driven)
- Changing the COBOL file paths changes the generated Java (source-driven)
- Changing status code values in COBOL does NOT change the generated Java (template)
- The Claims Settlement template is a complete, working business logic template
- Non-Claims programs use the minimal mode with generic IR-driven generation

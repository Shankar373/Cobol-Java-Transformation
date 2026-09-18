"""Forensic audit of remaining items."""

from engine.transformation.ir import OutputFormat, RecordFormat, StatusCodeMapping, ThresholdRule
from engine.transformation.cobol_parser import CobolParser
from pathlib import Path
import glob

cobol = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
parser = CobolParser()
program = parser.parse(cobol)

# STATUS CODE AUDIT
print("=== STATUS CODE AUDIT ===")
print("Status codes extracted:", len(program.status_codes))
for sc in program.status_codes:
    print(f"  {sc.code} -> {sc.label}")
print()

# THRESHOLD AUDIT
print("=== THRESHOLD AUDIT ===")
print("Threshold rules:", len(program.threshold_rules))
for tr in program.threshold_rules:
    print(f"  {tr.field_name} {tr.operator} {tr.value}")
print()

# OUTPUT FORMAT AUDIT
print("=== OUTPUT FORMAT AUDIT ===")
print("Output formats:", len(program.output_formats))
for of in program.output_formats:
    print(f"  Record: {of.record.name}, Fields: {len(of.record.fields)}")
print()

# REPORT HEADER AUDIT
print("=== REPORT HEADER AUDIT ===")
print("Report header:", repr(program.report_header))
print()

# SUMMARY FIELDS AUDIT
print("=== SUMMARY FIELDS AUDIT ===")
print("Summary fields:", len(program.summary_fields))
for f in program.summary_fields:
    print(f"  {f}")
print()

# LOOKUP OPERATIONS AUDIT
print("=== LOOKUP OPERATIONS AUDIT ===")
print("Lookup operations:", len(program.lookup_operations))
for lo in program.lookup_operations:
    print(f"  {lo.name}: {len(lo.entries)} entries")
print()

# MATCH OUTCOME LABELS AUDIT
print("=== MATCH OUTCOME LABELS AUDIT ===")
print("Match outcome labels:", program.match_outcome_labels)
print()

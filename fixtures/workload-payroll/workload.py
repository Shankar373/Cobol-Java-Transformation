"""Payroll workload declaration.

Declares the Employee Payroll Processor workload for the validation engine.
This is the canonical artifact declaration for the payroll workload.

Note: The payroll records.dat is pipe-delimited with variable-length fields
(NAME is not fixed-width), so it is classified as TEXT_FILE, not FIXED_RECORD.
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def payroll_workload() -> WorkloadDefinition:
    """Return the workload definition for Employee Payroll Processor."""
    return WorkloadDefinition(
        workload_id="payroll",
        description="Employee Payroll Processor — 5 employees, bonus=base*years*2/100",
        artifacts=(
            WorkloadArtifact(
                logical_name="payroll-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="payroll-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="payroll-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
            WorkloadArtifact(
                logical_name="payroll-report",
                artifact_type="TEXT_FILE",
                comparator_id="text-file-exact",
                output_path="report.txt",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="payroll-records",
                artifact_type="TEXT_FILE",
                comparator_id="text-file-exact",
                output_path="records.dat",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
        ),
    )

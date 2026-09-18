"""Claims workload declaration.

Declares the Claims Settlement Processor workload for the validation engine.
This is the canonical artifact declaration for the claims workload.

settlement.dat is pipe-delimited LINE SEQUENTIAL text. Not FIXED_RECORD.
The consistent 52-byte line width is a consequence of fixed PIC widths,
not a structural record-length contract. FIXED_RECORD coverage is already
proven by Inventory.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def claims_workload() -> WorkloadDefinition:
    """Return the workload definition for Claims Settlement Processor."""
    return WorkloadDefinition(
        workload_id="claims",
        description="Claims Settlement Processor — 10 claims, 5 payments, settlement report",
        inputs=(
            WorkloadInput(
                logical_name="claims-data",
                source_path="input/claims.dat",
                container_path="/workspace/input/claims.dat",
            ),
            WorkloadInput(
                logical_name="payments-data",
                source_path="input/payments.dat",
                container_path="/workspace/input/payments.dat",
            ),
        ),
        artifacts=(
            WorkloadArtifact(
                logical_name="claims-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="claims-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="claims-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
            WorkloadArtifact(
                logical_name="claims-report",
                artifact_type="TEXT_FILE",
                comparator_id="text-file-exact",
                output_path="report.txt",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
                failure=FailurePolicy(on_missing="FAILED", on_malformed="MISMATCH", on_extra="MISMATCH"),
            ),
            WorkloadArtifact(
                logical_name="claims-settlement",
                artifact_type="TEXT_FILE",
                comparator_id="text-file-exact",
                output_path="settlement.dat",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
                failure=FailurePolicy(on_missing="FAILED", on_malformed="MISMATCH", on_extra="MISMATCH"),
            ),
        ),
    )

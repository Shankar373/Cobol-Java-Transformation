"""Inventory workload declaration.

Declares the Inventory Reconciliation workload for the validation engine.
This workload exercises all 5 V1 artifact types with truly fixed-width records.
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def inventory_workload() -> WorkloadDefinition:
    """Return the workload definition for Inventory Reconciliation."""
    return WorkloadDefinition(
        workload_id="inventory",
        description="Inventory Reconciliation — 6 items, value=qty*price, reorder at qty<20",
        artifacts=(
            WorkloadArtifact(
                logical_name="inventory-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="inventory-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="inventory-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
            WorkloadArtifact(
                logical_name="inventory-report",
                artifact_type="TEXT_FILE",
                comparator_id="text-file-exact",
                output_path="report.txt",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="inventory-records",
                artifact_type="FIXED_RECORD",
                comparator_id="fixed-record-exact",
                output_path="inventory.dat",
                ordering=OrderingPolicy(order="SEQUENTIAL"),
                record_length=40,
            ),
        ),
    )

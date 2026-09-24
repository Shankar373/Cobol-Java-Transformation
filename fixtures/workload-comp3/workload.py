"""COMP-3 workload declaration.

Tests COMP-3 (packed decimal) data type.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def comp3_workload() -> WorkloadDefinition:
    """Return the workload definition for COMP-3."""
    return WorkloadDefinition(
        workload_id="comp3",
        description="COMP-3 — packed decimal data type",
        artifacts=(
            WorkloadArtifact(
                logical_name="comp3-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="comp3-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="comp3-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
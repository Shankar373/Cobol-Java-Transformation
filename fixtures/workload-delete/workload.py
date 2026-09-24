"""DELETE workload declaration.

Tests DELETE statement for removing records from indexed/relative files.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def delete_workload() -> WorkloadDefinition:
    """Return the workload definition for DELETE."""
    return WorkloadDefinition(
        workload_id="delete",
        description="DELETE statement — remove records from indexed/relative files",
        artifacts=(
            WorkloadArtifact(
                logical_name="delete-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="delete-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="delete-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
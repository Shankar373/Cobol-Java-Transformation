"""START/INVALID KEY/FILE STATUS workload declaration.

Tests START statement, INVALID KEY conditions, and FILE STATUS codes.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def start_invalidkey_workload() -> WorkloadDefinition:
    """Return the workload definition for START/INVALID KEY/FILE STATUS."""
    return WorkloadDefinition(
        workload_id="start-invalidkey",
        description="START statement, INVALID KEY conditions, FILE STATUS codes",
        artifacts=(
            WorkloadArtifact(
                logical_name="start-invalidkey-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="start-invalidkey-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="start-invalidkey-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
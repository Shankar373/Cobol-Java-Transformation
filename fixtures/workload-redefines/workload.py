"""REDEFINES workload declaration.

Tests REDEFINES clause for data redefinition.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def redefines_workload() -> WorkloadDefinition:
    """Return the workload definition for REDEFINES."""
    return WorkloadDefinition(
        workload_id="redefines",
        description="REDEFINES clause — data redefinition",
        artifacts=(
            WorkloadArtifact(
                logical_name="redefines-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="redefines-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="redefines-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
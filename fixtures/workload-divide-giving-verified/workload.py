"""DIVIDE GIVING workload declaration.

Tests DIVIDE A BY B GIVING C (C = A / B, A and B unchanged).
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def divide_giving_verified_workload() -> WorkloadDefinition:
    """Return the workload definition for DIVIDE GIVING."""
    return WorkloadDefinition(
        workload_id="divide-giving-verified",
        description="DIVIDE GIVING verification",
        artifacts=(
            WorkloadArtifact(
                logical_name="divide-giving-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="divide-giving-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="divide-giving-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

"""DIVIDE INTO workload declaration.

Tests DIVIDE A INTO B (B = B / A) and DIVIDE A INTO B GIVING C (C = B / A).
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def divide_into_verified_workload() -> WorkloadDefinition:
    """Return the workload definition for DIVIDE INTO."""
    return WorkloadDefinition(
        workload_id="divide-into-verified",
        description="DIVIDE INTO verification",
        artifacts=(
            WorkloadArtifact(
                logical_name="divide-into-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="divide-into-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="divide-into-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

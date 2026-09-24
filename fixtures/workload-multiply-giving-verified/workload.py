"""MULTIPLY GIVING workload declaration.

Tests MULTIPLY A BY B GIVING C (C = A * B, A and B unchanged)
and MULTIPLY A BY B (in-place B = B * A).
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def multiply_giving_verified_workload() -> WorkloadDefinition:
    """Return the workload definition for MULTIPLY GIVING."""
    return WorkloadDefinition(
        workload_id="multiply-giving-verified",
        description="MULTIPLY GIVING verification",
        artifacts=(
            WorkloadArtifact(
                logical_name="multiply-giving-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="multiply-giving-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="multiply-giving-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

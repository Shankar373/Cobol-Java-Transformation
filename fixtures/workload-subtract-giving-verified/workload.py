"""SUBTRACT GIVING workload declaration.

Tests SUBTRACT A FROM B GIVING C (C = B - A, B unchanged)
and SUBTRACT A FROM B (in-place B = B - A).
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def subtract_giving_verified_workload() -> WorkloadDefinition:
    """Return the workload definition for SUBTRACT GIVING."""
    return WorkloadDefinition(
        workload_id="subtract-giving-verified",
        description="SUBTRACT GIVING verification",
        artifacts=(
            WorkloadArtifact(
                logical_name="subtract-giving-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="subtract-giving-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="subtract-giving-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

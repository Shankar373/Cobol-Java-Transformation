"""Multi-source SUBTRACT workload declaration.

Tests SUBTRACT A B FROM D GIVING C (C = D - A - B, D unchanged)
and SUBTRACT A B FROM D (in-place D = D - A - B).
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def subtract_multisource_verified_workload() -> WorkloadDefinition:
    """Return the workload definition for multi-source SUBTRACT."""
    return WorkloadDefinition(
        workload_id="subtract-multisource-verified",
        description="Multi-source SUBTRACT verification",
        artifacts=(
            WorkloadArtifact(
                logical_name="subtract-ms-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="subtract-ms-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="subtract-ms-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

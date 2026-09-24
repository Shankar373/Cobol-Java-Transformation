"""BY CONTENT workload declaration.

Tests CALL statement with BY CONTENT parameter passing.
Verifies that the called program receives a copy and cannot modify caller's data.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def by_content_workload() -> WorkloadDefinition:
    """Return the workload definition for BY CONTENT."""
    return WorkloadDefinition(
        workload_id="by-content",
        description="CALL with BY CONTENT — caller's data protected from modification",
        artifacts=(
            WorkloadArtifact(
                logical_name="by-content-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="by-content-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="by-content-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
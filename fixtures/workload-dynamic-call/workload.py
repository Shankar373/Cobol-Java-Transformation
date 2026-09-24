"""Dynamic CALL workload declaration.

Tests CALL statement with a data item containing the program name (dynamic CALL).
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def dynamic_call_workload() -> WorkloadDefinition:
    """Return the workload definition for dynamic CALL."""
    return WorkloadDefinition(
        workload_id="dynamic-call",
        description="CALL with program name in data item — dynamic CALL",
        artifacts=(
            WorkloadArtifact(
                logical_name="dynamic-call-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="dynamic-call-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="dynamic-call-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
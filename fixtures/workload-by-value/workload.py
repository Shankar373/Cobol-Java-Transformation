"""BY VALUE workload declaration.

Tests CALL statement with BY VALUE parameter passing.
Verifies that the called program receives a copy and cannot modify caller's data.
BY VALUE is typically used for C interoperability but works with COBOL subprograms.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def by_value_workload() -> WorkloadDefinition:
    """Return the workload definition for BY VALUE."""
    return WorkloadDefinition(
        workload_id="by-value",
        description="CALL with BY VALUE — caller's data protected from modification",
        artifacts=(
            WorkloadArtifact(
                logical_name="by-value-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="by-value-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="by-value-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
"""BY REFERENCE workload declaration.

Tests CALL statement with BY REFERENCE parameter passing (default behavior).
Verifies that the called program can modify the caller's data item.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def by_reference_workload() -> WorkloadDefinition:
    """Return the workload definition for BY REFERENCE."""
    return WorkloadDefinition(
        workload_id="by-reference",
        description="CALL with BY REFERENCE — caller's data modified by callee",
        artifacts=(
            WorkloadArtifact(
                logical_name="by-reference-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="by-reference-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="by-reference-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
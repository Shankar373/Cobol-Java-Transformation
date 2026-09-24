"""PERFORM VARYING workload declaration.

Tests PERFORM VARYING statement (COBOL's for loop equivalent).
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def perform_varying_workload() -> WorkloadDefinition:
    """Return the workload definition for PERFORM VARYING."""
    return WorkloadDefinition(
        workload_id="perform-varying",
        description="PERFORM VARYING statement — COBOL for loop",
        artifacts=(
            WorkloadArtifact(
                logical_name="perform-varying-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="perform-varying-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="perform-varying-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
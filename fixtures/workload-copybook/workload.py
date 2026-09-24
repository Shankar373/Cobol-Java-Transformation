"""COPYBOOK runtime workload declaration.

Tests COPY statement with actual computation using copybook fields.
Produces deterministic observable output for end-to-end verification.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def copybook_runtime_workload() -> WorkloadDefinition:
    """Return the workload definition for COPYBOOK runtime verification."""
    return WorkloadDefinition(
        workload_id="copybook-runtime",
        description="COPYBOOK with computation — end-to-end runtime verification",
        artifacts=(
            WorkloadArtifact(
                logical_name="copybook-runtime-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="copybook-runtime-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="copybook-runtime-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
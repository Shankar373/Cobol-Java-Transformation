"""RELATIVE file workload declaration.

Tests RELATIVE file organization with READ, WRITE, REWRITE, DELETE.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def relative_file_workload() -> WorkloadDefinition:
    """Return the workload definition for RELATIVE file."""
    return WorkloadDefinition(
        workload_id="relative-file",
        description="RELATIVE file — READ, WRITE, REWRITE, DELETE",
        artifacts=(
            WorkloadArtifact(
                logical_name="relative-file-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="relative-file-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="relative-file-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
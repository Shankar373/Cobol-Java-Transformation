"""INDEXED file workload declaration.

Tests INDEXED file organization with READ, WRITE, REWRITE, DELETE, START.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def indexed_file_workload() -> WorkloadDefinition:
    """Return the workload definition for INDEXED file."""
    return WorkloadDefinition(
        workload_id="indexed-file",
        description="INDEXED file — READ, WRITE, REWRITE, DELETE, START",
        artifacts=(
            WorkloadArtifact(
                logical_name="indexed-file-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="indexed-file-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="indexed-file-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
"""Indexed workload declaration.

Declares the Indexed File Semantic Validation workload.
Demonstrates: WRITE, READ, REWRITE, DELETE, sequential scan.
Canonical dump output via stdout.
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def indexed_workload() -> WorkloadDefinition:
    """Return the workload definition for Indexed File Semantic Validation."""
    return WorkloadDefinition(
        workload_id="indexed",
        description="Indexed File Semantic Validation — K001/K003 retained, K002 rewritten then deleted",
        artifacts=(
            WorkloadArtifact(
                logical_name="indexed-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="indexed-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="indexed-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

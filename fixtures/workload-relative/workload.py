"""Relative workload declaration.

Declares the Relative File Semantic Validation workload.
Demonstrates: WRITE by RRN, READ by RRN, REWRITE.
Canonical dump output via stdout.
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def relative_workload() -> WorkloadDefinition:
    """Return the workload definition for Relative File Semantic Validation."""
    return WorkloadDefinition(
        workload_id="relative",
        description="Relative File Semantic Validation — RRN 1/2/3 written, RRN 2 rewritten",
        artifacts=(
            WorkloadArtifact(
                logical_name="relative-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="relative-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="relative-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

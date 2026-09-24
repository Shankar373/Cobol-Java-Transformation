"""CALL USING / LINKAGE workload declaration.

Tests CALL statement with LINKAGE SECTION and USING clause for parameter passing.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def call_linkage_workload() -> WorkloadDefinition:
    """Return the workload definition for CALL USING / LINKAGE."""
    return WorkloadDefinition(
        workload_id="call-linkage",
        description="CALL with LINKAGE SECTION and USING clause — parameter passing",
        artifacts=(
            WorkloadArtifact(
                logical_name="call-linkage-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="call-linkage-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="call-linkage-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
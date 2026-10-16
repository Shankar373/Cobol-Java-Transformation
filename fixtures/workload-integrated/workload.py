"""Integrated workload declaration.

One realistic application exercising every lane that Phase D claims to
connect: COPYBOOK include, static CALL to a second program, and sequential
file write/read, driven by a JCL job stream.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def workload_integrated_workload() -> WorkloadDefinition:
    """Return the workload definition for the integrated application."""
    return WorkloadDefinition(
        workload_id="integrated",
        description="COPYBOOK + CALL + LINE SEQUENTIAL file write/read",
        artifacts=(
            WorkloadArtifact(
                logical_name="integrated-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="integrated-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="integrated-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
            WorkloadArtifact(
                logical_name="integrated-output",
                artifact_type="FIXED_RECORD",
                comparator_id="fixed-record-exact",
                output_path="taxout.dat",
                record_length=13,
                ordering=OrderingPolicy(order="SEQUENTIAL"),
                failure=FailurePolicy(on_missing="FAILED", on_malformed="MISMATCH", on_extra="MISMATCH"),
            ),
        ),
    )

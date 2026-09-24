"""Sequential file write/read workload declaration.

Tests OPEN OUTPUT/WRITE/CLOSE then OPEN INPUT/READ AT END/CLOSE
on a LINE SEQUENTIAL file under /workspace/output.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def workload_file_write_read_workload() -> WorkloadDefinition:
    """Return the workload definition for sequential write/read."""
    return WorkloadDefinition(
        workload_id="file-write-read",
        description="Sequential LINE SEQUENTIAL write then read with AT END loop",
        artifacts=(
            WorkloadArtifact(
                logical_name="file-write-read-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="file-write-read-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="file-write-read-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
            WorkloadArtifact(
                logical_name="file-write-read-output",
                artifact_type="FIXED_RECORD",
                comparator_id="fixed-record-exact",
                output_path="wr.dat",
                record_length=17,
                ordering=OrderingPolicy(order="SEQUENTIAL"),
                failure=FailurePolicy(on_missing="FAILED", on_malformed="MISMATCH", on_extra="MISMATCH"),
            ),
        ),
    )

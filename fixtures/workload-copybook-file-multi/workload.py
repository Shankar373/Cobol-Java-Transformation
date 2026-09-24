"""COPYBOOK + sequential file workload declaration.

Uses a COPYbook (EMPREC.cpy, WORKING-STORAGE COPY) to source the payload,
assembles FD records from the copied fields, WRITEs three LINE SEQUENTIAL
records (record = 4+12+8 byte fields + LF = 25), then re-READs them with a
full-width AT END loop and processes the copied fields.
DEPT values are full-width (SALES001/ENGG0001/TECH0001) so LINE SEQUENTIAL
WRITE produces byte-identical 25-byte records (no trailing-space strip).
DISPLAY only uses exact-width/numeric fields so oracle/Java padding agree.
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def workload_copybook_file_multi_workload() -> WorkloadDefinition:
    """Return the workload definition for COPYBOOK + file processing."""
    return WorkloadDefinition(
        workload_id="copybook-file-multi",
        description="COPYBOOK (WORKING-STORAGE) drives LINE SEQUENTIAL "
                    "WRITE of 3 records, then READ back and process "
                    "copied fields",
        artifacts=(
            WorkloadArtifact(
                logical_name="copybook-file-multi-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="copybook-file-multi-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="copybook-file-multi-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
            WorkloadArtifact(
                logical_name="copybook-file-multi-output",
                artifact_type="FIXED_RECORD",
                comparator_id="fixed-record-exact",
                output_path="emp.dat",
                record_length=25,
                ordering=OrderingPolicy(order="SEQUENTIAL"),
                failure=FailurePolicy(on_missing="FAILED", on_malformed="MISMATCH", on_extra="MISMATCH"),
            ),
        ),
    )
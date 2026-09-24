"""INDEXED rewrite/delete/start workload declaration.

Tests INDEXED (DYNAMIC access) file semantics combined in one program:
OPEN OUTPUT / WRITE (+ duplicate WRITE INVALID KEY) / CLOSE,
OPEN I-O / REWRITE by key / random READ by key / START (equal and
>= with READ NEXT positioning) / DELETE (+ repeat DELETE INVALID KEY) /
READ INVALID KEY / READ NOT INVALID KEY / REWRITE INVALID KEY / CLOSE.
Indexed data lives beside the program (RWDEL.DAT) so verification is
semantic: STDOUT / STDERR / EXIT_STATUS exact.
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def workload_indexed_rewrite_delete_start_workload() -> WorkloadDefinition:
    """Return the workload definition for indexed rewrite/delete/start."""
    return WorkloadDefinition(
        workload_id="indexed-rewrite-delete-start",
        description="INDEXED DYNAMIC — WRITE/dup INVALID KEY, REWRITE, "
                    "random READ, START (= and >=) + READ NEXT, DELETE, "
                    "INVALID/NOT INVALID KEY READ, CLOSE",
        artifacts=(
            WorkloadArtifact(
                logical_name="indexed-rewrite-delete-start-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="indexed-rewrite-delete-start-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="indexed-rewrite-delete-start-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
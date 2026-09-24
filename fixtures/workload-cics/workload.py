"""CICS modernization lane workload declaration.

Declares the CICS workload for the validation engine.  The workload does not
claim to execute on IBM CICS Transaction Server: it is a declarative source
fixture consumed by the CICS modernization lane (``engine.cics``) to map and
generate an explicit Java/Spring representation.

Artifacts mirror the standard ``STDOUT`` / ``STDERR`` / ``EXIT_STATUS``
declaration used by other lanes; no CICS-specific runtime oracle exists.
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def cics_workload() -> WorkloadDefinition:
    """Return the workload definition for the CICS modernization lane."""
    return WorkloadDefinition(
        workload_id="cics",
        description=(
            "CICS pseudo-conversational programs (CUSTINQ, ORDPROC) mapped to "
            "explicit Spring services; NOT executed on CICS TS."
        ),
        artifacts=(
            WorkloadArtifact(
                logical_name="cics-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="cics-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="cics-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )
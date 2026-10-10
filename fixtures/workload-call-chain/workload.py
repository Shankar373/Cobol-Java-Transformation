"""Multi-program CALL chain (A -> B -> C) workload declaration.

MAIN (CHAINMAIN) calls MIDPROG which calls LEAFPROG, passing a result
area BY REFERENCE through two levels so mutation is observable in the
final DISPLAY. Deterministic observable output for end-to-end
verification.
"""

from __future__ import annotations

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition


def chain_runtime_workload() -> WorkloadDefinition:
    """Return the workload definition for the CALL chain runtime proof."""
    return WorkloadDefinition(
        workload_id="call-chain-runtime",
        description="A->B->C static CALL with BY REFERENCE result propagation",
        artifacts=(
            WorkloadArtifact(
                logical_name="call-chain-runtime-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="call-chain-runtime-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="call-chain-runtime-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

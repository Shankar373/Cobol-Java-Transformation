"""Fresh business-logic verified workload declaration.

Multi-program COBOL workload exercising:
- CALL
- MOVE (single and multi-target)
- SUBTRACT (in-place and GIVING)
- MULTIPLY (in-place and GIVING)
- COMPUTE (arithmetic expressions)
- EVALUATE (switch/case)
- PERFORM VARYING (for loop)
"""

from __future__ import annotations

from engine.contracts.models import FailurePolicy, NormalizationPolicy, OrderingPolicy
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput


def fresh_business_logic_workload() -> WorkloadDefinition:
    """Return the workload definition for fresh business logic verification."""
    return WorkloadDefinition(
        workload_id="fresh-business-logic",
        description="Fresh business-logic verification — multi-program COBOL with arithmetic, control flow, and multi-target MOVE",
        artifacts=(
            WorkloadArtifact(
                logical_name="business-logic-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="business-logic-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="business-logic-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

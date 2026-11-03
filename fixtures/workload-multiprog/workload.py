"""Multi-program workload declaration (MAINPROG CALLs CALCULATE).

The programs only DISPLAY: the observable behaviour is stdout, stderr and
the exit status. The previous declaration passed keyword arguments that
``WorkloadDefinition``/``WorkloadInput``/``WorkloadArtifact`` do not accept
(``cobol_sources``, ``name``, ``path``, ``comparator``) and declared an input
file and an ``output.txt`` the programs never touch, so resolving it always
failed (audit V18).
"""

from __future__ import annotations

from engine.workload import WorkloadArtifact, WorkloadDefinition


def workload_multiprog_workload() -> WorkloadDefinition:
    """Return the workload definition for the CALL-based multi-program app."""
    return WorkloadDefinition(
        workload_id="multiprog",
        description="MAINPROG calls CALCULATE by static CALL; both DISPLAY",
        artifacts=(
            WorkloadArtifact(
                logical_name="multiprog-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
            ),
            WorkloadArtifact(
                logical_name="multiprog-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
            ),
            WorkloadArtifact(
                logical_name="multiprog-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )

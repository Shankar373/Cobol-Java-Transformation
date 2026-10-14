"""Shared construction of the JCL dependency graph.

``JclParser`` and ``JclDiscovery`` carried verbatim copies of this
construction; the single implementation here keeps the two lanes from
drifting.  Order is preserved exactly (step-order pairs per job, then EXEC
program references, then DD dataset references).
"""

from __future__ import annotations

from engine.transformation.ir import JclDependency, JclJob


def build_all_dependencies(jobs: list[JclJob]) -> list[JclDependency]:
    """Build step-order, EXEC, and DD dependencies from parsed jobs."""
    dependencies: list[JclDependency] = []

    for job in jobs:
        # Step order dependencies
        for i in range(len(job.steps) - 1):
            current = job.steps[i]
            next_step = job.steps[i + 1]

            if current.condition is None:
                dependencies.append(JclDependency(
                    source=current.name,
                    target=next_step.name,
                    dependency_type="JCL_STEP_ORDER",
                    metadata=f"job={job.name}",
                ))

        # EXEC program references
        for step in job.steps:
            if step.exec_ and step.exec_.program:
                dependencies.append(JclDependency(
                    source=f"{job.name}.{step.name}",
                    target=step.exec_.program,
                    dependency_type="JCL_EXEC",
                    metadata=f"job={job.name}",
                ))

        # DD dataset references
        for step in job.steps:
            for dd in step.dd_statements:
                if dd.dataset:
                    dependencies.append(JclDependency(
                        source=f"{job.name}.{step.name}.{dd.name}",
                        target=dd.dataset,
                        dependency_type="JCL_DD",
                        metadata=f"disp={dd.disposition}" if dd.disposition else "",
                    ))

    return dependencies

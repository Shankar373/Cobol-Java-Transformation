"""Shared construction of the JCL dependency graph.

``JclParser`` and ``JclDiscovery`` carried verbatim copies of this
construction; the single implementation here keeps the two lanes from
drifting.  Order is preserved exactly (step-order pairs per job, then EXEC
program references, then step DD dataset references, then job-level DD
dataset references).
"""

from __future__ import annotations

from engine.transformation.ir import JclDependency, JclJob


def build_all_dependencies(jobs: list[JclJob]) -> list[JclDependency]:
    """Build step-order, EXEC, and DD dependencies from parsed jobs."""
    dependencies: list[JclDependency] = []

    for job in jobs:
        # Step order dependencies.  Every consecutive pair gets an edge:
        # a COND step still has a source-order successor (the semantic
        # lane emits it too — BL-076 parity).  The condition stays
        # visible in metadata instead of the edge silently vanishing.
        for i in range(len(job.steps) - 1):
            current = job.steps[i]
            next_step = job.steps[i + 1]

            metadata = f"job={job.name}"
            if current.condition is not None:
                code = current.condition.code or current.condition.condition_type
                metadata = f"{metadata};cond={code}"
            dependencies.append(JclDependency(
                source=current.name,
                target=next_step.name,
                dependency_type="JCL_STEP_ORDER",
                metadata=metadata,
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

        # Job-level DD datasets (JOBLIB & co. — BL-073): the job is the
        # owning scope, so the edge source has no step segment.
        for dd in job.job_dd_statements:
            if dd.dataset:
                dependencies.append(JclDependency(
                    source=f"{job.name}.{dd.name}",
                    target=dd.dataset,
                    dependency_type="JCL_DD",
                    metadata=f"disp={dd.disposition}" if dd.disposition else "",
                ))

    return dependencies

"""Java/Spring Batch representation IR for the JCL modernization lane.

Defines the target representation that a JCL modernization profile produces:

    JclSemanticModel
        ↓
    JclSpringBatchMapper
        ↓
    SpringBatchApplication
        ├── SpringBatchJob (one per JCL JOB)
        │   ├── SpringBatchStep (one per EXEC step)
        │   │   └── SpringBatchResource (one per DD)
        │   └── SpringBatchFlowEdge (step activation/ordering)
        └── SpringBatchDatasetEdge (dataset producer → consumer)

The representation is *declared*, not executed:

- Steps carry the EXEC PGM they invoke as a tasklet.
- Step activation is described with Spring Batch exit-status descriptors
  (SUCCESS / FAILED / "*" / CONDITIONAL).
- Return-code conditions are preserved as ``CONDITIONAL`` declared gates.

No JES/z/OS runtime equivalence is claimed anywhere in this model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

PROFILE_VERSION = "1.0"

# Spring Batch exit-status descriptors used by the mapper.
EXIT_STATUS_SUCCESS = "SUCCESS"
EXIT_STATUS_FAILED = "FAILED"
EXIT_STATUS_ANY = "*"
EXIT_STATUS_CONDITIONAL = "CONDITIONAL"
EXIT_STATUS_UNKNOWN = "UNKNOWN"


class SpringBatchResourceType(Enum):
    """Role of a DD resource in the Spring Batch job."""

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    TEMP = "TEMP"
    SYSOUT_LOG = "SYSOUT_LOG"
    INLINE_PARAMS = "INLINE_PARAMS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SpringBatchResource:
    """A DD resource mapped onto a Spring Batch reader/writer/log boundary."""

    name: str  # DD name
    resource_type: SpringBatchResourceType
    dsn: str = ""
    disposition: str = ""
    bean: str = ""  # deterministic Spring bean name
    step_ref: str = ""  # owning step name


@dataclass(frozen=True)
class SpringBatchStep:
    """A Spring Batch step mapped from a JCL EXEC step.

    ``program`` is the EXEC PGM the step's tasklet would invoke. Empty when the
    JCL step had no usable program (the diagnostic trail explains why).
    """

    name: str  # deterministic step/bean name
    program: str  # EXEC PGM (empty for no-op placeholders)
    tasklet_bean: str
    resources: tuple[SpringBatchResource, ...] = ()
    activation: str = EXIT_STATUS_SUCCESS  # how this step is reached
    raw_condition: str = ""  # preserved COND text when activation is CONDITIONAL
    source_step: str = ""  # original JCL step name


@dataclass(frozen=True)
class SpringBatchFlowEdge:
    """A Spring Batch conditional-flow transition between steps."""

    source: str  # preceding step name
    target: str  # step name being activated
    on_status: str  # SUCCESS / FAILED / "*" / CONDITIONAL


@dataclass(frozen=True)
class SpringBatchDatasetEdge:
    """Dataset producer → consumer relationship within a job."""

    job: str
    dataset: str
    producer: str  # step name or "" for external input
    consumer: str


@dataclass(frozen=True)
class SpringBatchJob:
    """A Spring Batch job mapped from a JCL JOB."""

    name: str
    job_bean: str
    start_step: str  # first step executed by the job
    steps: tuple[SpringBatchStep, ...] = ()
    flows: tuple[SpringBatchFlowEdge, ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()
    source_path: str = ""


@dataclass(frozen=True)
class SpringBatchApplication:
    """The complete Java/Spring Batch modernization representation."""

    application_id: str
    base_package: str = "com.generated.batch"
    jobs: tuple[SpringBatchJob, ...] = ()
    resources: tuple[SpringBatchResource, ...] = ()  # global inventory
    dataset_edges: tuple[SpringBatchDatasetEdge, ...] = ()
    profile_version: str = PROFILE_VERSION

    def get_job(self, name: str) -> SpringBatchJob | None:
        """Find a job by name."""
        for job in self.jobs:
            if job.name == name:
                return job
        return None

    def get_step(self, job_name: str, step_name: str) -> SpringBatchStep | None:
        """Find a step by job and step name."""
        job = self.get_job(job_name)
        if job is None:
            return None
        for step in job.steps:
            if step.name == step_name:
                return step
        return None

    def validate(self) -> list[str]:
        """Validate the Spring Batch representation.

        Returns a list of validation errors (empty when valid).
        """
        errors: list[str] = []

        seen_jobs: set[str] = set()
        for job in self.jobs:
            if job.name in seen_jobs:
                errors.append(f"Duplicate job name: {job.name}")
            seen_jobs.add(job.name)

            step_names = {step.name for step in job.steps}
            if job.start_step and job.start_step not in step_names:
                errors.append(
                    f"Job {job.name} start step not in steps: {job.start_step}"
                )

            for flow in job.flows:
                if flow.source and flow.source not in step_names:
                    errors.append(
                        f"Invalid flow source: {flow.source} in job {job.name}"
                    )
                if flow.target not in step_names:
                    errors.append(
                        f"Invalid flow target: {flow.target} in job {job.name}"
                    )

            seen_beans: set[str] = set()
            for step in job.steps:
                if step.tasklet_bean in seen_beans:
                    errors.append(
                        f"Duplicate tasklet bean: {step.tasklet_bean} in job {job.name}"
                    )
                seen_beans.add(step.tasklet_bean)

        seen_resources: set[tuple[str, str, str]] = set()
        for resource in self.resources:
            key = (resource.name, resource.dsn, resource.step_ref)
            if key in seen_resources:
                errors.append(
                    f"Duplicate resource: {resource.name} in {resource.step_ref}"
                )
            seen_resources.add(key)

        return errors

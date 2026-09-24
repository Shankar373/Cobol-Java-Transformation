"""Semantic JCL model.

A deterministic, domain-neutral model of the *supported subset* of JCL:

- JOB statements
- EXEC steps (PGM only in the initial profile)
- DD statements and dataset references
- step ordering
- simple step dependencies/control (COND=EVEN, COND=ONLY, discrete
  return-code conditions)

The model is built from the discovery JCL IR (``JclApplication``) plus raw
source text, which lets it report explicit diagnostics for constructs that the
discovery parser intentionally skips.

The model is an *application model*, not a runtime model. It describes what
steps exist, in what order, touching which datasets, subject to which declared
controls. It makes no claim about how JES/z/OS would execute it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JclExecMode(Enum):
    """Kind of EXEC statement."""

    PROGRAM = "PROGRAM"
    PROCEDURE = "PROCEDURE"
    NONE = "NONE"


class JclResourceKind(Enum):
    """Kind of DD resource."""

    DATASET = "DATASET"
    TEMPORARY = "TEMPORARY"
    SYSOUT = "SYSOUT"
    SYSIN_INLINE = "SYSIN_INLINE"
    UNKNOWN = "UNKNOWN"


class JclDisposition(Enum):
    """Normalized first-level dataset disposition."""

    SHR = "SHR"
    OLD = "OLD"
    NEW = "NEW"
    MOD = "MOD"
    UNSPECIFIED = "UNSPECIFIED"


class JclDatasetUse(Enum):
    """Dataset usage direction inferred from disposition."""

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    UNSPECIFIED = "UNSPECIFIED"


class JclControlKind(Enum):
    """How a step is activated relative to preceding steps."""

    SEQUENTIAL = "SEQUENTIAL"  # runs after prior step succeeds
    EVEN = "EVEN"  # COND=EVEN — runs regardless of prior outcome
    ONLY = "ONLY"  # COND=ONLY — runs only when a prior step failed
    RETURN_CODE = "RETURN_CODE"  # COND=(rc,comparator) — declared, not executed
    UNSUPPORTED = "UNSUPPORTED"  # recognized but outside the subset


@dataclass(frozen=True)
class JclExec:
    """Semantic EXEC for a step."""

    mode: JclExecMode = JclExecMode.NONE
    program: str = ""
    procedure: str = ""
    parameters: dict[str, str] | None = None


@dataclass(frozen=True)
class JclResource:
    """A semantic DD resource attached to a step."""

    name: str
    kind: JclResourceKind
    dataset: str = ""
    disposition: str = ""  # raw DISP text as written
    norm_disposition: JclDisposition = JclDisposition.UNSPECIFIED
    dataset_use: JclDatasetUse = JclDatasetUse.UNSPECIFIED
    is_temporary: bool = False
    sysout_target: str = ""
    is_inline: bool = False


@dataclass(frozen=True)
class JclControl:
    """Activation control for a step relative to prior steps."""

    kind: JclControlKind
    expression: str = ""  # raw COND text, e.g. "(0,NE)", "EVEN"
    exit_status: str = ""  # Spring Batch exit-status descriptor where derivable


@dataclass(frozen=True)
class JclSemanticStep:
    """A single execution step in a job."""

    name: str
    exec_: JclExec | None = None
    resources: tuple[JclResource, ...] = ()
    control: JclControl | None = None
    order_index: int = 0
    source_job: str = ""


@dataclass(frozen=True)
class JclDatasetFlow:
    """Within-job producer/consumer flow for one dataset.

    ``producer`` is the step that created the dataset (DISP=NEW/MOD), or empty
    when the dataset is an external input (no in-job producer).
    """

    job: str
    dataset: str
    producer: str
    consumers: tuple[str, ...]
    disposition: str = ""


@dataclass(frozen=True)
class JclDatasetInventory:
    """Model-wide occurrence of a dataset across jobs."""

    name: str
    jobs: tuple[str, ...] = ()
    kind: JclResourceKind = JclResourceKind.UNKNOWN
    uses: tuple[JclDatasetUse, ...] = ()


@dataclass(frozen=True)
class JclStepDependency:
    """Step activation dependency within a job.

    ``source`` is the preceding step ("" for the job start). ``target`` is the
    step being activated. The ``exit_status`` is the Java/Spring Batch
    transition descriptor the mapper will emit.
    """

    job: str
    source: str
    target: str
    control_kind: JclControlKind
    exit_status: str
    raw_condition: str = ""


@dataclass(frozen=True)
class JclSemanticJob:
    """A semantic JCL job."""

    name: str
    source_path: str = ""
    parameters: dict[str, str] | None = None
    steps: tuple[JclSemanticStep, ...] = ()
    dataset_flows: tuple[JclDatasetFlow, ...] = ()
    dependencies: tuple[JclStepDependency, ...] = ()


@dataclass(frozen=True)
class JclSemanticModel:
    """A complete semantic JCL application model."""

    jobs: tuple[JclSemanticJob, ...] = ()
    dataset_inventory: tuple[JclDatasetInventory, ...] = ()
    source_path: str = ""

    def get_job(self, job_name: str) -> JclSemanticJob | None:
        """Find a job by name."""
        for job in self.jobs:
            if job.name == job_name:
                return job
        return None

    def get_step(self, job_name: str, step_name: str) -> JclSemanticStep | None:
        """Find a step by job and step name."""
        job = self.get_job(job_name)
        if job is None:
            return None
        for step in job.steps:
            if step.name == step_name:
                return step
        return None

    def step_order(self, job_name: str) -> list[str]:
        """Ordered step names for a job (source order semantics)."""
        job = self.get_job(job_name)
        if job is None:
            return []
        return [s.name for s in job.steps]

    def dataset_references(self, job_name: str) -> list[tuple[str, str, str]]:
        """All (step, dd_name, dataset) references for a job."""
        refs: list[tuple[str, str, str]] = []
        job = self.get_job(job_name)
        if job is None:
            return refs
        for step in job.steps:
            for resource in step.resources:
                if resource.dataset:
                    refs.append((step.name, resource.name, resource.dataset))
        return refs

    def validate(self) -> list[str]:
        """Validate the semantic model.

        Returns a list of validation errors. An empty list means the model is
        internally consistent for the supported subset.
        """
        errors: list[str] = []
        for job in self.jobs:
            if not job.name:
                errors.append(
                    f"Malformed JOB in {job.source_path or '<unknown>'}: missing name"
                )
            seen: set[str] = set()
            for step in job.steps:
                if step.name in seen:
                    errors.append(f"Duplicate step name: {step.name} in job {job.name}")
                seen.add(step.name)
                if step.exec_ is None or (
                    step.exec_.mode == JclExecMode.NONE
                    and not step.exec_.program
                    and not step.exec_.procedure
                ):
                    errors.append(
                        f"Step {step.name} in job {job.name} has no EXEC program"
                    )
            for dep in job.dependencies:
                names = {s.name for s in job.steps}
                if dep.source and dep.source not in names:
                    errors.append(
                        f"Dependency source not a step: {dep.source} in job {job.name}"
                    )
                if dep.target not in names:
                    errors.append(
                        f"Dependency target not a step: {dep.target} in job {job.name}"
                    )
        return errors

    def unsupported_jobs(self) -> list[str]:
        """Job names whose model indicates unsupported constructs (no-op stub).

        Provided for symmetry with the shared IR; the diagnostics carried by
        the modernization profile are the authoritative signal.
        """
        return []

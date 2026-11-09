"""JCL job runners as part of application assembly (roadmap unit 39).

``engine.jcl.orchestrator`` turns a parsed job into a plain-Java launcher. This module is the integration: it finds the
JCL members of the source tree, plans every job against the programs the assembly generated, and writes one runner per
runnable job next to the generated programs, so a modernized job stream ships with the programs it runs. A job that is
outside the orchestrator's certified subset gets no runner and its refusals are reported, never guessed.

Only the command-line runtimes carry the runner: their programs are plain classes with a ``main`` in the default
package, which is what a job step launches. A Spring Boot project packages programs as framework components, so the
runner is not generated there and the report says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.jcl.orchestrator import orchestrate, runner_class_name
from engine.transformation.jcl_discovery import find_jcl_members
from engine.transformation.jcl_parser import JclParser

#: Runtime targets whose generated programs are launchable classes (default package, ``public static void main``).
JOB_RUNNER_RUNTIMES = frozenset({"plain_java", "quarkus", "micronaut", "jakarta_ee"})


@dataclass(frozen=True)
class JobAssembly:
    job: str
    runner_class: str  # empty when the job is refused
    refusals: tuple[str, ...] = ()
    source: str = ""

    @property
    def runnable(self) -> bool:
        return bool(self.runner_class)

    def to_dict(self) -> dict:
        return {"job": self.job, "runner_class": self.runner_class, "runnable": self.runnable,
                "refusals": list(self.refusals), "source": self.source}


def has_jcl_members(source_dir: str | Path) -> bool:
    return bool(find_jcl_members(Path(source_dir)))


def assemble_job_runners(
    source_dir: str | Path,
    project_dir: str | Path,
    program_classes: dict[str, str],
) -> tuple[JobAssembly, ...]:
    """Write a runner per runnable job under ``project_dir`` and return one record per job found in ``source_dir``.

    ``program_classes`` maps PROGRAM-ID (upper case) to the generated main class.
    """
    root = Path(source_dir)
    sources = {
        str(member.relative_to(root)).replace("\\", "/"): member.read_text(encoding="utf-8", errors="replace")
        for member in find_jcl_members(root)
    }
    if not sources:
        return ()
    app = JclParser().parse_application(sources)
    result = orchestrate(app, {k.upper(): v for k, v in program_classes.items()})
    java_dir = Path(project_dir) / "src" / "main" / "java"
    java_dir.mkdir(parents=True, exist_ok=True)
    names = [runner_class_name(plan.job) for plan in result.plans if plan.runnable]
    duplicated = {name for name in names if names.count(name) > 1}
    for name, source in result.files.items():
        if name not in duplicated:  # two jobs of one name would share a class: neither gets a runner
            (java_dir / f"{name}.java").write_text(source, encoding="utf-8")
    records = []
    for job, plan in zip(app.jobs, result.plans, strict=True):
        runner = runner_class_name(plan.job) if plan.runnable else ""
        refusals = plan.refusals
        if runner in duplicated:
            runner, refusals = "", (*refusals, f"job {plan.job} is defined more than once")
        records.append(JobAssembly(job=plan.job, runner_class=runner, refusals=refusals,
                                   source=getattr(job, "source_path", "") or ""))
    return tuple(records)

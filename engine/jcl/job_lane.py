"""The JCL job lane of the validation workflow (roadmap unit 40).

For every job the assembly gave a runner, run the job twice in hardened containers and compare:

* **Java side**: the generated project's sources are compiled and the pipeline-generated runner executes the job;
* **reference side**: the COBOL programs are compiled by GnuCOBOL and ``engine.jcl.reference`` executes the same job
  as shell steps.

Standard output (step order, ``BYPASSED`` markers, return codes, JCL errors), the exit status (highest return code, 255
for a JCL error) and the bytes of every dataset left under the data directory must be identical. A job the reference
driver cannot reproduce, a program that cannot be compiled and a missing Docker image are never a pass: the verdict is
``UNAVAILABLE`` with the reason. The evidence is GnuCOBOL against generated Java under *documented* JCL semantics
(``SIMULATOR`` grade for JCL itself); it is not an IBM JES or z/OS result.

Datasets a job reads (``DISP=OLD`` / ``SHR``) are seeded from ``<source>/datasets/`` when that directory exists, into
both data directories.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from engine.candidate.image_provenance import resolve_docker_image_identity
from engine.execution.container_hardening import container_run_hardening_flags, prepare_host_tree
from engine.execution.container_runner import run_container
from engine.execution.sandbox_paths import docker_volume_arg, sandbox_staging_dir
from engine.jcl.assembly import JobAssembly
from engine.jcl.orchestrator import JobPlan, plan_job
from engine.jcl.reference import ReferenceUnavailable, render_reference
from engine.transformation.jcl_discovery import find_jcl_members
from engine.transformation.jcl_parser import JclParser
from engine.transformation.source_format import detect_source_format

ORACLE_IMAGE = "gnucobol-ocesql:latest"
JAVA_IMAGE = "eclipse-temurin:21-jdk"

VERIFIED = "VERIFIED"
MISMATCH = "MISMATCH"
UNAVAILABLE = "UNAVAILABLE"

_PROGRAM_ID = re.compile(r"PROGRAM-ID\.\s+([A-Za-z0-9-]+)", re.IGNORECASE)
_FRAMEWORK_IMPORT = re.compile(r"^import\s+(?:io\.quarkus|io\.micronaut|jakarta|javax|org\.springframework)\.", re.MULTILINE)
_COBOL_SUFFIXES = {".cob", ".cbl", ".cobol"}
_COPYBOOK_SUFFIXES = {".cpy", ".copy"}


@dataclass(frozen=True)
class JobVerification:
    job: str
    verdict: str  # VERIFIED | MISMATCH | UNAVAILABLE
    reasons: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()  # the "JCL step ..." lines of the reference run, in order
    exit_status: int | None = None
    datasets: tuple[str, ...] = ()  # compared dataset paths
    evidence_hash: str = ""
    grade: str = "GnuCOBOL programs under documented JCL semantics (simulator-grade JCL; not IBM JES)"
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job": self.job, "verdict": self.verdict, "reasons": list(self.reasons), "steps": list(self.steps),
            "exit_status": self.exit_status, "datasets": list(self.datasets),
            "evidence_hash": self.evidence_hash, "grade": self.grade, "details": dict(self.details),
        }


def program_sources(source_dir: Path) -> dict[str, Path]:
    """PROGRAM-ID (upper case) -> source file, for the COBOL files of the tree."""
    found: dict[str, Path] = {}
    for path in sorted(source_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in _COBOL_SUFFIXES:
            match = _PROGRAM_ID.search(path.read_text(encoding="utf-8", errors="replace"))
            if match:
                found.setdefault(match.group(1).upper(), path)
    return found


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` except the job's temporary area, by relative path."""
    files: dict[str, bytes] = {}
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_file() and not relative.startswith("_tmp/"):
                files[relative] = path.read_bytes()
    return files


def _image_ref(image: str) -> str:
    observation = resolve_docker_image_identity(image)
    if not observation.is_complete:
        raise RuntimeError(f"image {image} has no immutable identity (is it pulled?)")
    return observation.identity


def _cleanup(name: str) -> tuple[bool, str]:
    proc = subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
    return proc.returncode == 0, proc.stderr.decode(errors="replace").strip()


def _run(image_ref: str, work: Path, script: str, *, lane: str, name: str, seconds: int):
    prepare_host_tree(work, writable=True)
    command = [
        "docker", "run", "--rm", "--init", *container_run_hardening_flags(lane), "--name", name,
        "--network", "none", "--memory", "1g", "--cpus", "2", "--pids-limit", "256",
        "--workdir", "/w", *docker_volume_arg(work, "/w", readonly=False), image_ref, "sh", "-c", script,
    ]
    return run_container(
        command, input_data=None, timeout_seconds=seconds, container_name=name, label=lane, cleanup=_cleanup)


def _compile_script(plan: JobPlan, sources: dict[str, Path], source_dir: Path, staged: Path) -> str:
    """The ``cobc`` commands of every program the job runs (each linked with the other modules of the tree)."""
    programs = sorted({s.program for s in plan.steps if not s.utility})
    missing = [p for p in programs if p not in sources]
    if missing:
        raise ReferenceUnavailable(tuple(f"COBOL source of program {p} not found" for p in missing))
    formats = {detect_source_format(path.read_text(encoding="utf-8", errors="replace")) for path in sources.values()}
    if len(formats) > 1:
        raise ReferenceUnavailable(("the COBOL sources mix source formats; one cobc flag cannot compile them all",))
    flag = "-free" if formats == {"free"} else ""
    copy_dirs = sorted({p.parent for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() in _COPYBOOK_SUFFIXES})
    includes = " ".join(
        "-I " + ("/w/src/" + d.relative_to(source_dir).as_posix()).rstrip("/.") for d in copy_dirs)
    lines = ["mkdir -p /w/bin"]
    for program in programs:
        others = " ".join(
            f"/w/src/{path.relative_to(source_dir).as_posix()}" for pid, path in sorted(sources.items())
            if pid != program)
        main = f"/w/src/{sources[program].relative_to(source_dir).as_posix()}"
        lines.append(f"cobc -x {flag} {includes} -o /w/bin/{program} {main} {others} || exit 254")
    return " && ".join(f"( {line} )" if line.startswith("cobc") else line for line in lines)


def verify_job(
    assembly: JobAssembly,
    plan: JobPlan,
    *,
    source_dir: Path,
    project_dir: Path,
    seconds: int = 120,
) -> JobVerification:
    """Run one job on both sides and compare (never raises: every failure is an ``UNAVAILABLE`` verdict)."""
    job = assembly.job
    if not assembly.runnable:
        return JobVerification(job, UNAVAILABLE, reasons=("no runner was generated: " + "; ".join(assembly.refusals),))
    try:
        reference = render_reference(plan)
        oracle_ref, java_ref = _image_ref(ORACLE_IMAGE), _image_ref(JAVA_IMAGE)
        sources = program_sources(source_dir)
        with sandbox_staging_dir("jcl-job-") as staging:
            root = Path(staging)
            cobol_dir, java_dir = root / "cobol", root / "java"
            for side in (cobol_dir, java_dir):
                (side / "data").mkdir(parents=True)
            shutil.copytree(source_dir, cobol_dir / "src", ignore=shutil.ignore_patterns("datasets"))
            (java_dir / "src").mkdir()
            for java in (project_dir / "src" / "main" / "java").glob("*.java"):
                # the programs and the runner are dependency-free; a framework entry class (Quarkus, Micronaut) is
                # not part of what a job step launches and cannot compile without its framework
                if not _FRAMEWORK_IMPORT.search(java.read_text(encoding="utf-8", errors="replace")):
                    shutil.copy(java, java_dir / "src" / java.name)
            seed = source_dir / "datasets"
            if seed.is_dir():
                for side in (cobol_dir, java_dir):
                    shutil.copytree(seed, side / "data", dirs_exist_ok=True)
            (cobol_dir / "reference.sh").write_text(reference, encoding="utf-8", newline="\n")
            digest = hashlib.sha256(os.urandom(8)).hexdigest()[:10]
            compile_script = _compile_script(plan, sources, source_dir, cobol_dir)
            cobol = _run(
                oracle_ref, cobol_dir, f"{compile_script} && sh /w/reference.sh /w/data /w/bin",
                lane="oracle", name=f"jcl-ref-{digest}", seconds=seconds)
            java = _run(
                java_ref, java_dir,
                f"mkdir -p /tmp/c && javac -nowarn -d /tmp/c /w/src/*.java && "
                f"java -cp /tmp/c {assembly.runner_class} /w/data /tmp/c",
                lane="java-exec", name=f"jcl-run-{digest}", seconds=seconds)
            if cobol.termination in ("error", "timeout") or java.termination in ("error", "timeout"):
                return JobVerification(job, UNAVAILABLE, reasons=(
                    f"reference run {cobol.termination}, generated run {java.termination}",))
            if cobol.exit_code == 254:
                return JobVerification(job, UNAVAILABLE, reasons=(
                    "a COBOL program of the job did not compile under GnuCOBOL: "
                    + cobol.stdout.decode(errors="replace")[-300:] + cobol.stderr.decode(errors="replace")[-300:],))
            data_ref, data_java = _tree(cobol_dir / "data"), _tree(java_dir / "data")
    except ReferenceUnavailable as exc:
        return JobVerification(job, UNAVAILABLE, reasons=exc.reasons)
    except Exception as exc:  # noqa: BLE001 - the lane must never fail the run, only withhold the proof
        return JobVerification(job, UNAVAILABLE, reasons=(f"job lane failed: {exc}",))

    reasons: list[str] = []
    if java.stdout != cobol.stdout:
        reasons.append("standard output differs (step order, bypasses, return codes or program output)")
    if java.exit_code != cobol.exit_code:
        reasons.append(f"exit status differs: reference {cobol.exit_code}, generated {java.exit_code}")
    for name in sorted(set(data_ref) | set(data_java)):
        if data_ref.get(name) != data_java.get(name):
            reasons.append(f"dataset {name} differs or exists on one side only")
    lines = tuple(line for line in cobol.stdout.decode(errors="replace").splitlines() if line.startswith("JCL "))
    evidence = hashlib.sha256(cobol.stdout + bytes([cobol.exit_code or 0]) + b"".join(
        k.encode() + v for k, v in sorted(data_ref.items()))).hexdigest()
    return JobVerification(
        job, MISMATCH if reasons else VERIFIED, reasons=tuple(reasons), steps=lines,
        exit_status=cobol.exit_code, datasets=tuple(sorted(data_ref)), evidence_hash=evidence)


def verify_jobs(
    source_dir: str | Path,
    project_dir: str | Path,
    assemblies: tuple[JobAssembly, ...],
    *,
    seconds: int = 120,
) -> tuple[JobVerification, ...]:
    """Verify every job of ``assemblies`` (the records ``assemble_job_runners`` returned)."""
    root, project = Path(source_dir), Path(project_dir)
    members = {
        str(member.relative_to(root)).replace("\\", "/"): member.read_text(encoding="utf-8", errors="replace")
        for member in find_jcl_members(root)
    }
    program_classes = {pid: pid for pid in program_sources(root)}
    app = JclParser().parse_application(members) if members else None
    plans: dict[str, JobPlan] = {}
    if app is not None:
        for job in app.jobs:
            plans.setdefault(job.name, plan_job(job, program_classes))
    results = []
    for assembly in assemblies:
        plan = plans.get(assembly.job)
        if plan is None:
            results.append(JobVerification(assembly.job, UNAVAILABLE, reasons=("job not found in the JCL members",)))
        else:
            results.append(verify_job(assembly, plan, source_dir=root, project_dir=project, seconds=seconds))
    return tuple(results)


__all__ = ["JobVerification", "MISMATCH", "UNAVAILABLE", "VERIFIED", "verify_job", "verify_jobs"]

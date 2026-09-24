"""Fresh Baseline Differential Verification — real SystemaOps path, 20 workloads.

Runs each workload through the REAL production modernization + validation
chain exactly as api/service.py does:

    load workload.py factory (declared artifacts/comparators)
    -> ApplicationDiscovery().discover(cobol_dir, application_id)
    -> ApplicationGenerator().generate(discovered, entrypoint=main, source_root=cobol_dir)
    -> map_java_application_to_spring_boot(java_application, entry_program=main, copybook_models)
    -> SpringBootGenerator().generate_project(spring_app)
    -> write project files into an isolated project directory
    -> VerticalSlicePipeline(docker oracle + docker spring-boot candidate)
    -> real compare/evidence/verdict

Each workload's outcome is recorded as a ladder stage:

    NOT_IMPLEMENTED -> PARSED_ONLY -> MODELED_ONLY -> TRANSFORMED
    -> BUILDS -> EXECUTES -> ORACLE_MATCHED -> FRESH_VERIFIED

plus an explicit failure cause (DOCKER_UNAVAILABLE -> ENVIRONMENTAL,
PARSE_ERROR, TRANSFORM_ERROR, SPRING_MAPPING_ERROR, MAVEN_BUILD_FAILED,
EXECUTION_ERROR, MISMATCH, EVIDENCE_ERROR, VACUOUS_FIXED_RECORD).

Empty-vs-empty FIXED_RECORD matches are flagged as VACUOUS and never count
as genuine ORACLE_MATCHED/VERIFIED evidence.

THIS FILE ONLY READS PRODUCTION CODE AND WRITES TEST/VERIFICATION OUTPUT.
It never imports or executes host javac/java (production boundary).
Host java is NEVER used. Docker is the only validation boundary.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.candidate.docker_spring_boot_adapter import (  # noqa: E402
    DockerSpringBootCandidateAdapter,
)
from engine.pipeline import PipelineConfig, VerticalSlicePipeline  # noqa: E402
from engine.transformation.application_discovery import ApplicationDiscovery  # noqa: E402
from engine.transformation.application_generator import ApplicationGenerator  # noqa: E402
from engine.transformation.java_to_spring_mapping import (  # noqa: E402
    map_java_application_to_spring_boot,
)
from engine.transformation.spring_boot_generator import SpringBootGenerator  # noqa: E402

FIXTURES_ROOT = REPO_ROOT / "fixtures"
RESULTS_DIR = Path(__file__).parent / "results_fresh"
GENERATED_ROOT = RESULTS_DIR / "generated_apps"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_ROOT.mkdir(parents=True, exist_ok=True)

WORKLOAD_ORDER = [
    "workload-call-linkage", "workload-by-reference", "workload-by-content",
    "workload-by-value", "workload-dynamic-call", "workload-copybook",
    "workload-subtract", "workload-multiply", "workload-evaluate",
    "workload-perform-varying", "workload-occurs", "workload-redefines",
    "workload-level88", "workload-comp", "workload-comp3",
    "workload-indexed-file", "workload-relative-file", "workload-rewrite",
    "workload-delete", "workload-start-invalidkey",
    "workload-file-write-read",
]

STAGE_ORDER = [
    "NOT_IMPLEMENTED", "PARSED_ONLY", "MODELED_ONLY", "TRANSFORMED",
    "BUILDS", "EXECUTES", "ORACLE_MATCHED", "FRESH_VERIFIED",
]

MAIN_MARKERS = {"main.cob", "main.cbl", "MAIN.COB", "MAIN.CBL"}


def git_head() -> str:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, timeout=10, cwd=str(REPO_ROOT),
        )
        return r.stdout.decode().strip() or ""
    except Exception:
        return ""


def load_workload_factory(workload_dir: Path):
    """Import the workload factory module and return its factory callable."""
    workload_py = workload_dir / "workload.py"
    if not workload_py.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        f"wl_{workload_dir.name}", workload_py
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    func_name = f"{workload_dir.name.replace('-', '_')}_workload"
    if not hasattr(module, func_name):
        for attr in dir(module):
            if attr.endswith("_workload") and callable(getattr(module, attr)):
                func_name = attr
                break
    return getattr(module, func_name, None)


def discover_main_program_id(discovered, source_root: Path) -> str:
    """Deterministic main selection using the same conventions as the oracle adapter."""
    units = list(discovered.programs)
    if not units:
        return ""
    primary = [
        u for u in units
        if Path(u.source_path).name in MAIN_MARKERS
        or u.program_id.upper() == "MAIN"
    ]
    if primary:
        return primary[0].program_id
    if len(units) == 1:
        return units[0].program_id
    return units[0].program_id


@dataclass
class WorkloadOutcome:
    workload_id: str
    capability: str
    stage: str
    oracle: str
    java: str
    comparators: str
    evidence: str
    verdict: str
    failure_cause: str
    detail: dict


def _write_project_files(files, project_dir: Path) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    resolved_root = project_dir.resolve()
    for gen_file in files:
        rel = getattr(gen_file, "path", "") or gen_file.filename
        parts = [p for p in Path(rel).parts if p not in ("", ".", "..") and ":" not in p]
        if not parts:
            continue
        target = (resolved_root / Path(*parts)).resolve()
        if target != resolved_root and resolved_root not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(gen_file.source_code, encoding="utf-8")
    return project_dir


def _measure_vacuous(artifact_type: str, oracle_ca, candidate_ca) -> bool:
    if artifact_type != "FIXED_RECORD":
        return False
    o_len = getattr(oracle_ca, "size_bytes", 0) if oracle_ca else 0
    c_len = getattr(candidate_ca, "size_bytes", 0) if candidate_ca else 0
    return o_len == 0 and c_len == 0


def run_workload(workload_id: str) -> WorkloadOutcome:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    detail: dict = {
        "workload_id": workload_id,
        "timestamp": ts,
        "git_head": git_head(),
        "stages": {s: False for s in STAGE_ORDER},
        "artifacts": [],
        "generated_files": [],
        "errors": [],
    }
    wl_dir = FIXTURES_ROOT / workload_id
    cobol_dir = wl_dir / "cobol"
    project_dir = GENERATED_ROOT / workload_id
    if project_dir.exists():
        import shutil
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    def cap_stage(name: str) -> None:
        detail["stages"][name] = True

    def set_stage_and_cause(stage: str, cause: str) -> WorkloadOutcome | None:
        cap_stage(stage)
        detail["failure_cause"] = cause
        out = WorkloadOutcome(
            workload_id=workload_id,
            capability=wl_dir.name,
            stage=stage if stage in STAGE_ORDER else "NOT_IMPLEMENTED",
            oracle=detail.get("oracle", ""),
            java=detail.get("java", ""),
            comparators=",".join(detail.get("comparator_ids", [])),
            evidence=detail.get("evidence_summary", ""),
            verdict=detail.get("verdict_state", ""),
            failure_cause=cause,
            detail=detail,
        )
        return out

    # -- 0. workload.py factory (declared contract) -------------------------
    factory = load_workload_factory(wl_dir)
    workload_def = None
    if factory is not None:
        try:
            workload_def = factory()
        except Exception as exc:
            detail["errors"].append(f"workload factory error: {exc}")
    if workload_def is None:
        return set_stage_and_cause("NOT_IMPLEMENTED", "workload.py missing or factory failed")
    detail["workload_description"] = getattr(workload_def, "description", "")
    detail["declared_artifacts"] = [
        a.artifact_type for a in getattr(workload_def, "artifacts", ())
    ]
    detail["declared_comparators"] = [
        a.comparator_id for a in getattr(workload_def, "artifacts", ())
    ]

    # -- 1. parse + discovery (PARSED_ONLY) ---------------------------------
    try:
        discovered = ApplicationDiscovery().discover(
            cobol_dir, application_id=f"{workload_id}-app"
        )
    except Exception as exc:
        detail["errors"].append(f"discovery error: {exc}")
        return set_stage_and_cause("NOT_IMPLEMENTED", f"PARSE_ERROR: {exc}")
    detail["program_ids"] = [u.program_id for u in discovered.programs]
    detail["source_files"] = [u.source_path for u in discovered.programs]
    detail["copybooks"] = list(discovered.copybooks)
    if not discovered.programs:
        return set_stage_and_cause("NOT_IMPLEMENTED", "PARSE_ERROR: no programs discovered")
    cap_stage("PARSED_ONLY")

    # -- 2. per-program transform + application assembly (JavaApplication) ---
    main_program_id = discover_main_program_id(discovered, cobol_dir)
    detail["main_program_id"] = main_program_id
    try:
        result = ApplicationGenerator().generate(
            discovered,
            entrypoint=main_program_id,
            source_root=str(cobol_dir),
        )
    except Exception as exc:
        detail["errors"].append(f"transform error: {exc}")
        return set_stage_and_cause("PARSED_ONLY", f"TRANSFORM_ERROR: {exc}")
    if not result.success:
        detail["errors"].extend(list(result.errors))
        return set_stage_and_cause(
            "PARSED_ONLY", "TRANSFORM_ERROR: " + "; ".join(result.errors)
        )
    if result.java_application is None:
        return set_stage_and_cause("PARSED_ONLY", "TRANSFORM_ERROR: no java_application")
    detail["java_application_files"] = [f.filename for f in result.generated_files]
    detail["program_ids"] = list(result.program_ids)
    cap_stage("MODELED_ONLY")

    # -- 3. Spring Boot mapping + generation ---------------------------------
    try:
        spring_app = map_java_application_to_spring_boot(
            result.java_application,
            entry_program=main_program_id,
            copybook_models=result.copybook_models,
        )
    except Exception as exc:
        detail["errors"].append(f"spring mapping error: {exc}")
        return set_stage_and_cause("MODELED_ONLY", f"SPRING_MAPPING_ERROR: {exc}")
    violations = spring_app.validate()
    if violations:
        return set_stage_and_cause(
            "MODELED_ONLY", "SPRING_MAPPING_ERROR: " + "; ".join(violations)
        )
    try:
        files = SpringBootGenerator().generate_project(spring_app)
    except Exception as exc:
        detail["errors"].append(f"spring generation error: {exc}")
        return set_stage_and_cause("MODELED_ONLY", f"SPRING_MAPPING_ERROR: {exc}")
    if not files:
        return set_stage_and_cause("MODELED_ONLY", "SPRING_MAPPING_ERROR: no files")
    _write_project_files(files, project_dir)
    entry = spring_app.entry_point
    entry_fqn = f"{entry.package}.{entry.class_name}" if entry and entry.package else ""
    detail["java_entrypoint"] = entry_fqn
    detail["generated_files"] = sorted(
        str(p.relative_to(project_dir)).replace("\\", "/")
        for p in project_dir.rglob("*") if p.is_file()
    )
    detail["pom_exists"] = (project_dir / "pom.xml").exists()
    cap_stage("TRANSFORMED")
    if not entry_fqn:
        return set_stage_and_cause("TRANSFORMED", "TRANSFORMED: no Spring entry point")

    # -- 4+ docker pipeline (oracle + spring-boot candidate) -----------------
    adapter = DockerSpringBootCandidateAdapter()
    detail["candidate_adapter_available"] = adapter._status.value
    detail["oracle"] = "gnucobol-ocesql:latest"
    detail["java"] = (
        f"maven-offline-springboot:latest -> eclipse-temurin:21-jdk "
        f"(entry {entry_fqn})"
    )
    if not adapter.available:
        return set_stage_and_cause(
            "TRANSFORMED", "ENVIRONMENTAL: Docker unavailable -> candidate adapter UNAVAILABLE"
        )

    config = PipelineConfig(
        workload_id=workload_id,
        cobol_source_path=str(cobol_dir),
        java_candidate_path=str(project_dir),
        java_entrypoint=entry_fqn,
        workload=workload_def,
        use_docker_java=True,
    )
    progress_log: list[str] = []
    try:
        pipeline = VerticalSlicePipeline(config, candidate_adapter=adapter)
        pr = pipeline.run(progress=lambda phase: progress_log.append(phase))
    except Exception as exc:
        detail["errors"].append(f"pipeline error: {exc}")
        traceback.print_exc(limit=3)
        return set_stage_and_cause("TRANSFORMED", f"EXECUTION_ERROR: {exc}")

    detail["progress_phases"] = progress_log
    detail["verdict_state"] = pr.verdict.state.value
    detail["oracle_termination"] = pr.oracle_evidence.termination_status
    detail["candidate_termination"] = pr.candidate_evidence.termination_status
    detail["oracle_exit_code"] = pr.oracle_exit_code
    detail["candidate_exit_code"] = pr.candidate_exit_code
    detail["oracle_stdout_len"] = len(pr.oracle_stdout)
    detail["candidate_stdout_len"] = len(pr.candidate_stdout)

    # Build stage: reliable marker — pipeline synthesizes *-compile-fail for build crashes
    compile_failed = pr.candidate_evidence.execution_id.value.endswith("-compile-fail")
    detail["candidate_execution_id"] = pr.candidate_evidence.execution_id.value
    cap_stage("BUILDS")

    if compile_failed:
        stderr_head = pr.candidate_stderr.decode(errors="replace")[:400]
        return set_stage_and_cause(
            "TRANSFORMED", f"MAVEN_BUILD_FAILED: {stderr_head}"
        )

    cap_stage("EXECUTES")

    # -- compare + evidence + verdict ----------------------------------------
    comparator_ids: list[str] = []
    comparison_rows: list[dict] = []
    vacuous_flags: list[str] = []
    integrity_violations: list[str] = []
    for ce in pr.comparison_evidence:
        comparator_ids.append(ce.comparator_id)
        rows = {
            "artifact_type": ce.artifact_type,
            "comparator_id": ce.comparator_id,
            "result": ce.result,
            "differences": list(ce.differences),
            "oracle_artifact_id": ce.oracle_artifact_id,
            "candidate_artifact_id": ce.candidate_artifact_id,
        }
        oracle_ca = next(
            (a for a in pr.artifact_evidence if a.artifact.artifact_id == ce.oracle_artifact_id),
            None,
        )
        candidate_ca = next(
            (a for a in pr.artifact_evidence if a.artifact.artifact_id == ce.candidate_artifact_id),
            None,
        )
        vac = _measure_vacuous(ce.artifact_type, oracle_ca, candidate_ca)
        if vac:
            vacuous_flags.append(ce.artifact_type)
        rows["vacuous"] = vac
        comparison_rows.append(rows)
        if ce.artifact_type == "FIXED_RECORD":
            rows["oracle_size"] = getattr(oracle_ca, "size_bytes", 0) if oracle_ca else 0
            rows["candidate_size"] = getattr(candidate_ca, "size_bytes", 0) if candidate_ca else 0

    detail["comparisons"] = comparison_rows
    detail["comparator_ids"] = sorted(set(comparator_ids))

    # Capture actual streams for mismatch diagnosis (test-only, not evidence).
    try:
        detail["oracle_stdout"] = pr.oracle_stdout.decode("utf-8", errors="replace")
        detail["candidate_stdout"] = pr.candidate_stdout.decode("utf-8", errors="replace")
        detail["oracle_stderr"] = pr.oracle_stderr.decode("utf-8", errors="replace")
        detail["candidate_stderr"] = pr.candidate_stderr.decode("utf-8", errors="replace")
    except Exception as exc:
        detail["errors"].append(f"stream capture: {exc}")

    manifest = pr.evidence_manifest
    detail["evidence_manifest_hash"] = str(manifest.manifest_hash)
    detail["executed_check_count"] = pr.verdict.executed_check_count
    detail["diff_count"] = len(list(pr.verdict.differences))

    integrity_result = (
        __import__("engine.evidence.integrity", fromlist=["EvidenceIntegrityValidator"])
        .EvidenceIntegrityValidator().validate(manifest)
    )
    if isinstance(integrity_result, list):
        integrity_violations = [v.description for v in integrity_result]
    detail["integrity_violations"] = integrity_violations

    detail["evidence_summary"] = (
        f"{len(comparison_rows)} comparisons, "
        f"{sum(1 for r in comparison_rows if r['result'] == 'MATCH')} MATCH, "
        f"{len(vacuous_flags)} vacuous, "
        f"{len(integrity_violations)} integrity violations"
    )

    all_match = comparison_rows and all(r["result"] == "MATCH" for r in comparison_rows)
    oracle_normal = pr.oracle_evidence.termination_status in ("normal", "nonzero_exit")
    candidate_normal = pr.candidate_evidence.termination_status in ("normal", "nonzero_exit")

    if integrity_violations:
        return set_stage_and_cause(
            "EXECUTES",
            "EVIDENCE_ERROR: " + "; ".join(integrity_violations),
        )
    if not all_match:
        diffs = [
            f"{r['artifact_type']}:{r['result']}"
            for r in comparison_rows if r["result"] != "MATCH"
        ]
        return set_stage_and_cause("EXECUTES", "MISMATCH: " + "; ".join(diffs))
    if vacuous_flags:
        detail["vacuous_fixed_records"] = vacuous_flags
        # Everything matched but a FIXED_RECORD artifact was empty on BOTH sides.
        # Not genuine record-level evidence — cap at ORACLE_MATCHED (flagged).
        cap_stage("ORACLE_MATCHED")
        return set_stage_and_cause(
            "ORACLE_MATCHED",
            "VACUOUS_FIXED_RECORD: FIXED_RECORD empty on both sides "
            "(relative ASSIGN writes to /workspace, not /workspace/output)",
        )
    cap_stage("ORACLE_MATCHED")
    cap_stage("FRESH_VERIFIED")
    return set_stage_and_cause("FRESH_VERIFIED", "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fresh baseline differential verification")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--skip", action="append", default=[])
    args = parser.parse_args()

    targets = args.only or WORKLOAD_ORDER
    targets = [t for t in targets if t not in set(args.skip or [])]

    outcomes: list[WorkloadOutcome] = []
    for idx, wl in enumerate(targets, start=1):
        print(f"\n=== [{idx}/{len(targets)}] {wl} ===", flush=True)
        outcome = run_workload(wl)
        outcomes.append(outcome)
        detail = outcome.detail
        (RESULTS_DIR / f"{wl}.json").write_text(
            json.dumps(detail, indent=2), encoding="utf-8"
        )
        print(
            f"   stage={outcome.stage} verdict={outcome.verdict or '-'} "
            f"cause={outcome.failure_cause or '-'}",
            flush=True,
        )

    summary_path = RESULTS_DIR / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "Workload", "Capability", "Current Stage", "Oracle", "Java",
            "Comparator", "Evidence", "Verdict", "Failure Cause",
        ])
        for o in outcomes:
            writer.writerow([
                o.workload_id, o.capability, o.stage, o.oracle, o.java,
                o.comparators, o.evidence, o.verdict, o.failure_cause,
            ])

    print("\n===== SUMMARY =====")
    header = ["Workload", "Stage", "Verdict", "Cause"]
    print(" | ".join(header))
    print("-" * 90)
    for o in outcomes:
        print(f"{o.workload_id:28s} | {o.stage:14s} | {o.verdict or '-':9s} | {o.failure_cause or '-'}")
    print(f"\nResults written to {RESULTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
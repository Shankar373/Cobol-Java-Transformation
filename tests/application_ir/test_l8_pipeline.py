"""Layer 8 L8-P1/P2 end to end: the plan the production pipeline draws, enforces and hands to Layer 7's capability record.

Real ``UniversalModernizationPipeline`` runs (generation only: no Docker, no oracle, no LLM).
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from engine.modernization import pipeline as pipeline_module
from engine.modernization.capability_analyzer import CapabilityLevel as L
from engine.modernization.capability_record import plan_id_of
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.modernization.transformation_plan import TransformationAction as A
from engine.transformation.entrypoint import normalise

REPO = Path(__file__).resolve().parents[2]


def prog(pid: str, calls: tuple[str, ...] = ()) -> str:
    body = "".join(f"           CALL '{c}'.\n" for c in calls)
    return ("       IDENTIFICATION DIVISION.\n" f"       PROGRAM-ID. {pid}.\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n"
            f"           DISPLAY '{pid}'.\n" + body + "           GOBACK.\n")


def run(tmp_path: Path, sources: dict[str, str], entrypoint: str = "", runtime: str = "spring_boot"):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    for name, text in sources.items():
        (src / name).write_text(text, encoding="utf-8")
    config = ModernizationConfig(source_dir=str(src), output_dir=str(out), application_id="l8", entrypoint=entrypoint,
                                 docker_available=True, target_runtime=runtime)
    return UniversalModernizationPipeline(config).execute()


def test_a_generated_multi_program_plan_is_ordered_callees_first_and_agrees_with_generation(tmp_path):
    report = run(tmp_path, {"main.cob": prog("MAIN", ("SUB",)), "sub.cob": prog("SUB")}, entrypoint="MAIN")
    plan = report.transformation_plan
    assert report.generation_success, report.generation_errors
    assert plan.execution_order == ("SUB", "MAIN") and plan.oracle.entry_program == "MAIN"
    assert plan.entry_transformable and plan.evidence_conflicts == ()
    # the pipeline itself refuses a generator/plan entry disagreement, so generation having succeeded proves agreement
    assert {normalise(p) for p in report.generated_program_ids} == {normalise(p) for p in plan.execution_order}
    assert normalise(plan.oracle.entry_program) in {normalise(p) for p in report.generated_program_ids}
    assert plan.assembly.include_service_registry is True
    assert plan.oracle.link_modules == ("sub.cob",)


def test_the_capability_record_binds_exactly_the_plan_the_pipeline_enforced(tmp_path):
    report = run(tmp_path, {"main.cob": prog("MAIN", ("SUB",)), "sub.cob": prog("SUB")}, entrypoint="MAIN")
    assert dict(report.capability_record)["plan_id"] == plan_id_of(report.transformation_plan)


def test_the_report_dict_carries_the_plan_evidence_fields(tmp_path):
    report = run(tmp_path, {"main.cob": prog("MAIN", ("SUB",)), "sub.cob": prog("SUB")}, entrypoint="MAIN")
    plan = report.to_dict()["plan"]
    assert plan["evidence_conflicts"] == [] and plan["oracle"]["link_modules"] == ["sub.cob"]
    assert [c["priority"] for c in plan["components"] if c["component_id"] in ("MAIN", "SUB")] == [2, 1]
    assert all(c["capability_level"] == "SUPPORTED" for c in plan["components"] if c["component_id"] in ("MAIN", "SUB"))


def test_a_refused_callee_blocks_its_caller_in_the_plan_but_the_refusal_names_the_root_cause_only(tmp_path):
    shutil.copytree(REPO / "fixtures" / "workload-multiprog" / "cobol", tmp_path / "fx")
    sources = {p.name: p.read_text(encoding="utf-8") for p in (tmp_path / "fx").iterdir() if p.is_file()}
    report = run(tmp_path, sources, entrypoint="MAINPROG")
    plan = report.transformation_plan
    by_id = {c.component_id: c for c in plan.components if c.component_type == "PROGRAM"}
    assert not report.generation_success
    assert by_id["CALCULATE"].action is A.SKIP and by_id["CALCULATE"].blocked_by == ""
    assert by_id["MAINPROG"].action is A.SKIP and by_id["MAINPROG"].blocked_by == "calls CALCULATE"
    assert report.generation_errors == ("Transformation plan contains non-transformable programs: CALCULATE",)
    assert not any("Dependency blocked" in line for line in report.limitations)


def test_a_conflicting_capability_report_is_refused_by_the_pipeline(tmp_path, monkeypatch):
    real = pipeline_module.CapabilityAnalyzer.analyze

    def forged(self, *args, **kwargs):
        return dataclasses.replace(real(self, *args, **kwargs), application_id="SOMEONE-ELSE")

    monkeypatch.setattr(pipeline_module.CapabilityAnalyzer, "analyze", forged)
    report = run(tmp_path, {"main.cob": prog("MAIN")}, entrypoint="MAIN")
    assert not report.generation_success and report.generated_project_dir == ""
    assert report.transformation_plan.evidence_conflicts
    assert any("conflict" in line for line in report.limitations)
    assert report.transformation_plan.transformable_programs == 0


def test_an_unproven_capability_level_never_reaches_generation(tmp_path, monkeypatch):
    real = pipeline_module.CapabilityAnalyzer.analyze

    def forged(self, *args, **kwargs):
        rep = real(self, *args, **kwargs)
        return dataclasses.replace(rep, overall_level=L.UNKNOWN, components=tuple(
            dataclasses.replace(c, level=L.UNKNOWN) for c in rep.components))

    monkeypatch.setattr(pipeline_module.CapabilityAnalyzer, "analyze", forged)
    report = run(tmp_path, {"main.cob": prog("MAIN")}, entrypoint="MAIN")
    assert not report.generation_success
    assert {c.action for c in report.transformation_plan.components if c.component_type == "PROGRAM"} == {A.SKIP}


def test_every_runtime_target_gets_the_same_actions_and_order(tmp_path):
    plans = []
    for runtime in ("spring_boot", "plain_java", "quarkus"):
        sub = tmp_path / runtime
        sub.mkdir()
        plan = run(sub, {"main.cob": prog("MAIN", ("SUB",)), "sub.cob": prog("SUB")}, "MAIN", runtime).transformation_plan
        plans.append(([(c.component_id, c.action, c.priority) for c in plan.components], plan.execution_order,
                      plan.assembly.output_type))
    assert plans[0][:2] == plans[1][:2] == plans[2][:2]
    assert len({p[2] for p in plans}) == 3          # only the assembly target differs

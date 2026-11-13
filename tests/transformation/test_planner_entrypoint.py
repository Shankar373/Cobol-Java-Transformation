"""G-24: the planner resolves the entrypoint with the generator's rules, or says it cannot.

``TransformationPlanGenerator._resolve_entrypoint`` fell back to the first transformable
program, then to the first program, so a plan for two independent programs carried an
apparently valid oracle entry although the generator (G-15) refuses the same application.
Contract: the same fail-closed selection in both layers; an unresolved plan has an empty
``oracle.entry_program``, an explicit ``entry_resolution == "UNRESOLVED"`` and the reason;
the pipeline refuses it; the generator and planner agree on every case.
Dependency-free (pytest only).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.modernization.transformation_plan import TransformationPlanGenerator
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator


def source(pid: str, calls: tuple[str, ...] = (), extra: str = "") -> str:
    body = "".join(f"           CALL '{c}'.\n" for c in calls)
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {pid}.\n"
        + extra +
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"           DISPLAY '{pid}'.\n"
        + body +
        "           GOBACK.\n"
    )


def build(tmp_path: Path, programs: dict[str, tuple[str, ...]], extra_files: dict[str, str] | None = None):
    for pid, calls in programs.items():
        (tmp_path / f"{pid.lower()}.cob").write_text(source(pid, calls), encoding="utf-8")
    for name, text in (extra_files or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    report = CapabilityAnalyzer(docker_available=False).analyze(app)
    return app, report


def plan_for(tmp_path, programs, requested="", extra_files=None):
    app, report = build(tmp_path, programs, extra_files)
    return app, TransformationPlanGenerator().generate(app, report, requested)


def norm(name: str) -> str:
    return name.replace("-", "").replace("_", "").upper()


def test_a_single_call_root_is_resolved_and_marked_resolved(tmp_path):
    _, plan = plan_for(tmp_path, {"MAIN": ("CALC",), "CALC": ()})
    assert plan.oracle.entry_program == "MAIN" and plan.oracle.entry_resolution == "RESOLVED"
    assert plan.entrypoint_resolved and plan.oracle.entry_diagnostic == ""


def test_an_explicit_request_may_name_a_callee(tmp_path):
    _, plan = plan_for(tmp_path, {"MAIN": ("CALC",), "CALC": ()}, requested="calc")
    assert plan.oracle.entry_program == "CALC" and plan.entrypoint_resolved


def test_a_wrong_request_does_not_fall_back(tmp_path):
    _, plan = plan_for(tmp_path, {"MAIN": ("CALC",), "CALC": ()}, requested="NOPE")
    assert plan.oracle.entry_program == "" and not plan.entrypoint_resolved
    assert plan.oracle.entry_resolution == "UNRESOLVED"
    assert "Requested entrypoint 'NOPE' matches no program" in plan.oracle.entry_diagnostic


def test_independent_programs_with_no_request_are_unresolved_and_named(tmp_path):
    _, plan = plan_for(tmp_path, {"ALPHA": (), "BETA": ()})
    assert plan.oracle.entry_program == "" and not plan.entrypoint_resolved
    assert "ambiguous" in plan.oracle.entry_diagnostic
    assert "ALPHA" in plan.oracle.entry_diagnostic and "BETA" in plan.oracle.entry_diagnostic


def test_several_roots_need_an_explicit_choice(tmp_path):
    _, plan = plan_for(tmp_path, {"ROOT1": ("LEAF",), "ROOT2": ("LEAF",), "LEAF": ()})
    assert not plan.entrypoint_resolved
    assert "ROOT1" in plan.oracle.entry_diagnostic and "ROOT2" in plan.oracle.entry_diagnostic
    assert "(ROOT1, ROOT2)" in plan.oracle.entry_diagnostic  # LEAF is called, so it is not a root
    _, chosen = plan_for(tmp_path, {"ROOT1": ("LEAF",), "ROOT2": ("LEAF",), "LEAF": ()},
                         requested="ROOT2")
    assert chosen.oracle.entry_program == "ROOT2"


def test_a_self_call_does_not_hide_the_root(tmp_path):
    _, plan = plan_for(tmp_path, {"RECUR": ("RECUR", "LEAF"), "LEAF": ()})
    assert plan.oracle.entry_program == "RECUR" and plan.entrypoint_resolved


def test_a_call_cycle_has_no_derivable_root(tmp_path):
    _, plan = plan_for(tmp_path, {"PING": ("PONG",), "PONG": ("PING",)})
    assert plan.oracle.entry_program == "" and not plan.entrypoint_resolved
    assert "every program is the target of a CALL" in plan.oracle.entry_diagnostic


def test_a_single_program_is_its_own_entrypoint(tmp_path):
    _, plan = plan_for(tmp_path, {"ONLY": ()})
    assert plan.oracle.entry_program == "ONLY" and plan.entrypoint_resolved


def test_a_copybook_is_never_the_entrypoint(tmp_path):
    _, plan = plan_for(tmp_path, {"ONLY": ()}, extra_files={"COMMON.cpy": "       01 COMMON-REC PIC X(10).\n"})
    assert plan.oracle.entry_program == "ONLY"
    _, bad = plan_for(tmp_path, {"ONLY": ()}, requested="COMMON")
    assert bad.oracle.entry_program == "" and not bad.entrypoint_resolved


def test_a_proven_root_that_cannot_be_transformed_stays_the_entry_but_the_program_is_skipped(tmp_path):
    (tmp_path / "root.cob").write_text(
        source("ROOT", ("LEAF",), extra="") .replace("           GOBACK.\n",
                                                      "           EXEC CICS RETURN END-EXEC.\n           GOBACK.\n"),
        encoding="utf-8")
    (tmp_path / "leaf.cob").write_text(source("LEAF"), encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    report = CapabilityAnalyzer(docker_available=False).analyze(app)
    plan = TransformationPlanGenerator().generate(app, report, "")
    root = next(c for c in plan.components if c.component_id == "ROOT")
    assert root.action.name == "SKIP"                       # refused for its construct
    assert plan.oracle.entry_program == "ROOT"              # an established root, not an arbitrary program


@pytest.mark.parametrize("programs,requested", [
    ({"MAIN": ("CALC",), "CALC": ()}, ""),
    ({"MAIN": ("CALC",), "CALC": ()}, "calc"),
    ({"MAIN": ("CALC",), "CALC": ()}, "NOPE"),
    ({"ALPHA": (), "BETA": ()}, ""),
    ({"ALPHA": (), "BETA": ()}, "beta"),
    ({"R1": ("L",), "R2": ("L",), "L": ()}, ""),
    ({"PING": ("PONG",), "PONG": ("PING",)}, ""),
    ({"RECUR": ("RECUR", "LEAF"), "LEAF": ()}, ""),
    ({"ONLY": ()}, ""),
])
def test_generator_and_planner_agree_or_both_refuse(tmp_path, programs, requested):
    app, plan = plan_for(tmp_path, programs, requested)
    generated = ApplicationGenerator().generate(app, entrypoint=requested, source_root=tmp_path)
    if plan.entrypoint_resolved:
        assert generated.success and norm(generated.entrypoint) == norm(plan.oracle.entry_program)
    else:
        assert not generated.success and generated.entrypoint == ""


def test_the_plan_serialises_its_entrypoint_state(tmp_path):
    _, plan = plan_for(tmp_path, ({"ALPHA": (), "BETA": ()}))
    data = plan.to_dict()
    assert data["oracle"]["entry_resolution"] == "UNRESOLVED"
    assert data["oracle"]["entry_program"] == "" and "ambiguous" in data["oracle"]["entry_diagnostic"]


def test_the_pipeline_refuses_an_unresolved_plan_before_generating(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for pid in ("ALPHA", "BETA"):
        (src / f"{pid}.cob").write_text(source(pid), encoding="utf-8")
    report = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(src), output_dir=str(tmp_path / "out"), application_id="two-roots",
        entrypoint="", docker_available=True, target_runtime="plain_java")).execute()
    assert report.generated_project_dir == ""
    assert any("ambiguous" in e for e in report.generation_errors)
    assert any("ambiguous" in limitation for limitation in report.limitations)

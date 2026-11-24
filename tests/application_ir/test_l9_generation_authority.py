"""Layer 9 L9-P1: the Layer 8 plan is the authority over what ``ApplicationGenerator`` may emit.

Unit (the two pure checks), mutation/adversarial (forged plans, an emitter that drops or adds a class), differential (with a plan
the generator emits exactly the bytes it emits without one, over the whole fixture corpus) and pipeline contract (the production
pipeline hands the generator the plan it enforced and the adapter the plan's entry).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from engine.application_ir.consume import canonical_application, ir_for_application
from engine.modernization import pipeline as pipeline_module
from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.modernization.transformation_plan import TransformationAction as A
from engine.modernization.transformation_plan import TransformationPlanGenerator
from engine.transformation import generation_authority as auth
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.java_generator import JavaGenerator

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())


def prog(pid: str, calls: tuple[str, ...] = ()) -> str:
    body = "".join(f"           CALL '{c}'.\n" for c in calls)
    return ("       IDENTIFICATION DIVISION.\n" f"       PROGRAM-ID. {pid}.\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n"
            f"           DISPLAY '{pid}'.\n" + body + "           GOBACK.\n")


def parts(tmp_path: Path, sources: dict[str, str], entry: str = ""):
    for name, text in sources.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path, application_id="l9")
    ir = ir_for_application(app, tmp_path)
    report = CapabilityAnalyzer(docker_available=True).analyze(app, tmp_path, ir=ir)
    plan = TransformationPlanGenerator().generate(canonical_application(app, ir, tmp_path), report, entry)
    return app, ir, plan


def generate(app, ir, plan, root, entry=""):
    return ApplicationGenerator().generate(app, entrypoint=entry, source_root=root, ir=ir, plan=plan)


def with_action(plan, program_id, action):
    return dataclasses.replace(plan, components=tuple(
        dataclasses.replace(c, action=action) if (c.component_type, c.component_id) == ("PROGRAM", program_id) else c
        for c in plan.components))


@pytest.fixture()
def two(tmp_path):
    return (*parts(tmp_path, {"main.cob": prog("MAIN", ("SUB",)), "sub.cob": prog("SUB")}, "MAIN"), tmp_path)


# ---- unit: preflight -------------------------------------------------------------------------------------------------------

def test_a_consistent_plan_has_no_preflight_problem(two):
    app, _ir, plan, _root = two
    assert auth.preflight(plan, "l9", [u.program_id for u in app.programs], "MAIN") == []
    assert auth.preflight(plan, "l9", [u.program_id for u in app.programs], "main") == []  # entry comparison is normalised
    assert auth.approved_program_ids(plan) == ("SUB", "MAIN")


def test_an_absent_plan_is_refused():
    assert auth.preflight(None, "l9", ["A"]) == ["Transformation plan is absent: generation requires an approved plan"]


def test_a_plan_for_another_application_is_refused(two):
    app, _ir, plan, _root = two
    assert any("not 'other'" in p for p in auth.preflight(plan, "other", ["MAIN", "SUB"]))


def test_a_plan_in_evidence_conflict_is_refused(two):
    _app, _ir, plan, _root = two
    forged = dataclasses.replace(plan, evidence_conflicts=("report is for another application",))
    assert any("conflict" in p for p in auth.preflight(forged, "l9", ["MAIN", "SUB"], "MAIN"))


@pytest.mark.parametrize("discovered", [["MAIN"], ["MAIN", "SUB", "EXTRA"], ["MAIN", "SUB", "SUB"]])
def test_a_plan_that_disagrees_with_the_application_on_programs_is_refused(two, discovered):
    _app, _ir, plan, _root = two
    assert any("disagree on programs" in p for p in auth.preflight(plan, "l9", discovered, "MAIN"))


def test_a_blocked_program_or_dependency_refuses_generation(two):
    _app, _ir, plan, _root = two
    blocked = with_action(plan, "SUB", A.SKIP)
    problems = auth.preflight(blocked, "l9", ["MAIN", "SUB"], "MAIN")
    assert any("PROGRAM SUB" in p for p in problems)


def test_a_plan_that_approves_nothing_or_has_no_entry_is_refused(tmp_path):
    _app, _ir, plan = parts(tmp_path, {"a.cob": prog("A"), "b.cob": prog("B")})  # two roots, no entry requested
    assert not plan.entrypoint_resolved
    assert plan.oracle.entry_diagnostic in auth.preflight(plan, "l9", ["A", "B"])


def test_an_entry_that_is_not_approved_is_refused(two):
    app, _ir, plan, _root = two
    forged = with_action(plan, "MAIN", A.SKIP)
    assert any("not approved" in p for p in auth.preflight(forged, "l9", ["MAIN", "SUB"]))


def test_a_requested_entry_that_disagrees_with_the_plan_is_refused(two):
    _app, _ir, plan, _root = two
    assert any("disagrees with the plan" in p for p in auth.preflight(plan, "l9", ["MAIN", "SUB"], "SUB"))


# ---- unit: verify_output -----------------------------------------------------------------------------------------------------

def _names(plan):
    gen = JavaGenerator()
    return [gen.class_name_for(p) for p in auth.approved_program_ids(plan)], gen.class_name_for


def test_exactly_the_approved_programs_verify(two):
    _app, _ir, plan, _root = two
    classes, namer = _names(plan)
    assert auth.verify_output(plan, classes, ["SUB", "MAIN"], "Main", namer) == []


@pytest.mark.parametrize("mutate", ["drop", "extra", "rename", "entry", "ids"])
def test_any_departure_from_the_approved_programs_is_named(two, mutate):
    _app, _ir, plan, _root = two
    classes, namer = _names(plan)
    ids, entry = ["SUB", "MAIN"], "Main"
    if mutate == "drop":
        classes = classes[:1]
    elif mutate == "extra":
        classes = classes + ["Ghost"]
    elif mutate == "rename":
        classes = ["Sub", "Renamed"]
    elif mutate == "entry":
        entry = "Sub"
    else:
        ids = ["MAIN"]
    assert auth.verify_output(plan, classes, ids, entry, namer)


# ---- generator: refusal produces nothing ------------------------------------------------------------------------------------

def test_the_generator_with_the_approving_plan_succeeds(two):
    app, ir, plan, root = two
    result = generate(app, ir, plan, root, "MAIN")
    assert result.success, result.errors
    assert result.entrypoint == "Main" and {f.class_name for f in result.generated_files} >= {"Main", "Sub", "ServiceRegistry"}


def test_the_generator_refuses_a_plan_that_blocks_a_program_and_emits_nothing(two):
    app, ir, plan, root = two
    result = generate(app, ir, with_action(plan, "SUB", A.SKIP), root, "MAIN")
    assert not result.success and result.generated_files == () and result.java_application is None
    assert result.errors and all(e.startswith("Transformation plan refuses generation: ") for e in result.errors)


def test_the_generator_refuses_a_plan_for_other_programs(two, tmp_path_factory):
    app, ir, _plan, root = two
    other_root = tmp_path_factory.mktemp("other")
    _a, _i, other_plan = parts(other_root, {"x.cob": prog("X")}, "X")
    assert not generate(app, ir, other_plan, root, "MAIN").success


def test_the_generator_refuses_an_entry_the_plan_did_not_establish(two):
    app, ir, plan, root = two
    result = generate(app, ir, plan, root, "SUB")
    assert not result.success and any("disagrees with the plan" in e for e in result.errors)


@pytest.mark.parametrize("fault", ["drops", "adds"])
def test_the_generator_refuses_output_that_departs_from_the_plan(two, monkeypatch, fault):
    app, ir, plan, root = two
    real = JavaGenerator.generate_from_java

    def faulty(self, java_app):
        files = list(real(self, java_app))
        if fault == "drops":
            return [f for f in files if f.class_name != "Sub"]
        return files + [dataclasses.replace(files[0], filename="Ghost.java", class_name="Ghost")]

    monkeypatch.setattr(JavaGenerator, "generate_from_java", faulty)
    result = generate(app, ir, plan, root, "MAIN")
    assert not result.success and any("departs from the transformation plan" in e for e in result.errors)
    assert result.generated_files == ()


def test_without_a_plan_the_generator_is_unchanged(two):
    app, ir, _plan, root = two
    assert ApplicationGenerator().generate(app, entrypoint="MAIN", source_root=root, ir=ir).success


# ---- differential: the plan does not change a byte --------------------------------------------------------------------------

@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_differential_with_a_plan_the_generator_emits_the_same_bytes_or_refuses_for_the_plan(app_dir):
    app = ApplicationDiscovery().discover(app_dir, application_id="fx")
    ir = ir_for_application(app, app_dir)
    if ir is None or app.discovery_errors:
        pytest.skip("no source text / discovery incomplete")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, app_dir, ir=ir)
    plan = TransformationPlanGenerator().generate(canonical_application(app, ir, app_dir), report)
    plain = ApplicationGenerator().generate(app, source_root=app_dir, ir=ir)
    planned = ApplicationGenerator().generate(app, source_root=app_dir, ir=ir, plan=plan)
    if planned.success:
        assert plain.success and planned.entrypoint == plain.entrypoint and planned.program_ids == plain.program_ids
        assert [(f.filename, f.source_code) for f in planned.generated_files] == [
            (f.filename, f.source_code) for f in plain.generated_files]
    else:
        # the plan may only be stricter than the bare generator, and always names why
        assert planned.generated_files == () and planned.errors


# ---- pipeline: the production path hands the generator the plan and the adapter the plan's entry ----------------------------

def _run(tmp_path, sources, entrypoint="", runtime="plain_java"):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    for name, text in sources.items():
        (src / name).write_text(text, encoding="utf-8")
    config = ModernizationConfig(source_dir=str(src), output_dir=str(out), application_id="l9", entrypoint=entrypoint,
                                 docker_available=True, target_runtime=runtime)
    return UniversalModernizationPipeline(config).execute()


def test_the_pipeline_hands_the_generator_the_plan_it_enforced(tmp_path, monkeypatch):
    seen = {}
    real = ApplicationGenerator.generate

    def spy(self, *args, **kwargs):
        seen["plan"] = kwargs.get("plan")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(ApplicationGenerator, "generate", spy)
    report = _run(tmp_path, {"main.cob": prog("MAIN", ("SUB",)), "sub.cob": prog("SUB")}, "MAIN")
    assert report.generation_success and seen["plan"] is report.transformation_plan


def test_a_plan_the_generator_refuses_stops_the_pipeline_before_assembly(tmp_path, monkeypatch):
    real = pipeline_module.UniversalModernizationPipeline._plan_generator if False else None  # noqa: F841
    original = TransformationPlanGenerator.generate

    def forged(self, *args, **kwargs):
        plan = original(self, *args, **kwargs)
        return dataclasses.replace(plan, application_id="someone-else")

    monkeypatch.setattr(TransformationPlanGenerator, "generate", forged)
    report = _run(tmp_path, {"main.cob": prog("MAIN")}, "MAIN")
    assert not report.generation_success and report.generated_project_dir == ""
    assert any("Transformation plan refuses generation" in e for e in report.generation_errors)


LAUNCHERS = ("pom.xml", "Application.java", "CobolQuarkusMain.java", "CobolMicronautMain.java")


@pytest.mark.parametrize("runtime", ["plain_java", "spring_boot", "quarkus", "micronaut", "jakarta_ee"])
def test_with_no_requested_entry_every_runtime_launches_the_entry_the_plan_established(tmp_path, runtime):
    # SUB sorts first, so "the first program" and "the plan's entry" differ: the plan decides.
    report = _run(tmp_path, {"a_sub.cob": prog("SUB"), "driver.cob": prog("DRIVER", ("SUB",))}, "", runtime)
    assert report.generation_success, report.generation_errors
    assert report.transformation_plan.oracle.entry_program == "DRIVER"
    launchers = [p.read_text(encoding="utf-8") for p in sorted(Path(report.generated_project_dir).rglob("*"))
                 if p.name in LAUNCHERS]
    assert launchers and all("Sub" not in text.replace("Subsystem", "") for text in launchers)
    assert any("Driver" in text or "driver" in text for text in launchers)


# ---- architecture lint: there is one production path and the plan governs it --------------------------------------------------

PRODUCTION_ROOTS = ("api", "engine", "scripts", "tools")


def _production_files():
    for root in PRODUCTION_ROOTS:
        yield from (REPO / root).rglob("*.py")


def test_the_pipeline_is_the_only_production_constructor_of_the_application_generator():
    users = sorted(p.relative_to(REPO).as_posix() for p in _production_files()
                   if "ApplicationGenerator(" in p.read_text(encoding="utf-8") and p.name != "application_generator.py")
    assert users == ["engine/modernization/pipeline.py"]


def test_the_pipeline_generates_only_with_the_plan_and_assembles_only_the_plans_entry():
    text = (REPO / "engine" / "modernization" / "pipeline.py").read_text(encoding="utf-8")
    assert text.count("self._generator.generate(") == 1 and "plan=plan," in text
    assert "entry_program=plan.oracle.entry_program" in text and 'entry_program=self._config.entrypoint or' not in text


def test_the_experimental_producer_manifest_is_not_in_the_production_path():
    """``ProducerManifest`` is timestamped metadata of the experimental producers (tests only); the production lineage is the sealed
    generation record, which carries no clock."""
    allowed = {"engine/transformation/manifest.py", "engine/transformation/producer.py", "engine/transformation/__init__.py",
               "engine/transformation/producers/internal_native.py", "engine/transformation/producers/opensource4j.py"}
    users = sorted(p.relative_to(REPO).as_posix() for p in _production_files()
                   if re.search(r"import[^\n]*ProducerManifest|ProducerManifest(?:\(|\.create)",p.read_text(encoding="utf-8")))
    assert set(users) <= allowed, users


def test_the_generation_authority_reads_no_clock_and_no_files():
    text = (REPO / "engine" / "transformation" / "generation_authority.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", '"')))
    assert not any(token in code for token in ("datetime", "time.", "random", "open(", "Path(", "read_text", "subprocess"))

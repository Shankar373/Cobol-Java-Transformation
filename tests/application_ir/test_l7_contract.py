"""Layer 7 -> Layer 8 contract: the capability report is complete, consistent, deterministic and fail-closed for the planner.

Corpus contract (every fixture application), consistency (every unit and every CALL edge is classified exactly once), determinism
(a repeated analysis is byte-identical), and the planner's reading of the report (nothing but SUPPORTED reaches TRANSFORM).
"""

from __future__ import annotations

import dataclasses
import json
from collections import Counter
from pathlib import Path

import pytest

from engine.application_ir.consume import ir_for_application
from engine.application_ir.model import IRNote
from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.modernization.transformation_plan import TransformationAction, TransformationPlanGenerator
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.ir import normalize_cobol_name
from engine.transformation.semantic_capability import worst_level

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())
LEVELS = {level.value for level in CapabilityLevel}


def _analysis(app_dir: Path):
    app = ApplicationDiscovery().discover(app_dir)
    ir = ir_for_application(app, app_dir)
    if ir is None:
        pytest.skip("no source text")
    return app, ir, CapabilityAnalyzer(docker_available=True).analyze(app, app_dir, ir=ir)


@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_every_unit_has_exactly_one_program_component(app_dir):
    app, _ir, report = _analysis(app_dir)
    programs = Counter(normalize_cobol_name(c.component_id) for c in report.components if c.component_type == "PROGRAM")
    assert programs == Counter(normalize_cobol_name(u.program_id) for u in app.programs)


@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_every_call_edge_has_a_call_component(app_dir):
    app, _ir, report = _analysis(app_dir)
    classified = Counter(c.component_id for c in report.components if c.component_type == "CALL" and "->" in c.component_id)
    for edge in (e for e in app.edges if e.edge_type == "CALL"):
        assert classified[f"{edge.source}->{edge.target}"] >= 1


@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_levels_are_a_closed_vocabulary_and_overall_is_the_worst(app_dir):
    _app, _ir, report = _analysis(app_dir)
    assert {c.level.value for c in report.components} <= LEVELS
    worst = worst_level([c.level for c in report.components]) or CapabilityLevel.SUPPORTED
    assert report.overall_level is worst


@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_a_repeated_analysis_is_byte_identical(app_dir):
    app, ir, first = _analysis(app_dir)
    second = CapabilityAnalyzer(docker_available=True).analyze(app, app_dir, ir=ir)
    dump = lambda r: json.dumps(r.to_dict(), sort_keys=True)  # noqa: E731
    assert dump(first) == dump(second)
    assert [dataclasses.asdict(c) for c in first.components] == [dataclasses.asdict(c) for c in second.components]


@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_the_planner_transforms_only_what_the_report_calls_supported(app_dir):
    app, _ir, report = _analysis(app_dir)
    plan = TransformationPlanGenerator().generate(app, report)
    level = {c.component_id: c.level for c in report.components if c.component_type == "PROGRAM"}
    for component in plan.components:
        if component.component_type == "PROGRAM" and component.action == TransformationAction.TRANSFORM:
            assert level[component.component_id] is CapabilityLevel.SUPPORTED


# --- planner reading of the new findings ------------------------------------------------------------------------------

SRC = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P1.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
       "       01 A PIC 9(4) EXTERNAL.\n       PROCEDURE DIVISION.\n       R.\n           MOVE 1 TO A.\n           STOP RUN.\n")


def _single(tmp_path):
    (tmp_path / "P1.cob").write_text(SRC, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    return app, ir_for_application(app, tmp_path)


def test_an_ir_unsupported_program_is_skipped_by_the_planner(tmp_path):
    app, ir = _single(tmp_path)
    report = CapabilityAnalyzer(docker_available=True).analyze(app, tmp_path, ir=ir)
    plan = TransformationPlanGenerator().generate(app, report)
    program = next(c for c in plan.components if c.component_type == "PROGRAM")
    assert program.action == TransformationAction.SKIP and plan.transformable_programs == 0


def test_an_unattributable_ir_note_reaches_the_plan_as_a_skip(tmp_path):
    app, ir = _single(tmp_path)
    ir = dataclasses.replace(ir, notes=ir.notes + (IRNote("n:1", "refusal", "diag:GONE.cob:X:line 1", "X", None, "n:1", ()),))
    report = CapabilityAnalyzer(docker_available=True).analyze(app, tmp_path, ir=ir)
    plan = TransformationPlanGenerator().generate(app, report)
    entry = next(c for c in plan.components if c.component_id == "IR-NOTES")
    assert entry.action == TransformationAction.SKIP and "IR-NOTES" in {c.component_id for c in report.components}

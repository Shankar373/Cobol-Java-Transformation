"""Layer 7 L7-P1: the capability analyzer refuses what Layer 5 names as read-but-not-modelled.

Contract (reports identical over every fixture application, which carry no such reason), unit (one test per named reason and the
closed table), mutation (an unknown reason and a removed table entry are not silently supported) and integration (the pipeline
hands the analyzer the IR, so a source-level GLOBAL/EXTERNAL clause is no longer reported SUPPORTED).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engine.application_ir.consume import ir_for_application
from engine.modernization import ir_unsupported
from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())

HEAD = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P1.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
TAIL = "       PROCEDURE DIVISION.\n       R.\n           MOVE 1 TO A.\n           STOP RUN.\n"
GLOBAL_SRC = HEAD + "       01 A PIC 9(4) GLOBAL.\n" + TAIL
EXTERNAL_SRC = HEAD + "       01 A PIC 9(4) EXTERNAL.\n" + TAIL
PLAIN_SRC = HEAD + "       01 A PIC 9(4).\n" + TAIL


def _discover(tmp_path: Path, source: str):
    (tmp_path / "P1.cob").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    return app, ir_for_application(app, tmp_path)


def _program(report, name="P1"):
    return next(c for c in report.components if c.component_type == "PROGRAM" and c.component_id == name)


def _analyze(app, ir, root=None):
    return CapabilityAnalyzer(docker_available=True).analyze(app, root, ir=ir)


def test_an_external_clause_is_unsupported_with_its_named_reason(tmp_path):
    app, ir = _discover(tmp_path, EXTERNAL_SRC)
    comp = _program(_analyze(app, ir, tmp_path))
    assert comp.level is CapabilityLevel.UNSUPPORTED
    assert "EXTERNAL_CLAUSE_NOT_READ" in comp.reason and comp.details["ir_unsupported"] == "EXTERNAL_CLAUSE_NOT_READ"


def test_a_global_clause_is_not_reported_supported(tmp_path):
    app, ir = _discover(tmp_path, GLOBAL_SRC)
    comp = _program(_analyze(app, ir, tmp_path))
    assert comp.level is CapabilityLevel.PARTIAL and "GLOBAL_CLAUSE_NOT_READ" in comp.reason


def test_a_plain_program_stays_supported(tmp_path):
    app, ir = _discover(tmp_path, PLAIN_SRC)
    comp = _program(_analyze(app, ir, tmp_path))
    assert comp.level is CapabilityLevel.SUPPORTED and "ir_unsupported" not in comp.details


def test_without_an_ir_behaviour_is_unchanged(tmp_path):
    app, _ = _discover(tmp_path, EXTERNAL_SRC)
    assert _program(_analyze(app, None)).level is CapabilityLevel.SUPPORTED


def test_the_overall_level_follows_the_ir_finding(tmp_path):
    app, ir = _discover(tmp_path, EXTERNAL_SRC)
    assert _analyze(app, ir, tmp_path).overall_level is CapabilityLevel.UNSUPPORTED


def test_every_layer5_not_modelled_reason_is_in_the_closed_table():
    for reason in ("EXTERNAL_CLAUSE_NOT_READ", "GLOBAL_CLAUSE_NOT_READ", "NESTED_PROGRAM_NOT_MODELLED", "RENAMES_NOT_MODELLED"):
        assert reason in ir_unsupported.REASON_LEVELS


def test_an_unknown_reason_fails_closed():
    assert ir_unsupported.level_of("SOME_FUTURE_REASON") is CapabilityLevel.UNSUPPORTED


def test_a_forged_reason_on_the_ir_is_not_silently_supported(tmp_path):
    app, ir = _discover(tmp_path, PLAIN_SRC)
    forged = dataclasses.replace(ir, programs=tuple(dataclasses.replace(p, unsupported=("FORGED",)) for p in ir.programs))
    assert _program(_analyze(app, forged, tmp_path)).level is CapabilityLevel.UNSUPPORTED


def test_removing_a_table_entry_is_detected(tmp_path, monkeypatch):
    app, ir = _discover(tmp_path, GLOBAL_SRC)
    weakened = {k: v for k, v in ir_unsupported.REASON_LEVELS.items() if k != "GLOBAL_CLAUSE_NOT_READ"}
    monkeypatch.setattr(ir_unsupported, "REASON_LEVELS", weakened)
    # an unlisted reason is the fail-closed default, never SUPPORTED
    assert _program(_analyze(app, ir, tmp_path)).level is CapabilityLevel.UNSUPPORTED


def test_a_caller_of_an_unsupported_callee_is_not_supported(tmp_path):
    (tmp_path / "P1.cob").write_text(EXTERNAL_SRC, encoding="utf-8")
    (tmp_path / "MAIN.cob").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        "       01 A PIC 9(4).\n       PROCEDURE DIVISION.\n       R.\n           CALL 'P1'.\n           STOP RUN.\n", encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    report = _analyze(app, ir_for_application(app, tmp_path), tmp_path)
    call = next(c for c in report.components if c.component_type == "CALL" and c.component_id.upper().endswith("->P1"))
    assert call.level is not CapabilityLevel.SUPPORTED


@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_fixture_reports_are_identical_with_and_without_the_ir_finding(app_dir):
    app = ApplicationDiscovery().discover(app_dir)
    ir = ir_for_application(app, app_dir)
    if ir is None:
        pytest.skip("no source text")
    assert not any(p.unsupported for p in ir.programs)
    assert _analyze(app, ir, app_dir).to_dict() == _analyze(app, None, app_dir).to_dict()


def test_the_pipeline_report_for_an_external_clause_is_not_supported(tmp_path):
    from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline

    src = tmp_path / "src"
    src.mkdir()
    (src / "P1.cob").write_text(EXTERNAL_SRC, encoding="utf-8")
    result = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(src), output_dir=str(tmp_path / "out"), application_id="l7", entrypoint="P1",
        docker_available=True)).execute()
    assert result.capability_report is not None
    assert result.capability_report.overall_level is CapabilityLevel.UNSUPPORTED
    assert "EXTERNAL_CLAUSE_NOT_READ" in _program(result.capability_report).reason

"""Layer 6 migration M1: the capability analyzer takes its CALL edges from the canonical Application IR.

Contract (report identical from IR and from discovery over every fixture application), unit (the fail-closed source rules),
mutation (a wrong IR edge is detected and reported, never silently trusted) and integration (the modernization pipeline
hands the analyzer the IR).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engine.application_ir.consume import (
    canonical_call_edges,
    ir_for_application,
    with_canonical_call_edges,
)
from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())

MAIN = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        "       01 A PIC 9(4).\n       PROCEDURE DIVISION.\n       RUN-IT.\n           CALL 'SUB1' USING A.\n"
        "           CALL 'GHOST' USING A.\n           STOP RUN.\n")
SUB1 = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SUB1.\n       DATA DIVISION.\n       LINKAGE SECTION.\n"
        "       01 P1 PIC 9(4).\n       PROCEDURE DIVISION USING P1.\n       ENTRY-P.\n           GOBACK.\n")


def _app(tmp_path: Path):
    (tmp_path / "MAIN.cob").write_text(MAIN, encoding="utf-8")
    (tmp_path / "SUB1.cob").write_text(SUB1, encoding="utf-8")
    return ApplicationDiscovery().discover(tmp_path)


def _analyze(app, ir=None, root=None):
    return CapabilityAnalyzer().analyze(app, root, ir=ir)


def test_the_ir_of_a_discovered_application_supplies_its_call_edges(tmp_path):
    app = _app(tmp_path)
    ir = ir_for_application(app)
    resolved = canonical_call_edges(app, ir)
    assert resolved.source == "ir" and resolved.reason == ""
    legacy = [e for e in app.edges if e.edge_type == "CALL"]
    assert [(e.source, e.target, e.resolution) for e in resolved.edges] == [(e.source, e.target, e.resolution) for e in legacy]


def test_without_an_ir_the_discovery_edges_are_used_and_the_reason_is_stated(tmp_path):
    app = _app(tmp_path)
    resolved = canonical_call_edges(app, None)
    assert (resolved.source, resolved.reason) == ("discovery", "IR_NOT_SUPPLIED")


def test_an_ir_that_does_not_contain_every_program_is_not_used(tmp_path):
    app = _app(tmp_path)
    ir = ir_for_application(app)
    partial = dataclasses.replace(ir, programs=tuple(p for p in ir.programs if p.name != "SUB1"))
    resolved = canonical_call_edges(app, partial)
    assert (resolved.source, resolved.reason, resolved.detail) == ("discovery", "IR_INCOMPLETE", "SUB1")


def test_a_unit_without_source_text_means_no_ir(tmp_path):
    app = _app(tmp_path)
    blind = dataclasses.replace(app, programs=tuple(dataclasses.replace(u, source_text="") for u in app.programs))
    assert ir_for_application(blind) is None


def test_edge_order_follows_discovery_so_per_edge_reports_keep_their_order(tmp_path):
    app = _app(tmp_path)
    resolved = canonical_call_edges(app, ir_for_application(app))
    assert [e.target for e in resolved.edges] == [e.target for e in app.edges if e.edge_type == "CALL"]
    replaced = with_canonical_call_edges(app, resolved)
    assert {e.edge_type for e in replaced.edges} == {e.edge_type for e in app.edges}


def test_the_report_from_the_ir_equals_the_report_from_discovery(tmp_path):
    app = _app(tmp_path)
    assert _analyze(app, ir_for_application(app), tmp_path).to_dict() == _analyze(app, None, tmp_path).to_dict()


@pytest.mark.parametrize("directory", APP_DIRS, ids=lambda d: d.parent.name)
def test_contract_every_fixture_application_has_an_identical_report(directory):
    try:
        app = ApplicationDiscovery().discover(directory)
    except Exception:       # noqa: BLE001 - discovery refuses this application: there is no baseline to compare
        pytest.skip("discovery refused this application")
    ir = ir_for_application(app)
    if ir is None:
        pytest.skip("no source text")
    assert _analyze(app, ir, directory).to_dict() == _analyze(app, None, directory).to_dict()
    resolved = canonical_call_edges(app, ir)
    assert resolved.reason in ("", "IR_INCOMPLETE") and (resolved.reason != "IR_DIVERGES_FROM_DISCOVERY")


def test_a_wrong_ir_edge_is_reported_unsupported_and_discovery_edges_are_kept(tmp_path):
    app = _app(tmp_path)
    ir = ir_for_application(app)
    forged_edges = tuple(
        dataclasses.replace(e, resolution=dataclasses.replace(e.resolution, state="unresolved", candidates=(),
                                                                reason="missing-program", confidence="unresolved"),
                            target="")
        if e.kind == "call" and dict(e.attributes).get("target") == "SUB1" else e for e in ir.edges)
    forged = dataclasses.replace(ir, edges=forged_edges)
    assert canonical_call_edges(app, forged).reason == "IR_DIVERGES_FROM_DISCOVERY"
    report = _analyze(app, forged, tmp_path)
    finding = [c for c in report.components if c.component_id == "IR->DISCOVERY"]
    assert len(finding) == 1 and finding[0].level == CapabilityLevel.UNSUPPORTED
    honest = _analyze(app, ir, tmp_path)
    assert not [c for c in honest.components if c.component_id == "IR->DISCOVERY"]
    # everything else is what discovery alone says: the forged IR changed nothing but the explicit finding
    rest = [c for c in report.components if c.component_id != "IR->DISCOVERY"]
    assert [c.to_dict() if hasattr(c, "to_dict") else c for c in rest] == \
        [c.to_dict() if hasattr(c, "to_dict") else c for c in _analyze(app, None, tmp_path).components]


def test_the_modernization_pipeline_hands_the_analyzer_the_ir(tmp_path, monkeypatch):
    from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline

    src = tmp_path / "src"
    src.mkdir()
    (src / "MAIN.cob").write_text(MAIN, encoding="utf-8")
    (src / "SUB1.cob").write_text(SUB1, encoding="utf-8")
    seen: list = []
    real = CapabilityAnalyzer.analyze

    def spy(self, application, source_root=None, ir=None):
        seen.append(ir)
        return real(self, application, source_root, ir=ir)

    monkeypatch.setattr(CapabilityAnalyzer, "analyze", spy)
    UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(src), output_dir=str(tmp_path / "out"), application_id="m1", entrypoint="MAIN",
        docker_available=True)).execute()
    assert seen and seen[0] is not None and {p.name for p in seen[0].programs} == {"MAIN", "SUB1"}


def test_an_application_stub_without_source_text_yields_no_ir_instead_of_failing():
    from types import SimpleNamespace

    assert ir_for_application(SimpleNamespace(programs=[SimpleNamespace(program_id="X")])) is None
    assert ir_for_application(SimpleNamespace()) is None

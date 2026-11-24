"""Layer 6 migration M2: the ModernizationPlanner takes CALL relationships and entry points from the canonical Application IR.

Contract: the plan (and its transformation plan) is identical from the IR path and the legacy path over every fixture
application.  Unit: the entry-point adapter's fail-closed rules.  Mutation: a wrong IR is detected and discovery's values are
kept.  Integration: the planner really goes through the IR.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engine.application_ir import consume
from engine.application_ir.consume import (
    canonical_entry_points,
    ir_for_application,
    with_canonical_entry_points,
)
from engine.modernization.modernization_planner import ModernizationPlanner
from engine.transformation.application_discovery import ApplicationDiscovery

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())

MAIN = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        "       01 A PIC 9(4).\n       PROCEDURE DIVISION.\n       RUN-IT.\n           CALL 'SUB1' USING A.\n"
        "           CALL 'GHOST' USING A.\n           STOP RUN.\n")
SUB1 = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SUB1.\n       DATA DIVISION.\n       LINKAGE SECTION.\n"
        "       01 P1 PIC 9(4).\n       PROCEDURE DIVISION USING P1.\n       ENTRY-P.\n           GOBACK.\n"
        "           ENTRY 'Alt1' USING P1.\n           GOBACK.\n")


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "MAIN.cob").write_text(MAIN, encoding="utf-8")
    (tmp_path / "SUB1.cob").write_text(SUB1, encoding="utf-8")
    return tmp_path


def _plans(directory: Path, entrypoint: str = ""):
    return (ModernizationPlanner(use_application_ir=True).plan(directory, application_id="m2", entrypoint=entrypoint),
            ModernizationPlanner(use_application_ir=False).plan(directory, application_id="m2", entrypoint=entrypoint))


# --- unit: entry points -----------------------------------------------------------------------------------------------

def test_the_ir_confirms_discoverys_entry_points_and_discovery_spelling_is_kept(tmp_path):
    app = ApplicationDiscovery().discover(_tree(tmp_path))
    resolved = canonical_entry_points(app, ir_for_application(app))
    assert (resolved.source, resolved.reason) == ("ir", "")
    assert dict(resolved.by_program)["SUB1"] == tuple(u for u in app.programs if u.program_id == "SUB1")[0].entry_points
    assert with_canonical_entry_points(app, resolved) == app


def test_entry_points_without_an_ir_or_with_an_incomplete_one_fall_back_by_name(tmp_path):
    app = ApplicationDiscovery().discover(_tree(tmp_path))
    assert canonical_entry_points(app, None).reason == "IR_NOT_SUPPLIED"
    ir = ir_for_application(app)
    partial = dataclasses.replace(ir, programs=tuple(p for p in ir.programs if p.name != "SUB1"))
    assert (canonical_entry_points(app, partial).reason, canonical_entry_points(app, partial).detail) == (
        "IR_INCOMPLETE", "SUB1")


def test_an_entry_point_the_ir_does_not_confirm_keeps_discovery_and_is_reported(tmp_path):
    app = ApplicationDiscovery().discover(_tree(tmp_path))
    ir = ir_for_application(app)
    kept = tuple(d for d in ir.declarations if d.kind != "entry")
    for program in ir.programs:
        assert isinstance(program.entries, tuple)
    stripped = dataclasses.replace(
        ir, declarations=kept, programs=tuple(dataclasses.replace(p, entries=()) for p in ir.programs))
    resolved = canonical_entry_points(app, stripped)
    assert (resolved.source, resolved.reason, resolved.detail) == ("discovery", "IR_DIVERGES_FROM_DISCOVERY", "SUB1")
    assert dict(resolved.by_program)["SUB1"]       # discovery's entry points are still delivered


def _comparable(plan_dict: dict) -> dict:
    """The plan dict without the IR-only Layer 5 provenance ids (Layer 7/8 add them when an IR is supplied)."""
    out = dict(plan_dict)
    tp = dict(out.get("transformation_plan") or {})
    tp["components"] = [{k: v for k, v in c.items() if k != "provenance"} for c in tp.get("components", [])]
    out["transformation_plan"] = tp
    return out


# --- contract: the whole corpus ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("directory", APP_DIRS, ids=lambda d: d.parent.name)
def test_contract_the_plan_is_identical_from_the_ir_and_from_discovery(directory):
    try:
        via_ir, legacy = _plans(directory)
    except Exception as exc:        # noqa: BLE001 - both paths must fail the same way
        with pytest.raises(type(exc)):
            ModernizationPlanner(use_application_ir=False).plan(directory, application_id="m2")
        return
    assert _comparable(via_ir.to_dict()) == _comparable(legacy.to_dict())


def test_the_plan_with_calls_and_entries_is_identical_and_non_trivial(tmp_path):
    via_ir, legacy = _plans(_tree(tmp_path), entrypoint="MAIN")
    assert _comparable(via_ir.to_dict()) == _comparable(legacy.to_dict())
    assert len(via_ir.call_relationships) == 2 and {c.resolution for c in via_ir.call_relationships} == {"RESOLVED", "UNRESOLVED"}
    assert any(e.entry_points for e in via_ir.entry_programs) or via_ir.entry_programs


# --- mutation ------------------------------------------------------------------------------------------------------------

def _forge_calls(ir):
    edges = tuple(
        dataclasses.replace(e, target="", resolution=dataclasses.replace(
            e.resolution, state="unresolved", candidates=(), reason="missing-program", confidence="unresolved"))
        if e.kind == "call" and dict(e.attributes).get("target") == "SUB1" else e for e in ir.edges)
    return dataclasses.replace(ir, edges=edges)


def _without_ir_provenance(component):
    """Layer 7 adds IR provenance to a component's details when an IR is supplied; level and reason stay compared."""
    details = {k: v for k, v in component.details.items() if k not in ("ir_provenance", "ir_unsupported")}
    return dataclasses.replace(component, details=details)


def test_a_wrong_ir_changes_nothing_in_the_plan_but_is_reported(tmp_path, monkeypatch):
    directory = _tree(tmp_path)
    _, legacy = _plans(directory)
    real = consume.ir_for_application
    monkeypatch.setattr(consume, "ir_for_application", lambda app, *args, **kw: _forge_calls(real(app, *args, **kw)))
    forged = ModernizationPlanner(use_application_ir=True).plan(directory, application_id="m2")
    reported = [c for c in forged.capability_report.components if c.component_id == "IR->DISCOVERY"]
    assert len(reported) == 1
    assert [_without_ir_provenance(c) for c in forged.capability_report.components if c.component_id != "IR->DISCOVERY"] == \
        [_without_ir_provenance(c) for c in legacy.capability_report.components]
    assert forged.call_relationships == legacy.call_relationships and forged.entry_programs == legacy.entry_programs


# --- integration -----------------------------------------------------------------------------------------------------------

def test_the_planner_goes_through_the_ir_and_the_legacy_switch_does_not(tmp_path, monkeypatch):
    directory = _tree(tmp_path)
    seen = []
    real = consume.canonical_call_edges
    monkeypatch.setattr(consume, "canonical_call_edges", lambda app, ir: (seen.append(ir is not None), real(app, ir))[1])
    ModernizationPlanner(use_application_ir=False).plan(directory, application_id="m2")
    assert seen == []
    ModernizationPlanner(use_application_ir=True).plan(directory, application_id="m2")
    assert seen and all(seen)

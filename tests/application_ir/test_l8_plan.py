"""Layer 8 L8-P1: the production ``TransformationPlanGenerator`` reconciles the capability evidence and reads the CALL graph.

Unit (evidence reconciliation, dependency order, oracle parameters), contract (the whole fixture corpus; the ``plan_id`` definition
Layer 7 binds), mutation (a fail-open reconciliation is detected), adversarial (forged and contradictory reports) and
differential (the oracle adapter's own module selection).  No Docker, no LLM.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from engine.modernization import transformation_plan as tp
from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel as L, CapabilityReport, ComponentCapability
from engine.modernization.capability_record import plan_id_of
from engine.modernization.plan_evidence import ReconciledEvidence, reconcile
from engine.modernization.plan_graph import blocked_by_dependency, dependency_order, oracle_parameters
from engine.modernization.transformation_plan import TransformationAction as A, TransformationPlanGenerator
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.ir import CopybookReference
from enterprise.discovery.graph import canonical_bytes

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())


def prog(pid: str, calls: tuple[str, ...] = (), free: bool = False) -> str:
    body = "".join(f"           CALL '{c}'.\n" for c in calls)
    if free:
        return f"IDENTIFICATION DIVISION.\nPROGRAM-ID. {pid}.\nPROCEDURE DIVISION.\nMAIN-PARA.\n    DISPLAY '{pid}'.\n" + \
            "".join(f"    CALL '{c}'.\n" for c in calls) + "    GOBACK.\n"
    return ("       IDENTIFICATION DIVISION.\n" f"       PROGRAM-ID. {pid}.\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n"
            f"           DISPLAY '{pid}'.\n" + body + "           GOBACK.\n")


def build(tmp_path: Path, programs: dict[str, tuple[str, ...]], free: tuple[str, ...] = ()):
    for pid, calls in programs.items():
        (tmp_path / f"{pid.lower()}.cob").write_text(prog(pid, calls, pid in free), encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    return app, CapabilityAnalyzer(docker_available=True).analyze(app, tmp_path)


def actions(plan, kind="PROGRAM"):
    return {c.component_id: c.action for c in plan.components if c.component_type == kind}


def with_components(report, *extra, drop=lambda c: False):
    return dataclasses.replace(report, components=tuple(c for c in report.components if not drop(c)) + tuple(extra))


def cap(cid, level, ctype="PROGRAM", reason="r", **details):
    return ComponentCapability(cid, ctype, level, reason, dict(details))


GEN = TransformationPlanGenerator()


# --- unit: evidence reconciliation ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("order", ["supported_last", "supported_first"])
def test_duplicate_evidence_never_lets_a_supported_statement_hide_an_unsupported_one(tmp_path, order):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    bad = cap("SUB", L.UNSUPPORTED, reason="forged")
    sub = next(c for c in report.components if c.component_id == "SUB" and c.component_type == "PROGRAM")
    pair = (bad, sub) if order == "supported_last" else (sub, bad)
    forged = dataclasses.replace(report, components=tuple(c for c in report.components if c is not sub) + pair,
                                 overall_level=L.UNSUPPORTED)
    plan = GEN.generate(app, forged)
    assert actions(plan)["SUB"] is A.SKIP and plan.transformable_programs == 0


def test_a_disagreement_between_two_statements_is_recorded_as_a_note_and_the_worst_level_applies(tmp_path):
    app, report = build(tmp_path, {"MAIN": ()})
    main = next(c for c in report.components if c.component_type == "PROGRAM")
    forged = dataclasses.replace(report, components=(main, cap("MAIN", L.PARTIAL, reason="half")), overall_level=L.PARTIAL)
    evidence = reconcile(app, forged)
    assert evidence.capability("PROGRAM", "MAIN").level is L.PARTIAL and evidence.conflicts == ()
    assert len(evidence.notes) == 1 and "disagreed" in evidence.notes[0]
    plan = GEN.generate(app, forged)
    assert plan.evidence_notes == evidence.notes and actions(plan)["MAIN"] is A.SKIP


def test_evidence_is_keyed_by_type_and_id_so_a_copybook_never_borrows_a_programs_capability(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    colliding = dataclasses.replace(app, copybooks=("SUB",))
    plan = GEN.generate(colliding, report)
    assert actions(plan, "COPYBOOK") == {"SUB": A.SKIP}
    copybook = next(c for c in plan.components if c.component_type == "COPYBOOK")
    assert copybook.capability_level == "MISSING"


def test_a_level_that_is_not_a_capability_level_blocks_instead_of_crashing(tmp_path):
    app, report = build(tmp_path, {"MAIN": ()})
    forged = dataclasses.replace(report, components=tuple(dataclasses.replace(c, level="SUPPORTED") for c in report.components))
    plan = GEN.generate(app, forged)
    assert actions(plan)["MAIN"] is A.SKIP and plan.transformable_programs == 0


@pytest.mark.parametrize("forge, fragment", [
    (lambda r: dataclasses.replace(r, application_id="SOMEONE-ELSE"), "SOMEONE-ELSE"),
    (lambda r: dataclasses.replace(r, overall_level=L.UNSUPPORTED), "overall level"),
    (lambda r: with_components(r, cap("GHOST", L.SUPPORTED)), "GHOST"),
    (lambda r: with_components(r, cap("NOTACOPYBOOK", L.SUPPORTED, "COPYBOOK")), "NOTACOPYBOOK"),
])
def test_conflicting_report_blocks_every_program_and_names_the_conflict(tmp_path, forge, fragment):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    plan = GEN.generate(app, forge(report))
    assert plan.evidence_conflicts and any(fragment in c for c in plan.evidence_conflicts)
    assert set(actions(plan).values()) == {A.SKIP} and plan.transformable_programs == 0 and not plan.has_transformations
    assert all(fragment in c.reason or "conflict" in c.reason for c in plan.components if c.component_type == "PROGRAM")


def test_a_consistent_report_has_no_conflicts_and_no_notes(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    evidence = reconcile(app, report)
    assert evidence.conflicts == () and evidence.notes == ()


# --- unit: dependency order and blocking ---------------------------------------------------------------------------------

def test_dependency_order_puts_callees_before_callers_and_is_stable(tmp_path):
    app, _ = build(tmp_path, {"AAA": ("ZZZ",), "BBB": (), "ZZZ": ("BBB",)})
    order = dependency_order(app)
    assert order.index("BBB") < order.index("ZZZ") < order.index("AAA")
    assert order == dependency_order(app)


def test_independent_programs_keep_discovery_order(tmp_path):
    app, _ = build(tmp_path, {"ONE": (), "TWO": (), "THREE": ()})
    assert dependency_order(app) == tuple(u.program_id for u in app.programs)


def test_a_cycle_is_not_ordered_away_and_does_not_hang(tmp_path):
    app, report = build(tmp_path, {"AAA": ("BBB",), "BBB": ("AAA",)})
    assert sorted(dependency_order(app)) == ["AAA", "BBB"]
    plan = GEN.generate(app, report)
    assert plan.transformable_programs == 0 or any(c.action is A.SKIP for c in plan.components)


def test_plan_priority_and_execution_order_follow_the_call_graph(tmp_path):
    app, report = build(tmp_path, {"AAA": ("ZZZ",), "BBB": (), "ZZZ": ("BBB",)})
    plan = GEN.generate(app, report)
    assert plan.execution_order == dependency_order(app)
    priorities = {c.component_id: c.priority for c in plan.components if c.component_type == "PROGRAM"}
    assert sorted(priorities.values()) == [1, 2, 3] and priorities["BBB"] < priorities["ZZZ"] < priorities["AAA"]
    assert [c.component_id for c in plan.components if c.component_type == "PROGRAM"] == [u.program_id for u in app.programs]


def test_a_caller_of_a_blocked_callee_is_blocked_transitively_with_the_callee_named(tmp_path):
    app, report = build(tmp_path, {"TOP": ("MID",), "MID": ("LEAF",), "LEAF": ()})
    forged = dataclasses.replace(
        report, components=tuple(dataclasses.replace(c, level=L.UNSUPPORTED, reason="forced")
                                 if c.component_id == "LEAF" and c.component_type == "PROGRAM" else c for c in report.components),
        overall_level=L.UNSUPPORTED)
    plan = GEN.generate(app, forged)
    by_id = {c.component_id: c for c in plan.components if c.component_type == "PROGRAM"}
    assert {k: v.action for k, v in by_id.items()} == {"TOP": A.SKIP, "MID": A.SKIP, "LEAF": A.SKIP}
    assert by_id["MID"].blocked_by == "calls LEAF" and by_id["TOP"].blocked_by == "calls MID" and by_id["LEAF"].blocked_by == ""
    assert blocked_by_dependency(app, ["TOP", "MID"]) == {"TOP": "calls MID", "MID": "calls LEAF"}


def test_dependency_blocking_never_blocks_an_independent_program(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("BAD",), "BAD": (), "OTHER": ()})
    forged = dataclasses.replace(
        report, components=tuple(dataclasses.replace(c, level=L.UNSUPPORTED) if c.component_id == "BAD" and
                                 c.component_type == "PROGRAM" else c for c in report.components), overall_level=L.UNSUPPORTED)
    plan = GEN.generate(app, forged, "MAIN")
    assert actions(plan) == {"MAIN": A.SKIP, "BAD": A.SKIP, "OTHER": A.TRANSFORM}


def _with_copybook(app, program="MAIN", name="CPY"):
    units = tuple(dataclasses.replace(u, copybooks=u.copybooks + (CopybookReference(u.program_id, name),))
                  if u.program_id == program else u for u in app.programs)
    return dataclasses.replace(app, programs=units, copybooks=app.copybooks + (name,))


def test_a_program_using_a_blocked_copybook_is_blocked_and_the_copybook_stays_the_named_cause(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    app = _with_copybook(app)
    forged = with_components(report, cap("CPY", L.UNSUPPORTED, "COPYBOOK", "bad copybook"))
    forged = dataclasses.replace(forged, overall_level=L.UNSUPPORTED)
    plan = GEN.generate(app, forged)
    by_id = {c.component_id: c for c in plan.components}
    assert actions(plan) == {"MAIN": A.SKIP, "SUB": A.TRANSFORM}
    assert by_id["MAIN"].blocked_by == "uses copybook CPY" and by_id["CPY"].action is A.SKIP
    assert plan.execution_order == ("SUB", "MAIN")


def test_a_supported_copybook_blocks_nobody(tmp_path):
    app, report = build(tmp_path, {"MAIN": ()})
    plan = GEN.generate(_with_copybook(app), with_components(report, cap("CPY", L.SUPPORTED, "COPYBOOK")))
    assert actions(plan) == {"MAIN": A.TRANSFORM} and actions(plan, "COPYBOOK") == {"CPY": A.TRANSFORM}


def test_an_unsupported_file_component_blocks_its_owning_program_even_when_the_program_claims_support(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    forged = dataclasses.replace(with_components(report, cap("SUB:CUSTFILE", L.UNSUPPORTED, "FILE", "indexed file")),
                                 overall_level=L.UNSUPPORTED)
    plan = GEN.generate(app, forged)
    by_id = {c.component_id: c for c in plan.components if c.component_type == "PROGRAM"}
    assert {k: v.action for k, v in by_id.items()} == {"MAIN": A.SKIP, "SUB": A.SKIP}
    assert "file CUSTFILE" in by_id["SUB"].reason and "indexed file" in by_id["SUB"].reason and by_id["SUB"].blocked_by == ""
    assert by_id["MAIN"].blocked_by == "calls SUB"


@pytest.mark.parametrize("resolution", ["AMBIGUOUS", "SOMETHING-NEW"])   # "" cannot be forged: DependencyEdge re-derives it
def test_a_call_edge_that_is_not_resolved_is_planned_as_a_skip(tmp_path, resolution):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    edges = tuple(dataclasses.replace(e, resolution=resolution) if e.edge_type == "CALL" else e for e in app.edges)
    plan = GEN.generate(dataclasses.replace(app, edges=edges), report)
    calls = [c for c in plan.components if c.component_type == "CALL"]
    assert calls and all(c.action is A.SKIP for c in calls)
    assert all("not RESOLVED" in c.reason for c in calls)


# --- entry ------------------------------------------------------------------------------------------------------------------

def test_an_entry_whose_program_is_not_transformed_is_not_a_transformable_entry(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    assert GEN.generate(app, report).entry_transformable
    forged = dataclasses.replace(
        report, components=tuple(dataclasses.replace(c, level=L.PARTIAL) if c.component_id == "MAIN" and
                                 c.component_type == "PROGRAM" else c for c in report.components), overall_level=L.PARTIAL)
    blocked = GEN.generate(app, forged)
    assert blocked.entrypoint_resolved and not blocked.entry_transformable


# --- oracle parameters: unit + differential ---------------------------------------------------------------------------------

def test_source_format_is_derived_from_the_programs_not_assumed(tmp_path):
    (tmp_path / "a").mkdir()
    fixed, _ = build(tmp_path / "a", {"MAIN": ()})
    assert oracle_parameters(fixed, "MAIN")[0] == "fixed"
    (tmp_path / "f").mkdir()
    free, _ = build(tmp_path / "f", {"MAIN": ()}, free=("MAIN",))
    assert oracle_parameters(free, "MAIN")[0] == "free"
    (tmp_path / "m").mkdir()
    mixed, _ = build(tmp_path / "m", {"MAIN": ("SUB",), "SUB": ()}, free=("SUB",))
    assert oracle_parameters(mixed, "MAIN")[0] == "mixed"


def test_no_program_text_means_no_format_claim():
    assert oracle_parameters(tp.CobolApplication(application_id="x"), "") == ("", ())


def test_link_modules_are_the_other_source_files_sorted_and_empty_without_an_entry(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("B2", "A1"), "B2": (), "A1": ()})
    plan = GEN.generate(app, report, "MAIN")
    assert plan.oracle.link_modules == ("a1.cob", "b2.cob")
    assert GEN.generate(app, report, "NOPE").oracle.link_modules == ()


@pytest.mark.parametrize("directory", APP_DIRS, ids=lambda d: d.parent.name)
def test_differential_the_plan_links_what_the_oracle_adapter_links(directory):
    try:
        app = ApplicationDiscovery().discover(directory)
    except Exception:       # noqa: BLE001 - discovery refusals are not this test's subject
        pytest.skip("discovery refuses this fixture")
    plan = GEN.generate(app, CapabilityAnalyzer(docker_available=True).analyze(app, directory))
    if not plan.entrypoint_resolved:
        pytest.skip("no entry is established for this fixture")
    module_dir, _ = DockerOracleAdapter.module_directory(directory)
    entry_file, others = DockerOracleAdapter.select_modules(module_dir, plan.oracle.entry_program) if module_dir else (None, [])
    if entry_file is None:
        pytest.skip("the oracle adapter selects no module here")
    assert set(plan.oracle.link_modules) == set(others)
    assert entry_file not in plan.oracle.link_modules


# --- contract: the corpus ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("directory", APP_DIRS, ids=lambda d: d.parent.name)
def test_contract_corpus_plans_are_consistent_with_their_evidence(directory):
    try:
        app = ApplicationDiscovery().discover(directory)
    except Exception:       # noqa: BLE001
        pytest.skip("discovery refuses this fixture")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, directory)
    plan = GEN.generate(app, report)
    evidence = reconcile(app, report)
    assert evidence.conflicts == () and plan.evidence_conflicts == ()      # a real report never conflicts with its own app
    programs = [c for c in plan.components if c.component_type == "PROGRAM"]
    assert [c.component_id for c in programs] == [u.program_id for u in app.programs]
    for c in programs:                                                      # only SUPPORTED evidence may transform
        if c.action is A.TRANSFORM:
            assert c.capability_level == "SUPPORTED" and not c.blocked_by
    assert sorted(c.priority for c in programs) == list(range(1, len(programs) + 1))
    assert sorted(plan.execution_order) == sorted(c.component_id for c in programs)
    assert plan.transformable_programs + plan.skipped_programs == plan.total_programs == len(programs)
    assert plan.to_dict() == GEN.generate(app, report).to_dict()            # deterministic


def test_every_transform_has_supported_evidence_for_its_own_type_and_id(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    plan = GEN.generate(app, report)
    levels = {(c.component_type, c.component_id): c.level for c in report.components}
    for c in plan.components:
        if c.action is A.TRANSFORM:
            assert levels[(c.component_type, c.component_id)] is L.SUPPORTED


# --- the plan_id contract Layer 7 binds ------------------------------------------------------------------------------------

def test_plan_id_definition_is_unchanged_and_ignores_priority_provenance_and_blocking_metadata(tmp_path):
    app, report = build(tmp_path, {"MAIN": ("SUB",), "SUB": ()})
    plan = GEN.generate(app, report)
    rows = [[c.component_id, c.component_type, c.action.value] for c in plan.components]
    expected = hashlib.sha256(canonical_bytes(
        {"components": rows, "total": plan.total_programs, "transformable": plan.transformable_programs})).hexdigest()
    assert plan_id_of(plan) == expected
    decorated = dataclasses.replace(plan, components=tuple(
        dataclasses.replace(c, priority=99, provenance="x", capability_level="Y", blocked_by="Z") for c in plan.components),
        evidence_notes=("n",))
    assert plan_id_of(decorated) == expected
    flipped = dataclasses.replace(plan, components=(dataclasses.replace(plan.components[0], action=A.SKIP),) + plan.components[1:])
    assert plan_id_of(flipped) != expected


def test_the_plan_dict_carries_the_new_evidence_fields_additively(tmp_path):
    app, report = build(tmp_path, {"MAIN": ()})
    data = GEN.generate(app, report).to_dict()
    assert {"evidence_conflicts", "evidence_notes"} <= set(data)
    assert {"priority", "capability_level", "provenance", "blocked_by"} <= set(data["components"][0])
    assert {"source_format", "link_modules"} <= set(data["oracle"])


# --- mutation ------------------------------------------------------------------------------------------------------------------

def test_a_fail_open_reconciliation_would_be_detected(tmp_path, monkeypatch):
    """The duplicate-evidence property is real: with the former last-wins lookup the same report plans TRANSFORM."""
    app, report = build(tmp_path, {"MAIN": ()})
    main = next(c for c in report.components if c.component_type == "PROGRAM")
    forged = dataclasses.replace(report, components=(cap("MAIN", L.UNSUPPORTED), main), overall_level=L.UNSUPPORTED)
    assert actions(GEN.generate(app, forged))["MAIN"] is A.SKIP

    def last_wins(application, rep):
        by_key = {(c.component_type, c.component_id): c for c in rep.components}
        return ReconciledEvidence(by_key=by_key, conflicts=())

    monkeypatch.setattr(tp, "reconcile", last_wins)
    assert actions(GEN.generate(app, forged))["MAIN"] is A.TRANSFORM


def test_a_missing_capability_still_blocks(tmp_path):
    app, report = build(tmp_path, {"MAIN": (), "OTHER": ()})
    trimmed = CapabilityReport(application_id=report.application_id,
                               components=tuple(c for c in report.components if c.component_id != "OTHER"),
                               overall_level=L.SUPPORTED)
    plan = GEN.generate(app, trimmed)
    assert actions(plan) == {"MAIN": A.TRANSFORM, "OTHER": A.SKIP}
    assert next(c for c in plan.components if c.component_id == "OTHER").capability_level == "MISSING"


# --- provenance ----------------------------------------------------------------------------------------------------------------

def test_the_layer5_provenance_of_a_capability_finding_reaches_the_plan_component(tmp_path):
    app, report = build(tmp_path, {"MAIN": ()})
    forged = dataclasses.replace(report, components=tuple(
        dataclasses.replace(c, level=L.UNSUPPORTED, reason="r", details={"ir_provenance": "n:1,n:2"})
        if c.component_type == "PROGRAM" else c for c in report.components), overall_level=L.UNSUPPORTED)
    component = next(c for c in GEN.generate(app, forged).components if c.component_id == "MAIN")
    assert component.provenance == "n:1,n:2" and component.capability_level == "UNSUPPORTED" and component.action is A.SKIP


# --- authority: one production planner, fed by the canonical IR -------------------------------------------------------------

@pytest.mark.parametrize("directory", APP_DIRS, ids=lambda d: d.parent.name)
def test_differential_the_plan_from_the_canonical_ir_equals_the_plan_from_discovery(directory):
    from engine.application_ir.consume import canonical_application, ir_for_application

    try:
        app = ApplicationDiscovery().discover(directory)
    except Exception:       # noqa: BLE001
        pytest.skip("discovery refuses this fixture")
    ir = ir_for_application(app, directory)
    report = CapabilityAnalyzer(docker_available=True).analyze(app, directory, ir=ir)
    assert GEN.generate(canonical_application(app, ir, directory), report).to_dict() == GEN.generate(app, report).to_dict()


def test_the_experimental_planner_is_not_wired_into_production():
    """Only the package ``__init__`` re-export may name ``modernization_planner``; no production caller, no second plan generator."""
    offenders = []
    for root in ("engine", "api", "enterprise", "tools"):
        for path in (REPO / root).rglob("*.py"):
            if path.name == "modernization_planner.py" or path == REPO / "engine" / "modernization" / "__init__.py":
                continue
            if "modernization_planner" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []
    generators = [p.name for p in (REPO / "engine").rglob("*.py") if "class TransformationPlanGenerator" in p.read_text(
        encoding="utf-8", errors="ignore")]
    assert generators == ["transformation_plan.py"]

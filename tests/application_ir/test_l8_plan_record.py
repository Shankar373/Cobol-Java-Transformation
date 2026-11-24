"""Layer 8 L8-P2: the transformation-plan record (content, binding to the Layer 7 record, verification, pipeline survival).

Unit (deterministic content, every plan decision moves the digest), mutation/adversarial (verification names what was tampered
with; an absent or mismatched input yields no record), contract (every fixture application's record verifies, is reproducible and
names the same plan as its capability record) and end-to-end (the modernization pipeline carries both records).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engine.application_ir.consume import ir_for_application
from engine.modernization import capability_record as cr
from engine.modernization import plan_record as pr
from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.modernization.transformation_plan import TransformationAction, TransformationPlanGenerator
from engine.transformation.application_discovery import ApplicationDiscovery

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())
SRC = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P1.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
       "       01 A PIC 9(4).\n       PROCEDURE DIVISION.\n       R.\n           MOVE 1 TO A.\n           STOP RUN.\n")


def _parts(directory: Path, application_id: str = "app"):
    app = ApplicationDiscovery().discover(directory)
    ir = ir_for_application(app, directory)
    report = CapabilityAnalyzer(docker_available=True).analyze(app, directory, ir=ir)
    plan = TransformationPlanGenerator().generate(app, report)
    capability = cr.build_record(application_id, report, plan, ir, directory)
    return plan, capability, pr.build_record(application_id, plan, capability, directory)


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "P1.cob").write_text(SRC, encoding="utf-8")
    return tmp_path


def test_the_record_has_exactly_the_documented_keys_and_valid_digests(tree):
    plan, _capability, record = _parts(tree)
    values = dict(record)
    assert sorted(values) == sorted(pr.KEYS) and list(record) == sorted(record)
    assert values["entry_resolution"] == plan.oracle.entry_resolution
    assert all(len(values[k]) == 64 and set(values[k]) <= set("0123456789abcdef") for k in pr.DIGEST_KEYS)


def test_the_record_is_reproducible(tree):
    assert _parts(tree)[2] == _parts(tree)[2]


def test_the_record_names_the_same_analysis_and_plan_as_the_capability_record(tree):
    _plan, capability, record = _parts(tree)
    assert pr.disagreements_with_capability(record, capability) == []
    assert dict(record)["plan_id"] == dict(capability)["plan_id"]


def test_every_plan_decision_moves_the_digest_even_those_plan_id_ignores(tree):
    plan, _capability, record = _parts(tree)
    base = dict(record)["plan_digest"]
    decoration_only = (
        dataclasses.replace(plan, components=tuple(dataclasses.replace(c, priority=c.priority + 5) for c in plan.components)),
        dataclasses.replace(plan, components=tuple(dataclasses.replace(c, provenance="x") for c in plan.components)),
        dataclasses.replace(plan, components=tuple(dataclasses.replace(c, reason=c.reason + "!") for c in plan.components)),
        dataclasses.replace(plan, evidence_notes=("note",)),
        dataclasses.replace(plan, oracle=dataclasses.replace(plan.oracle, link_modules=("x.cob",))),
        dataclasses.replace(plan, assembly=dataclasses.replace(plan.assembly, output_type="NATIVE_JAVA")),
    )
    for changed in decoration_only:
        assert pr.plan_digest_of(changed) != base
        assert cr.plan_id_of(changed) == cr.plan_id_of(plan)  # the Layer 7 plan_id is blind to all of these


def test_no_plan_capability_record_id_or_source_means_no_record(tree):
    plan, capability, _record = _parts(tree)
    assert pr.build_record("app", None, capability, tree) == ()
    assert pr.build_record("app", plan, (), tree) == ()
    assert pr.build_record("app", plan, capability, tree / "missing") == ()
    assert pr.build_record("", plan, capability, tree) == ()


def test_a_capability_record_for_another_plan_or_source_yields_no_record(tree):
    plan, capability, _record = _parts(tree)
    other_plan = tuple((k, "e" * 64 if k == "plan_id" else v) for k, v in capability)
    other_source = tuple((k, "e" * 64 if k == "source_hash" else v) for k, v in capability)
    assert pr.build_record("app", plan, other_plan, tree) == ()
    assert pr.build_record("app", plan, other_source, tree) == ()


def test_a_correct_record_verifies(tree):
    plan, capability, record = _parts(tree)
    assert pr.verify_record(record, "app", plan, capability, tree) == []


@pytest.mark.parametrize("key", pr.KEYS)
def test_tampering_with_any_recorded_value_is_named(tree, key):
    plan, capability, record = _parts(tree)
    forged = tuple((k, ("other" if k in ("application_id", "entry_resolution") else "e" * 64) if k == key else v)
                   for k, v in record)
    problems = pr.verify_record(forged, "app", plan, capability, tree)
    assert problems and any(key in p for p in problems)


@pytest.mark.parametrize("pairs", [(), (("plan_id", "x"),), (("extra", "x"),)])
def test_a_malformed_or_missing_record_fails_verification(tree, pairs):
    plan, capability, _record = _parts(tree)
    assert pr.verify_record(pairs, "app", plan, capability, tree)


def test_a_plan_that_was_edited_after_recording_is_detected(tree):
    plan, capability, record = _parts(tree)
    edited = dataclasses.replace(plan, components=tuple(
        dataclasses.replace(c, priority=c.priority + 1) for c in plan.components))
    assert any("plan_digest" in p for p in pr.verify_record(record, "app", edited, capability, tree))


def test_a_skipped_plan_is_detected_through_both_digests(tree):
    plan, capability, record = _parts(tree)
    skipped = dataclasses.replace(plan, components=tuple(
        dataclasses.replace(c, action=TransformationAction.SKIP) for c in plan.components))
    assert pr.verify_record(record, "app", skipped, capability, tree) == ["transformation_plan: the inputs cannot produce a record"]


@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_every_fixture_record_verifies_is_reproducible_and_agrees_with_its_capability_record(app_dir):
    app = ApplicationDiscovery().discover(app_dir)
    if ir_for_application(app, app_dir) is None:
        pytest.skip("no source text")
    plan, capability, record = _parts(app_dir, "fx")
    assert record and pr.verify_record(record, "fx", plan, capability, app_dir) == []
    assert pr.disagreements_with_capability(record, capability) == []
    assert _parts(app_dir, "fx")[2] == record


def test_the_pipeline_report_carries_both_records_for_the_one_plan(tree, tmp_path_factory):
    from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline

    out = tmp_path_factory.mktemp("out")
    result = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(tree), output_dir=str(out), application_id="l8p2", entrypoint="P1", docker_available=True)).execute()
    assert result.plan_record and result.capability_record
    assert pr.verify_record(result.plan_record, "l8p2", result.transformation_plan, result.capability_record, tree) == []
    assert pr.disagreements_with_capability(result.plan_record, result.capability_record) == []
    assert result.to_dict()["plan_record"] == dict(result.plan_record)


def test_a_run_that_stops_before_planning_carries_no_plan_record(tmp_path):
    from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline

    empty = tmp_path / "empty"
    empty.mkdir()
    result = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(empty), output_dir=str(tmp_path / "out"), application_id="none", docker_available=True)).execute()
    assert result.plan_record == () and result.to_dict()["plan_record"] == {}

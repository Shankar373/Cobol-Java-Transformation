"""Layer 7 L7-P3: the IR-keyed capability record (content, binding, verification, pipeline survival).

Unit (deterministic content, every input moves the id), mutation/adversarial (verification names what was tampered with; an
absent input yields no record), contract (every fixture application's record verifies and is reproducible) and end-to-end (the
modernization pipeline carries the record, consistent with its Layer 8 plan).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engine.application_ir.consume import ir_for_application
from engine.modernization import capability_record as cr
from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel, ComponentCapability
from engine.modernization.transformation_plan import TransformationPlanGenerator
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
    return app, ir, report, plan, cr.build_record(application_id, report, plan, ir, directory)


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "P1.cob").write_text(SRC, encoding="utf-8")
    return tmp_path


def test_the_record_has_exactly_the_documented_keys_and_valid_digests(tree):
    _a, ir, report, _p, record = _parts(tree)
    values = dict(record)
    assert sorted(values) == sorted(cr.KEYS) and list(record) == sorted(record)
    assert values["ir_id"] != values["semantic_id"] and values["overall_level"] == report.overall_level.value
    assert all(len(values[k]) == 64 and set(values[k]) <= set("0123456789abcdef")
               for k in ("capability_id", "ir_id", "plan_id", "semantic_id", "source_hash"))


def test_the_record_is_reproducible(tree):
    assert _parts(tree)[4] == _parts(tree)[4]


def test_the_record_binds_to_the_ir_the_analysis_consumed(tree):
    from engine.application_ir.project import ir_id_of

    _a, ir, *_rest, record = _parts(tree)
    assert dict(record)["ir_id"] == ir_id_of(ir) and dict(record)["semantic_id"] == ir.binding("semantic_id")


def test_the_source_hash_is_the_evidence_source_identity_algorithm(tree):
    from engine.domain.identities import SourceIdentity  # noqa: F401  (the algorithm lives in engine.pipeline)
    from engine.pipeline import PipelineConfig, VerticalSlicePipeline

    config = PipelineConfig(workload_id="w", cobol_source_path=str(tree), java_candidate_path=str(tree), java_entrypoint="Main")
    identity = VerticalSlicePipeline.__new__(VerticalSlicePipeline)
    identity._config = config
    assert dict(_parts(tree)[4])["source_hash"] == identity._compute_source_identity().source_hash.digest


def test_no_ir_no_report_or_no_plan_means_no_record(tree):
    app, ir, report, plan, _record = _parts(tree)
    assert cr.build_record("app", report, plan, None, tree) == ()
    assert cr.build_record("app", None, plan, ir, tree) == ()
    assert cr.build_record("app", report, None, ir, tree) == ()
    assert cr.build_record("app", report, plan, ir, tree / "missing") == ()
    assert cr.build_record("", report, plan, ir, tree) == ()


def test_a_correct_record_verifies(tree):
    _a, ir, report, plan, record = _parts(tree)
    assert cr.verify_record(record, "app", report, plan, ir, tree) == []


def test_every_input_moves_the_capability_id(tree):
    _a, ir, report, plan, record = _parts(tree)
    base = dict(record)["capability_id"]
    worse = dataclasses.replace(report, components=report.components + (ComponentCapability(
        "X", "PROGRAM", CapabilityLevel.UNSUPPORTED, "forged"),))
    assert dict(cr.build_record("app", worse, plan, ir, tree))["capability_id"] != base
    reasons = dataclasses.replace(report, components=tuple(
        dataclasses.replace(c, reason=c.reason + "!") for c in report.components))
    assert dict(cr.build_record("app", reasons, plan, ir, tree))["capability_id"] != base
    details = dataclasses.replace(report, components=tuple(
        dataclasses.replace(c, details={**c.details, "ir_provenance": "forged"}) for c in report.components))
    assert dict(cr.build_record("app", details, plan, ir, tree))["capability_id"] != base
    assert dict(cr.build_record("other", report, plan, ir, tree))["capability_id"] != base
    (tree / "P1.cob").write_text(SRC + "      * changed\n", encoding="utf-8")
    assert dict(cr.build_record("app", report, plan, ir, tree))["capability_id"] != base


@pytest.mark.parametrize("key", cr.KEYS)
def test_tampering_with_any_recorded_value_is_named(tree, key):
    _a, ir, report, plan, record = _parts(tree)
    forged = tuple((k, ("other" if k in ("application_id", "overall_level") else "e" * 64) if k == key else v)
                   for k, v in record)
    problems = cr.verify_record(forged, "app", report, plan, ir, tree)
    assert problems and any(key in p for p in problems)


@pytest.mark.parametrize("pairs", [(), (("capability_id", "x"),), (("extra", "x"),)])
def test_a_malformed_or_missing_record_fails_verification(tree, pairs):
    _a, ir, report, plan, _record = _parts(tree)
    assert cr.verify_record(pairs, "app", report, plan, ir, tree)


def test_a_plan_that_disagrees_with_the_report_is_detected(tree):
    app, ir, report, plan, record = _parts(tree)
    skipped = dataclasses.replace(plan, components=tuple(
        dataclasses.replace(c, action=type(c.action).SKIP) for c in plan.components))
    assert any("plan_id" in p for p in cr.verify_record(record, "app", report, skipped, ir, tree))


@pytest.mark.parametrize("app_dir", APP_DIRS, ids=lambda p: p.parent.name)
def test_every_fixture_record_verifies_and_is_reproducible(app_dir):
    app = ApplicationDiscovery().discover(app_dir)
    if ir_for_application(app, app_dir) is None:
        pytest.skip("no source text")
    _a, ir, report, plan, record = _parts(app_dir, "fx")
    assert record and cr.verify_record(record, "fx", report, plan, ir, app_dir) == []
    assert _parts(app_dir, "fx")[4] == record


def test_the_pipeline_report_carries_the_record_consistent_with_its_plan(tree, tmp_path_factory):
    from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline

    out = tmp_path_factory.mktemp("out")
    result = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(tree), output_dir=str(out), application_id="l7p3", entrypoint="P1", docker_available=True)).execute()
    ir = ir_for_application(ApplicationDiscovery().discover(tree), tree)
    assert result.capability_record
    assert cr.verify_record(result.capability_record, "l7p3", result.capability_report, result.transformation_plan,
                            ir, tree) == []
    assert result.to_dict()["capability_record"] == dict(result.capability_record)

"""Layer 8 end to end through the real API service: generation -> stored report -> validation -> sealed manifest.

The plan record the modernization pipeline computes must survive into the sealed evidence manifest beside the capability record it
was built from, be reproducible from the source, and disappear (not degrade) when its bridge is removed.
"""

# ruff: noqa: F811  (the imported `service` fixture is redefined by each test parameter)
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import api.service as service_module
from api.service import _plan_pairs
from engine.application_ir.consume import canonical_application, ir_for_application
from engine.evidence.integrity import EvidenceIntegrityValidator
from engine.modernization import capability_record as cr
from engine.modernization import plan_record as pr
from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.modernization.transformation_plan import TransformationPlanGenerator
from engine.transformation.application_discovery import ApplicationDiscovery
from tests.test_capability_analysis_api import _generate_and_validate
from tests.test_library_order_profile_api import _estate_root, service  # the `service` fixture is imported, then used as a parameter


def test_the_sealed_manifest_carries_the_plan_record_beside_its_capability_record(service, tmp_path, monkeypatch):
    app, run = _generate_and_validate(service, tmp_path, monkeypatch, _estate_root(tmp_path))
    manifest = run.evidence_manifest
    recorded = dict(manifest.transformation_plan)
    assert sorted(recorded) == sorted(pr.KEYS)
    assert recorded == run.modernization_report["pipeline_report"]["plan_record"]
    assert recorded["source_hash"] == manifest.source_identity.source_hash.digest and recorded["application_id"] == app.id
    assert pr.disagreements_with_capability(manifest.transformation_plan, manifest.capability_analysis) == []
    result = EvidenceIntegrityValidator().validate(manifest)
    assert not (result if isinstance(result, list) else [])


def test_the_record_is_consistent_with_the_stored_plan(service, tmp_path, monkeypatch):
    _app, run = _generate_and_validate(service, tmp_path, monkeypatch, _estate_root(tmp_path))
    stored = run.modernization_report["pipeline_report"]["plan"]
    assert dict(run.evidence_manifest.transformation_plan)["entry_resolution"] == stored["oracle"]["entry_resolution"]


def test_the_record_is_reproducible_from_the_source(service, tmp_path, monkeypatch):
    root = _estate_root(tmp_path)
    app, run = _generate_and_validate(service, tmp_path, monkeypatch, root)
    orders = {program: program_orders for program, program_orders in service._engine_wiring(str(root), app.name)[0]}
    discovered = ApplicationDiscovery().discover(root, application_id=app.id, **({"orders": orders} if orders else {}))
    ir = ir_for_application(discovered, root, orders or ())
    report = CapabilityAnalyzer(docker_available=True).analyze(discovered, root, ir=ir)
    stored = run.modernization_report["pipeline_report"]["plan"]
    plan = TransformationPlanGenerator().generate(
        canonical_application(discovered, ir, root), report, stored["oracle"]["entry_program"],
        assembly_output_type=stored["assembly"]["output_type"])
    capability = cr.build_record(app.id, report, plan, ir, root)
    assert pr.verify_record(run.evidence_manifest.transformation_plan, app.id, plan, capability, root) == []


def test_dropping_the_bridge_leaves_the_manifest_without_the_record(service, tmp_path, monkeypatch):
    """Mutation check: the manifest's plan record comes from ``_plan_pairs``, nowhere else."""
    monkeypatch.setattr(service_module, "_plan_pairs", lambda run: ())
    _app, run = _generate_and_validate(service, tmp_path, monkeypatch, _estate_root(tmp_path))
    assert run.evidence_manifest.transformation_plan == () and run.evidence_manifest.capability_analysis


def test_a_stored_record_that_is_not_well_formed_reaches_the_validator_instead_of_vanishing():
    run = SimpleNamespace(modernization_report={"pipeline_report": {"plan_record": {"plan_id": 5}}})
    assert _plan_pairs(run) == (("plan_id", "5"),)
    assert pr.shape_problems(_plan_pairs(run))


@pytest.mark.parametrize("report", [None, {}, {"pipeline_report": None}, {"pipeline_report": {}},
                                    {"pipeline_report": {"plan_record": {}}}, {"pipeline_report": {"plan_record": "x"}}])
def test_a_run_without_a_stored_record_records_none(report):
    assert _plan_pairs(SimpleNamespace(modernization_report=report)) == ()

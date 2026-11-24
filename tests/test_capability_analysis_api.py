"""Layer 7 end to end through the real API service: generation -> stored report -> validation -> sealed manifest.

The capability record the modernization pipeline computes must survive into the sealed evidence manifest, be reproducible from the
source, be consistent with the Layer 8 plan of the same run, and disappear (not degrade) when its bridge is removed.
"""

# ruff: noqa: F811  (the imported `service` fixture is redefined by each test parameter)
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import api.service as service_module
from api.service import Service, _capability_pairs
from engine.application_ir.consume import ir_for_application
from engine.evidence.integrity import EvidenceIntegrityValidator
from engine.modernization import capability_record as cr
from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.modernization.transformation_plan import TransformationPlanGenerator
from engine.transformation.application_discovery import ApplicationDiscovery
from tests.comparison_doubles import Candidate, Oracle
from tests.test_library_order_profile_api import _application, _estate_root, _run, service  # the `service` fixture is imported, then used as a parameter


def _generate_and_validate(service, tmp_path, monkeypatch, root: Path):
    app = _application(service, root)
    run = _run(service, app)
    project, entry = service._generate_application(app, run)

    class EntryOracle(Oracle):
        def execute(self, run_id, source_path, input_data=None, input_files=None, **_ignored):
            return super().execute(run_id, source_path, input_data, input_files)

    class Doubled(service_module.VerticalSlicePipeline):
        def __init__(self, config, candidate_adapter=None, registry=None):
            super().__init__(config, candidate_adapter=Candidate(b"HI\n", None, 0), registry=registry)
            self._oracle_adapter = EntryOracle(b"HI\n", None, 0)

    monkeypatch.setattr(service_module, "VerticalSlicePipeline", Doubled)
    monkeypatch.setattr(Service, "_run_job_lane", lambda *a, **k: None)
    monkeypatch.setattr(Service, "_persist_integrated_proof", lambda *a, **k: None)
    service._run_validation(app, run, Path(project), entry)
    return app, service._store.get_run(run.id)


def test_the_sealed_manifest_carries_the_capability_record_of_the_generation(service, tmp_path, monkeypatch):
    root = _estate_root(tmp_path)
    app, run = _generate_and_validate(service, tmp_path, monkeypatch, root)
    manifest = run.evidence_manifest
    recorded = dict(manifest.capability_analysis)
    assert sorted(recorded) == sorted(cr.KEYS)
    assert recorded == run.modernization_report["pipeline_report"]["capability_record"]
    assert recorded["source_hash"] == manifest.source_identity.source_hash.digest
    assert recorded["application_id"] == app.id
    result = EvidenceIntegrityValidator().validate(manifest)
    assert not (result if isinstance(result, list) else [])


def test_the_record_is_consistent_with_the_stored_report_and_plan(service, tmp_path, monkeypatch):
    root = _estate_root(tmp_path)
    _app, run = _generate_and_validate(service, tmp_path, monkeypatch, root)
    stored = run.modernization_report["pipeline_report"]
    assert dict(run.evidence_manifest.capability_analysis)["overall_level"] == stored["capability"]["overall_level"]
    plan = stored["plan"]
    assert plan["transformable_programs"] + plan["skipped_programs"] == plan["total_programs"]


def test_the_record_is_reproducible_from_the_source(service, tmp_path, monkeypatch):
    root = _estate_root(tmp_path)
    app, run = _generate_and_validate(service, tmp_path, monkeypatch, root)
    orders = {program: program_orders for program, program_orders in service._engine_wiring(str(root), app.name)[0]}
    discovered = ApplicationDiscovery().discover(root, **({"orders": orders} if orders else {}))
    ir = ir_for_application(discovered, root, orders or ())
    report = CapabilityAnalyzer(docker_available=True).analyze(discovered, root, ir=ir)
    plan = TransformationPlanGenerator().generate(discovered, report)
    problems = cr.verify_record(run.evidence_manifest.capability_analysis, app.id, report, plan, ir, root)
    assert problems == []


def test_dropping_the_bridge_leaves_the_manifest_without_the_record(service, tmp_path, monkeypatch):
    """Mutation check: the manifest's capability record comes from ``_capability_pairs``, nowhere else."""
    monkeypatch.setattr(service_module, "_capability_pairs", lambda run: ())
    _app, run = _generate_and_validate(service, tmp_path, monkeypatch, _estate_root(tmp_path))
    assert run.evidence_manifest.capability_analysis == ()


def test_a_stored_record_that_is_not_well_formed_reaches_the_validator_instead_of_vanishing():
    run = SimpleNamespace(modernization_report={"pipeline_report": {"capability_record": {"ir_id": 5}}})
    assert _capability_pairs(run) == (("ir_id", "5"),)
    assert cr.shape_problems(_capability_pairs(run))


@pytest.mark.parametrize("report", [None, {}, {"pipeline_report": None}, {"pipeline_report": {}},
                                    {"pipeline_report": {"capability_record": {}}},
                                    {"pipeline_report": {"capability_record": "x"}}])
def test_a_run_without_a_stored_record_records_none(report):
    assert _capability_pairs(SimpleNamespace(modernization_report=report)) == ()

"""Layer 9 end to end through the real API service: generation -> stored report -> validation -> sealed manifest.

The generation record the modernization pipeline computes must survive into the sealed evidence manifest beside the plan and
capability records it was built from, and disappear (not degrade) when its bridge is removed.
"""

# ruff: noqa: F811  (the imported `service` fixture is redefined by each test parameter)
from __future__ import annotations

from types import SimpleNamespace

import pytest

import api.service as service_module
from api.service import _generation_pairs
from engine.evidence.integrity import EvidenceIntegrityValidator
from engine.modernization import generation_record as gr
from tests.test_capability_analysis_api import _generate_and_validate
from tests.test_library_order_profile_api import _estate_root, service  # the `service` fixture is imported, then used as a parameter


def test_the_sealed_manifest_carries_the_generation_record_beside_its_plan_record(service, tmp_path, monkeypatch):
    app, run = _generate_and_validate(service, tmp_path, monkeypatch, _estate_root(tmp_path))
    manifest = run.evidence_manifest
    recorded = dict(manifest.java_generation)
    assert sorted(recorded) == sorted(gr.KEYS)
    assert recorded == run.modernization_report["pipeline_report"]["generation_record"]
    assert recorded["source_hash"] == manifest.source_identity.source_hash.digest and recorded["application_id"] == app.id
    assert recorded["target_runtime"] == app.target_runtime
    assert gr.disagreements_with_plan(manifest.java_generation, manifest.transformation_plan) == []
    result = EvidenceIntegrityValidator().validate(manifest)
    assert not (result if isinstance(result, list) else [])


def test_the_record_agrees_with_the_stored_plan(service, tmp_path, monkeypatch):
    _app, run = _generate_and_validate(service, tmp_path, monkeypatch, _estate_root(tmp_path))
    stored = run.modernization_report["pipeline_report"]["plan"]
    assert dict(run.evidence_manifest.java_generation)["entry_program"] == stored["oracle"]["entry_program"]


def test_dropping_the_bridge_leaves_the_manifest_without_the_record(service, tmp_path, monkeypatch):
    """Mutation check: the manifest's generation record comes from ``_generation_pairs``, nowhere else."""
    monkeypatch.setattr(service_module, "_generation_pairs", lambda run: ())
    _app, run = _generate_and_validate(service, tmp_path, monkeypatch, _estate_root(tmp_path))
    assert run.evidence_manifest.java_generation == () and run.evidence_manifest.transformation_plan


def test_a_stored_record_that_is_not_well_formed_reaches_the_validator_instead_of_vanishing():
    run = SimpleNamespace(modernization_report={"pipeline_report": {"generation_record": {"plan_id": 5}}})
    assert _generation_pairs(run) == (("plan_id", "5"),)
    assert gr.shape_problems(_generation_pairs(run))


@pytest.mark.parametrize("report", [None, {}, {"pipeline_report": None}, {"pipeline_report": {}},
                                    {"pipeline_report": {"generation_record": {}}},
                                    {"pipeline_report": {"generation_record": "x"}}])
def test_a_run_without_a_stored_record_records_none(report):
    assert _generation_pairs(SimpleNamespace(modernization_report=report)) == ()

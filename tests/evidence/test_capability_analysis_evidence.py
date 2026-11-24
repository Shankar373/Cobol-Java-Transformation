"""Capability record in the sealed evidence manifest (Layer 7): conditional key, integrity, serialization, pipeline wiring."""

from __future__ import annotations

import dataclasses
import json

import pytest

from api import serialization
from api.serialization import PersistenceCorruptionError
from engine.evidence.integrity import EvidenceIntegrityValidator, ViolationType
from engine.evidence.models import canonical_evidence_graph
from engine.modernization.capability_record import KEYS

LEGACY_MANIFEST_HASH = "sha256:7b07e99e957d4120fd17d19b0739c0e78db140d8e98f7fd172bb9eed5d4de866"


def _base():
    from tests.test_persistence_integrity import _manifest

    return _manifest()


def _record(base=None, **override):
    base = base or _base()
    values = {"application_id": "app", "capability_id": "1" * 64, "ir_id": "2" * 64, "overall_level": "SUPPORTED",
              "plan_id": "3" * 64, "semantic_id": "4" * 64, "source_hash": base.source_identity.source_hash.digest}
    values.update(override)
    return tuple(sorted(values.items()))


def _with(**fields):
    return dataclasses.replace(_base(), **fields)


def _violations(manifest):
    result = EvidenceIntegrityValidator().validate(manifest)
    return [v for v in (result if isinstance(result, list) else [])
            if v.violation_type is ViolationType.CAPABILITY_ANALYSIS_BINDING_MISMATCH]


def test_a_manifest_without_the_record_keeps_its_exact_hash():
    base = _base()
    assert str(base.manifest_hash) == LEGACY_MANIFEST_HASH and "capability_analysis" not in canonical_evidence_graph(base)


def test_the_record_is_sealed_serialised_and_round_trips():
    manifest = _with(capability_analysis=_record())
    assert canonical_evidence_graph(manifest)["capability_analysis"] == dict(_record())
    assert manifest.manifest_hash != _base().manifest_hash
    decoded = serialization.decode_evidence_manifest(serialization.encode_evidence_manifest(manifest))
    assert decoded is not None and decoded.capability_analysis == manifest.capability_analysis
    assert decoded.manifest_hash == manifest.manifest_hash
    assert b"capability_analysis" not in serialization.encode_evidence_manifest(_base())


def test_every_recorded_value_is_sealed():
    base = _with(capability_analysis=_record())
    for key in ("capability_id", "ir_id", "plan_id", "semantic_id", "overall_level", "application_id"):
        changed = _with(capability_analysis=_record(**{key: "UNSUPPORTED" if key == "overall_level" else "f" * 64}))
        assert changed.manifest_hash != base.manifest_hash, key


def test_a_consistent_record_is_admitted():
    assert not _violations(_with(capability_analysis=_record()))


def test_tampering_after_sealing_and_persisted_tampering_are_detected():
    manifest = _with(capability_analysis=_record())
    manifest.capability_analysis = _record(capability_id="9" * 64)
    result = EvidenceIntegrityValidator().validate(manifest)
    assert ViolationType.MANIFEST_HASH_MISMATCH in {v.violation_type for v in (result if isinstance(result, list) else [])}
    raw = json.loads(serialization.encode_evidence_manifest(_with(capability_analysis=_record())))
    raw.get("payload", raw)["capability_analysis"]["capability_id"] = "9" * 64
    with pytest.raises(PersistenceCorruptionError):
        serialization.decode_evidence_manifest(json.dumps(raw).encode())


def test_a_record_for_another_source_is_refused():
    other = _with(capability_analysis=_record(source_hash="a" * 64))
    assert [v.field_path for v in _violations(other)] == ["capability_analysis.source_hash"]


@pytest.mark.parametrize("override", [
    {"ir_id": "nope"}, {"capability_id": "A" * 64}, {"plan_id": ""}, {"overall_level": "GREAT"}, {"application_id": ""},
    {"source_hash": "short"},
])
def test_malformed_values_are_violations(override):
    assert _violations(_with(capability_analysis=_record(**override)))


@pytest.mark.parametrize("drop", KEYS)
def test_a_missing_key_is_a_violation(drop):
    assert _violations(_with(capability_analysis=tuple(p for p in _record() if p[0] != drop)))


def test_an_extra_key_is_a_violation():
    assert _violations(_with(capability_analysis=_record() + (("extra", "x"),)))


def test_the_pipeline_config_records_the_pairs_in_the_sealed_manifest():
    from engine.pipeline import PipelineConfig

    assert "capability_analysis" in {f.name for f in dataclasses.fields(PipelineConfig)}

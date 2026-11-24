"""Generation record in the sealed evidence manifest (Layer 9): conditional key, integrity, cross-binding, serialization, wiring."""

from __future__ import annotations

import dataclasses
import json

import pytest

from api import serialization
from api.serialization import PersistenceCorruptionError
from engine.evidence.integrity import EvidenceIntegrityValidator, ViolationType
from engine.evidence.models import canonical_evidence_graph
from engine.modernization.generation_record import KEYS

LEGACY_MANIFEST_HASH = "sha256:7b07e99e957d4120fd17d19b0739c0e78db140d8e98f7fd172bb9eed5d4de866"


def _base():
    from tests.test_persistence_integrity import _manifest

    return _manifest()


def _source():
    return _base().source_identity.source_hash.digest


def _capability():
    return tuple(sorted({"application_id": "app", "capability_id": "1" * 64, "ir_id": "2" * 64, "overall_level": "SUPPORTED",
                         "plan_id": "3" * 64, "semantic_id": "4" * 64, "source_hash": _source()}.items()))


def _plan():
    return tuple(sorted({"application_id": "app", "capability_id": "1" * 64, "entry_resolution": "RESOLVED", "ir_id": "2" * 64,
                         "plan_digest": "5" * 64, "plan_id": "3" * 64, "source_hash": _source()}.items()))


def _record(**override):
    values = {"application_id": "app", "entry_class": "Main", "entry_program": "MAIN", "ir_id": "2" * 64,
              "output_digest": "6" * 64, "plan_digest": "5" * 64, "plan_id": "3" * 64, "program_map_digest": "7" * 64,
              "source_hash": _source(), "target_runtime": "plain_java"}
    values.update(override)
    return tuple(sorted(values.items()))


def _with(**fields):
    return dataclasses.replace(_base(), **fields)


def _all(**override):
    return _with(capability_analysis=_capability(), transformation_plan=_plan(), java_generation=_record(**override))


def _violations(manifest):
    result = EvidenceIntegrityValidator().validate(manifest)
    return [v for v in (result if isinstance(result, list) else [])
            if v.violation_type is ViolationType.JAVA_GENERATION_BINDING_MISMATCH]


def test_a_manifest_without_the_record_keeps_its_exact_hash():
    base = _base()
    assert str(base.manifest_hash) == LEGACY_MANIFEST_HASH and "java_generation" not in canonical_evidence_graph(base)


def test_the_record_is_sealed_serialised_and_round_trips():
    manifest = _all()
    assert canonical_evidence_graph(manifest)["java_generation"] == dict(_record())
    decoded = serialization.decode_evidence_manifest(serialization.encode_evidence_manifest(manifest))
    assert decoded is not None and decoded.java_generation == manifest.java_generation
    assert decoded.manifest_hash == manifest.manifest_hash
    assert b"java_generation" not in serialization.encode_evidence_manifest(_base())


def test_every_recorded_value_is_sealed():
    base = _all()
    for key in KEYS:
        changed = _all(**{key: "x" if key in ("application_id", "entry_class", "entry_program", "target_runtime") else "f" * 64})
        assert changed.manifest_hash != base.manifest_hash, key


def test_a_consistent_chain_of_records_is_admitted():
    assert not _violations(_all())


def test_tampering_after_sealing_and_persisted_tampering_are_detected():
    manifest = _all()
    manifest.java_generation = _record(output_digest="9" * 64)
    result = EvidenceIntegrityValidator().validate(manifest)
    assert ViolationType.MANIFEST_HASH_MISMATCH in {v.violation_type for v in (result if isinstance(result, list) else [])}
    raw = json.loads(serialization.encode_evidence_manifest(_all()))
    raw.get("payload", raw)["java_generation"]["output_digest"] = "9" * 64
    with pytest.raises(PersistenceCorruptionError):
        serialization.decode_evidence_manifest(json.dumps(raw).encode())


def test_a_record_for_another_source_is_refused():
    other = _with(capability_analysis=_capability(), transformation_plan=_plan(), java_generation=_record(source_hash="a" * 64))
    assert [v.field_path for v in _violations(other)] == ["java_generation.source_hash"]


def test_a_generation_record_without_a_plan_record_is_refused():
    lone = _with(java_generation=_record())
    assert [v.field_path for v in _violations(lone)] == ["java_generation"]


@pytest.mark.parametrize("key", ["application_id", "ir_id", "plan_digest", "plan_id"])
def test_a_generation_record_naming_another_plan_than_the_plan_record_is_refused(key):
    value = "other" if key == "application_id" else "e" * 64
    assert [v.field_path for v in _violations(_all(**{key: value}))] == [f"java_generation.{key}"]


@pytest.mark.parametrize("override", [
    {"output_digest": "nope"}, {"program_map_digest": "A" * 64}, {"plan_id": ""}, {"target_runtime": "tomcat"},
    {"entry_class": ""}, {"entry_program": ""}, {"application_id": ""}, {"source_hash": "short"},
])
def test_malformed_values_are_violations(override):
    assert _violations(_all(**override))


@pytest.mark.parametrize("drop", KEYS)
def test_a_missing_key_is_a_violation(drop):
    assert _violations(_with(capability_analysis=_capability(), transformation_plan=_plan(),
                             java_generation=tuple(p for p in _record() if p[0] != drop)))


def test_an_extra_key_is_a_violation():
    assert _violations(_with(capability_analysis=_capability(), transformation_plan=_plan(),
                             java_generation=_record() + (("extra", "x"),)))


def test_the_pipeline_config_records_the_pairs_in_the_sealed_manifest():
    from engine.pipeline import PipelineConfig

    assert "java_generation" in {f.name for f in dataclasses.fields(PipelineConfig)}

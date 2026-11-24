"""Build-artifact record in the sealed evidence manifest (Layer 10): conditional key, integrity, binding to generation, wiring."""

from __future__ import annotations

import dataclasses
import json

import pytest

from api import serialization
from api.serialization import PersistenceCorruptionError
from engine.candidate.build_record import KEYS
from engine.evidence.integrity import EvidenceIntegrityValidator, ViolationType
from engine.evidence.models import canonical_evidence_graph

LEGACY_MANIFEST_HASH = "sha256:7b07e99e957d4120fd17d19b0739c0e78db140d8e98f7fd172bb9eed5d4de866"


def _base():
    from tests.test_persistence_integrity import _manifest

    return _manifest()


def _record(**override):
    values = {"artifact_digest": "a" * 64, "artifact_name": "app.jar", "built_tree_digest": "6" * 64}
    values.update(override)
    return tuple(sorted(values.items()))


def _generation(**override):
    values = {"application_id": "app", "entry_class": "Main", "entry_program": "MAIN", "ir_id": "2" * 64, "output_digest": "6" * 64,
              "plan_digest": "5" * 64, "plan_id": "3" * 64, "program_map_digest": "7" * 64,
              "source_hash": _base().source_identity.source_hash.digest, "target_runtime": "plain_java"}
    values.update(override)
    return tuple(sorted(values.items()))


def _with(**fields):
    return dataclasses.replace(_base(), **fields)


def _violations(manifest):
    result = EvidenceIntegrityValidator().validate(manifest)
    return [v for v in (result if isinstance(result, list) else [])
            if v.violation_type is ViolationType.BUILD_ARTIFACT_BINDING_MISMATCH]


def test_a_manifest_without_the_record_keeps_its_exact_hash():
    base = _base()
    assert str(base.manifest_hash) == LEGACY_MANIFEST_HASH and "build_artifact" not in canonical_evidence_graph(base)


def test_the_record_is_sealed_serialised_and_round_trips():
    manifest = _with(build_artifact=_record())
    assert canonical_evidence_graph(manifest)["build_artifact"] == dict(_record())
    assert manifest.manifest_hash != _base().manifest_hash
    decoded = serialization.decode_evidence_manifest(serialization.encode_evidence_manifest(manifest))
    assert decoded is not None and decoded.build_artifact == manifest.build_artifact
    assert decoded.manifest_hash == manifest.manifest_hash
    assert b"build_artifact" not in serialization.encode_evidence_manifest(_base())


def test_every_recorded_value_is_sealed():
    base = _with(build_artifact=_record())
    for key, value in (("artifact_digest", "b" * 64), ("artifact_name", "other.jar"), ("built_tree_digest", "c" * 64)):
        assert _with(build_artifact=_record(**{key: value})).manifest_hash != base.manifest_hash, key


def test_a_record_alone_and_a_record_for_the_recorded_generation_are_admitted():
    assert not _violations(_with(build_artifact=_record()))
    assert not _violations(_with(build_artifact=_record(), java_generation=_generation()))


def test_a_build_from_another_tree_than_the_recorded_generation_is_refused():
    other = _with(build_artifact=_record(built_tree_digest="d" * 64), java_generation=_generation())
    assert [v.field_path for v in _violations(other)] == ["build_artifact.built_tree_digest"]


def test_tampering_after_sealing_and_persisted_tampering_are_detected():
    manifest = _with(build_artifact=_record())
    manifest.build_artifact = _record(artifact_digest="9" * 64)
    result = EvidenceIntegrityValidator().validate(manifest)
    assert ViolationType.MANIFEST_HASH_MISMATCH in {v.violation_type for v in (result if isinstance(result, list) else [])}
    raw = json.loads(serialization.encode_evidence_manifest(_with(build_artifact=_record())))
    raw.get("payload", raw)["build_artifact"]["artifact_digest"] = "9" * 64
    with pytest.raises(PersistenceCorruptionError):
        serialization.decode_evidence_manifest(json.dumps(raw).encode())


@pytest.mark.parametrize("override", [{"artifact_digest": "nope"}, {"built_tree_digest": "A" * 64}, {"artifact_name": "app.zip"},
                                      {"artifact_name": "../app.jar"}])
def test_malformed_values_are_violations(override):
    assert _violations(_with(build_artifact=_record(**override)))


@pytest.mark.parametrize("drop", KEYS)
def test_a_missing_key_is_a_violation(drop):
    assert _violations(_with(build_artifact=tuple(p for p in _record() if p[0] != drop)))


def test_an_extra_key_is_a_violation():
    assert _violations(_with(build_artifact=_record() + (("extra", "x"),)))

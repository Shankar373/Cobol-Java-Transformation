"""Application IR addresses in the sealed evidence manifest (Layer 6): conditional key, integrity, serialization."""

from __future__ import annotations

import dataclasses
import json

import pytest

from api import serialization
from api.serialization import PersistenceCorruptionError
from engine.evidence.integrity import EvidenceIntegrityValidator, ViolationType, profiles_digest
from engine.evidence.models import canonical_evidence_graph

LEGACY_MANIFEST_HASH = "sha256:7b07e99e957d4120fd17d19b0739c0e78db140d8e98f7fd172bb9eed5d4de866"
GRAPH, SEM, IR = "a" * 64, "c" * 64, "d" * 64
PROFILES = (("src/A.cbl", "b" * 64),)


def _semantic():
    return tuple(sorted((("semantic_id", SEM), ("facts_digest", "e" * 64), ("graph_id", GRAPH),
                         ("profiles_digest", profiles_digest(PROFILES)))))


def _base():
    from tests.test_persistence_integrity import _manifest

    return _manifest()


def _with(**fields):
    return dataclasses.replace(_base(), **fields)


def _consistent(ir=(("ir_id", IR), ("semantic_id", SEM))):
    return _with(graph_traceability=(("graph_id", GRAPH),), dialect_profiles=PROFILES, semantic_facts=_semantic(),
                 application_ir=ir)


def _ir_violations(manifest):
    result = EvidenceIntegrityValidator().validate(manifest)
    return [v for v in (result if isinstance(result, list) else [])
            if v.violation_type is ViolationType.APPLICATION_IR_BINDING_MISMATCH]


def test_a_manifest_without_the_ir_keeps_its_exact_hash():
    base = _base()
    assert str(base.manifest_hash) == LEGACY_MANIFEST_HASH and "application_ir" not in canonical_evidence_graph(base)


def test_the_ir_is_sealed_serialised_and_round_trips():
    manifest = _consistent()
    assert canonical_evidence_graph(manifest)["application_ir"] == {"ir_id": IR, "semantic_id": SEM}
    assert manifest.manifest_hash != _consistent(ir=()).manifest_hash
    decoded = serialization.decode_evidence_manifest(serialization.encode_evidence_manifest(manifest))
    assert decoded is not None and decoded.application_ir == manifest.application_ir
    assert decoded.manifest_hash == manifest.manifest_hash
    assert b"application_ir" not in serialization.encode_evidence_manifest(_consistent(ir=()))


def test_a_consistent_manifest_is_admitted():
    assert not _ir_violations(_consistent())


def test_tampering_after_sealing_and_persisted_tampering_are_detected():
    manifest = _consistent()
    manifest.application_ir = (("ir_id", "e" * 64), ("semantic_id", SEM))
    result = EvidenceIntegrityValidator().validate(manifest)
    assert ViolationType.MANIFEST_HASH_MISMATCH in {v.violation_type for v in (result if isinstance(result, list) else [])}
    raw = json.loads(serialization.encode_evidence_manifest(_consistent()))
    raw.get("payload", raw)["application_ir"]["ir_id"] = "e" * 64
    with pytest.raises(PersistenceCorruptionError):
        serialization.decode_evidence_manifest(json.dumps(raw).encode())


def test_the_ir_must_be_bound_to_the_recorded_semantic_facts():
    other = _with(graph_traceability=(("graph_id", GRAPH),), dialect_profiles=PROFILES, semantic_facts=_semantic(),
                  application_ir=(("ir_id", IR), ("semantic_id", "f" * 64)))
    assert [v.field_path for v in _ir_violations(other)] == ["application_ir.semantic_id"]
    orphan = _with(application_ir=(("ir_id", IR), ("semantic_id", SEM)))
    assert [v.field_path for v in _ir_violations(orphan)] == ["application_ir"]


@pytest.mark.parametrize("pairs", [
    (("ir_id", IR),), (("ir_id", IR), ("semantic_id", SEM), ("extra", "x")), (("ir_id", "nope"), ("semantic_id", SEM)),
])
def test_malformed_pairs_are_violations(pairs):
    assert _ir_violations(_consistent(ir=pairs))

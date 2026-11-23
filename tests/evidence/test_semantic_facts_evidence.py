"""Semantic-facts addresses in the sealed evidence manifest (Layer 5, phase P4).

``semantic_id`` / ``facts_digest`` / ``graph_id`` / ``profiles_digest`` are recorded through the conditional-key pattern:
a manifest without them keeps the exact seal it always had; with them they are sealed, serialised, cross-checked against
the sibling lineage fields, and tamper-evident.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from api import serialization
from api.serialization import PersistenceCorruptionError
from api.workload_contract import default_contract
from engine.evidence.integrity import EvidenceIntegrityValidator, ViolationType, profiles_digest
from engine.evidence.models import canonical_evidence_graph
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from tests.comparison_doubles import Candidate as _Candidate, Oracle as _Oracle

#: ``_manifest().manifest_hash`` as it was before ``semantic_facts`` existed (the same value the Layer 4 test pins).
LEGACY_MANIFEST_HASH = "sha256:7b07e99e957d4120fd17d19b0739c0e78db140d8e98f7fd172bb9eed5d4de866"
GRAPH = "a" * 64
PROFILES = (("src/A.cbl", "b" * 64),)
_PLAIN = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"


def _pairs(graph_id: str = GRAPH, profiles=PROFILES):
    return tuple(sorted((("semantic_id", "c" * 64), ("facts_digest", "d" * 64), ("graph_id", graph_id),
                         ("profiles_digest", profiles_digest(tuple(profiles))))))


def _base():
    from tests.test_persistence_integrity import _manifest

    return _manifest()


def _with(**fields):
    return dataclasses.replace(_base(), **fields)


def _consistent():
    return _with(graph_traceability=(("graph_id", GRAPH),), dialect_profiles=PROFILES, semantic_facts=_pairs())


def _violations(manifest):
    result = EvidenceIntegrityValidator().validate(manifest)
    return result if isinstance(result, list) else []


def _semantic(manifest):
    return [v for v in _violations(manifest) if v.violation_type is ViolationType.SEMANTIC_FACTS_BINDING_MISMATCH]


def test_manifest_without_semantic_facts_keeps_its_exact_hash_and_graph() -> None:
    base = _base()
    assert str(base.manifest_hash) == LEGACY_MANIFEST_HASH
    assert "semantic_facts" not in canonical_evidence_graph(base)
    assert not _violations(base)


def test_semantic_facts_are_sealed_serialised_and_round_trip() -> None:
    base, recorded = _base(), _consistent()
    assert canonical_evidence_graph(recorded)["semantic_facts"] == dict(_pairs())
    assert recorded.manifest_hash != base.manifest_hash
    payload = serialization.encode_evidence_manifest(recorded)
    assert b"semantic_facts" in payload
    decoded = serialization.decode_evidence_manifest(payload)
    assert decoded is not None
    assert decoded.semantic_facts == _pairs() and decoded.manifest_hash == recorded.manifest_hash
    assert b"semantic_facts" not in serialization.encode_evidence_manifest(base)


def test_a_consistent_manifest_is_admitted() -> None:
    assert not _violations(_consistent())


def test_a_run_without_a_graph_records_an_empty_graph_id() -> None:
    manifest = _with(dialect_profiles=PROFILES, semantic_facts=_pairs(graph_id=""))
    assert not _violations(manifest)


def test_tampering_after_sealing_is_detected() -> None:
    manifest = _consistent()
    manifest.semantic_facts = tuple(sorted((k, "e" * 64 if k == "semantic_id" else v) for k, v in manifest.semantic_facts))
    assert ViolationType.MANIFEST_HASH_MISMATCH in {v.violation_type for v in _violations(manifest)}


def test_persisted_tampering_fails_decoding() -> None:
    raw = json.loads(serialization.encode_evidence_manifest(_consistent()))
    body = raw.get("payload", raw)
    body["semantic_facts"]["semantic_id"] = "e" * 64
    with pytest.raises(PersistenceCorruptionError):
        serialization.decode_evidence_manifest(json.dumps(raw).encode())


@pytest.mark.parametrize("graph_traceability,semantic_graph", [
    ((), GRAPH),                                       # facts claim a graph the run does not record
    ((("graph_id", GRAPH),), ""),                      # run records a graph the facts do not state
    ((("graph_id", GRAPH),), "f" * 64),                # two different graphs
])
def test_graph_id_must_agree_with_graph_traceability(graph_traceability, semantic_graph) -> None:
    manifest = _with(graph_traceability=graph_traceability, dialect_profiles=PROFILES,
                     semantic_facts=_pairs(graph_id=semantic_graph))
    assert [v.field_path for v in _semantic(manifest)] == ["semantic_facts.graph_id"]


def test_profiles_digest_must_match_the_recorded_dialect_profiles() -> None:
    manifest = _with(graph_traceability=(("graph_id", GRAPH),), dialect_profiles=(("src/A.cbl", "9" * 64),),
                     semantic_facts=_pairs())
    assert [v.field_path for v in _semantic(manifest)] == ["semantic_facts.profiles_digest"]


@pytest.mark.parametrize("pairs", [
    (("semantic_id", "c" * 64),),                                                                   # missing keys
    _pairs() + (("extra", "x"),),                                                                   # extra key
    tuple(("semantic_id", "c" * 64) if k == "semantic_id" else (k, v) for k, v in _pairs()) + (("semantic_id", "c" * 64),),
])
def test_missing_extra_or_duplicate_keys_are_violations(pairs) -> None:
    manifest = _with(graph_traceability=(("graph_id", GRAPH),), dialect_profiles=PROFILES, semantic_facts=pairs)
    assert [v.field_path for v in _semantic(manifest)] == ["semantic_facts"]


def test_malformed_digests_are_violations() -> None:
    bad = tuple(sorted((k, "not-a-sha" if k == "facts_digest" else v) for k, v in _pairs()))
    manifest = _with(graph_traceability=(("graph_id", GRAPH),), dialect_profiles=PROFILES, semantic_facts=bad)
    assert [v.field_path for v in _semantic(manifest)] == ["semantic_facts.facts_digest"]


# --- pipeline level --------------------------------------------------------------------------------------------


def _run(tmp_path: Path, **config):
    src = tmp_path / "MAIN.cob"
    src.write_text(_PLAIN, encoding="latin-1")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    cfg = PipelineConfig(
        workload_id="wl-semantic", cobol_source_path=str(src), java_candidate_path=str(cand), java_entrypoint="Main",
        workload=default_contract("wl-semantic").workload, use_docker_java=True, **config)
    pipe = VerticalSlicePipeline(cfg, candidate_adapter=_Candidate(b"HI\n", None, 0))
    pipe._oracle_adapter = _Oracle(b"HI\n", None, 0)
    return pipe.run()


def test_pipeline_seals_the_configured_semantic_facts(tmp_path: Path) -> None:
    result = _run(tmp_path, graph_traceability=(("graph_id", GRAPH),), dialect_profiles=PROFILES,
                  semantic_facts=_pairs())
    manifest = result.evidence_manifest
    assert manifest.semantic_facts == _pairs()
    assert canonical_evidence_graph(manifest)["semantic_facts"] == dict(_pairs())
    assert not _violations(manifest)


def test_pipeline_without_semantic_facts_seals_no_key(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.evidence_manifest.semantic_facts == ()
    assert "semantic_facts" not in canonical_evidence_graph(result.evidence_manifest)

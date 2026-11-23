"""Dialect profile ids in the sealed evidence manifest (Layer 4, acceptance criterion 10).

``(file, profile_id)`` pairs from the discovery ``DialectProfile`` of each COBOL source file are recorded in the
manifest through the conditional-key pattern: a manifest without them keeps the exact seal it always had.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from api import serialization
from api.workload_contract import default_contract
from engine.evidence.integrity import EvidenceIntegrityValidator, ViolationType
from engine.evidence.models import canonical_evidence_graph
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from tests.comparison_doubles import Candidate as _Candidate, Oracle as _Oracle

ID_A, ID_B = "a" * 64, "b" * 64
PAIRS = (("src/A.cbl", ID_A), ("src/B.cbl", ID_B))
#: ``_manifest().manifest_hash`` computed from the Layer-4-complete tree BEFORE this field existed (verified at HEAD).
LEGACY_MANIFEST_HASH = "sha256:7b07e99e957d4120fd17d19b0739c0e78db140d8e98f7fd172bb9eed5d4de866"
_PLAIN = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"


def _base():
    from tests.test_persistence_integrity import _manifest

    return _manifest()


def _with_profiles(pairs=PAIRS):
    return dataclasses.replace(_base(), dialect_profiles=tuple(pairs))


def _violations(manifest):
    result = EvidenceIntegrityValidator().validate(manifest)
    return result if isinstance(result, list) else []


def test_manifest_without_profiles_keeps_its_exact_hash_and_graph() -> None:
    base = _base()
    assert str(base.manifest_hash) == LEGACY_MANIFEST_HASH
    assert "dialect_profiles" not in canonical_evidence_graph(base)
    assert not _violations(base)


def test_profiles_are_sealed_serialised_and_round_trip() -> None:
    base, recorded = _base(), _with_profiles()
    assert canonical_evidence_graph(recorded)["dialect_profiles"] == dict(PAIRS)
    assert recorded.manifest_hash != base.manifest_hash
    payload = serialization.encode_evidence_manifest(recorded)
    assert b"dialect_profiles" in payload
    decoded = serialization.decode_evidence_manifest(payload)
    assert decoded is not None
    assert decoded.dialect_profiles == PAIRS and decoded.manifest_hash == recorded.manifest_hash
    plain = serialization.decode_evidence_manifest(serialization.encode_evidence_manifest(base))
    assert plain is not None and plain.dialect_profiles == () and plain.manifest_hash == base.manifest_hash
    assert b"dialect_profiles" not in serialization.encode_evidence_manifest(base)


def test_a_valid_recorded_manifest_is_admitted() -> None:
    assert not _violations(_with_profiles())


def test_tampering_with_recorded_profile_ids_after_sealing_is_detected() -> None:
    manifest = _with_profiles()
    manifest.dialect_profiles = (("src/A.cbl", "c" * 64), PAIRS[1])  # in-place edit of sealed evidence
    types = {v.violation_type for v in _violations(manifest)}
    assert ViolationType.MANIFEST_HASH_MISMATCH in types


def test_persisted_profile_tampering_fails_decoding() -> None:
    import json

    import pytest

    from api.serialization import PersistenceCorruptionError

    raw = json.loads(serialization.encode_evidence_manifest(_with_profiles()))
    body = raw.get("payload", raw)
    body["dialect_profiles"]["src/A.cbl"] = "c" * 64
    with pytest.raises(PersistenceCorruptionError):
        serialization.decode_evidence_manifest(json.dumps(raw).encode() if isinstance(raw, dict) else raw)


def test_oracle_profile_id_must_be_one_of_the_recorded_ids() -> None:
    base = _with_profiles()
    forged = dataclasses.replace(base, oracle_identity=dataclasses.replace(base.oracle_identity, profile_id="d" * 64))
    mismatches = [v for v in _violations(forged) if v.violation_type is ViolationType.PROFILE_BINDING_MISMATCH]
    assert [v.field_path for v in mismatches] == ["oracle_identity.profile_id"]
    honest = dataclasses.replace(base, oracle_identity=dataclasses.replace(base.oracle_identity, profile_id=ID_B))
    assert not _violations(honest)


def test_malformed_and_duplicate_pairs_are_violations() -> None:
    bad = _violations(_with_profiles((("src/A.cbl", "not-a-sha"),)))
    assert any(v.violation_type is ViolationType.PROFILE_BINDING_MISMATCH for v in bad)
    dup = _violations(_with_profiles((("src/A.cbl", ID_A), ("src/A.cbl", ID_B))))
    assert any(v.violation_type is ViolationType.PROFILE_BINDING_MISMATCH for v in dup)


def test_a_legacy_oracle_profile_id_without_pairs_is_unaffected() -> None:
    base = _base()
    legacy = dataclasses.replace(base, oracle_identity=dataclasses.replace(base.oracle_identity, profile_id="f" * 64))
    assert not _violations(legacy)


# --- pipeline level -------------------------------------------------------------------------------------------


def _run(tmp_path: Path, **config):
    src = tmp_path / "MAIN.cob"
    src.write_text(_PLAIN, encoding="latin-1")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    cfg = PipelineConfig(
        workload_id="wl-profiles", cobol_source_path=str(src), java_candidate_path=str(cand), java_entrypoint="Main",
        workload=default_contract("wl-profiles").workload, use_docker_java=True, **config)
    pipe = VerticalSlicePipeline(cfg, candidate_adapter=_Candidate(b"HI\n", None, 0))
    pipe._oracle_adapter = _Oracle(b"HI\n", None, 0)
    return pipe.run()


def test_pipeline_seals_the_configured_profiles_and_sets_the_sole_profile_id(tmp_path: Path) -> None:
    result = _run(tmp_path, dialect_profiles=(("src/A.cbl", ID_A),))
    manifest = result.evidence_manifest
    assert manifest.dialect_profiles == (("src/A.cbl", ID_A),)
    assert result.oracle_identity.profile_id == ID_A
    assert canonical_evidence_graph(manifest)["dialect_profiles"] == {"src/A.cbl": ID_A}


def test_pipeline_with_several_files_records_pairs_but_no_single_oracle_profile_id(tmp_path: Path) -> None:
    result = _run(tmp_path, dialect_profiles=tuple(reversed(PAIRS)))
    assert result.evidence_manifest.dialect_profiles == PAIRS  # sorted by file
    assert result.oracle_identity.profile_id is None


def test_pipeline_without_profiles_seals_no_profile_key(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.evidence_manifest.dialect_profiles == ()
    assert "dialect_profiles" not in canonical_evidence_graph(result.evidence_manifest)

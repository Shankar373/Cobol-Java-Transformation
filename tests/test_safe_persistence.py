"""Safe persistence serialization tests (P1: pickle removed from the store).

The control-plane store persists evidence manifests and verdicts. These tests
pin the contract:
  - blobs are a versioned JSON envelope (interoperable, no code on load);
  - round-trip fidelity is exact (canonical serialization is unchanged);
  - legacy pickle and corrupt/unknown payloads fail closed;
  - a pickle payload can never execute code while loading.
"""

from __future__ import annotations

import json
import pickle
import sqlite3
from pathlib import Path

import pytest

import api.store as store_mod
from api.store import (
    BLOB_FORMAT,
    BLOB_VERSION,
    KIND_EVIDENCE_MANIFEST,
    KIND_VERDICT,
    RunRecord,
    Store,
    StoreError,
    _dumps_blob,
    _loads_blob,
)
from engine.domain.identities import (
    ArtifactIdentity,
    CandidateIdentity,
    ContentHash,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    WorkloadId,
)
from engine.evidence.models import (
    ArtifactEvidence,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)
from engine.verdict.derivation import Verdict, VerdictDeriver


def _manifest() -> EvidenceManifest:
    h = ContentHash.from_string("safe-persistence-probe")
    run_id = RunId("run-safe-001")
    oracle_exec = ExecutionEvidence(
        execution_id=ExecutionId("exec-oracle-001"), run_id=run_id,
        runtime_id="oracle-gnucobol", command="cobc", working_directory="/w",
        environment_variables={}, start_time="t0", end_time="t1",
        exit_code=0, stdout_hash=h, stderr_hash=h, generated_files={},
        source_tree_hash_before=h, source_tree_hash_after=h,
        termination_status="normal", timeout_applied=False,
    )
    cand_exec = ExecutionEvidence(
        execution_id=ExecutionId("exec-cand-001"), run_id=run_id,
        runtime_id="candidate-java", command="java", working_directory="/w",
        environment_variables={}, start_time="t0", end_time="t1",
        exit_code=0, stdout_hash=h, stderr_hash=h, generated_files={},
        source_tree_hash_before=h, source_tree_hash_after=h,
        termination_status="normal", timeout_applied=False,
    )
    art_o = ArtifactIdentity("art-o-1", "STDOUT", "stdout", "ORACLE", h, 5)
    art_c = ArtifactIdentity("art-c-1", "STDOUT", "stdout", "CANDIDATE", h, 5)
    comp = ComparisonEvidence(
        comparison_id="comp-stdout", run_id=run_id,
        comparator_id="stdout-exact", comparator_version="1.0.0",
        oracle_artifact_id="art-o-1", candidate_artifact_id="art-c-1",
        artifact_type="STDOUT", result="MATCH", normalization_applied=(),
        differences=(), field_level_results=(), content_hash=h,
    )
    return EvidenceManifest(
        manifest_version="1.0", run_id=run_id, workload_id=WorkloadId("wl-safe"),
        source_identity=SourceIdentity("src-1", h, 1, 10),
        candidate_identity=CandidateIdentity("cand-1", h, h, 1, 10),
        oracle_identity=OracleIdentity("gnucobol-3.1.2", "sha256:" + "a" * 64, "3.1.2.0"),
        environment_identities=(),
        controlled_input=InputIdentity("in-1", stdin_hash=h),
        execution_evidence=(oracle_exec, cand_exec),
        artifact_evidence=(
            ArtifactEvidence(art_o, ExecutionId("exec-oracle-001"), "t1", h, 5),
            ArtifactEvidence(art_c, ExecutionId("exec-cand-001"), "t1", h, 5),
        ),
        comparison_evidence=(comp,),
    )


class TestJsonEnvelope:
    def test_blob_is_versioned_json_envelope(self):
        raw = _dumps_blob(_manifest())
        assert raw is not None
        assert raw[:1] == b"{"
        envelope = json.loads(raw.decode("utf-8"))
        assert envelope["format"] == BLOB_FORMAT
        assert envelope["version"] == BLOB_VERSION
        assert envelope["kind"] == KIND_EVIDENCE_MANIFEST
        assert isinstance(envelope["payload"], dict)

    def test_verdict_blob_kind(self):
        verdict = VerdictDeriver().derive(_manifest())
        envelope = json.loads(_dumps_blob(verdict).decode("utf-8"))
        assert envelope["kind"] == KIND_VERDICT

    def test_serialization_is_deterministic(self):
        manifest = _manifest()
        assert _dumps_blob(manifest) == _dumps_blob(manifest)

    def test_store_module_does_not_use_pickle(self):
        source = Path(store_mod.__file__).read_text(encoding="utf-8")
        assert "import pickle" not in source
        assert not hasattr(store_mod, "pickle")

    def test_unserializable_object_fails_closed(self):
        with pytest.raises(StoreError):
            _dumps_blob(object())


class TestRoundTripFidelity:
    def test_manifest_round_trip_is_exact(self):
        manifest = _manifest()
        restored = _loads_blob(_dumps_blob(manifest))
        assert isinstance(restored, EvidenceManifest)
        assert restored.canonical_serialization() == manifest.canonical_serialization()
        assert restored.manifest_hash == manifest.manifest_hash
        assert len(restored.execution_evidence) == 2
        assert len(restored.artifact_evidence) == 2
        assert len(restored.comparison_evidence) == 1
        assert restored.comparison_evidence[0].comparator_version == "1.0.0"
        assert restored.comparison_evidence[0].content_hash == manifest.comparison_evidence[0].content_hash

    def test_verdict_round_trip_is_exact(self):
        verdict = VerdictDeriver().derive(_manifest())
        restored = _loads_blob(_dumps_blob(verdict))
        assert isinstance(restored, Verdict)
        assert restored.to_dict() == verdict.to_dict()
        assert restored.state is verdict.state

    def test_to_dict_only_object_round_trips(self):
        class _Stub:
            def to_dict(self) -> dict:
                return {"state": "UNPROVEN", "run_id": "r-1"}

        restored = _loads_blob(_dumps_blob(_Stub()))
        assert restored.to_dict() == {"state": "UNPROVEN", "run_id": "r-1"}

    def test_none_round_trips(self):
        assert _dumps_blob(None) is None
        assert _loads_blob(None) is None


class TestFailClosedDecoding:
    def test_legacy_pickle_is_refused(self):
        payload = pickle.dumps(_manifest(), protocol=pickle.HIGHEST_PROTOCOL)
        with pytest.raises(StoreError, match="pickle"):
            _loads_blob(payload)

    def test_pickle_payload_never_executes(self, tmp_path):
        marker = tmp_path / "executed.txt"

        class _Exploit:
            def __reduce__(self):
                import os
                return (os.system, (f"echo pwned > {marker}",))

        payload = pickle.dumps(_Exploit())
        with pytest.raises(StoreError):
            _loads_blob(payload)
        assert not marker.exists()

    def test_corrupt_json_is_refused(self):
        with pytest.raises(StoreError, match="corrupt"):
            _loads_blob(b"{not json")

    def test_non_object_json_is_refused(self):
        with pytest.raises(StoreError, match="corrupt"):
            _loads_blob(b"[]")

    def test_unknown_format_is_refused(self):
        raw = json.dumps({
            "format": "other", "version": BLOB_VERSION,
            "kind": KIND_VERDICT, "payload": {},
        }).encode()
        with pytest.raises(StoreError, match="format"):
            _loads_blob(raw)

    def test_unknown_version_is_refused(self):
        raw = json.dumps({
            "format": BLOB_FORMAT, "version": 999,
            "kind": KIND_VERDICT, "payload": {},
        }).encode()
        with pytest.raises(StoreError, match="version"):
            _loads_blob(raw)

    def test_unknown_kind_is_refused(self):
        raw = json.dumps({
            "format": BLOB_FORMAT, "version": BLOB_VERSION,
            "kind": "something-else", "payload": {},
        }).encode()
        with pytest.raises(StoreError, match="kind"):
            _loads_blob(raw)

    def test_invalid_payload_is_refused(self):
        raw = json.dumps({
            "format": BLOB_FORMAT, "version": BLOB_VERSION,
            "kind": KIND_VERDICT, "payload": {"state": "NOT-A-STATE"},
        }).encode()
        with pytest.raises(StoreError, match="payload"):
            _loads_blob(raw)


class TestStorePersistsJson:
    def test_run_evidence_survives_reopen(self, tmp_path):
        db_path = str(tmp_path / "control-plane.db")
        manifest = _manifest()
        verdict = VerdictDeriver().derive(manifest)

        store = Store(db_path)
        store.add_run(RunRecord(
            id="run-json-001", application_id="app-1",
            workload_id="wl-safe", evidence_manifest=manifest,
            verdict=verdict,
        ))

        reopened = Store(db_path)
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT evidence_blob, verdict_blob FROM runs WHERE id = ?",
                ("run-json-001",),
            ).fetchone()
        finally:
            conn.close()
        assert row[0][:1] == b"{"
        assert row[1][:1] == b"{"

        loaded = reopened.get_run("run-json-001")
        assert loaded is not None
        assert loaded.evidence_manifest.manifest_hash == manifest.manifest_hash
        assert loaded.verdict.to_dict() == verdict.to_dict()

    def test_legacy_pickle_row_is_refused(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        store = Store(db_path)
        store._conn.execute(
            "INSERT INTO runs (id, application_id, workload_id, stage,"
            " created_at, verdict_blob) VALUES (?, ?, ?, ?, ?, ?)",
            ("run-legacy-001", "app-1", "wl", "COMPLETED",
             "2026-01-01T00:00:00+00:00",
             pickle.dumps(_manifest())),
        )
        store._conn.commit()
        with pytest.raises(StoreError, match="pickle"):
            Store(db_path).get_run("run-legacy-001")

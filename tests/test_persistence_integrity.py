"""Persistence integrity tests (Phase B).

Proves persisted state is versioned JSON that fails closed:

  * evidence/verdict/report round-trip losslessly through the store;
  * legacy pickle payloads, malformed JSON, tampered evidence seals,
    unknown envelope schema versions and unknown stage values are all
    rejected as ``PersistenceCorruptionError`` instead of being coerced
    into a benign default (``CREATED``/``None``/``()``);
  * a database written by a newer schema is refused (``UnsupportedSchemaError``);
  * interrupted (non-terminal) runs are failed exactly once at startup;
  * ``api/`` never imports pickle;
  * corruption surfaces as a controlled HTTP 500 without leaking internals.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import serialization
from api.app import app
from api.errors import PersistenceCorruptionError, UnsupportedSchemaError
from api.models import RunStage
from api.service import Service
from api.store import ApplicationRecord, DB_SCHEMA_VERSION, RunRecord, Store
from engine.domain.identities import (
    CandidateIdentity,
    ContentHash,
    ExecutionId,
    EnvironmentIdentity,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    WorkloadId,
)
from engine.evidence.models import (
    ArtifactEvidence,
    ArtifactIdentity,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)
from engine.verdict.derivation import VerdictDeriver
from tests.common import make_stub_verdict

client = TestClient(app)

_HASH = ContentHash.from_string("persistence-probe")


@pytest.fixture(autouse=True)
def _reset_store(tmp_path):
    """File-backed store per test: production wiring, isolated database."""
    import api.app as app_mod

    store = Store(tmp_path / "control-plane.db")
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    yield store


def _manifest() -> EvidenceManifest:
    run_id = RunId("run-persist-001")
    workload_id = WorkloadId("wl-persist")

    def execution(eid: str, runtime: str) -> ExecutionEvidence:
        return ExecutionEvidence(
            execution_id=ExecutionId(eid),
            run_id=run_id,
            runtime_id=runtime,
            command="java -jar app.jar",
            working_directory="/workspace",
            environment_variables={"LANG": "C"},
            start_time="2024-01-01T00:00:00+00:00",
            end_time="2024-01-01T00:00:05+00:00",
            exit_code=0,
            stdout_hash=_HASH,
            stderr_hash=_HASH,
            generated_files={"out/report.txt": _HASH},
            source_tree_hash_before=_HASH,
            source_tree_hash_after=_HASH,
            termination_status="normal",
            timeout_applied=False,
        )

    oracle_exec = execution("exec-oracle-001", "oracle-gnucobol")
    candidate_exec = execution("exec-candidate-001", "candidate-java")
    oracle_art = ArtifactIdentity(
        "art-oracle-1", "STDOUT", "stdout", "ORACLE", _HASH, 128, 7
    )
    candidate_art = ArtifactIdentity(
        "art-candidate-1", "STDOUT", "stdout", "CANDIDATE", _HASH, 128
    )
    comparison = ComparisonEvidence(
        comparison_id="comp-stdout",
        run_id=run_id,
        comparator_id="stdout-exact",
        comparator_version="1.0.0",
        oracle_artifact_id="art-oracle-1",
        candidate_artifact_id="art-candidate-1",
        artifact_type="STDOUT",
        result="MATCH",
        normalization_applied=("crlf_to_lf",),
        differences=(),
        field_level_results=(),
        content_hash=_HASH,
        workload_id=workload_id,
    )
    return EvidenceManifest(
        manifest_version="1.0",
        run_id=run_id,
        workload_id=workload_id,
        source_identity=SourceIdentity("src-1", _HASH, 3, 1024),
        candidate_identity=CandidateIdentity("cand-1", _HASH, _HASH, 3, 1024),
        oracle_identity=OracleIdentity(
            "gnucobol-3.1.2", "sha256:deadbeef", "3.1.2", "ppw", "base"
        ),
        environment_identities=(
            EnvironmentIdentity(
                runtime_id="candidate-java",
                java_version="21",
                network_policy="none",
                resource_limits={"cpu": "1"},
            ),
        ),
        controlled_input=InputIdentity("in-1", _HASH, {"a.dat": _HASH}),
        execution_evidence=(oracle_exec, candidate_exec),
        artifact_evidence=(
            ArtifactEvidence(
                oracle_art, ExecutionId("exec-oracle-001"), "t1", _HASH, 128, 7
            ),
            ArtifactEvidence(
                candidate_art, ExecutionId("exec-candidate-001"), "t1", _HASH, 128
            ),
        ),
        comparison_evidence=(comparison,),
        created_at="2024-01-01T00:00:00+00:00",
    )


def _verdict(manifest: EvidenceManifest):
    return VerdictDeriver().derive(manifest)


def _seeded_run(store: Store, run_id: str = "run-seeded") -> RunRecord:
    record = RunRecord(
        id=run_id, application_id="app-seeded", workload_id="wl-persist"
    )
    store.add_run(record)
    record = store.get_run(run_id)
    record.stage = RunStage.COMPLETED
    record.completed_at = "2024-01-01T00:00:05+00:00"
    record.evidence_manifest = _manifest()
    record.verdict = _verdict(record.evidence_manifest)
    store.update_run(record)
    return store.get_run(run_id)


# ---------------------------------------------------------------------------
# Round trip fidelity
# ---------------------------------------------------------------------------


class TestCodecRoundTrip:
    def test_manifest_and_verdict_survive_encode_decode(self):
        manifest = _manifest()
        verdict = _verdict(manifest)

        decoded_manifest = serialization.decode_evidence_manifest(
            serialization.encode_evidence_manifest(manifest)
        )
        decoded_verdict = serialization.decode_verdict(
            serialization.encode_verdict(verdict)
        )

        assert decoded_manifest == manifest
        assert decoded_manifest.sealed_hash == manifest.sealed_hash
        assert decoded_manifest.artifact_evidence[0].artifact == (
            manifest.artifact_evidence[0].artifact
        )
        assert decoded_manifest.created_at == manifest.created_at
        assert decoded_verdict == verdict

    def test_store_round_trip_preserves_objects(self, _reset_store):
        store = _reset_store
        seeded = _seeded_run(store)
        restored = store.get_run("run-seeded")

        assert restored.stage == RunStage.COMPLETED
        assert restored.evidence_manifest == seeded.evidence_manifest
        assert restored.verdict == seeded.verdict
        assert str(restored.verdict.evidence_manifest_hash) == str(
            restored.evidence_manifest.manifest_hash
        )

    def test_report_round_trip(self):
        report = {"phases": [{"name": "discovery", "status": "ok"}], "count": 1}
        decoded = serialization.decode_report(
            serialization.encode_report(report)
        )
        assert decoded == report

    def test_str_list_round_trip(self):
        assert serialization.decode_str_list(
            serialization.encode_str_list(("a", "b"))
        ) == ("a", "b")
        assert serialization.decode_str_list("[]") == ()


# ---------------------------------------------------------------------------
# Fail-closed decoding
# ---------------------------------------------------------------------------


class TestFailClosedDecoding:
    def test_legacy_pickle_rejected(self):
        with pytest.raises(PersistenceCorruptionError) as exc:
            serialization.decode_verdict(pickle.dumps({"anything": True}))
        assert "not UTF-8 JSON" in str(exc.value)

    def test_malformed_json_rejected(self):
        with pytest.raises(PersistenceCorruptionError):
            serialization.decode_evidence_manifest(b"{not json")

    def test_tampered_evidence_rejected(self):
        blob = serialization.encode_evidence_manifest(_manifest())
        tampered = blob.replace(b'"exit_code": 0', b'"exit_code": 1', 1)
        assert tampered != blob
        with pytest.raises(PersistenceCorruptionError) as exc:
            serialization.decode_evidence_manifest(tampered)
        assert "seal mismatch" in str(exc.value)

    def test_unknown_envelope_version_rejected(self):
        blob = json.loads(serialization.encode_evidence_manifest(_manifest()))
        blob["schema_version"] = 99
        with pytest.raises(UnsupportedSchemaError):
            serialization.decode_evidence_manifest(
                json.dumps(blob).encode("utf-8")
            )

    def test_wrong_schema_name_rejected(self):
        blob = json.loads(serialization.encode_evidence_manifest(_manifest()))
        blob["schema"] = "verdict"
        with pytest.raises(PersistenceCorruptionError) as exc:
            serialization.decode_evidence_manifest(
                json.dumps(blob).encode("utf-8")
            )
        assert "unexpected persisted schema" in str(exc.value)

    def test_verdict_with_bogus_state_rejected(self):
        blob = json.loads(serialization.encode_verdict(_verdict(_manifest())))
        blob["payload"]["state"] = "TOTALLY_FINE"
        with pytest.raises(PersistenceCorruptionError):
            serialization.decode_verdict(json.dumps(blob).encode("utf-8"))

    def test_unknown_stage_in_database_rejected(self, _reset_store):
        store = _reset_store
        store.add_run(
            RunRecord(id="run-bogus", application_id="a", workload_id="w")
        )
        store._conn.execute(
            "UPDATE runs SET stage = 'LAUNCH_ROCKET' WHERE id = 'run-bogus'"
        )
        store._conn.commit()
        with pytest.raises(PersistenceCorruptionError):
            store.get_run("run-bogus")

    def test_corrupt_string_list_rejected(self, _reset_store):
        store = _reset_store
        store.add_application(
            ApplicationRecord(
                id="app-1",
                name="n",
                description="",
                workload_id="w",
                java_entrypoint="Main",
            )
        )
        store._conn.execute(
            "UPDATE applications SET discovered_program_ids = 'not-json'"
            " WHERE id = 'app-1'"
        )
        store._conn.commit()
        with pytest.raises(PersistenceCorruptionError):
            store.get_application("app-1")


# ---------------------------------------------------------------------------
# Database schema versioning
# ---------------------------------------------------------------------------


class TestSchemaVersioning:
    def test_newer_database_schema_rejected(self, tmp_path):
        import sqlite3

        path = tmp_path / "future.db"
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()

        with pytest.raises(UnsupportedSchemaError):
            Store(path)

    def test_current_schema_written_on_create(self, _reset_store):
        row = _reset_store._conn.execute("PRAGMA user_version").fetchone()
        assert int(row[0]) == DB_SCHEMA_VERSION

    def test_migration_adds_generation_columns(self, tmp_path):
        import sqlite3

        # v1-era table layout: no report_blob / validation_generation.
        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE applications (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                workload_id TEXT NOT NULL DEFAULT '',
                java_entrypoint TEXT NOT NULL DEFAULT 'Main',
                cobol_source_path TEXT, java_candidate_path TEXT,
                discovered_program_ids TEXT NOT NULL DEFAULT '[]',
                generated_app_path TEXT, generated_entrypoint TEXT,
                generated_program_ids TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE TABLE runs (
                id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
                workload_id TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'CREATED',
                created_at TEXT NOT NULL, completed_at TEXT, error TEXT,
                evidence_blob BLOB, verdict_blob BLOB
            );
            PRAGMA user_version = 1;
            """
        )
        conn.commit()
        conn.close()

        store = Store(path)
        store.add_run(
            RunRecord(id="run-legacy", application_id="a", workload_id="w")
        )
        record = store.get_run("run-legacy")
        assert record.validation_generation == 0
        assert record.certification_contract is None

        # New columns are usable immediately.
        record.stage = RunStage.COMPLETED
        store.update_run(record)
        assert store.get_run("run-legacy").stage == RunStage.COMPLETED


# ---------------------------------------------------------------------------
# Startup reconciliation
# ---------------------------------------------------------------------------


class TestInterruptedRunReconciliation:
    def test_non_terminal_runs_failed_on_restart(self, tmp_path):
        path = tmp_path / "restart.db"
        first = Store(path)
        first.add_run(
            RunRecord(
                id="run-inflight",
                application_id="a",
                workload_id="w",
                stage=RunStage.EXECUTING_ORACLE,
            )
        )
        first.add_run(
            RunRecord(
                id="run-done",
                application_id="a",
                workload_id="w",
                stage=RunStage.COMPLETED,
            )
        )
        first.add_run(
            RunRecord(
                id="run-failed",
                application_id="a",
                workload_id="w",
                stage=RunStage.FAILED,
            )
        )

        # Simulate a process restart over the same database file.
        second = Store(path)
        marked = second.mark_interrupted_runs()
        assert marked == 1

        interrupted = second.get_run("run-inflight")
        assert interrupted.stage == RunStage.FAILED
        assert "restart" in (interrupted.error or "")
        assert interrupted.completed_at is not None
        assert second.get_run("run-done").stage == RunStage.COMPLETED
        assert second.get_run("run-failed").error is None

        # Reconciliation is idempotent.
        assert second.mark_interrupted_runs() == 0

    def test_startup_reconciliation_applies_to_api_store(self, _reset_store):
        import api.app as app_mod

        store = _reset_store
        store.add_run(
            RunRecord(
                id="run-leftover",
                application_id="a",
                workload_id="w",
                stage=RunStage.TRANSFORMING,
            )
        )
        # api.app performs this at import/startup.
        assert store.mark_interrupted_runs() == 1
        assert app_mod._store.get_run("run-leftover").stage == RunStage.FAILED


# ---------------------------------------------------------------------------
# Static and HTTP-surface guards
# ---------------------------------------------------------------------------


class TestNoPickleAnywhereInApi:
    def test_api_modules_never_import_pickle(self):
        api_dir = Path(__file__).resolve().parent.parent / "api"
        offenders = []
        for source in sorted(api_dir.glob("*.py")):
            text = source.read_text(encoding="utf-8")
            if "import pickle" in text or "pickle.loads" in text:
                offenders.append(source.name)
        assert offenders == [], f"pickle used in {offenders}"

    def test_legacy_pickle_row_is_rejected_not_served(self, _reset_store):
        import api.app as app_mod

        store = _reset_store
        store.add_run(
            RunRecord(id="run-pickled", application_id="a", workload_id="w")
        )
        store._conn.execute(
            "UPDATE runs SET evidence_blob = ? WHERE id = 'run-pickled'",
            (pickle.dumps({"stage": "COMPLETED"}),),
        )
        store._conn.commit()

        with pytest.raises(PersistenceCorruptionError):
            store.get_run("run-pickled")
        assert app_mod._store is store


class TestHttpCorruptionSurface:
    def test_corrupt_run_returns_controlled_500(self, _reset_store):
        import api.app as app_mod

        store = _reset_store
        store.add_run(
            RunRecord(id="run-corrupt", application_id="a", workload_id="w")
        )
        store._conn.execute(
            "UPDATE runs SET evidence_blob = ? WHERE id = 'run-corrupt'",
            (b"\x80\x04legacy-pickle-bytes",),
        )
        store._conn.commit()
        assert app_mod._store is store

        resp = client.get("/runs/run-corrupt")

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "Traceback" not in detail
        assert "site-packages" not in detail
        assert len(detail) <= 500

    def test_corrupt_verdict_returns_controlled_500(self, _reset_store):
        import api.app as app_mod

        store = _reset_store
        store.add_run(
            RunRecord(id="run-bad-verdict", application_id="a", workload_id="w")
        )
        store._conn.execute(
            "UPDATE runs SET verdict_blob = ? WHERE id = 'run-bad-verdict'",
            (b"{{{",),
        )
        store._conn.commit()
        assert app_mod._store is store

        resp = client.get("/runs/run-bad-verdict/verdict")

        assert resp.status_code == 500
        assert "Traceback" not in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Evidence <-> verdict consistency
# ---------------------------------------------------------------------------


class TestEvidenceVerdictConsistency:
    def test_matched_pair_serves_through_api(self, _reset_store):
        store = _reset_store
        _seeded_run(store, "run-pair")

        resp = client.get("/runs/run-pair/verdict")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["run_id"] == "run-pair"
        assert body["evidence_manifest_hash"].removeprefix("sha256:") == str(
            store.get_run("run-pair").evidence_manifest.manifest_hash
        ).removeprefix("sha256:")

    def test_mismatched_pair_is_rejected(self, _reset_store):
        import dataclasses

        store = _reset_store
        record = _seeded_run(store, "run-mismatch")
        foreign_hash = ContentHash.from_string("a verdict from another run")
        record.verdict = dataclasses.replace(
            record.verdict, evidence_manifest_hash=foreign_hash
        )

        with pytest.raises(PersistenceCorruptionError) as exc:
            Service._check_evidence_verdict_consistency(record)
        assert "hash mismatch" in str(exc.value)

        # Serving the mismatched pair over HTTP fails closed with 500.
        store.update_run(record)
        resp = client.get("/runs/run-mismatch/verdict")
        assert resp.status_code == 500
        assert "hash mismatch" in resp.json()["detail"]

    def test_verdict_without_evidence_is_still_valid(self, _reset_store):
        """A verdict with no stored manifest skips the cross-check.

        (The engine may run without persisting a full manifest; only a
        *present* manifest can be compared.)
        """
        store = _reset_store
        record = RunRecord(
            id="run-verdict-only", application_id="a", workload_id="w"
        )
        store.add_run(record)
        record = store.get_run("run-verdict-only")
        record.verdict = make_stub_verdict("run-verdict-only", "w")
        Service._check_evidence_verdict_consistency(record)  # no raise
        store.update_run(record)

        resp = client.get("/runs/run-verdict-only/verdict")
        assert resp.status_code == 200
        assert resp.json()["state"] == "UNPROVEN"

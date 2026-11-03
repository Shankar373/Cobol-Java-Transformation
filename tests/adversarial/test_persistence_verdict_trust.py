"""Trust-boundary persistence attacks: stale VERIFIED state must fail closed.

PERSISTENCE ATTACK contract:
  1. produce a genuine VERIFIED result via the validated path
  2. persist the evidence manifest + verdict
  3. mutate the stored evidence (and/or the verdict)
  4. restart: fresh Store/Service over the same SQLite file
  5. attempt to retrieve the verdict / run detail
  6. the system MUST NOT trust stale VERIFIED state (fail closed)

Two independent layers guard against this:
  * the evidence seal re-verification on decode (api.serialization), and
  * the verdict <-> evidence hash-consistency check on retrieval
    (api.service.Service._check_evidence_verdict_consistency).

A coherent full-database forgery (both blobs rewritten self-consistently)
cannot be detected by hash chaining alone; see docs/TRUST_BOUNDARY.md.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from api import serialization
from api.app import app
from api.errors import PersistenceCorruptionError
from api.models import RunStage
from api.service import Service
from api.store import RunRecord, Store
from engine.domain.identities import RunId, VerdictState, WorkloadId
from engine.evidence.integrity import (
    EvidenceIntegrityValidator,
    ValidatedEvidenceManifest,
)
from engine.verdict.derivation import derive_verdict_validated

from .conftest import (
    make_artifact,
    make_artifact_evidence,
    make_comparison,
    make_manifest,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixture: a genuine VERIFIED run backed by a file-backed store
# ---------------------------------------------------------------------------


def _genuine_verified_run() -> RunRecord:
    run_id = RunId(value="run-persist-trust")
    oracle_art = make_artifact("art-oracle-stdout", "STDOUT", "ORACLE", b"out")
    candidate_art = make_artifact("art-candidate-stdout", "STDOUT", "CANDIDATE", b"out")
    manifest = make_manifest(
        run_id=run_id,
        artifacts=(
            make_artifact_evidence(oracle_art, "oracle-exec-1"),
            make_artifact_evidence(candidate_art, "candidate-exec-1"),
        ),
        comparisons=(
            make_comparison(
                run_id,
                result="MATCH",
                oracle_id="art-oracle-stdout",
                candidate_id="art-candidate-stdout",
            ),
        ),
    )
    validated = EvidenceIntegrityValidator().validate(manifest)
    assert isinstance(validated, ValidatedEvidenceManifest), validated
    verdict = derive_verdict_validated(validated)
    assert verdict.state == VerdictState.VERIFIED

    record = RunRecord(
        id="run-persist-trust",
        application_id="app-persist-trust",
        workload_id="test-workload",
        stage=RunStage.COMPLETED,
        completed_at="2026-10-08T00:00:00+00:00",
        evidence_manifest=manifest,
        verdict=verdict,
    )
    return record


@pytest.fixture()
def persistent_db(tmp_path):
    """File-backed store; yields (db_path, record) after seeding VERIFIED."""
    import api.app as app_mod

    from api.store import ApplicationRecord

    db_path = tmp_path / "control-plane.db"
    store = Store(db_path)
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc

    store.add_application(
        ApplicationRecord(
            id="app-persist-trust",
            name="persist-trust",
            description="",
            workload_id="test-workload",
            java_entrypoint="Main",
        )
    )
    record = _genuine_verified_run()
    created = RunRecord(
        id=record.id,
        application_id=record.application_id,
        workload_id=record.workload_id,
    )
    store.add_run(created)
    record.validation_generation = created.validation_generation
    store.update_run(record)
    return db_path, record


def _restart(db_path) -> Store:
    """Fresh objects over the same database file (process restart)."""
    import api.app as app_mod

    store = Store(db_path)
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    return store


def _tamper_evidence_blob(db_path, mutate) -> None:
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT evidence_blob FROM runs WHERE id = 'run-persist-trust'"
        ).fetchone()
        document = json.loads(bytes(row[0]).decode("utf-8"))
        mutate(document["payload"])
        conn.execute(
            "UPDATE runs SET evidence_blob = ? WHERE id = 'run-persist-trust'",
            (json.dumps(document, sort_keys=True).encode("utf-8"),),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The PERSISTENCE ATTACK, end to end
# ---------------------------------------------------------------------------


class TestPersistenceAttackFailsClosed:
    def test_genuine_verified_pair_serves_before_tampering(self, persistent_db):
        db_path, _ = persistent_db
        _restart(db_path)
        resp = client.get("/runs/run-persist-trust/verdict")
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "VERIFIED"

    def test_mutated_evidence_rejected_after_restart(self, persistent_db):
        """Stale evidence (byte-level mutation) breaks the seal: every
        retrieval surface fails closed after a process restart."""
        db_path, _ = persistent_db

        def mutate(payload: dict) -> None:
            payload["comparison_evidence"][0]["result"] = "MISMATCH"

        _tamper_evidence_blob(db_path, mutate)

        store = _restart(db_path)
        with pytest.raises(PersistenceCorruptionError):
            store.get_run("run-persist-trust")
        for url in (
            "/runs/run-persist-trust",
            "/runs/run-persist-trust/verdict",
            "/runs/run-persist-trust/detail",
        ):
            resp = client.get(url)
            assert resp.status_code == 500, (url, resp.text)
            assert "Traceback" not in resp.text

    def test_forged_evidence_seal_rejected_by_verdict_binding(self, persistent_db):
        """Attacker re-seals mutated evidence (seal is self-consistent);
        the stored verdict no longer hash-matches the evidence, so the
        verdict and detail endpoints fail closed."""
        db_path, record = persistent_db

        mutated = dataclasses.replace(
            record.evidence_manifest,
            comparison_evidence=tuple(
                dataclasses.replace(c, result="MISMATCH")
                for c in record.evidence_manifest.comparison_evidence
            ),
        )

        import sqlite3

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE runs SET evidence_blob = ? WHERE id = 'run-persist-trust'",
                (serialization.encode_evidence_manifest(mutated),),
            )
            conn.commit()
        finally:
            conn.close()

        _restart(db_path)
        resp = client.get("/runs/run-persist-trust/verdict")
        assert resp.status_code == 500
        assert "hash mismatch" in resp.json()["detail"]

        resp = client.get("/runs/run-persist-trust/detail")
        assert resp.status_code == 500

    def test_verdict_swap_rejected_by_hash_binding(self, persistent_db):
        """A verdict persisted from another run does not hash-match the
        stored evidence and is never served."""
        db_path, record = persistent_db
        forged = dataclasses.replace(
            record.verdict,
            evidence_manifest_hash="sha256:" + "f" * 64,
        )

        import sqlite3

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE runs SET verdict_blob = ? WHERE id = 'run-persist-trust'",
                (serialization.encode_verdict(forged),),
            )
            conn.commit()
        finally:
            conn.close()

        _restart(db_path)
        resp = client.get("/runs/run-persist-trust/verdict")
        assert resp.status_code == 500
        assert "hash mismatch" in resp.json()["detail"]

        resp = client.get("/runs/run-persist-trust/detail")
        assert resp.status_code == 500

    def test_verified_verdict_without_evidence_fails_closed(self, persistent_db):
        """A persisted VERIFIED verdict with no evidence manifest has no
        hash-lock and must never be served as certification."""
        db_path, record = persistent_db

        import sqlite3

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE runs SET evidence_blob = NULL WHERE id = 'run-persist-trust'"
            )
            conn.commit()
        finally:
            conn.close()

        _restart(db_path)
        resp = client.get("/runs/run-persist-trust/verdict")
        assert resp.status_code == 500
        resp = client.get("/runs/run-persist-trust/detail")
        assert resp.status_code == 500

    def test_non_certifying_state_without_manifest_still_served(self):
        """Compatibility: negative states (e.g. UNPROVEN) may still be
        served without a manifest; only VERIFIED is rejected."""
        record = RunRecord(
            id="run-unproven-only",
            application_id="app-x",
            workload_id="w",
            stage=RunStage.COMPLETED,
        )
        Service._check_evidence_verdict_consistency(record)  # no manifest, no verdict
        from tests.common import make_stub_verdict

        record.verdict = make_stub_verdict("run-unproven-only", "w")
        Service._check_evidence_verdict_consistency(record)  # must not raise

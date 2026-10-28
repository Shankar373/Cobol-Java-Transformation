"""Phase 12 batch P4 (BL-091): customer approval workflow — red-first.

D-1 resolved 2026-10-17 with an explicit product scope; this file pins
that scope as executable contracts.  Every test here fails against the
pre-P4 code (the endpoints do not exist and the download endpoint has no
approval gate).

Approved scope (D-1, 2026-10-17):

* per-run approval states ``PENDING`` / ``APPROVED`` / ``REJECTED``;
* the record stores approver string, timestamp and reason — rejection
  REQUIRES a reason, approval reason is optional;
* ``GET /runs/{id}/download`` is blocked with HTTP 409 unless the run is
  ``APPROVED`` (the gate runs before artifact lookup and size caps so no
  archive detail leaks pre-approval; an unknown run is still 404);
* every new run and every re-validation starts ``PENDING`` — approval is
  never carried forward across attempts;
* the existing bearer-token auth covers the new endpoints (no RBAC); the
  approver string is recorded input, NOT a verified identity;
* the record persists in the existing SQLite run store; no
  evidence-manifest seal integration and no cryptographic tamper-evidence
  is claimed.

fastapi/store-dependent: deliberately NOT wired into the dependency-free
capability-truth gate (same convention as the Phase 11 P2 file).
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.service import Service
from api.store import ApplicationRecord, RunRecord, Store

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset module-level singletons for test isolation."""
    import api.app as app_mod

    store = Store()
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    yield store


def _create_app(name: str, workload_id: str = "wl-bl091") -> str:
    resp = client.post(
        "/applications", json={"name": name, "workload_id": workload_id}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _start_run(app_id: str) -> str:
    """Upload a source file and start a run with the worker stubbed out."""
    upload = client.post(
        f"/applications/{app_id}/upload",
        files=[("files", ("A.cob", io.BytesIO(b"A"), "text/plain"))],
    )
    assert upload.status_code == 201, upload.text
    from api.service import Service as _Service

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_Service, "_modernize_background", lambda *a, **k: None)
        resp = client.post(f"/applications/{app_id}/modernize")
    assert resp.status_code == 202, resp.text
    return resp.json()["run_id"]


def _seed_generated(run_id: str, files: list[tuple[str, bytes]]) -> Path:
    """Attach a generated-app directory to the run's application."""
    import api.app as app_mod
    from api.artifact_seal import compute_generated_seal

    run = app_mod._service.get_run(run_id)
    app_rec = app_mod._service.get_application(run.application_id)
    target = Path(app_rec.cobol_source_path or ".")  # stable per-app dir
    target = target.parent / f"{app_rec.id}-generated"
    target.mkdir(parents=True, exist_ok=True)
    for rel, content in files:
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    app_rec.generated_app_path = str(target)
    app_mod._service._store.update_application(app_rec)
    # A real run seals its generated bundle at generation time
    # (api.artifact_seal); approval/export verify the seal, so the
    # fixture seals the seeded bytes exactly like the pipeline would.
    app_mod._service._store.set_generated_seal(
        run_id, compute_generated_seal(target)
    )
    return target


def _decide(
    run_id: str,
    decision: str,
    approver: str = "reviewer-a",
    reason: str | None = None,
):
    body: dict = {"decision": decision, "approver": approver}
    if reason is not None:
        body["reason"] = reason
    return client.post(f"/runs/{run_id}/approval", json=body)


def _get_approval(run_id: str):
    return client.get(f"/runs/{run_id}/approval")


def _make_terminal(run_id: str) -> None:
    """Move a stubbed run to COMPLETED so revalidation is allowed."""
    import api.app as app_mod

    store: Store = app_mod._service._store
    rec = store.get_run(run_id)
    assert rec is not None
    rec.stage = rec.stage.__class__.COMPLETED
    store.update_run(rec)


# ---------------------------------------------------------------------------
# Approval state defaults and recording
# ---------------------------------------------------------------------------


class TestApprovalStateDefaults:
    def test_new_run_starts_pending(self):
        app_id = _create_app("bl091-new-run")
        run_id = _start_run(app_id)

        resp = _get_approval(run_id)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["run_id"] == run_id
        assert body["state"] == "PENDING"
        assert body["approver"] is None
        assert body["reason"] is None
        assert body["decided_at"] is None

    def test_unknown_run_approval_is_404(self):
        assert _get_approval("run-ghost").status_code == 404
        assert _decide("run-ghost", "APPROVED").status_code == 404


class TestApprovalDecisions:
    def test_approve_records_approver_and_timestamp(self):
        app_id = _create_app("bl091-approve")
        run_id = _start_run(app_id)

        resp = _decide(run_id, "APPROVED", approver="reviewer-a")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "APPROVED"
        assert body["approver"] == "reviewer-a"
        assert body["reason"] is None  # approval reason is optional
        assert body["decided_at"]

        persisted = _get_approval(run_id).json()
        assert persisted == body

    def test_approve_with_reason_records_reason(self):
        app_id = _create_app("bl091-approve-reason")
        run_id = _start_run(app_id)

        resp = _decide(run_id, "APPROVED", approver="reviewer-a", reason="spot check ok")

        assert resp.status_code == 200, resp.text
        assert resp.json()["reason"] == "spot check ok"

    def test_reject_without_reason_is_422_and_state_unchanged(self):
        app_id = _create_app("bl091-reject-no-reason")
        run_id = _start_run(app_id)

        resp = _decide(run_id, "REJECTED", approver="reviewer-a")

        assert resp.status_code == 422, resp.text
        body = _get_approval(run_id).json()
        assert body["state"] == "PENDING", body
        assert body["approver"] is None

    def test_reject_with_whitespace_reason_is_422(self):
        app_id = _create_app("bl091-reject-ws")
        run_id = _start_run(app_id)

        resp = _decide(run_id, "REJECTED", approver="reviewer-a", reason="   ")

        assert resp.status_code == 422, resp.text
        assert _get_approval(run_id).json()["state"] == "PENDING"

    def test_reject_with_reason_records_everything(self):
        app_id = _create_app("bl091-reject")
        run_id = _start_run(app_id)

        resp = _decide(
            run_id, "REJECTED", approver="reviewer-b", reason="verdict scope mismatch"
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "REJECTED"
        assert body["approver"] == "reviewer-b"
        assert body["reason"] == "verdict scope mismatch"
        assert body["decided_at"]

    def test_decision_pending_is_invalid_422(self):
        app_id = _create_app("bl091-decision-pending")
        run_id = _start_run(app_id)

        resp = _decide(run_id, "PENDING", approver="reviewer-a")

        assert resp.status_code == 422, resp.text
        assert _get_approval(run_id).json()["state"] == "PENDING"

    def test_unknown_decision_is_422(self):
        app_id = _create_app("bl091-decision-unknown")
        run_id = _start_run(app_id)

        resp = _decide(run_id, "MAYBE", approver="reviewer-a")

        assert resp.status_code == 422, resp.text
        assert _get_approval(run_id).json()["state"] == "PENDING"

    @pytest.mark.parametrize("approver", ["", "   "])
    def test_blank_approver_is_422(self, approver):
        app_id = _create_app(f"bl091-blank-approver-{len(approver)}")
        run_id = _start_run(app_id)

        resp = _decide(run_id, "APPROVED", approver=approver)

        assert resp.status_code == 422, resp.text
        assert _get_approval(run_id).json()["state"] == "PENDING"

    def test_later_decision_replaces_earlier(self):
        """A new explicit decision supersedes the previous one (audit: the
        latest approver/timestamp/reason is the record of truth)."""
        app_id = _create_app("bl091-redecide")
        run_id = _start_run(app_id)
        assert _decide(run_id, "APPROVED", approver="reviewer-a").status_code == 200

        resp = _decide(
            run_id, "REJECTED", approver="reviewer-c", reason="second look failed"
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "REJECTED"
        assert body["approver"] == "reviewer-c"
        assert body["reason"] == "second look failed"


# ---------------------------------------------------------------------------
# Export gate (BL-093 sibling contract: download requires APPROVED)
# ---------------------------------------------------------------------------


class TestDownloadRequiresApproval:
    def test_download_blocked_while_pending_is_409(self):
        app_id = _create_app("bl091-dl-pending")
        run_id = _start_run(app_id)
        _seed_generated(run_id, [("Main.java", b"class Main {}")])

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 409, resp.text
        assert "approval" in resp.text.lower()

    def test_download_blocked_when_rejected_is_409(self):
        app_id = _create_app("bl091-dl-rejected")
        run_id = _start_run(app_id)
        _seed_generated(run_id, [("Main.java", b"class Main {}")])
        assert _decide(
            run_id, "REJECTED", approver="reviewer-a", reason="no"
        ).status_code == 200

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 409, resp.text

    def test_download_succeeds_after_approval(self):
        app_id = _create_app("bl091-dl-approved")
        run_id = _start_run(app_id)
        _seed_generated(run_id, [("Main.java", b"class Main {}")])
        assert _decide(run_id, "APPROVED", approver="reviewer-a").status_code == 200

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/zip"

    def test_unknown_run_download_still_404(self):
        """The approval gate must not change the unknown-run 404 contract."""
        assert client.get("/runs/run-ghost/download").status_code == 404


# ---------------------------------------------------------------------------
# Per-run isolation and re-validation reset
# ---------------------------------------------------------------------------


class TestPerRunIsolationAndReset:
    def test_approval_is_per_run(self):
        app_id = _create_app("bl091-isolation")
        run_a = _start_run(app_id)
        run_b = _start_run(app_id)
        assert _decide(run_a, "APPROVED", approver="reviewer-a").status_code == 200

        assert _get_approval(run_a).json()["state"] == "APPROVED"
        b = _get_approval(run_b).json()
        assert b["state"] == "PENDING"
        assert b["approver"] is None

    def test_revalidation_resets_approval_to_pending(self):
        """Approval never carries forward: a re-validation starts PENDING."""
        app_id = _create_app("bl091-rerun-reset")
        run_id = _start_run(app_id)
        _seed_generated(run_id, [("Main.java", b"class Main {}")])
        assert _decide(run_id, "APPROVED", approver="reviewer-a").status_code == 200
        _make_terminal(run_id)

        resp = client.post(f"/runs/{run_id}/validate")
        assert resp.status_code == 202, resp.text

        body = _get_approval(run_id).json()
        assert body["state"] == "PENDING", body
        assert body["approver"] is None
        assert body["reason"] is None
        assert body["decided_at"] is None
        # The stale approval no longer unlocks export.
        dl = client.get(f"/runs/{run_id}/download")
        assert dl.status_code == 409, dl.text


# ---------------------------------------------------------------------------
# Authorization (existing bearer-token auth; no RBAC added)
# ---------------------------------------------------------------------------


class TestApprovalAuthorization:
    def test_approval_endpoints_require_bearer_token(self, monkeypatch):
        app_id = _create_app("bl091-authn")
        run_id = _start_run(app_id)
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        assert _get_approval(run_id).status_code == 401
        assert _decide(run_id, "APPROVED").status_code == 401
        assert client.get(f"/runs/{run_id}/download").status_code == 401

        headers = {"Authorization": "Bearer sekret-token"}
        ok = client.post(
            f"/runs/{run_id}/approval",
            json={"decision": "APPROVED", "approver": "reviewer-a"},
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        assert client.get(f"/runs/{run_id}/approval", headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# Store persistence and schema migration (existing SQLite run store)
# ---------------------------------------------------------------------------


class TestApprovalPersistence:
    def test_store_roundtrip_and_revalidation_clear(self, tmp_path):
        db = tmp_path / "control.db"
        store = Store(db)
        app_rec = store.add_application(
            ApplicationRecord(
                id="app-1",
                name="n",
                description="",
                workload_id="wl",
                java_entrypoint="Main",
            )
        )
        store.add_run(
            RunRecord(id="run-1", application_id=app_rec.id, workload_id="wl")
        )

        rec = store.set_run_approval(
            "run-1", state="APPROVED", approver="reviewer-a", reason=None
        )
        assert rec.approval_state == "APPROVED"
        assert rec.approval_decided_at

        # Survives a reopen (durable SQLite file, not in-memory).
        reopened = Store(db)
        persisted = reopened.get_run("run-1")
        assert persisted is not None
        assert persisted.approval_state == "APPROVED"
        assert persisted.approval_approver == "reviewer-a"

        # Re-validation clears the record atomically with the stage reset.
        persisted.stage = persisted.stage.__class__.COMPLETED
        reopened.update_run(persisted)
        reset = reopened.begin_revalidation("run-1")
        assert reset.approval_state == "PENDING"
        assert reset.approval_approver is None
        assert reset.approval_reason is None
        assert reset.approval_decided_at is None

    def test_store_rejects_invalid_approval_state(self, tmp_path):
        from api.errors import ApiError

        store = Store(tmp_path / "control.db")
        app_rec = store.add_application(
            ApplicationRecord(
                id="app-1",
                name="n",
                description="",
                workload_id="wl",
                java_entrypoint="Main",
            )
        )
        store.add_run(
            RunRecord(id="run-1", application_id=app_rec.id, workload_id="wl")
        )

        with pytest.raises((ApiError, ValueError)):
            store.set_run_approval(
                "run-1", state="PENDING", approver="x", reason=None
            )

    def test_existing_v4_database_migrates_with_runs_pending(self, tmp_path):
        """A pre-P4 database (schema v4, no approval columns) opens cleanly
        and every existing run reads back as PENDING."""
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE applications (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                workload_id TEXT NOT NULL DEFAULT '',
                java_entrypoint TEXT NOT NULL DEFAULT 'Main',
                target_runtime TEXT NOT NULL DEFAULT 'spring_boot',
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
            INSERT INTO applications (id, name, created_at)
                VALUES ('app-legacy', 'legacy', '2026-10-10T00:00:00+00:00');
            INSERT INTO runs (id, application_id, created_at)
                VALUES ('run-legacy', 'app-legacy', '2026-10-10T00:00:00+00:00');
            PRAGMA user_version = 4;
            """
        )
        conn.commit()
        conn.close()

        store = Store(db)

        legacy = store.get_run("run-legacy")
        assert legacy is not None
        assert legacy.approval_state == "PENDING"
        assert legacy.approval_approver is None

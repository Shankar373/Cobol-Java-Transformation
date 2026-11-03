"""Run summary endpoints must expose the verdict state (dashboard truth).

The dashboard's "Verified" stat previously counted every COMPLETED run
regardless of its verdict, so a run whose verdict was FAILED or UNPROVEN
was displayed as "Verified" — a capability-truth overclaim in the UI
(Master README §14/§60: never present unproven behaviour as proven).

The honest fix threads the persisted verdict state through
``RunResponse`` (additive, optional) using the same fail-closed
consistency rule ``GET /runs/{id}/detail`` already applies: the state is
served only when the verdict hash-matches its evidence manifest pair
(``Service._check_evidence_verdict_consistency``), and a VERIFIED
verdict without a persisted manifest is a ``PersistenceCorruptionError``.

Red-first: against the unmodified API the ``verdict_state`` key does not
exist on ``GET /runs/{id}`` or ``GET /applications/{id}/runs``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app
from api.models import RunStage
from api.service import Service
from api.store import ApplicationRecord, RunRecord, Store
from engine.domain.identities import VerdictState
from tests.common import make_stub_verdict

client = TestClient(app)


def _fresh_service(tmp_path):
    """Reset module-level singletons for isolation (test_api pattern)."""
    import api.app as app_mod
    import api.service as svc_mod

    store = Store(db_path=tmp_path / "verdict-state.db")
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    svc_mod._store = store
    svc_mod._service = svc
    return svc


def _seed_runs(svc) -> None:
    app_rec = ApplicationRecord(
        id="app-verdict-state",
        name="verdict-state",
        description="",
        workload_id="wl-verdict-state",
        java_entrypoint="Main",
    )
    svc._store.add_application(app_rec)

    # Completed run without any verdict (validation never produced one).
    svc._store.add_run(
        RunRecord(
            id="run-no-verdict",
            application_id=app_rec.id,
            workload_id=app_rec.workload_id,
            stage=RunStage.COMPLETED,
            completed_at="2024-01-01T00:01:00+00:00",
        )
    )
    # Completed run whose verdict is FAILED (non-certifying states may be
    # served without a manifest — see _check_evidence_verdict_consistency).
    svc._store.add_run(
        RunRecord(
            id="run-failed-verdict",
            application_id=app_rec.id,
            workload_id=app_rec.workload_id,
            stage=RunStage.COMPLETED,
            completed_at="2024-01-01T00:02:00+00:00",
            verdict=make_stub_verdict(
                "run-failed-verdict",
                app_rec.workload_id,
                state=VerdictState.FAILED,
            ),
        )
    )
    # In-flight run: no completed_at, no verdict.
    svc._store.add_run(
        RunRecord(
            id="run-in-flight",
            application_id=app_rec.id,
            workload_id=app_rec.workload_id,
            stage=RunStage.BUILDING,
        )
    )


class TestRunSummaryExposesVerdictState:
    def test_get_run_exposes_verdict_state(self, tmp_path):
        _seed_runs(_fresh_service(tmp_path))

        body = client.get("/runs/run-failed-verdict").json()
        assert body["verdict_state"] == "FAILED", body

        body = client.get("/runs/run-no-verdict").json()
        assert body["verdict_state"] is None, body

        body = client.get("/runs/run-in-flight").json()
        assert body["verdict_state"] is None, body

    def test_run_list_exposes_verdict_state_per_run(self, tmp_path):
        _seed_runs(_fresh_service(tmp_path))

        resp = client.get("/applications/app-verdict-state/runs")
        assert resp.status_code == 200, resp.text
        by_id = {r["id"]: r for r in resp.json()}

        assert by_id["run-failed-verdict"]["verdict_state"] == "FAILED"
        assert by_id["run-no-verdict"]["verdict_state"] is None
        assert by_id["run-in-flight"]["verdict_state"] is None

    def test_verified_stat_requires_verified_verdict_not_mere_completion(
        self, tmp_path
    ):
        """The dashboard's verified count must not be the completed count.

        Mirrors the Dashboard filter (``verdict_state === 'VERIFIED'``):
        a COMPLETED run with a FAILED verdict must never be counted as
        verified, and a run without a verdict must never be counted.
        """
        _seed_runs(_fresh_service(tmp_path))

        runs = client.get("/applications/app-verdict-state/runs").json()
        completed = [r for r in runs if r["stage"] == "COMPLETED"]
        verified = [r for r in runs if r["verdict_state"] == "VERIFIED"]

        assert len(completed) == 2  # run-no-verdict + run-failed-verdict
        assert verified == [], verified

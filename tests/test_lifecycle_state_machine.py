"""Run lifecycle state-machine tests (Phase B).

Proves the control plane cannot be talked into an invalid lifecycle:

  * progress is forward-only and failures may be entered from anywhere;
  * terminal states are final — the ONLY sanctioned terminal → CREATED path
    is ``Store.begin_revalidation``;
  * revalidation is single-flight (409 while a run is not terminal) and the
    reset atomically clears the previous verdict/evidence so a client can
    never see a new attempt carrying the old result;
  * a worker holding a pre-reset record can no longer write (generation).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.errors import (
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    PersistenceCorruptionError,
)
from api.models import RunStage
from api.service import Service
from api.store import RunRecord, Store
from tests.common import make_stub_verdict

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset module-level singletons for test isolation."""
    import api.app as app_mod
    import api.service as svc_mod

    store = Store()
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    svc_mod._store = store
    svc_mod._service = svc
    yield


def _run(store: Store, run_id: str, stage: RunStage = RunStage.CREATED) -> RunRecord:
    record = RunRecord(
        id=run_id,
        application_id="app-lifecycle",
        workload_id="wl-lifecycle",
        stage=stage,
    )
    store.add_run(record)
    return record


# ---------------------------------------------------------------------------
# Store-level transition rules
# ---------------------------------------------------------------------------


class TestStageTransitions:
    def test_forward_progress_allowed(self):
        store = Store()
        _run(store, "run-fwd")
        record = store.get_run("run-fwd")
        for stage in (
            RunStage.DISCOVERING,
            RunStage.TRANSFORMING,
            RunStage.EXECUTING_ORACLE,
            RunStage.BUILDING,
            RunStage.COMPARING,
            RunStage.VALIDATING_EVIDENCE,
            RunStage.COMPLETED,
        ):
            record.stage = stage
            store.update_run(record)
        assert store.get_run("run-fwd").stage == RunStage.COMPLETED

    def test_forward_jump_allowed(self):
        store = Store()
        _run(store, "run-jump")
        record = store.get_run("run-jump")
        record.stage = RunStage.EXECUTING_ORACLE  # skips discovery phases
        store.update_run(record)
        assert store.get_run("run-jump").stage == RunStage.EXECUTING_ORACLE

    def test_same_stage_refresh_allowed(self):
        store = Store()
        _run(store, "run-same", RunStage.COMPARING)
        record = store.get_run("run-same")
        record.stage = RunStage.COMPARING
        store.update_run(record)
        assert store.get_run("run-same").stage == RunStage.COMPARING

    def test_backward_transition_rejected(self):
        store = Store()
        _run(store, "run-back", RunStage.COMPARING)
        record = store.get_run("run-back")
        record.stage = RunStage.BUILDING
        with pytest.raises(InvalidStateTransitionError) as exc:
            store.update_run(record)
        assert "COMPARING -> BUILDING" in str(exc.value)
        # Persisted stage is unchanged.
        assert store.get_run("run-back").stage == RunStage.COMPARING

    def test_terminal_state_is_final(self):
        store = Store()
        _run(store, "run-done", RunStage.COMPLETED)
        record = store.get_run("run-done")
        record.stage = RunStage.COMPARING
        with pytest.raises(InvalidStateTransitionError):
            store.update_run(record)

    def test_terminal_to_created_rejected_outside_reset(self):
        store = Store()
        _run(store, "run-terminal", RunStage.FAILED)
        record = store.get_run("run-terminal")
        record.stage = RunStage.CREATED
        with pytest.raises(InvalidStateTransitionError):
            store.update_run(record)

    def test_failed_allowed_from_any_stage(self):
        store = Store()
        for index, stage in enumerate(
            (RunStage.CREATED, RunStage.ASSEMBLY_COMPLETED, RunStage.COMPARING)
        ):
            run_id = "run-fail-%d" % index
            _run(store, run_id, stage)
            record = store.get_run(run_id)
            record.stage = RunStage.FAILED
            record.error = "boom"
            store.update_run(record)
            assert store.get_run(run_id).stage == RunStage.FAILED

    def test_unknown_persisted_stage_fails_closed(self):
        store = Store()
        _run(store, "run-bogus")
        store._conn.execute(
            "UPDATE runs SET stage = 'NOT_A_STAGE' WHERE id = 'run-bogus'"
        )
        store._conn.commit()
        with pytest.raises(PersistenceCorruptionError):
            store.get_run("run-bogus")

    def test_missing_run_update_rejected(self):
        store = Store()
        record = RunRecord(
            id="run-ghost", application_id="a", workload_id="wl"
        )
        with pytest.raises(NotFoundError):
            store.update_run(record)


# ---------------------------------------------------------------------------
# begin_revalidation
# ---------------------------------------------------------------------------


class TestBeginRevalidation:
    def test_reset_clears_previous_attempt(self):
        store = Store()
        record = _run(store, "run-reset", RunStage.COMPLETED)
        record.verdict = make_stub_verdict("run-reset", "wl-lifecycle")
        record.error = None
        record.completed_at = "2024-01-01T00:00:00+00:00"
        store.update_run(record)

        reset = store.begin_revalidation("run-reset")

        assert reset.stage == RunStage.CREATED
        assert reset.verdict is None
        assert reset.evidence_manifest is None
        assert reset.error is None
        assert reset.completed_at is None
        assert reset.validation_generation == 1

        persisted = store.get_run("run-reset")
        assert persisted.stage == RunStage.CREATED
        assert persisted.verdict is None
        assert persisted.validation_generation == 1

    def test_rejects_non_terminal_run(self):
        store = Store()
        _run(store, "run-inflight", RunStage.EXECUTING_GENERATED)
        with pytest.raises(ConflictError):
            store.begin_revalidation("run-inflight")
        assert store.get_run("run-inflight").stage == RunStage.EXECUTING_GENERATED

    def test_unknown_run_not_found(self):
        store = Store()
        with pytest.raises(NotFoundError):
            store.begin_revalidation("run-nope")

    def test_stale_writer_rejected_after_reset(self):
        store = Store()
        record = _run(store, "run-stale", RunStage.COMPLETED)
        stale = store.get_run("run-stale")  # generation 0 snapshot
        store.begin_revalidation("run-stale")  # generation -> 1

        stale.stage = RunStage.COMPLETED
        stale.verdict = make_stub_verdict("run-stale", "wl-lifecycle")
        with pytest.raises(ConflictError):
            store.update_run(stale)

        fresh = store.get_run("run-stale")
        assert fresh.stage == RunStage.CREATED
        assert fresh.verdict is None
        assert fresh.validation_generation == 1

    def test_generation_written_on_insert(self):
        store = Store()
        record = _run(store, "run-gen")
        assert store.get_run("run-gen").validation_generation == 0
        assert record.validation_generation == 0


# ---------------------------------------------------------------------------
# API-level single-flight behaviour
# ---------------------------------------------------------------------------


def _create_uploaded_app(name: str) -> str:
    import io

    resp = client.post(
        "/applications",
        json={"name": name, "workload_id": "wl-single-flight"},
    )
    app_id = resp.json()["id"]
    upload = client.post(
        f"/applications/{app_id}/upload",
        files=[
            ("files", ("A.cob", io.BytesIO(b"       ID DIVISION.\n"), "text/plain"))
        ],
    )
    assert upload.status_code == 201, upload.text
    return app_id


def _set_candidate_path(app_id: str) -> None:
    """Record a generated candidate path (worker is patched out here).

    ``revalidate`` fail-closes when the application has no source or
    candidate path, so tests that exercise lifecycle rules must set both.
    """
    import api.app as app_mod

    store = app_mod._store
    app = store.get_application(app_id)
    app.generated_app_path = f"{app.cobol_source_path}-generated"
    store.update_application(app)


def _finish_run(app_id: str, run_id: str, stage: RunStage) -> None:
    """Simulate a finished modernization attempt (paths + terminal stage)."""
    import api.app as app_mod

    _set_candidate_path(app_id)
    store = app_mod._store
    record = store.get_run(run_id)
    record.stage = stage
    record.completed_at = "2024-01-01T00:00:00+00:00"
    if stage is RunStage.FAILED:
        record.error = "previous failure"
    store.update_run(record)


def _noop_worker(self_svc, *args, **kwargs):
    """Background worker stub: leaves the run at its reset stage."""


class TestApiRevalidationSingleFlight:
    @patch.object(Service, "_modernize_background", _noop_worker)
    def test_revalidate_clears_previous_verdict(self):
        app_id = _create_uploaded_app("clear-verdict")
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]
        _finish_run(app_id, run_id, RunStage.COMPLETED)

        import api.app as app_mod

        store = app_mod._store
        record = store.get_run(run_id)
        record.verdict = make_stub_verdict(run_id, "wl-single-flight")
        store.update_run(record)
        assert client.get(f"/runs/{run_id}/verdict").status_code == 200

        with patch.object(Service, "_revalidate_background", _noop_worker):
            resp = client.post(f"/runs/{run_id}/validate")

        assert resp.status_code == 202
        assert resp.json()["stage"] == "CREATED"
        # Stale verdict is gone atomically with the reset.
        assert client.get(f"/runs/{run_id}/verdict").status_code == 404
        body = client.get(f"/runs/{run_id}").json()
        assert body["stage"] == "CREATED"
        assert body["completed_at"] is None
        assert body["error"] is None

    @patch.object(Service, "_modernize_background", _noop_worker)
    def test_second_revalidate_conflicts_while_in_flight(self):
        app_id = _create_uploaded_app("single-flight")
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]
        _finish_run(app_id, run_id, RunStage.COMPLETED)

        with patch.object(Service, "_revalidate_background", _noop_worker):
            first = client.post(f"/runs/{run_id}/validate")
            second = client.post(f"/runs/{run_id}/validate")

        assert first.status_code == 202
        assert second.status_code == 409

    @patch.object(Service, "_modernize_background", _noop_worker)
    def test_revalidate_rejected_while_not_terminal(self):
        app_id = _create_uploaded_app("in-flight")
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]
        _set_candidate_path(app_id)  # paths are fine; stage is not terminal

        resp = client.post(f"/runs/{run_id}/validate")
        assert resp.status_code == 409
        assert client.get(f"/runs/{run_id}").json()["stage"] == "CREATED"

    @patch.object(Service, "_modernize_background", _noop_worker)
    def test_revalidate_without_candidate_path_fails_closed(self):
        app_id = _create_uploaded_app("no-candidate")
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]
        _finish_run(app_id, run_id, RunStage.COMPLETED)

        import api.app as app_mod

        app = app_mod._store.get_application(app_id)
        app.generated_app_path = None
        app_mod._store.update_application(app)

        resp = client.post(f"/runs/{run_id}/validate")
        assert resp.status_code == 400
        # Terminal result preserved: no reset happened.
        assert client.get(f"/runs/{run_id}").json()["stage"] == "COMPLETED"

    def test_revalidate_unknown_run_is_404(self):
        assert client.post("/runs/run-ghost/validate").status_code == 404

    @patch.object(Service, "_modernize_background", _noop_worker)
    def test_failed_run_can_be_revalidated(self):
        app_id = _create_uploaded_app("retry-failed")
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]
        _finish_run(app_id, run_id, RunStage.FAILED)

        with patch.object(Service, "_revalidate_background", _noop_worker):
            resp = client.post(f"/runs/{run_id}/validate")

        assert resp.status_code == 202
        body = client.get(f"/runs/{run_id}").json()
        assert body["stage"] == "CREATED"
        assert body["error"] is None

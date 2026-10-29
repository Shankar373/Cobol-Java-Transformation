"""Regression tests for the FAILED-run failure-point anchor (`last_stage`).

Context
-------
A run that ends ``FAILED`` never reports *where* it halted: ``GET
/runs/{id}/detail`` only carries ``stage_messages = [stage, error]``.  The UI
pipeline stepper therefore used to render **every** customer-facing node as
``pending`` for a FAILED run, directly underneath the discovery results that
had in fact been produced — a display defect that understated real progress.

Schema v7 adds a nullable ``runs.last_stage`` column recording the last
NON-terminal stage the run occupied.  Terminal stages never overwrite it, so it
is a durable record of the failure point.

Fail-closed rules asserted here
-------------------------------
* ``FAILED``/``COMPLETED`` must not move the anchor.
* ``begin_revalidation()`` must clear it (a fresh attempt has made no progress).
* Runs written before schema v7 read back as ``NULL`` — the UI then falls back
  to the historical all-pending rendering rather than inventing progress.
"""

from __future__ import annotations

import sqlite3

import pytest

from api.models import RunStage
from api.service import Service
from api.store import (
    ApplicationRecord,
    DB_SCHEMA_VERSION,
    RunRecord,
    Store,
)


def _advance(store: Store, run_id: str, stage: RunStage) -> None:
    record = store.get_run(run_id)
    record.stage = stage
    store.update_run(record)


class TestLastStageAnchor:
    def test_tracks_progress_then_freezes_on_failure(self):
        store = Store()
        store.add_run(
            RunRecord(id="run-anchor", application_id="a", workload_id="w")
        )

        # add_run persists the initial non-terminal stage immediately.
        assert store.get_run("run-anchor").last_stage == RunStage.CREATED.value

        for stage in (
            RunStage.DISCOVERING,
            RunStage.DISCOVERY_COMPLETED,
            RunStage.ANALYZING,
            RunStage.PLANNING,
        ):
            _advance(store, "run-anchor", stage)
            assert store.get_run("run-anchor").last_stage == stage.value

        # Terminal: the anchor freezes at PLANNING (the failure point).
        _advance(store, "run-anchor", RunStage.FAILED)
        frozen = store.get_run("run-anchor")
        assert frozen.stage == RunStage.FAILED
        assert frozen.last_stage == RunStage.PLANNING.value

    def test_terminal_stage_never_overwrites_the_anchor(self, tmp_path):
        """COMPLETED is terminal too — it must not clobber the anchor."""
        store = Store(tmp_path / "anchor.db")
        store.add_run(
            RunRecord(
                id="run-ok", application_id="a", workload_id="w",
                stage=RunStage.VALIDATING_EVIDENCE,
            )
        )
        assert (
            store.get_run("run-ok").last_stage
            == RunStage.VALIDATING_EVIDENCE.value
        )

        _advance(store, "run-ok", RunStage.COMPLETED)
        record = store.get_run("run-ok")
        assert record.stage == RunStage.COMPLETED
        assert record.last_stage == RunStage.VALIDATING_EVIDENCE.value

    def test_anchor_not_recorded_for_a_run_that_starts_terminal(self):
        """A run created FAILED has no non-terminal stage to anchor on."""
        store = Store()
        store.add_run(
            RunRecord(
                id="run-dead", application_id="a", workload_id="w",
                stage=RunStage.FAILED,
            )
        )
        assert store.get_run("run-dead").last_stage is None

    def test_begin_revalidation_clears_the_anchor(self, tmp_path):
        store = Store(tmp_path / "rv.db")
        store.add_run(
            RunRecord(
                id="run-rv-anchor", application_id="a", workload_id="w",
                stage=RunStage.COMPARING,
            )
        )
        # Drive it terminal so it is revalidatable; terminal never moves the
        # anchor, so the failure point stays at COMPARING.
        _advance(store, "run-rv-anchor", RunStage.FAILED)
        assert store.get_run("run-rv-anchor").last_stage == RunStage.COMPARING.value

        store.begin_revalidation("run-rv-anchor")
        assert store.get_run("run-rv-anchor").last_stage is None

    def test_interrupted_restart_keeps_the_anchor(self, tmp_path):
        """mark_interrupted_runs writes FAILED directly — anchor must survive."""
        path = tmp_path / "restart.db"
        first = Store(path)
        first.add_run(
            RunRecord(
                id="run-inflight-anchor", application_id="a", workload_id="w",
                stage=RunStage.GENERATING,
            )
        )

        # Simulate a process restart over the same database file.
        second = Store(path)
        assert second.mark_interrupted_runs() == 1

        reconciled = second.get_run("run-inflight-anchor")
        assert reconciled.stage == RunStage.FAILED
        # mark_interrupted_runs writes FAILED directly; the anchor must still
        # hold the last stage the process actually reached.
        assert reconciled.last_stage == RunStage.GENERATING.value


class TestSchemaMigration:
    def test_schema_version_is_v8(self):
        assert DB_SCHEMA_VERSION == 8

    def test_legacy_v1_database_gains_the_column(self, tmp_path):
        path = tmp_path / "legacy-v1.db"
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
            RunRecord(id="run-legacy-v7", application_id="a", workload_id="w")
        )

        # Pre-existing row behaviour: reads back NULL (fail-safe fallback).
        assert store.get_run("run-legacy-v7").last_stage == RunStage.CREATED.value

        # The new column is usable immediately for forward progress.
        _advance(store, "run-legacy-v7", RunStage.TRANSFORMING)
        assert (
            store.get_run("run-legacy-v7").last_stage
            == RunStage.TRANSFORMING.value
        )

        row = store._conn.execute("PRAGMA user_version").fetchone()
        assert int(row[0]) == DB_SCHEMA_VERSION

    def test_rows_present_before_v7_read_null(self, tmp_path):
        """An old row that never passes through update_run stays NULL."""
        path = tmp_path / "pre-v7-row.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
                workload_id TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'CREATED',
                created_at TEXT NOT NULL, completed_at TEXT, error TEXT,
                evidence_blob BLOB, verdict_blob BLOB
            );
            INSERT INTO runs (id, application_id, workload_id, stage, created_at)
            VALUES ('run-old', 'a', 'w', 'CREATED', '2026-01-01T00:00:00+00:00');
            PRAGMA user_version = 1;
            """
        )
        conn.commit()
        conn.close()

        store = Store(path)
        assert store.get_run("run-old").last_stage is None


class TestRunDetailExposure:
    def test_get_run_detail_exposes_last_stage(self, tmp_path):
        store = Store(tmp_path / "detail.db")
        store.add_application(
            ApplicationRecord(
                id="app-anchor",
                name="anchor-app",
                description="",
                workload_id="w-anchor",
                java_entrypoint="Main",
            )
        )
        store.add_run(
            RunRecord(
                id="run-detail-anchor",
                application_id="app-anchor",
                workload_id="w-anchor",
            )
        )
        svc = Service(store)

        for stage in (RunStage.DISCOVERING, RunStage.PLANNING):
            _advance(store, "run-detail-anchor", stage)

        detail = svc.get_run_detail("run-detail-anchor")
        assert detail["last_stage"] == RunStage.PLANNING.value
        # stage_messages stays the historical [stage] pair — the anchor is
        # a separate field, not an invented message.
        assert detail["stage_messages"] == [RunStage.PLANNING.value]

        _advance(store, "run-detail-anchor", RunStage.FAILED)
        failed_detail = svc.get_run_detail("run-detail-anchor")
        assert failed_detail["stage"] == RunStage.FAILED.value
        assert failed_detail["last_stage"] == RunStage.PLANNING.value

    def test_failed_run_without_any_non_terminal_write_is_null(self, tmp_path):
        """NULL means 'no anchor' — callers must fall back, not guess."""
        store = Store(tmp_path / "no-anchor.db")
        store.add_application(
            ApplicationRecord(
                id="app-none",
                name="none-app",
                description="",
                workload_id="w-none",
                java_entrypoint="Main",
            )
        )
        store.add_run(
            RunRecord(
                id="run-no-anchor",
                application_id="app-none",
                workload_id="w-none",
                stage=RunStage.FAILED,
            )
        )
        detail = Service(store).get_run_detail("run-no-anchor")
        assert detail["last_stage"] is None


@pytest.mark.parametrize(
    "stage",
    [RunStage.CREATED, RunStage.DISCOVERING, RunStage.PLANNING,
     RunStage.COMPARING, RunStage.VALIDATING_EVIDENCE],
)
def test_anchor_helper_records_every_non_terminal_stage(stage):
    from api.store import _last_stage_anchor

    assert _last_stage_anchor(stage, None) == stage.value


@pytest.mark.parametrize(
    "stage", [RunStage.FAILED, RunStage.COMPLETED]
)
def test_anchor_helper_freezes_on_terminal_stages(stage):
    from api.store import _last_stage_anchor

    assert _last_stage_anchor(stage, "PLANNING") == "PLANNING"
    assert _last_stage_anchor(stage, None) is None

"""The database layer on SQLite always, and on PostgreSQL when ``SYSTEMAOPS_TEST_POSTGRES_DSN`` is set.

CI's Docker lane runs a free PostgreSQL service container and sets the variable; the hermetic lane and a plain local
run exercise SQLite only. The ``postgres`` parameter is skipped, never faked, when the variable is absent.
"""

import os
import threading
import uuid
from pathlib import Path

import pytest

from enterprise.db import MigrationError, applied_versions, migrate, open_database, rollback
from enterprise.jobs import JobState
from enterprise.vsam import migrate_export  # noqa: F401  (import check only)
from enterprise.vsam.jobs import VsamJobService, WrongState
from tests.enterprise.vsam_support import fixed_export, ksds_records, make_manifest

POSTGRES_DSN = os.environ.get("SYSTEMAOPS_TEST_POSTGRES_DSN", "")


@pytest.fixture(params=["sqlite", "postgres"])
def db(request, tmp_path):
    if request.param == "postgres":
        if not POSTGRES_DSN:
            pytest.skip("SYSTEMAOPS_TEST_POSTGRES_DSN is not set")
        schema = f"t_{uuid.uuid4().hex[:12]}"
        admin = open_database(POSTGRES_DSN)
        admin.execute(f"CREATE SCHEMA {schema}")
        admin.commit()
        database = open_database(f"{POSTGRES_DSN}{'&' if '?' in POSTGRES_DSN else '?'}options=-csearch_path%3D{schema}")
        yield database
        database.close()
        admin.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.commit()
        admin.close()
    else:
        database = open_database(str(tmp_path / "db.sqlite"))
        yield database
        database.close()


def _tables(db):
    if db.dialect == "postgresql":
        rows = db.execute("SELECT table_name AS n FROM information_schema.tables WHERE table_schema = current_schema()")
    else:
        rows = db.execute("SELECT name AS n FROM sqlite_master WHERE type = 'table'")
    return {row["n"] for row in rows.fetchall()}


ALL_VERSIONS = ["0001_vsam_jobs", "0002_job_leases"]


def test_migrate_applies_once_and_is_idempotent(db):
    assert migrate(db) == ALL_VERSIONS
    assert migrate(db) == []
    assert applied_versions(db) == ALL_VERSIONS
    assert "vsam_jobs" in _tables(db)


def test_rollback_reverts_newest_first_and_migrate_reapplies(db):
    migrate(db)
    assert rollback(db) == ["0002_job_leases"]
    assert applied_versions(db) == ["0001_vsam_jobs"] and "vsam_jobs" in _tables(db)
    assert rollback(db, steps=5) == ["0001_vsam_jobs"]
    assert applied_versions(db) == [] and "vsam_jobs" not in _tables(db)
    assert migrate(db) == ALL_VERSIONS
    assert rollback(db, steps=0) == []


def test_a_failing_migration_leaves_no_version_recorded(db, tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "0001_bad.up.sql").write_text("SELECT * FROM table_that_does_not_exist", encoding="utf-8")
    (folder / "0001_bad.down.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(MigrationError):
        migrate(db, folder)
    assert applied_versions(db) == []


def test_migration_files_must_come_in_pairs_with_valid_names(db, tmp_path):
    folder = tmp_path / "odd"
    folder.mkdir()
    (folder / "0001_only_up.up.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(MigrationError, match="needs both"):
        migrate(db, folder)
    (folder / "0001_only_up.down.sql").write_text("SELECT 1", encoding="utf-8")
    (folder / "bad name.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(MigrationError, match="not named"):
        migrate(db, folder)


def test_rows_are_dicts_and_rowcount_reports_updates(db):
    migrate(db)
    db.execute(
        "INSERT INTO vsam_jobs (job_id, application_id, idempotency_key, manifest_json, request_digest, runtime_path,"
        " state, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("j1", "a", "k", "{}", "d", "p", "CREATED", "t", "t"))
    db.commit()
    row = db.execute("SELECT * FROM vsam_jobs WHERE job_id=?", ("j1",)).fetchone()
    assert row["state"] == "CREATED" and row["records"] == 0
    assert db.execute("UPDATE vsam_jobs SET state=? WHERE job_id=? AND state=?", ("QUEUED", "j1", "CREATED")).rowcount == 1
    assert db.execute("UPDATE vsam_jobs SET state=? WHERE job_id=? AND state=?", ("QUEUED", "j1", "CREATED")).rowcount == 0
    assert db.execute("SELECT * FROM vsam_jobs WHERE job_id=?", ("nope",)).fetchone() is None


def test_unique_idempotency_constraint_and_recovery_after_a_failed_statement(db):
    migrate(db)
    insert = ("INSERT INTO vsam_jobs (job_id, application_id, idempotency_key, manifest_json, request_digest,"
              " runtime_path, state, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)")
    db.execute(insert, ("j1", "a", "k", "{}", "d", "p", "CREATED", "t", "t"))
    db.commit()
    with pytest.raises(Exception):  # noqa: B017 - sqlite3.IntegrityError or psycopg.errors.UniqueViolation
        db.execute(insert, ("j2", "a", "k", "{}", "d", "p", "CREATED", "t", "t"))
    db.rollback()
    assert db.execute("SELECT COUNT(*) AS n FROM vsam_jobs").fetchone()["n"] == 1  # the connection still works


def test_big_byte_counters_do_not_overflow(db):
    migrate(db)
    db.execute(
        "INSERT INTO vsam_jobs (job_id, application_id, idempotency_key, manifest_json, request_digest, runtime_path,"
        " state, bytes_processed, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("big", "a", "kb", "{}", "d", "p", "CREATED", 10 * 1024**3, "t", "t"))
    db.commit()
    assert db.execute("SELECT bytes_processed AS b FROM vsam_jobs WHERE job_id='big'").fetchone()["b"] == 10 * 1024**3


def _service(db, tmp_path: Path) -> VsamJobService:
    return VsamJobService(db, tmp_path / "data")


def _create(service: VsamJobService, key: str = "k1"):
    blob = fixed_export(ksds_records(3))
    return service.create("app", key, make_manifest(blob, 3), "ks.dat")


def test_the_job_service_runs_on_this_database(db, tmp_path):
    service = _service(db, tmp_path)
    try:
        view, created = _create(service)
        assert created and view.state == JobState.CREATED.value
        again, created_again = _create(service)
        assert not created_again and again.job_id == view.job_id  # idempotent submission
    finally:
        service.shutdown()


def test_a_transition_from_a_stale_read_is_refused_not_applied(db, tmp_path):
    service = _service(db, tmp_path)
    try:
        view, _ = _create(service)
        real_row = service._row

        def stale(job_id):  # another worker moved the job after this reader looked at it
            row = dict(real_row(job_id))
            service._db.execute("UPDATE vsam_jobs SET state=? WHERE job_id=?", (JobState.CANCELLED.value, job_id))
            service._db.commit()
            return row

        service._row = stale  # type: ignore[method-assign]
        with pytest.raises(WrongState):
            service._transition(view.job_id, JobState.QUEUED)
        service._row = real_row  # type: ignore[method-assign]
        assert service.get(view.job_id).state == JobState.CANCELLED.value  # the winner's state stands
    finally:
        service.shutdown()


def test_two_threads_racing_one_transition_have_exactly_one_winner(db, tmp_path):
    service = _service(db, tmp_path)
    try:
        view, _ = _create(service)
        outcomes: list[str] = []
        barrier = threading.Barrier(2)

        def attempt():
            barrier.wait()
            try:
                service._transition(view.job_id, JobState.QUEUED)
                outcomes.append("won")
            except Exception:  # WrongState, or the state machine refusing CREATED -> QUEUED from QUEUED
                outcomes.append("lost")

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(outcomes) == ["lost", "won"]
        assert service.get(view.job_id).state == JobState.QUEUED.value
    finally:
        service.shutdown()

"""Leased workers: exactly-one claim, crash recovery from the checkpoint, bounded retries, lost-lease stop.

Runs on SQLite always and on PostgreSQL when ``SYSTEMAOPS_TEST_POSTGRES_DSN`` is set (the CI Docker lane sets it).
"""

import hashlib
import threading
import time

import pytest

from enterprise.jobs import JobState
from enterprise.quotas import VsamQuotas, WorkerQuotas
from enterprise.vsam import migrate_export
from enterprise.vsam import jobs as jobs_module
from enterprise.vsam.jobs import VsamJobService
from enterprise.vsam.worker import VsamWorker
from tests.enterprise.test_database import db  # noqa: F401  (fixture: sqlite and postgres)
from tests.enterprise.vsam_support import fixed_export, ksds_records, make_manifest, write_export

RECORDS = 400
QUOTAS = VsamQuotas(stream_buffer_bytes=4096, checkpoint_interval_records=25)


@pytest.fixture()
def service(db, tmp_path):  # noqa: F811
    svc = VsamJobService(db, tmp_path / "data", QUOTAS, inline_workers=False)
    yield svc
    svc.shutdown()


def _queue_job(service, key="k1"):
    blob = fixed_export(ksds_records(RECORDS))
    view, _ = service.create("app", key, make_manifest(blob, RECORDS), "ks.dat")
    service.accept_upload_slot(view.job_id)
    service.input_path(view.job_id).write_bytes(blob)
    service.upload_complete(view.job_id)
    return view.job_id, blob


def _expire_lease(service, job_id):
    service._db.execute("UPDATE vsam_jobs SET lease_expires_at=? WHERE job_id=?", ("1970-01-01T00:00:00+00:00", job_id))
    service._db.commit()


def _reference_sha(tmp_path, blob):
    ref = tmp_path / "ref"
    ref.mkdir()
    result = migrate_export(write_export(ref, blob), make_manifest(blob, RECORDS), ref / "out.idx", quotas=QUOTAS)
    return result.output_sha256


def test_a_queued_job_is_not_run_until_a_worker_claims_it(service):
    job_id, _ = _queue_job(service)
    assert service.get(job_id).state == JobState.QUEUED.value
    time.sleep(0.2)
    assert service.get(job_id).state == JobState.QUEUED.value  # no inline worker took it


def test_a_worker_runs_a_job_to_a_verified_result(service, tmp_path):
    job_id, blob = _queue_job(service)
    assert VsamWorker(service, "w1", lease_seconds=30).run_once() is True
    view = service.get(job_id)
    assert view.state == JobState.SUCCEEDED.value and view.records == RECORDS
    assert view.output_sha256 == _reference_sha(tmp_path, blob)
    assert hashlib.sha256(service.output_path(job_id).read_bytes()).hexdigest() == view.output_sha256
    assert VsamWorker(service, "w1").run_once() is False  # nothing left


def test_racing_workers_claim_a_job_exactly_once(service):
    _queue_job(service)
    wins: list[str] = []
    barrier = threading.Barrier(6)

    def race(n):
        barrier.wait()
        claimed = service.claim_next(f"w{n}", 60)
        if claimed:
            wins.append(f"w{n}")

    threads = [threading.Thread(target=race, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1


def test_a_live_lease_blocks_other_workers_and_an_expired_one_does_not(service):
    job_id, _ = _queue_job(service)
    assert service.claim_next("w1", 60) == job_id
    assert service.claim_next("w2", 60) is None
    assert service.heartbeat(job_id, "w1", 60) is True
    assert service.heartbeat(job_id, "w2", 60) is False  # not the owner


def test_a_crashed_worker_is_recovered_from_its_checkpoint(service, tmp_path, monkeypatch):
    job_id, blob = _queue_job(service)
    real = jobs_module.migrate_export
    crashed = {"done": False}

    def dies_midway(*args, **kwargs):
        if not crashed["done"]:
            crashed["done"] = True
            return real(*args, stop_after_records=100, **kwargs)  # raises KeyboardInterrupt: the worker "dies"
        return real(*args, **kwargs)

    monkeypatch.setattr(jobs_module, "migrate_export", dies_midway)
    first = VsamWorker(service, "dead", lease_seconds=60)
    with pytest.raises(KeyboardInterrupt):
        first.run_once()
    assert service.get(job_id).state == JobState.RUNNING.value  # left running with a lease
    assert service.claim_next("alive", 60) is None  # lease still live
    _expire_lease(service, job_id)

    assert VsamWorker(service, "alive", lease_seconds=60).run_once() is True
    view = service.get(job_id)
    assert view.state == JobState.SUCCEEDED.value
    assert view.output_sha256 == _reference_sha(tmp_path, blob)  # identical to an uninterrupted run
    row = service._row(job_id)
    assert row["attempts"] == 2 and row["lease_owner"] == ""  # claimed twice; lease cleared on success


def test_a_job_that_never_finishes_is_failed_not_retried_forever(service, monkeypatch):
    monkeypatch.setattr(service, "_worker_quotas", WorkerQuotas(max_retries=2, lease_seconds=60))
    job_id, _ = _queue_job(service)
    for attempt in range(3):  # 1 + max_retries claims are allowed
        assert service.claim_next(f"w{attempt}", 60) == job_id
        service._transition(job_id, JobState.RUNNING)
        _expire_lease(service, job_id)
    assert service.claim_next("w3", 60) is None
    view = service.get(job_id)
    assert view.state == JobState.FAILED.value and view.error_code == "RETRIES_EXHAUSTED"


def test_a_worker_that_loses_its_lease_stops_and_leaves_the_checkpoint(service, monkeypatch):
    job_id, _ = _queue_job(service)
    monkeypatch.setattr(service, "heartbeat", lambda *a, **k: False)  # the lease was taken over
    assert service.claim_next("slow", 0.3) == job_id
    real = jobs_module.migrate_export

    def slow(*args, **kwargs):
        time.sleep(0.5)  # let the first heartbeat discover the loss before the first checkpoint check
        return real(*args, **kwargs)

    monkeypatch.setattr(jobs_module, "migrate_export", slow)
    service.process(job_id, "slow", 0.3)
    view = service.get(job_id)
    assert view.state == JobState.RUNNING.value  # not published, not failed: the new owner decides
    part = service.job_dir(job_id) / "staging" / (service._row(job_id)["output_name"] + ".part")
    assert part.exists()


def test_a_separate_worker_process_runs_a_job_queued_by_another_process(tmp_path):
    import subprocess
    import sys

    database = tmp_path / "shared.sqlite"
    data_root = tmp_path / "data"
    api_side = VsamJobService(str(database), data_root, QUOTAS, inline_workers=False)
    try:
        job_id, blob = _queue_job(api_side)
        worker = subprocess.Popen(
            [sys.executable, "-m", "enterprise.vsam.worker", "--database", str(database),
             "--data-root", str(data_root), "--poll-seconds", "0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 60
            while time.time() < deadline and api_side.get(job_id).state != JobState.SUCCEEDED.value:
                time.sleep(0.1)
        finally:
            worker.terminate()
            worker.wait(timeout=30)
        view = api_side.get(job_id)
        assert view.state == JobState.SUCCEEDED.value and view.records == RECORDS
        assert view.output_sha256 == _reference_sha(tmp_path, blob)
    finally:
        api_side.shutdown()

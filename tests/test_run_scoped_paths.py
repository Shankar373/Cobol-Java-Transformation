"""Audit F6/F7: a run keeps its own source, bundle and discovery snapshot.

Generated bundles were already per run (``pipeline-output-<run id>-...``),
but revalidation, approval, export and the run-detail view read the
*application's* latest paths. Revalidating an older run therefore
validated the newest bundle and wrote that verdict onto the older run, and
a re-ingest silently swapped the COBOL source under it (F7). The run-detail
endpoint re-ran full discovery of the current source on every 1.5 s poll
(F6). Runs now record their own paths and a discovery snapshot (schema 9).
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from api.models import RunStage
from api.service import Service, ServiceError
from api.store import ApplicationRecord, RunRecord, Store


@pytest.fixture()
def store(tmp_path):
    return Store(str(tmp_path / "runs.db"))


def _tree(root: Path, name: str, files: dict[str, str]) -> Path:
    path = root / name
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text, encoding="utf-8")
    return path


def _two_runs(store: Store, tmp_path: Path):
    """App whose latest paths belong to run B; run A has its own."""
    sfx = uuid.uuid4().hex[:8]
    src_a = _tree(tmp_path, "src-a", {"A.cob": "A"})
    src_b = _tree(tmp_path, "src-b", {"B.cob": "B"})
    run_a, run_b = f"run-a{sfx}", f"run-b{sfx}"
    bundle_a = _tree(tmp_path, f"pipeline-output-{run_a}-x", {"pom.xml": "a", "A.java": "a"})
    bundle_b = _tree(tmp_path, f"pipeline-output-{run_b}-y", {"pom.xml": "b", "B.java": "b"})
    app_id = f"app-{sfx}"
    store.add_application(ApplicationRecord( target_runtime="spring_boot",
        id=app_id, name=f"paths-{sfx}", workload_id="wl-paths", description="",
        java_entrypoint="", cobol_source_path=str(src_b),
        generated_app_path=str(bundle_b), generated_entrypoint="EntryB",
    ))
    store.add_run(RunRecord(
        id=run_a, application_id=app_id, workload_id="wl-paths",
        stage=RunStage.COMPLETED, source_path=str(src_a),
        generated_app_path=str(bundle_a), generated_entrypoint="EntryA",
        discovery_snapshot={"programs": ["A"]},
    ))
    store.add_run(RunRecord(
        id=run_b, application_id=app_id, workload_id="wl-paths",
        stage=RunStage.COMPLETED, source_path=str(src_b),
        generated_app_path=str(bundle_b), generated_entrypoint="EntryB",
    ))
    return app_id, run_a, run_b, src_a, bundle_a


def _synchronous(monkeypatch, captured: dict):
    def launch(self, target, args, *, name):
        try:
            getattr(self, target)(*args)
        finally:
            with self._jobs_lock:
                self._active_jobs -= 1

    def validation(self, app, run, java_dir, entrypoint, adapter):
        captured.update(java_dir=Path(java_dir), entrypoint=entrypoint,
                        source=self._run_source(run, app))

    monkeypatch.setattr(Service, "_launch", launch)
    monkeypatch.setattr(Service, "_run_validation", validation)


def test_revalidation_uses_the_runs_own_bundle_and_source(store, tmp_path, monkeypatch):
    _, run_a, _, src_a, bundle_a = _two_runs(store, tmp_path)
    captured: dict = {}
    _synchronous(monkeypatch, captured)
    Service(store).revalidate(run_a)
    assert captured["java_dir"] == bundle_a
    assert captured["entrypoint"] == "EntryA"
    assert captured["source"] == str(src_a)
    assert store.get_run(run_a).stage == RunStage.COMPLETED


def test_revalidation_refuses_a_run_whose_source_was_replaced(store, tmp_path):
    _, run_a, _, src_a, _ = _two_runs(store, tmp_path)
    for f in src_a.iterdir():
        f.unlink()
    src_a.rmdir()  # what a later re-ingest does to the old workspace
    with pytest.raises(ServiceError, match="replaced"):
        Service(store).revalidate(run_a)
    assert store.get_run(run_a).stage == RunStage.COMPLETED


def test_legacy_run_is_refused_when_the_latest_bundle_is_another_runs(store, tmp_path):
    app_id, _, _, _, _ = _two_runs(store, tmp_path)
    legacy = f"run-legacy{uuid.uuid4().hex[:6]}"
    store.add_run(RunRecord(
        id=legacy, application_id=app_id, workload_id="wl-paths",
        stage=RunStage.FAILED,
    ))
    with pytest.raises(ServiceError, match="predates"):
        Service(store).revalidate(legacy)


def test_approval_and_export_check_the_runs_own_bundle(store, tmp_path, monkeypatch):
    _, run_a, _, _, bundle_a = _two_runs(store, tmp_path)
    svc = Service(store)
    assert svc.run_generated_path(store.get_run(run_a)) == str(bundle_a)
    seen = []
    monkeypatch.setattr("api.service.verify_generated_seal", lambda path, seal: seen.append(path))
    monkeypatch.setattr(Service, "require_verified_evidence", lambda self, run, action: None)
    svc.set_run_approval(run_a, decision="APPROVED", approver="qa", reason=None)
    assert seen == [str(bundle_a)]


def test_run_detail_serves_the_snapshot_and_the_runs_files(store, tmp_path, monkeypatch):
    _, run_a, _, _, _ = _two_runs(store, tmp_path)

    def no_discovery(*args, **kwargs):
        raise AssertionError("discovery must not re-run on a detail poll")

    monkeypatch.setattr("api.ingestion.discover_application", no_discovery)
    detail = Service(store).get_run_detail(run_a)
    assert detail["discovery"] == {"programs": ["A"]}
    assert detail["generated_files"] == ["A.java", "pom.xml"]


def test_modernize_records_the_source_on_the_run(store, tmp_path, monkeypatch):
    sfx = uuid.uuid4().hex[:8]
    src = _tree(tmp_path, "src", {"P.cob": "P"})
    store.add_application(ApplicationRecord( target_runtime="spring_boot",
        id=f"app-{sfx}", name=f"m-{sfx}", workload_id="wl-m", description="",
        java_entrypoint="", cobol_source_path=str(src),
    ))
    monkeypatch.setattr(Service, "_launch", lambda self, target, args, *, name: None)
    monkeypatch.setattr("api.service.resolve_certification_contract", lambda *a, **k: None)
    run = Service(store).modernize(f"app-{sfx}")
    assert store.get_run(run.id).source_path == str(src)


def test_store_round_trip_generation_binding_and_reset(store, tmp_path):
    sfx = uuid.uuid4().hex[:8]
    store.add_application(ApplicationRecord( target_runtime="spring_boot",
        id=f"app-{sfx}", name=f"s-{sfx}", workload_id="wl", description="",
        java_entrypoint="",
    ))
    store.add_run(RunRecord(
        id=f"run-{sfx}", application_id=f"app-{sfx}", workload_id="wl",
        stage=RunStage.COMPLETED, source_path="/src",
    ))
    store.set_run_discovery(f"run-{sfx}", {"n": 1})
    store.set_run_generated(f"run-{sfx}", "/bundle", "Main", expected_generation=0)
    run = store.get_run(f"run-{sfx}")
    assert (run.source_path, run.generated_app_path, run.generated_entrypoint,
            run.discovery_snapshot) == ("/src", "/bundle", "Main", {"n": 1})
    from api.errors import ConflictError
    with pytest.raises(ConflictError):
        store.set_run_generated(f"run-{sfx}", "/other", "X", expected_generation=5)
    # A revalidation reset keeps the run's own paths and snapshot.
    store.begin_revalidation(f"run-{sfx}", certification_contract=None)
    run = store.get_run(f"run-{sfx}")
    assert (run.source_path, run.generated_app_path, run.discovery_snapshot) == (
        "/src", "/bundle", {"n": 1})


def test_v8_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    Store(str(path))  # creates the current schema
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    assert {"source_path", "generated_app_path", "generated_entrypoint",
            "discovery_json"} <= cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
    conn.close()

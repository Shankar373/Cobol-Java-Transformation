"""Optimistic concurrency for application updates (audit L.3.2).

``Store.update_application`` and ``Store.update_application_fields`` accept an
optional ``expected_version``.  When supplied, the write is conditional on the
stored ``version`` matching it: a stale caller gets ``ConflictError`` (HTTP 409)
instead of silently overwriting a concurrent writer's changes.  Every successful
write bumps ``version``.  Omitting ``expected_version`` keeps the legacy
behaviour (no version check) so existing callers and fixtures are unaffected.
"""

from __future__ import annotations

import sqlite3

import pytest

from api.errors import ConflictError, NotFoundError
from api.store import ApplicationRecord, Store


def _app(store: Store, app_id: str = "app-oc") -> ApplicationRecord:
    return store.add_application(
        ApplicationRecord(
            id=app_id,
            name="before",
            description="desc",
            workload_id="wl",
            java_entrypoint="MAIN",
        )
    )


class TestVersionColumn:
    def test_fresh_store_has_version_column(self) -> None:
        store = Store()
        cols = {r[1] for r in store._conn.execute(
            "PRAGMA table_info(applications)"
        ).fetchall()}
        assert "version" in cols

    def test_new_application_starts_at_version_zero(self) -> None:
        store = Store()
        rec = _app(store)
        assert rec.version == 0
        assert store.get_application("app-oc").version == 0

    def test_migration_adds_version_to_legacy_database(self, tmp_path) -> None:
        """A database created without the version column must migrate cleanly."""
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        # Minimal legacy schema: applications without 'version'.
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
            """
        )
        conn.execute(
            "INSERT INTO applications (id,name,workload_id,created_at) "
            "VALUES ('a','n','w','2020-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        store = Store(db_path=str(db))
        rec = store.get_application("a")
        assert rec is not None
        assert rec.version == 0
        cols = {r[1] for r in store._conn.execute(
            "PRAGMA table_info(applications)"
        ).fetchall()}
        assert "version" in cols


class TestOptimisticConcurrency:
    def test_version_increments_on_full_row_update(self) -> None:
        store = Store()
        _app(store)
        rec = store.get_application("app-oc")
        assert rec is not None
        rec.description = "changed"
        updated = store.update_application(rec)
        assert updated.version == 1
        assert store.get_application("app-oc").version == 1

    def test_version_increments_on_field_update(self) -> None:
        store = Store()
        _app(store)
        updated = store.update_application_fields("app-oc", name="renamed")
        assert updated.version == 1
        assert store.get_application("app-oc").name == "renamed"
        assert store.get_application("app-oc").version == 1

    def test_full_row_update_conflicts_on_stale_version(self) -> None:
        store = Store()
        _app(store)
        rec = store.get_application("app-oc")
        assert rec is not None

        # A concurrent writer bumps the version first.
        fresh = store.get_application("app-oc")
        assert fresh is not None
        fresh.name = "concurrent"
        store.update_application(fresh)
        assert store.get_application("app-oc").version == 1

        # The stale caller (expected_version=0) must not overwrite.
        rec.name = "stale-overwrite"
        with pytest.raises(ConflictError) as exc:
            store.update_application(rec, expected_version=0)
        assert exc.value.status_code == 409
        # Concurrent writer's change survives.
        assert store.get_application("app-oc").name == "concurrent"
        assert store.get_application("app-oc").version == 1

    def test_field_update_conflicts_on_stale_version(self) -> None:
        store = Store()
        _app(store)

        # Concurrent writer bumps version.
        store.update_application_fields("app-oc", name="concurrent")
        assert store.get_application("app-oc").version == 1

        # Stale caller (expected_version=0) must not overwrite.
        with pytest.raises(ConflictError) as exc:
            store.update_application_fields(
                "app-oc", name="stale", expected_version=0
            )
        assert exc.value.status_code == 409
        assert store.get_application("app-oc").name == "concurrent"

    def test_field_update_succeeds_with_matching_version(self) -> None:
        store = Store()
        _app(store)
        updated = store.update_application_fields(
            "app-oc", name="ok", expected_version=0
        )
        assert updated.name == "ok"
        assert updated.version == 1

    def test_conflict_distinguished_from_not_found(self) -> None:
        store = Store()
        # Unknown app → NotFoundError, not ConflictError.
        with pytest.raises(NotFoundError):
            store.update_application_fields(
                "ghost", name="x", expected_version=0
            )

    def test_no_version_check_when_expected_version_omitted(self) -> None:
        """Legacy callers (no expected_version) keep working without 409."""
        store = Store()
        _app(store)
        # Bump version via a first write.
        store.update_application_fields("app-oc", name="first")
        # A second write without expected_version succeeds even though
        # version changed in between.
        updated = store.update_application_fields("app-oc", name="second")
        assert updated.name == "second"
        assert updated.version == 2

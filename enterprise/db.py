"""Database access for the control plane: SQLite for local use, PostgreSQL for deployment.

Both backends expose the same small surface (``execute`` with ``?`` placeholders, ``commit``, ``rollback``, ``close``) and
return rows as plain dicts, so the services written against it run unchanged on either. Schema changes are versioned SQL
files in ``enterprise/migrations`` (``NNNN_name.up.sql`` and ``NNNN_name.down.sql``) applied by :func:`migrate` and
reverted by :func:`rollback`; applied versions are recorded in ``schema_migrations``.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(up|down)\.sql$")
_MIGRATION_LOCK_KEY = 7_203_117  # PostgreSQL advisory lock: one migrator at a time
_POSTGRES_PREFIXES = ("postgresql://", "postgres://")


class MigrationError(Exception):
    """A migration file is malformed, missing its rollback, or cannot be applied."""


class Rows(Protocol):
    rowcount: int

    def fetchone(self) -> dict[str, Any] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...


class Database(Protocol):
    dialect: str

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Rows: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class _SqliteRows:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        return None if row is None else dict(row)

    def fetchall(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._cursor.fetchall()]


class SqliteDatabase:
    dialect = "sqlite"

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")  # readers and one writer across processes
            self._conn.execute("PRAGMA busy_timeout=30000")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _SqliteRows:
        with self._lock:
            return _SqliteRows(self._conn.execute(sql, tuple(params)))

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            self._conn.rollback()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class PostgresDatabase:
    dialect = "postgresql"

    def __init__(self, dsn: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self._conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
        self._lock = threading.RLock()

    def execute(self, sql: str, params: Sequence[Any] = ()):
        with self._lock:
            try:
                return self._conn.execute(sql.replace("?", "%s"), tuple(params))
            except Exception:
                self._conn.rollback()  # a failed statement must not poison the next one
                raise

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            self._conn.rollback()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def open_database(target: str) -> Database:
    """``postgresql://...`` opens PostgreSQL; ``sqlite:///path``, a file path or ``:memory:`` opens SQLite."""
    if target.startswith(_POSTGRES_PREFIXES):
        return PostgresDatabase(target)
    if target.startswith("sqlite:///"):
        target = target[len("sqlite:///"):]
    return SqliteDatabase(target)


def _split(sql: str) -> list[str]:
    return [part.strip() for part in sql.split(";") if part.strip()]


def _discover(directory: Path) -> dict[str, dict[str, Path]]:
    found: dict[str, dict[str, Path]] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION.match(path.name)
        if match is None:
            raise MigrationError(f"{path.name} is not named NNNN_name.up.sql or NNNN_name.down.sql")
        version = f"{match.group(1)}_{match.group(2)}"
        found.setdefault(version, {})[match.group(3)] = path
    for version, files in found.items():
        if set(files) != {"up", "down"}:
            raise MigrationError(f"migration {version} needs both an .up.sql and a .down.sql")
    return found


def _ensure_table(db: Database) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    db.commit()


def applied_versions(db: Database) -> list[str]:
    _ensure_table(db)
    return [row["version"] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]


def _lock(db: Database) -> None:
    if db.dialect == "postgresql":  # released at commit or rollback
        db.execute("SELECT pg_advisory_xact_lock(?)", (_MIGRATION_LOCK_KEY,))


def migrate(db: Database, directory: Path | None = None) -> list[str]:
    """Apply every pending migration in order; returns the versions applied. Safe to run twice."""
    migrations = _discover(directory or MIGRATIONS_DIR)
    _ensure_table(db)
    applied_now: list[str] = []
    for version in sorted(migrations):
        _lock(db)
        done = {row["version"] for row in db.execute("SELECT version FROM schema_migrations").fetchall()}
        if version in done:
            db.rollback()
            continue
        try:
            for statement in _split(migrations[version]["up"].read_text(encoding="utf-8")):
                db.execute(statement)
            db.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            raise MigrationError(f"migration {version} failed: {exc}") from exc
        applied_now.append(version)
    return applied_now


def rollback(db: Database, steps: int = 1, directory: Path | None = None) -> list[str]:
    """Revert the newest ``steps`` migrations with their ``.down.sql``; returns the versions reverted."""
    migrations = _discover(directory or MIGRATIONS_DIR)
    reverted: list[str] = []
    for version in reversed(applied_versions(db)[-steps:] if steps > 0 else []):
        if version not in migrations:
            raise MigrationError(f"applied migration {version} has no file to roll back with")
        _lock(db)
        try:
            for statement in _split(migrations[version]["down"].read_text(encoding="utf-8")):
                db.execute(statement)
            db.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
            db.commit()
        except Exception as exc:
            db.rollback()
            raise MigrationError(f"rollback of {version} failed: {exc}") from exc
        reverted.append(version)
    return reverted

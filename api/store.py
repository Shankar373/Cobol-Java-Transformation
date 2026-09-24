"""SQLite-backed store for applications and runs.

MVP persistence without distributed infrastructure: no PostgreSQL, no Redis,
no Celery/Kafka, no external queues.

The public ``Store`` abstraction is unchanged (same method names and record
types) so engine and service code does not know about the storage
implementation. ``Store()`` with no arguments keeps the historical
in-memory behaviour (used by unit tests); ``Store(db_path)`` persists to a
SQLite file so applications and runs survive process restarts.

Only metadata is persisted. Binary generated artifacts stay on the
filesystem; the database keeps their stable paths
(``generated_app_path`` etc.). Evidence manifests and verdicts are
persisted as opaque blobs (pickle) because the engine types expose
``to_dict()`` but no ``from_dict()`` round-trip; they are rehydrated into
the identical in-memory objects on load.
"""

from __future__ import annotations

import json
import pickle
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from api.models import RunStage
from engine.evidence.models import EvidenceManifest
from engine.verdict.derivation import Verdict


@dataclass
class ApplicationRecord:
    """Internal application record."""
    id: str
    name: str
    description: str
    workload_id: str
    java_entrypoint: str
    cobol_source_path: str | None = None
    java_candidate_path: str | None = None
    # Discovery provenance: PROGRAM-IDs seen by ApplicationDiscovery.
    discovered_program_ids: tuple[str, ...] = field(default_factory=tuple)
    # Generation provenance: the artifact produced by ApplicationGenerator.
    # The download endpoint serves generated_app_path ONLY — an uploaded
    # candidate is never labelled or served as "generated".
    generated_app_path: str | None = None
    generated_entrypoint: str | None = None
    generated_program_ids: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class RunRecord:
    """Internal run record."""
    id: str
    application_id: str
    workload_id: str
    stage: RunStage = RunStage.CREATED
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None
    error: str | None = None
    evidence_manifest: EvidenceManifest | None = None
    verdict: Verdict | None = None
    modernization_report: dict | None = None


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    workload_id TEXT NOT NULL DEFAULT '',
    java_entrypoint TEXT NOT NULL DEFAULT 'Main',
    cobol_source_path TEXT,
    java_candidate_path TEXT,
    discovered_program_ids TEXT NOT NULL DEFAULT '[]',
    generated_app_path TEXT,
    generated_entrypoint TEXT,
    generated_program_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    workload_id TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT 'CREATED',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    evidence_blob BLOB,
    verdict_blob BLOB
);
CREATE INDEX IF NOT EXISTS idx_runs_application_id ON runs(application_id);
CREATE INDEX IF NOT EXISTS idx_applications_name ON applications(name);
"""


def _encode_str_tuple(values: tuple[str, ...]) -> str:
    return json.dumps(list(values or []))


def _decode_str_tuple(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return ()
    if not isinstance(items, list):
        return ()
    return tuple(str(v) for v in items)


def _dumps_blob(obj: object | None) -> bytes | None:
    if obj is None:
        return None
    return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)


def _loads_blob(raw: bytes | None) -> object | None:
    if raw is None:
        return None
    return pickle.loads(bytes(raw))


def _dumps_dict(obj: dict | None) -> bytes | None:
    """Serialize a dict (or None) to JSON bytes for SQLite BLOB storage."""
    if obj is None:
        return None
    return json.dumps(obj).encode("utf-8")


def _loads_dict(raw: bytes | None) -> dict | None:
    """Deserialize JSON bytes back to a dict (or None)."""
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError):
        return None


class Store:
    """Thread-safe store for MVP.

    ``db_path`` selects the backend: ``None`` (default) keeps the
    historical in-memory SQLite database scoped to this instance;
    a filesystem path persists across restarts. A single connection
    guarded by a reentrant lock serves background modernization threads.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._db_path = str(db_path) if db_path is not None else None
        if self._db_path is not None:
            parent = Path(self._db_path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False: guarded by self._lock instead.
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        else:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA_V1)
            self._migrate_v2()
            self._conn.commit()

    def _migrate_v2(self) -> None:
        """Add report_blob column to runs if missing (schema migration)."""
        cursor = self._conn.execute("PRAGMA table_info(runs)")
        columns = {row[1] for row in cursor.fetchall()}
        if "report_blob" not in columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN report_blob BLOB")

    # -- applications -------------------------------------------------------

    def add_application(self, record: ApplicationRecord) -> ApplicationRecord:
        with self._lock:
            self._conn.execute(
                "INSERT INTO applications (id, name, description, workload_id,"
                " java_entrypoint, cobol_source_path, java_candidate_path,"
                " discovered_program_ids, generated_app_path,"
                " generated_entrypoint, generated_program_ids, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._app_params(record),
            )
            self._conn.commit()
            return record

    def get_application(self, app_id: str) -> ApplicationRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM applications WHERE id = ?", (app_id,)
            ).fetchone()
            return self._app_from_row(row) if row is not None else None

    def list_applications(self) -> list[ApplicationRecord]:
        """Return all applications ordered by creation time."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM applications ORDER BY created_at, id"
            ).fetchall()
            return [self._app_from_row(r) for r in rows]

    def update_application(self, record: ApplicationRecord) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE applications SET name = ?, description = ?,"
                " workload_id = ?, java_entrypoint = ?,"
                " cobol_source_path = ?, java_candidate_path = ?,"
                " discovered_program_ids = ?, generated_app_path = ?,"
                " generated_entrypoint = ?, generated_program_ids = ?,"
                " created_at = ? WHERE id = ?",
                (
                    record.name,
                    record.description,
                    record.workload_id,
                    record.java_entrypoint,
                    record.cobol_source_path,
                    record.java_candidate_path,
                    _encode_str_tuple(record.discovered_program_ids),
                    record.generated_app_path,
                    record.generated_entrypoint,
                    _encode_str_tuple(record.generated_program_ids),
                    record.created_at,
                    record.id,
                ),
            )
            self._conn.commit()

    def find_application_by_name(self, name: str) -> ApplicationRecord | None:
        """Find an application by its exact name."""
        with self._lock:
            return self._find_application_by_name_unlocked(name)

    def unique_name(self, base_name: str) -> str:
        """Return a unique application name, appending -2, -3 etc. as needed."""
        with self._lock:
            if self._find_application_by_name_unlocked(base_name) is None:
                return base_name
            n = 2
            while self._find_application_by_name_unlocked(f"{base_name}-{n}") is not None:
                n += 1
            return f"{base_name}-{n}"

    def _find_application_by_name_unlocked(self, name: str) -> ApplicationRecord | None:
        """Find by name without acquiring the lock (caller must hold it)."""
        row = self._conn.execute(
            "SELECT * FROM applications WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        return self._app_from_row(row) if row is not None else None

    # -- runs ---------------------------------------------------------------

    def add_run(self, record: RunRecord) -> RunRecord:
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (id, application_id, workload_id, stage,"
                " created_at, completed_at, error, evidence_blob, verdict_blob,"
                " report_blob)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._run_params(record),
            )
            self._conn.commit()
            return record

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            return self._run_from_row(row) if row is not None else None

    def list_runs_for_application(self, app_id: str) -> list[RunRecord]:
        """Return all runs for an application ordered by creation time."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs WHERE application_id = ?"
                " ORDER BY created_at, id",
                (app_id,),
            ).fetchall()
            return [self._run_from_row(r) for r in rows]

    def update_run(self, record: RunRecord) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET application_id = ?, workload_id = ?,"
                " stage = ?, created_at = ?, completed_at = ?, error = ?,"
                " evidence_blob = ?, verdict_blob = ?, report_blob = ? WHERE id = ?",
                (
                    record.application_id,
                    record.workload_id,
                    record.stage.value
                    if isinstance(record.stage, RunStage)
                    else str(record.stage),
                    record.created_at,
                    record.completed_at,
                    record.error,
                    _dumps_blob(record.evidence_manifest),
                    _dumps_blob(record.verdict),
                    _dumps_dict(record.modernization_report),
                    record.id,
                ),
            )
            self._conn.commit()

    # -- row mapping ----------------------------------------------------------

    @staticmethod
    def _app_params(record: ApplicationRecord) -> tuple:
        return (
            record.id,
            record.name,
            record.description,
            record.workload_id,
            record.java_entrypoint,
            record.cobol_source_path,
            record.java_candidate_path,
            _encode_str_tuple(record.discovered_program_ids),
            record.generated_app_path,
            record.generated_entrypoint,
            _encode_str_tuple(record.generated_program_ids),
            record.created_at,
        )

    @staticmethod
    def _app_from_row(row: sqlite3.Row) -> ApplicationRecord:
        return ApplicationRecord(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            workload_id=row["workload_id"] or "",
            java_entrypoint=row["java_entrypoint"] or "Main",
            cobol_source_path=row["cobol_source_path"],
            java_candidate_path=row["java_candidate_path"],
            discovered_program_ids=_decode_str_tuple(
                row["discovered_program_ids"]
            ),
            generated_app_path=row["generated_app_path"],
            generated_entrypoint=row["generated_entrypoint"],
            generated_program_ids=_decode_str_tuple(
                row["generated_program_ids"]
            ),
            created_at=row["created_at"],
        )

    @staticmethod
    def _run_params(record: RunRecord) -> tuple:
        return (
            record.id,
            record.application_id,
            record.workload_id,
            record.stage.value
            if isinstance(record.stage, RunStage)
            else str(record.stage),
            record.created_at,
            record.completed_at,
            record.error,
            _dumps_blob(record.evidence_manifest),
            _dumps_blob(record.verdict),
            _dumps_dict(record.modernization_report),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRecord:
        try:
            stage = RunStage(row["stage"])
        except ValueError:
            stage = RunStage.CREATED
        return RunRecord(
            id=row["id"],
            application_id=row["application_id"],
            workload_id=row["workload_id"] or "",
            stage=stage,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            evidence_manifest=_loads_blob(row["evidence_blob"]),  # type: ignore[arg-type]
            verdict=_loads_blob(row["verdict_blob"]),  # type: ignore[arg-type]
            modernization_report=_loads_dict(row["report_blob"]),  # type: ignore[arg-type]
        )

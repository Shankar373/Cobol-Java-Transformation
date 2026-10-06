"""SQLite-backed store for applications and runs.

MVP persistence without distributed infrastructure: no PostgreSQL, no Redis,
no Celery/Kafka, no external queues.

The public ``Store`` abstraction is unchanged (same method names and record
types) so engine and service code does not know about the storage
implementation. ``Store()`` with no argument keeps the historical in-memory
SQLite database scoped to this instance; ``Store(db_path)`` persists to a
SQLite file so applications and runs survive process restarts.

Only metadata is persisted. Binary generated artifacts stay on the
filesystem; the database keeps their stable paths (``generated_app_path``
etc.). Evidence manifests, verdicts and modernization reports are persisted
as **versioned JSON documents** produced by :mod:`api.serialization` — never
pickle. Every decode validates the envelope, schema version, field types and
the Phase A evidence seal; malformed, truncated, legacy-pickle or
unsupported-version payloads raise :class:`PersistenceCorruptionError`
(fail closed instead of fabricating ``CREATED``/``None``/``()``).

Lifecycle integrity is enforced here:

* run stage transitions must respect the declared state machine
  (forward-only, any stage to ``FAILED``, terminal states are final);
* the only sanctioned terminal → ``CREATED`` path is
  :meth:`Store.begin_revalidation`, which atomically clears evidence and
  verdict and increments ``validation_generation``;
* writes carrying a stale ``validation_generation`` (a background worker
  from before a revalidation reset) are rejected with ``ConflictError``.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from api import serialization
from api.errors import (
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    PersistenceCorruptionError,
    UnsupportedSchemaError,
)
from api.models import RunStage
from engine.evidence.models import EvidenceManifest
from engine.verdict.derivation import Verdict

# ---------------------------------------------------------------------------
# Lifecycle state machine
# ---------------------------------------------------------------------------

#: Canonical forward lifecycle order. Matches the order emitted by
#: ``VerticalSlicePipeline.run()`` (oracle before build) and the frontend
#: contract in ``frontend/src/api/stages.ts``.
STAGE_ORDER: tuple[RunStage, ...] = (
    RunStage.CREATED,
    RunStage.INGESTING,
    RunStage.DISCOVERING,
    RunStage.DISCOVERY_COMPLETED,
    RunStage.ANALYZING,
    RunStage.ANALYSIS_COMPLETED,
    RunStage.PLANNING,
    RunStage.PLAN_COMPLETED,
    RunStage.TRANSFORMING,
    RunStage.GENERATING,
    RunStage.ASSEMBLING,
    RunStage.ASSEMBLY_COMPLETED,
    RunStage.EXECUTING_ORACLE,
    RunStage.BUILDING,
    RunStage.EXECUTING_GENERATED,
    RunStage.COMPARING,
    RunStage.VALIDATING_EVIDENCE,
    RunStage.COMPLETED,
)

_STAGE_INDEX: dict[RunStage, int] = {
    stage: index for index, stage in enumerate(STAGE_ORDER)
}
TERMINAL_STAGES: frozenset[RunStage] = frozenset(
    {RunStage.COMPLETED, RunStage.FAILED}
)


def _parse_stage(value: object, where: str) -> RunStage:
    """Parse a persisted stage value; unknown stages fail closed."""
    if isinstance(value, RunStage):
        return value
    if not isinstance(value, str):
        raise PersistenceCorruptionError(
            f"{where} must be a stage string, got {type(value).__name__}"
        )
    try:
        return RunStage(value)
    except ValueError:
        raise PersistenceCorruptionError(
            f"{where} contains unknown run stage {value!r}"
        ) from None


def is_valid_transition(current: RunStage, target: RunStage) -> bool:
    """Return True when ``current → target`` is a permitted transition.

    Rules:
      * same-stage refresh is always allowed (idempotent progress writes);
      * ``FAILED`` may be entered from any non-terminal stage;
      * ``COMPLETED`` may be entered from any non-terminal stage;
      * non-terminal progress is forward-only in :data:`STAGE_ORDER`
        (jumps over intermediate stages are allowed, regressions are not);
      * terminal states are final — only :meth:`Store.begin_revalidation`
        may move a terminal run back to ``CREATED``.
    """
    if current == target:
        return True
    if current in TERMINAL_STAGES:
        return False
    if target == RunStage.FAILED:
        return True
    if target == RunStage.COMPLETED:
        return True
    current_index = _STAGE_INDEX.get(current)
    target_index = _STAGE_INDEX.get(target)
    if current_index is None or target_index is None:
        # Unknown non-terminal stage value — refuse the transition.
        return False
    return target_index >= current_index


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


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
    # Monotonic counter for validation attempts on this run. Incremented by
    # begin_revalidation(); writes from a worker holding an older value are
    # rejected so a stale worker cannot overwrite a newer attempt.
    validation_generation: int = 0
    # Which certification contract the (re)validation used: the workload's
    # declared contract id or the explicit default fallback.
    certification_contract: str | None = None


#: Database schema version written by this code. Payload schema versions are
#: tracked separately in :mod:`api.serialization`.
DB_SCHEMA_VERSION = 3

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            self._check_schema_version()
            self._migrate()
            self._conn.execute(
                f"PRAGMA user_version = {DB_SCHEMA_VERSION}"
            )
            self._conn.commit()

    # -- schema -------------------------------------------------------------

    def _check_schema_version(self) -> None:
        """Reject databases written by a newer schema (fail closed)."""
        row = self._conn.execute("PRAGMA user_version").fetchone()
        version = int(row[0]) if row is not None else 0
        if version > DB_SCHEMA_VERSION:
            raise UnsupportedSchemaError(
                f"database schema version {version} is newer than supported "
                f"version {DB_SCHEMA_VERSION}"
            )

    def _migrate(self) -> None:
        """Apply additive migrations for pre-existing databases."""
        cursor = self._conn.execute("PRAGMA table_info(runs)")
        columns = {row[1] for row in cursor.fetchall()}
        if "report_blob" not in columns:          # migration 2
            self._conn.execute("ALTER TABLE runs ADD COLUMN report_blob BLOB")
            columns.add("report_blob")
        if "validation_generation" not in columns:  # migration 3
            self._conn.execute(
                "ALTER TABLE runs ADD COLUMN validation_generation"
                " INTEGER NOT NULL DEFAULT 0"
            )
        if "certification_contract" not in columns:  # migration 3
            self._conn.execute(
                "ALTER TABLE runs ADD COLUMN certification_contract TEXT"
            )

    # -- applications -------------------------------------------------------

    def add_application(self, record: ApplicationRecord) -> ApplicationRecord:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO applications (id, name, description,"
                    " workload_id, java_entrypoint, cobol_source_path,"
                    " java_candidate_path, discovered_program_ids,"
                    " generated_app_path, generated_entrypoint,"
                    " generated_program_ids, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._app_params(record),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(
                    f"Application {record.id!r} already exists"
                ) from exc
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
            cursor = self._conn.execute(
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
                    serialization.encode_str_list(record.discovered_program_ids),
                    record.generated_app_path,
                    record.generated_entrypoint,
                    serialization.encode_str_list(record.generated_program_ids),
                    record.created_at,
                    record.id,
                ),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(f"Application {record.id!r} not found")
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
            stage = _parse_stage(record.stage, "run stage")
            try:
                self._conn.execute(
                    "INSERT INTO runs (id, application_id, workload_id,"
                    " stage, created_at, completed_at, error, evidence_blob,"
                    " verdict_blob, report_blob, validation_generation,"
                    " certification_contract)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._run_params(record, stage),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"Run {record.id!r} already exists") from exc
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

    def update_run(self, record: RunRecord, *, allow_reset: bool = False) -> None:
        """Persist a run record after validating its lifecycle transition.

        The database stage is the source of truth: the transition is checked
        against the *persisted* stage, so a worker holding a stale copy
        cannot roll a run backwards. ``allow_reset`` is reserved for the
        sanctioned terminal → ``CREATED`` reset performed by
        :meth:`begin_revalidation`.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT stage, validation_generation FROM runs WHERE id = ?",
                (record.id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Run {record.id!r} not found")

            current_stage = _parse_stage(row["stage"], "persisted run stage")
            target_stage = _parse_stage(record.stage, "run stage")

            stored_generation = int(row["validation_generation"] or 0)
            if int(record.validation_generation) != stored_generation:
                raise ConflictError(
                    f"Run {record.id!r} was reset by a newer validation"
                    " attempt; discarding stale update"
                )

            if not allow_reset and not is_valid_transition(
                current_stage, target_stage
            ):
                raise InvalidStateTransitionError(
                    f"invalid run state transition"
                    f" {current_stage.value} -> {target_stage.value}"
                )

            cursor = self._conn.execute(
                "UPDATE runs SET application_id = ?, workload_id = ?,"
                " stage = ?, created_at = ?, completed_at = ?, error = ?,"
                " evidence_blob = ?, verdict_blob = ?, report_blob = ?,"
                " validation_generation = ?, certification_contract = ?"
                " WHERE id = ?",
                # _run_params starts with the run id (used by INSERT);
                # the UPDATE binds the remaining columns then the id.
                self._run_params(record, target_stage)[1:] + (record.id,),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(f"Run {record.id!r} not found")
            self._conn.commit()

    def begin_revalidation(
        self,
        run_id: str,
        *,
        certification_contract: str | None = None,
    ) -> RunRecord:
        """Atomically reset a TERMINAL run for a new validation attempt.

        Clears the stale evidence manifest, verdict and error together with
        the stage change so a client can never observe a new ``CREATED``
        run carrying the previous attempt's verdict (consistent snapshot).
        Increments ``validation_generation`` so in-flight workers from the
        previous attempt can no longer write.

        Raises :class:`ConflictError` when the run is not terminal (the
        single-flight guard) and :class:`NotFoundError` when unknown.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Run {run_id!r} not found")

            current_stage = _parse_stage(row["stage"], "persisted run stage")
            if current_stage not in TERMINAL_STAGES:
                raise ConflictError(
                    f"Run {run_id!r} is not revalidatable: stage"
                    f" {current_stage.value} (only terminal runs are)"
                )

            generation = int(row["validation_generation"] or 0) + 1
            self._conn.execute(
                "UPDATE runs SET stage = ?, completed_at = NULL,"
                " error = NULL, evidence_blob = NULL, verdict_blob = NULL,"
                " validation_generation = ?, certification_contract = ?"
                " WHERE id = ?",
                (
                    RunStage.CREATED.value,
                    generation,
                    certification_contract,
                    run_id,
                ),
            )
            self._conn.commit()
            refreshed = self._conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            assert refreshed is not None  # updated above under the lock
            return self._run_from_row(refreshed)

    def mark_interrupted_runs(self) -> int:
        """Fail runs left non-terminal by a crash/restart. Returns the count.

        A daemon worker dies with the process, so any run still in a
        non-terminal stage at startup has no worker that can finish it.
        Leaving it frozen would make clients poll forever.
        """
        with self._lock:
            placeholders = ", ".join("?" for _ in TERMINAL_STAGES)
            rows = self._conn.execute(
                f"SELECT id FROM runs WHERE stage NOT IN ({placeholders})",
                tuple(stage.value for stage in TERMINAL_STAGES),
            ).fetchall()
            if not rows:
                return 0
            now = _utc_now()
            message = "Interrupted by process restart before completion"
            self._conn.executemany(
                "UPDATE runs SET stage = ?, completed_at = ?, error = ?"
                " WHERE id = ?",
                [
                    (RunStage.FAILED.value, now, message, row["id"])
                    for row in rows
                ],
            )
            self._conn.commit()
            return len(rows)

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
            serialization.encode_str_list(record.discovered_program_ids),
            record.generated_app_path,
            record.generated_entrypoint,
            serialization.encode_str_list(record.generated_program_ids),
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
            discovered_program_ids=serialization.decode_str_list(
                row["discovered_program_ids"]
            ),
            generated_app_path=row["generated_app_path"],
            generated_entrypoint=row["generated_entrypoint"],
            generated_program_ids=serialization.decode_str_list(
                row["generated_program_ids"]
            ),
            created_at=row["created_at"],
        )

    @staticmethod
    def _run_params(record: RunRecord, stage: RunStage) -> tuple:
        return (
            record.id,
            record.application_id,
            record.workload_id,
            stage.value,
            record.created_at,
            record.completed_at,
            record.error,
            serialization.encode_evidence_manifest(record.evidence_manifest)
            if record.evidence_manifest is not None else None,
            serialization.encode_verdict(record.verdict)
            if record.verdict is not None else None,
            serialization.encode_report(record.modernization_report),
            int(record.validation_generation),
            record.certification_contract,
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRecord:
        stage = _parse_stage(row["stage"], "persisted run stage")
        generation = row["validation_generation"]
        return RunRecord(
            id=row["id"],
            application_id=row["application_id"],
            workload_id=row["workload_id"] or "",
            stage=stage,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            evidence_manifest=serialization.decode_evidence_manifest(
                row["evidence_blob"]
            ),
            verdict=serialization.decode_verdict(row["verdict_blob"]),
            modernization_report=serialization.decode_report(row["report_blob"]),
            validation_generation=(
                int(generation) if generation is not None else 0
            ),
            certification_contract=row["certification_contract"],
        )

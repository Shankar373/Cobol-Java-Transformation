"""Durable VSAM migration jobs: SQLite store plus a bounded background runner.

State changes go through ``enterprise.jobs.next_state`` so a job can only
reach SUCCEEDED via VALIDATING and PUBLISHING with complete evidence. A
refusal becomes REFUSED with a stable code, never a partial artifact.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from enterprise.contracts import VsamExportManifest, utcnow
from enterprise.jobs import CompletionEvidence, JobState, next_state
from enterprise.quotas import VsamQuotas, load_vsam_quotas, load_worker_quotas
from enterprise.vsam.errors import VsamRefusal
from enterprise.vsam.layout_check import check_manifest_against_cobol
from enterprise.vsam.migrate import migrate_export, validate_manifest

_LOG = logging.getLogger(__name__)
_RUNTIME_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SUFFIX = {"KSDS": ".idx", "RRDS": ".rel", "ESDS": ""}
_RESUMABLE = (JobState.QUEUED, JobState.RUNNING, JobState.RETRYING)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vsam_jobs (
    job_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    runtime_path TEXT NOT NULL,
    state TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    records INTEGER NOT NULL DEFAULT 0,
    bytes_processed INTEGER NOT NULL DEFAULT 0,
    output_name TEXT NOT NULL DEFAULT '',
    output_sha256 TEXT NOT NULL DEFAULT '',
    output_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (application_id, idempotency_key)
)
"""


@dataclass(frozen=True)
class JobView:
    job_id: str
    application_id: str
    state: str
    runtime_path: str
    output_name: str
    records: int
    bytes_processed: int
    dataset_bytes: int
    output_sha256: str
    output_bytes: int
    error_code: str
    error_message: str

    def as_dict(self) -> dict:
        return dict(vars(self))


class IdempotencyConflict(Exception):
    """The idempotency key was reused with a different request."""


class JobNotFound(Exception):
    pass


class WrongState(Exception):
    pass


def safe_runtime_path(raw: str) -> str:
    if not _RUNTIME_PATH.match(raw) or ".." in raw:
        raise VsamRefusal("INVALID_RUNTIME_PATH", "runtime path must be a plain file name")
    return raw


class VsamJobService:
    def __init__(self, db_path: str, data_root: Path, quotas: VsamQuotas | None = None) -> None:
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db.execute(_SCHEMA)
        self._db.commit()
        self._root = data_root
        self._root.mkdir(parents=True, exist_ok=True)
        self._quotas = quotas or load_vsam_quotas()
        self._pool = ThreadPoolExecutor(max_workers=load_worker_quotas().concurrency)
        self._uploading: set[str] = set()

    # -- paths -----------------------------------------------------------
    def job_dir(self, job_id: str) -> Path:
        return self._root / job_id

    def input_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "input.dat"

    def output_path(self, job_id: str) -> Path:
        row = self._row(job_id)
        return self.job_dir(job_id) / "published" / row["output_name"]

    # -- persistence -----------------------------------------------------
    def _row(self, job_id: str) -> sqlite3.Row:
        with self._lock:
            row = self._db.execute("SELECT * FROM vsam_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return row

    def _view(self, row: sqlite3.Row) -> JobView:
        manifest = VsamExportManifest.model_validate_json(row["manifest_json"])
        return JobView(
            job_id=row["job_id"], application_id=row["application_id"], state=row["state"],
            runtime_path=row["runtime_path"], output_name=row["output_name"],
            records=row["records"], bytes_processed=row["bytes_processed"],
            dataset_bytes=manifest.dataset_bytes, output_sha256=row["output_sha256"],
            output_bytes=row["output_bytes"], error_code=row["error_code"],
            error_message=row["error_message"],
        )

    def get(self, job_id: str) -> JobView:
        return self._view(self._row(job_id))

    def _update(self, job_id: str, **fields) -> None:
        fields["updated_at"] = utcnow().isoformat()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE vsam_jobs SET {cols} WHERE job_id=?", (*fields.values(), job_id))
            self._db.commit()

    def _transition(self, job_id: str, target: JobState, evidence: CompletionEvidence | None = None, **fields) -> None:
        with self._lock:
            current = JobState(self._row(job_id)["state"])
            self._update(job_id, state=next_state(current, target, evidence).value, **fields)

    # -- API operations --------------------------------------------------
    def create(self, application_id: str, idempotency_key: str,
               manifest: VsamExportManifest, runtime_path: str,
               cobol_source: str | None = None, cobol_file: str | None = None) -> tuple[JobView, bool]:
        """Create a job; returns ``(view, created)``. Same key + request is idempotent.

        With ``cobol_source`` the manifest is also validated against the
        program's SELECT/FD; a mismatch is a refusal, not a warning.
        """
        manifest_json = manifest.model_dump_json()
        digest = hashlib.sha256(json.dumps(
            [manifest_json, runtime_path, cobol_source, cobol_file]).encode()).hexdigest()
        with self._lock:
            existing = self._db.execute(
                "SELECT * FROM vsam_jobs WHERE application_id=? AND idempotency_key=?",
                (application_id, idempotency_key)).fetchone()
            if existing is not None:
                if existing["request_digest"] != digest:
                    raise IdempotencyConflict(idempotency_key)
                return self._view(existing), False
            job_id = uuid.uuid4().hex
            now = utcnow().isoformat()
            output_name = runtime_path + _SUFFIX[manifest.organization]
            self._db.execute(
                "INSERT INTO vsam_jobs (job_id, application_id, idempotency_key, manifest_json,"
                " request_digest, runtime_path, state, output_name, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (job_id, application_id, idempotency_key, manifest_json, digest, runtime_path,
                 JobState.CREATED.value, output_name, now, now))
            self._db.commit()
        try:
            validate_manifest(manifest, self._quotas)
            if cobol_source:
                check_manifest_against_cobol(cobol_source, manifest, runtime_path, cobol_file)
        except VsamRefusal as refusal:
            self._transition(job_id, JobState.REFUSED, error_code=refusal.code,
                             error_message=refusal.message)
        return self.get(job_id), True

    def accept_upload_slot(self, job_id: str) -> VsamExportManifest:
        """Reserve the one upload a CREATED job accepts."""
        with self._lock:
            row = self._row(job_id)
            if JobState(row["state"]) is not JobState.CREATED or job_id in self._uploading:
                raise WrongState(row["state"])
            self._uploading.add(job_id)
        self.job_dir(job_id).mkdir(parents=True, exist_ok=True)
        return VsamExportManifest.model_validate_json(row["manifest_json"])

    def upload_complete(self, job_id: str) -> None:
        self._transition(job_id, JobState.QUEUED)
        self._uploading.discard(job_id)
        self._pool.submit(self._run, job_id)

    def upload_aborted(self, job_id: str) -> None:
        """The client stopped sending: drop the partial input; the job stays CREATED."""
        self.input_path(job_id).unlink(missing_ok=True)
        self._uploading.discard(job_id)

    def upload_failed(self, job_id: str, code: str, message: str) -> None:
        self.input_path(job_id).unlink(missing_ok=True)
        self._uploading.discard(job_id)
        self._transition(job_id, JobState.REFUSED, error_code=code, error_message=message)

    def recover_interrupted(self) -> int:
        """Re-queue jobs a restart interrupted; migration resumes from its checkpoint."""
        with self._lock:
            rows = self._db.execute(
                "SELECT job_id, state FROM vsam_jobs WHERE state IN (?,?,?)",
                tuple(s.value for s in _RESUMABLE)).fetchall()
        count = 0
        for row in rows:
            if not self.input_path(row["job_id"]).exists():
                self._transition(row["job_id"], JobState.FAILED, error_code="INPUT_LOST",
                                 error_message="uploaded input is missing after restart")
                continue
            if JobState(row["state"]) is JobState.RUNNING:
                self._transition(row["job_id"], JobState.RETRYING)
            if JobState(self._row(row["job_id"])["state"]) is JobState.RETRYING:
                self._transition(row["job_id"], JobState.QUEUED)
            self._pool.submit(self._run, row["job_id"])
            count += 1
        return count

    # -- worker ----------------------------------------------------------
    def _run(self, job_id: str) -> None:
        row = self._row(job_id)
        manifest = VsamExportManifest.model_validate_json(row["manifest_json"])
        out = self.job_dir(job_id) / "staging" / row["output_name"]
        try:
            if JobState(row["state"]) is JobState.QUEUED:
                self._transition(job_id, JobState.RUNNING)
            result = migrate_export(self.input_path(job_id), manifest, out, quotas=self._quotas)
            self._transition(job_id, JobState.VALIDATING, records=result.records,
                             bytes_processed=result.input_bytes)
            if file_sha256(out) != result.output_sha256:
                raise VsamRefusal("OUTPUT_CHECKSUM_MISMATCH", "output changed after migration")
            self._transition(job_id, JobState.PUBLISHING)
            published = self.job_dir(job_id) / "published" / row["output_name"]
            published.parent.mkdir(parents=True, exist_ok=True)
            out.replace(published)
            evidence = CompletionEvidence(processed=True, validated=True,
                                          checksum_verified=True, published=published.exists())
            self._transition(job_id, JobState.SUCCEEDED, evidence,
                             output_sha256=result.output_sha256,
                             output_bytes=published.stat().st_size)
        except VsamRefusal as refusal:
            self._fail(job_id, JobState.REFUSED, refusal.code, refusal.message)
        except Exception:  # noqa: BLE001 - recorded, never published as success
            _LOG.exception("vsam job %s failed", job_id)
            self._fail(job_id, JobState.FAILED, "INTERNAL_ERROR", "migration failed; see server log")

    def _fail(self, job_id: str, state: JobState, code: str, message: str) -> None:
        try:
            self._transition(job_id, state, error_code=code, error_message=message)
        except Exception:  # noqa: BLE001
            _LOG.exception("could not record failure for %s", job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

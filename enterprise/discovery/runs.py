"""Durable discovery runs for the control plane: submit, track, read artefacts, re-verify.

A run is one :func:`discover.discover` call executed on a bounded worker pool.  Its record is a small JSON file written
atomically after every progress event, so a restart can tell finished runs from interrupted ones; the discovery
artefacts themselves live in the checkpoint store and are the only source of truth for results.  The wall-clock values
here (``created_at``, step times) belong to the run, never to the deterministic artefacts.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checkpoint import checkpoint_dir, verify_checkpoint
from .discover import DiscoveryRequest, DiscoveryResult, discover
from .errors import IngestionError
from .kg_store import KGStore
from .limits import DEFAULT_LIMITS, Limits
from .model import rmtree_force
from .remotegit import NetworkPolicy

__all__ = ["DiscoveryRunService", "RunRecord", "RunNotFound", "ARTEFACTS", "RUN_ID_RE"]

RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
#: ``artefact name -> (file, media type)`` readable through the service and the API.
ARTEFACTS: dict[str, tuple[str, str]] = {
    "report": ("discovery-report.json", "application/json"),
    "graph": ("dependency-graph.json", "application/json"),
    "inventory": ("file-inventory.json", "application/json"),
    "unresolved": ("unresolved-references.json", "application/json"),
    "summary": ("discovery-summary.md", "text/markdown"),
    "compatibility": ("compiler-compatibility.json", "application/json"),
    "applications": ("applications.json", "application/json"),
    "readiness": ("transformation-readiness.json", "application/json"),
    "blueprint": ("application-blueprint.json", "application/json"),
}
_TERMINAL = ("succeeded", "failed", "interrupted")
MAX_EXCERPT_FILE_BYTES = 8 * 1024 * 1024


class RunNotFound(Exception):
    """No run with that id."""


@dataclass
class RunRecord:
    run_id: str
    kind: str
    label: str
    state: str = "queued"
    created_at: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_id: str = ""
    gate_status: str = ""
    ready_for_transformation: bool = False
    summary: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in (
            "run_id", "kind", "label", "state", "created_at", "steps", "checkpoint_id", "gate_status",
            "ready_for_transformation", "summary", "error_code", "error_message")}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_label(label: str | None, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", (label or "").strip())[:80]
    return cleaned or fallback


class DiscoveryRunService:
    """Owns the store, the run records and the worker pool; thread-safe."""

    def __init__(self, root: Path, *, limits: Limits = DEFAULT_LIMITS, workers: int = 2,
                 network_policy: NetworkPolicy | None = None) -> None:
        self.root = Path(root)
        self.store = self.root / "store"
        self.runs_dir = self.root / "runs"
        self.uploads_dir = self.root / "uploads"
        for directory in (self.store, self.runs_dir, self.uploads_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._limits = limits
        self.limits = limits
        self._policy = network_policy or NetworkPolicy()
        self._lock = threading.Lock()
        self._records: dict[str, RunRecord] = {}
        #: Durable, queryable snapshots of every finished run's graph (Layer 3), through ``enterprise/db.py``.
        self.kg = KGStore(self.root / "kg.sqlite3")
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="discovery")
        self._recover()

    # -- persistence --------------------------------------------------------------------------------------------------
    def _path(self, run_id: str) -> Path:
        if not RUN_ID_RE.fullmatch(run_id):
            raise RunNotFound(run_id)
        return self.runs_dir / f"{run_id}.json"

    def _save(self, record: RunRecord) -> None:
        target = self._path(record.run_id)
        temporary = target.with_name(f".{record.run_id}.{secrets.token_hex(4)}.tmp")
        temporary.write_text(json.dumps(record.as_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)

    def _recover(self) -> None:
        """Runs that were queued or running when the process died are marked ``interrupted`` (never silently lost)."""
        for path in sorted(self.runs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                record = RunRecord(**{k: data[k] for k in RunRecord.__dataclass_fields__ if k in data})
            except (OSError, ValueError, TypeError):
                continue
            if record.state not in _TERMINAL:
                record.state, record.error_code = "interrupted", "RUN_INTERRUPTED"
                record.error_message = "the service stopped before this run finished; submit it again"
                self._save(record)
            self._records[record.run_id] = record
        for leftover in self.uploads_dir.glob("*"):
            if leftover.is_file():
                leftover.unlink(missing_ok=True)

    # -- submission ---------------------------------------------------------------------------------------------------
    def new_upload_path(self) -> tuple[str, Path]:
        """Reserve a run id and the file the API streams the uploaded archive into."""
        run_id = secrets.token_hex(16)
        return run_id, self.uploads_dir / f"{run_id}.zip"

    def submit_zip(self, run_id: str, archive: Path, label: str | None) -> RunRecord:
        record = RunRecord(run_id, "zip", _safe_label(label, "upload"), created_at=_utc_now())
        return self._start(record, DiscoveryRequest("zip", str(archive), label=record.label), cleanup=archive)

    def submit_git(self, url: str, ref: str | None, label: str | None) -> RunRecord:
        record = RunRecord(secrets.token_hex(16), "git", _safe_label(label, "git"), created_at=_utc_now())
        request = DiscoveryRequest("git", url, ref=ref or None, label=None, allow_ssh=False, network_policy=self._policy)
        return self._start(record, request, cleanup=None)

    def _start(self, record: RunRecord, request: DiscoveryRequest, cleanup: Path | None) -> RunRecord:
        with self._lock:
            self._records[record.run_id] = record
            self._save(record)
        self._pool.submit(self._run, record.run_id, request, cleanup)
        return record

    def _progress(self, run_id: str) -> Callable[[str, str, str], None]:
        def report(step: str, status: str, message: str) -> None:
            with self._lock:
                record = self._records[run_id]
                record.state = "running"
                record.steps = [s for s in record.steps if s["id"] != step] + [{"id": step, "status": status,
                                                                               "message": message[:200]}]
                self._save(record)
        return report

    def _run(self, run_id: str, request: DiscoveryRequest, cleanup: Path | None) -> None:
        try:
            result = discover(request, self.store, progress=self._progress(run_id), limits=self._limits)
            self._finish(run_id, result)
        except IngestionError as exc:
            self._fail(run_id, exc.code, exc.message)
        except Exception:  # noqa: BLE001 - nothing about an internal failure is safe to echo to a client
            self._fail(run_id, "INTERNAL_ERROR", "discovery failed unexpectedly; see the server log")
        finally:
            if cleanup is not None:
                cleanup.unlink(missing_ok=True)

    def _finish(self, run_id: str, result: DiscoveryResult) -> None:
        gate = result.report["completeness"]
        # The snapshot is written before the record says "succeeded": a run whose graph could not be stored has not
        # produced its durable, queryable output, so it is failed by the caller rather than reported as complete.
        graph_id = self._store_snapshot(result)
        with self._lock:
            record = self._records[run_id]
            record.state, record.checkpoint_id = "succeeded", result.checkpoint.checkpoint_id
            record.gate_status, record.ready_for_transformation = gate["status"], gate["ready_for_transformation"]
            record.summary = {**result.report["summary"], "graph": result.report["dependency_graph"]["edges"],
                              "graph_id": graph_id, "reused_checkpoint": result.reused}
            self._save(record)

    def _store_snapshot(self, result: DiscoveryResult) -> str:
        """Persist the run's graph document as rows keyed by ``graph_id``; returns that id."""
        path = result.outdir / result.outputs["graph"]
        return self.kg.save(json.loads(path.read_text(encoding="utf-8")))

    def _fail(self, run_id: str, code: str, message: str) -> None:
        with self._lock:
            record = self._records[run_id]
            record.state, record.error_code, record.error_message = "failed", code, message[:300]
            self._save(record)

    # -- reads ----------------------------------------------------------------------------------------------------------
    def register_result(self, result: DiscoveryResult, *, kind: str, label: str) -> RunRecord:
        """Record a discovery that ran inline (for example during ingest) as a finished run, so its report is browsable."""
        record = RunRecord(secrets.token_hex(16), kind, _safe_label(label, kind), created_at=_utc_now())
        with self._lock:
            self._records[record.run_id] = record
        self._finish(record.run_id, result)
        with self._lock:
            record.steps = [{"id": sid, "status": "completed", "message": ""} for sid, _ in
                            (("ingestion", ""), ("checkpoint", ""), ("scanning_inventory", ""), ("dependency_analysis", ""),
                             ("compiler_discovery", ""), ("report", ""))]
            self._save(record)
        return RunRecord(**record.as_dict())

    def get(self, run_id: str) -> RunRecord:
        with self._lock:
            record = self._records.get(run_id) if RUN_ID_RE.fullmatch(run_id) else None
            if record is None:
                raise RunNotFound(run_id)
            return RunRecord(**record.as_dict())

    def list(self) -> list[RunRecord]:
        with self._lock:
            return sorted((RunRecord(**r.as_dict()) for r in self._records.values()),
                          key=lambda r: (r.created_at, r.run_id), reverse=True)

    def artefact_path(self, run_id: str, name: str) -> tuple[Path, str]:
        record = self.get(run_id)
        if name not in ARTEFACTS or record.state != "succeeded":
            raise RunNotFound(run_id)
        filename, media = ARTEFACTS[name]
        path = self.store / "discoveries" / record.checkpoint_id / filename
        if not path.is_file():
            raise RunNotFound(run_id)
        return path, media

    def verify(self, run_id: str) -> dict[str, Any]:
        """Re-hash the run's checkpoint; the answer is the verification report, never a cached verdict."""
        record = self.get(run_id)
        if record.state != "succeeded":
            raise RunNotFound(run_id)
        report = verify_checkpoint(checkpoint_dir(self.store, record.checkpoint_id))
        return {"checkpoint_id": record.checkpoint_id, "digest_ok": report.digest_ok, "errors": list(report.errors),
                "extra": list(report.extra), "missing": list(report.missing), "modified": list(report.modified),
                "ok": report.ok}

    def source_excerpt(self, run_id: str, path: str, line: int, context: int) -> dict[str, Any]:
        """Source lines around ``line`` from the run's checkpoint; ``path`` must be an inventoried file (no traversal possible)."""
        record = self.get(run_id)
        if record.state != "succeeded":
            raise RunNotFound(run_id)
        checkpoint = checkpoint_dir(self.store, record.checkpoint_id)
        inventory = json.loads((self.store / "discoveries" / record.checkpoint_id / "file-inventory.json").read_text(encoding="utf-8"))
        known = {f["path"]: f for f in inventory["files"]}
        entry = known.get(path)
        if entry is None or entry["size"] > MAX_EXCERPT_FILE_BYTES:
            raise RunNotFound(run_id)
        data = (checkpoint / "source" / Path(*path.split("/"))).read_bytes()
        from .textio import decode_source

        decoded = decode_source(data)
        if decoded.binary:
            raise RunNotFound(run_id)
        lines = decoded.text.splitlines()
        if not 1 <= line <= max(len(lines), 1):
            raise RunNotFound(run_id)
        context = max(0, min(context, 100))
        first, last = max(1, line - context), min(len(lines), line + context)
        return {"encoding": decoded.encoding, "file": path, "first_line": first, "line": line, "total_lines": len(lines),
                "lines": [{"number": n, "text": lines[n - 1][:400]} for n in range(first, last + 1)],
                "class": entry["class"], "sha256": entry["sha256"]}

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)
        self.kg.close()  # release the snapshot database so the run root can be removed on Windows

    def purge(self) -> None:  # pragma: no cover - test helper
        self.shutdown()
        rmtree_force(self.root)

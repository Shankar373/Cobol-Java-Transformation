"""Discovery-backed readiness of an application's source tree, shared by every downstream modernization entry point.

``assess_workspace`` runs the complete discovery workflow (immutable checkpoint, inventory, dependency graph, open-source compiler
check) over a source directory and returns a small readiness record.  ``Service`` stores one record per source tree and re-uses it
until the tree changes (a cheap size/mtime fingerprint), so modernize and revalidate consult the same evidence that the ingest screen
showed.  A tree that cannot be assessed (limits, unreadable files) is ``BLOCKED`` with the reason, never silently ready.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.errors import IngestionError
from enterprise.discovery.readiness import describe_blockers

logger = logging.getLogger(__name__)

#: Public keys of a readiness record (the API never returns local paths).
PUBLIC_KEYS = ("status", "allowed", "blockers", "blocking_references", "unsupported_total", "unsupported", "compile_errors",
               "applications", "checkpoint_id", "source_digest", "discovery_run_id", "gate_status", "toolchain")


def fingerprint(workspace: Path) -> str:
    """Cheap change detector for a source tree: relative path, size and mtime of every file."""
    digest = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(f"{path.relative_to(workspace).as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8", "surrogatepass"))
    return digest.hexdigest()


def blocked_record(code: str, message: str) -> dict[str, Any]:
    """A readiness record for a tree discovery could not assess."""
    return {"allowed": False, "applications": [], "blocking_references": [], "blockers": [{"detail": message[:200], "id": f"discovery-failed:{code}"}],
            "checkpoint_id": "", "compile_errors": [], "discovery_run_id": "", "gate_status": "INCOMPLETE", "source_digest": "",
            "status": "BLOCKED", "toolchain": {}, "unsupported": [], "unsupported_total": 0}


def assess_workspace(workspace: Path, label: str) -> dict[str, Any]:
    """Run discovery over ``workspace`` and return its readiness record (``BLOCKED`` when discovery itself is refused)."""
    from api.discovery_routes import get_service

    service = get_service()
    try:
        result = discover(DiscoveryRequest("directory", str(workspace), label=label[:80]), service.store, limits=service.limits)
    except IngestionError as exc:
        logger.warning("readiness assessment refused (%s)", exc.code)
        return blocked_record(exc.code, exc.message)
    except Exception:  # noqa: BLE001 - an assessment failure must block, and must not leak internals
        logger.exception("readiness assessment failed")
        return blocked_record("INTERNAL_ERROR", "discovery failed unexpectedly")
    readiness = result.report["readiness"]
    run = service.register_result(result, kind="directory", label=label)
    tools = result.report["compatibility"]["backend"]
    record = {key: readiness.get(key) for key in ("status", "allowed", "blockers", "blocking_references", "unsupported_total", "unsupported",
                                                  "compile_errors", "applications")}
    record.update(checkpoint_id=result.checkpoint.checkpoint_id, source_digest=result.checkpoint.source_digest,
                  discovery_run_id=run.run_id, gate_status=result.report["completeness"]["status"],
                  toolchain={"backend": tools["kind"], "version": tools.get("version", "")})
    return record


def public(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in PUBLIC_KEYS}


def refusal_message(record: dict[str, Any]) -> str:
    return "Modernization is blocked until discovery is complete: " + describe_blockers(record)

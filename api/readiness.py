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
               "unverified_total", "unverified", "applications", "checkpoint_id", "source_digest", "discovery_run_id", "gate_status", "toolchain")


#: Bump when the readiness policy changes: stored records of an older policy are re-assessed.
POLICY_VERSION = "2"
_CHUNK = 1 << 20


def is_transient(record: dict[str, Any]) -> bool:
    """An unexpected discovery failure: never cached, so the next request assesses again."""
    return any(b.get("id") == "discovery-failed:INTERNAL_ERROR" for b in record.get("blockers", []))


def fingerprint(workspace: Path) -> str:
    """Change detector for a source tree: relative path and SHA-256 of the *content* of every file, the assessing toolchain setting and the
    policy version. Content, not size/mtime: an edit that keeps both (or restores the mtime) still invalidates a stored READY."""
    from enterprise.discovery.compilers import ToolchainConfig

    config = ToolchainConfig.from_environment()
    digest = hashlib.sha256(f"policy={POLICY_VERSION}\0backend={config.backend}\0image={config.image}\n".encode())
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            content = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(_CHUNK), b""):
                        content.update(chunk)
            except OSError:
                content.update(b"unreadable")
            digest.update(f"{path.relative_to(workspace).as_posix()}\0{content.hexdigest()}\n".encode("utf-8", "surrogatepass"))
    return digest.hexdigest()


def blocked_record(code: str, message: str) -> dict[str, Any]:
    """A readiness record for a tree discovery could not assess."""
    return {"allowed": False, "applications": [], "blocking_references": [], "blockers": [{"detail": message[:200], "id": f"discovery-failed:{code}"}],
            "checkpoint_id": "", "compile_errors": [], "discovery_run_id": "", "gate_status": "INCOMPLETE", "source_digest": "",
            "status": "BLOCKED", "toolchain": {}, "unsupported": [], "unsupported_total": 0, "unverified": [], "unverified_total": 0}


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
                                                  "compile_errors", "unverified_total", "unverified", "applications")}
    record.update(checkpoint_id=result.checkpoint.checkpoint_id, source_digest=result.checkpoint.source_digest,
                  discovery_run_id=run.run_id, gate_status=result.report["completeness"]["status"],
                  toolchain={"backend": tools["kind"], "version": tools.get("version", "")})
    return record


def public(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in PUBLIC_KEYS}


def refusal_message(record: dict[str, Any]) -> str:
    return "Modernization is blocked until discovery is complete: " + describe_blockers(record)

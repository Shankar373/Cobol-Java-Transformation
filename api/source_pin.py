"""Source pins (Stage 1 B2/B3): an ingested source tree is bound to the checkpoint and blueprint discovery sealed for it.

The pin records what the application consumes (``content_digest`` of the workspace tree), what discovery sealed (``checkpoint_id``,
``source_digest``) and the Application Blueprint it produced (``blueprint_id``), plus where the bytes came from (``origin_kind`` and
``origin_ref``: the SHA-256 of an uploaded ZIP, or the commit of a Git source).  Every consumer that passes the readiness gate then
verifies the pin instead of trusting a path: a workspace that changed, a checkpoint that no longer re-hashes, or a blueprint whose id no
longer verifies is refused, never silently re-assessed into a new identity.  Re-ingesting is the one way to change a source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api.errors import ConflictError, ReadinessError
from api.readiness import content_digest
from enterprise.discovery.blueprint import verify_blueprint
from enterprise.discovery.checkpoint import checkpoint_dir, verify_checkpoint

__all__ = ["build_pin", "enforce_pin", "load_blueprint", "UNPINNED"]

#: ``origin_kind`` of a pin created on first use for a source ingested before pins existed (trust on first use).
UNPINNED = "unpinned"
BLUEPRINT_FILE = "application-blueprint.json"


def build_pin(workspace: Path, record: dict[str, Any], *, origin_kind: str, origin_ref: str = "",
              origin_checkpoint_id: str = "") -> dict[str, Any]:
    """The pin of ``workspace`` as assessed by readiness ``record``."""
    return {
        "blueprint_id": str(record.get("blueprint_id") or ""), "checkpoint_id": str(record.get("checkpoint_id") or ""),
        "content_digest": content_digest(workspace), "origin_checkpoint_id": origin_checkpoint_id, "origin_kind": origin_kind,
        "origin_ref": origin_ref, "source_digest": str(record.get("source_digest") or ""),
    }


def load_blueprint(discovery_store: Path, pin: dict[str, Any]) -> dict[str, Any]:
    """The pinned blueprint document, verified; :class:`ConflictError` when it is missing, unreadable or not the pinned one."""
    checkpoint_id, blueprint_id = str(pin.get("checkpoint_id") or ""), str(pin.get("blueprint_id") or "")
    path = Path(discovery_store) / "discoveries" / checkpoint_id / BLUEPRINT_FILE
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConflictError("the application blueprint is missing or unreadable; re-ingest the application") from None
    identity = document.get("identity") if isinstance(document, dict) else None
    if (not verify_blueprint(document) or document.get("blueprint_id") != blueprint_id
            or not isinstance(identity, dict) or identity.get("checkpoint_id") != checkpoint_id):
        raise ConflictError("the application blueprint no longer verifies against its pin; re-ingest the application")
    return document


def enforce_pin(store: Any, discovery_store: Path, source_path: str, record: dict[str, Any]) -> None:
    """Refuse (:class:`ReadinessError`) unless ``source_path`` still equals its pin and the pinned checkpoint and blueprint verify.

    A source with no pin (ingested before pins) is pinned now from ``record``, the current readiness assessment.
    """
    workspace = Path(source_path)
    if not workspace.is_dir():
        return  # a missing tree is already a SOURCE_MISSING readiness blocker
    pin = store.get_pin(source_path)
    if pin is None:
        store.put_pin(source_path, build_pin(workspace, record, origin_kind=UNPINNED))
        return
    if content_digest(workspace) != pin["content_digest"]:
        raise ReadinessError(
            f"the source changed after it was ingested (checkpoint {pin.get('checkpoint_id') or 'none'}); re-ingest the application")
    checkpoint_id = str(pin.get("checkpoint_id") or "")
    if not checkpoint_id:
        return
    if not verify_checkpoint(checkpoint_dir(Path(discovery_store), checkpoint_id)).ok:
        raise ReadinessError(f"the discovery checkpoint {checkpoint_id} failed integrity verification; re-ingest the application")
    if pin.get("blueprint_id"):
        try:
            load_blueprint(discovery_store, pin)
        except ConflictError as exc:
            raise ReadinessError(str(exc)) from None

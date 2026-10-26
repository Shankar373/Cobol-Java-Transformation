"""Sealed hashes for generated application bundles.

P0 evidence-substitution protection
-----------------------------------
``GET /runs/{id}/download`` packages whatever currently sits under the
application's ``generated_app_path``.  Before this module existed,
nothing re-checked those bytes after the run completed: an actor with
write access to the staging volume could substitute the generated
sources between execution and export (or between execution and customer
approval), and the control plane would serve the substitution as if it
were the verified artifact.  The evidence-manifest seal covers the
in-memory evidence graph (``engine.evidence.integrity``) — not the
on-disk bundle that customers download.

This module closes that gap:

* :func:`compute_generated_seal` hashes every file of the bundle
  (chunked SHA-256, POSIX-relative keys) at generation time; the seal is
  persisted with the run record (``runs.generated_seal``) by
  ``Store.set_generated_seal``;
* :func:`verify_generated_seal` re-derives the seal and refuses — via
  ``ConflictError`` (HTTP 409) — on any difference: changed bytes,
  added files, removed files, missing seal, malformed seal, or an
  unsupported algorithm.

Enforcement points: the customer-approval decision (APPROVED only —
rejecting a run must always work) and the download export.  The trust
boundary is the control-plane store: an attacker who can rewrite the
database can rewrite the seal too, exactly like every other persisted
fact.  This protects the far more likely case of filesystem substitution
of the artifact after execution.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from api.errors import ConflictError, ServiceError

#: The only accepted hashing algorithm.  A seal declaring anything else
#: is refused (fail closed) rather than silently re-interpreted.
SEAL_ALGORITHM = "sha256"

_CHUNK_BYTES = 1024 * 1024


def _hash_file(path: Path) -> str:
    """SHA-256 of one file, streamed so large artifacts stay bounded."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compute_generated_seal(root: str | Path) -> str:
    """Return the sealed-hash JSON document for the bundle under ``root``.

    The document is deterministic for identical bytes (sorted keys,
    POSIX-relative paths) apart from its informational ``sealed_at``
    timestamp.  Raises ``ServiceError`` when the tree is missing or a
    file cannot be read — a bundle that cannot be sealed must never be
    exported as verified.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise ServiceError("Generated application bundle is not available")

    files: dict[str, str] = {}
    try:
        for path in sorted(p for p in root_path.rglob("*") if p.is_file()):
            files[path.relative_to(root_path).as_posix()] = _hash_file(path)
    except OSError as exc:
        raise ServiceError(
            "Generated application bundle could not be sealed (unreadable file)"
        ) from exc

    payload = {
        "algorithm": SEAL_ALGORITHM,
        "files": files,
        "sealed_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def verify_generated_seal(root: str | Path, seal_json: str | None) -> None:
    """Fail closed unless ``root`` matches its sealed evidence exactly.

    Raises ``ConflictError`` (409) for a missing/malformed seal or any
    mismatch, and ``ServiceError`` (400) when the current tree cannot be
    hashed at all — both refuse the operation.
    """
    if not seal_json:
        raise ConflictError(
            "Run has no sealed evidence for its generated application;"
            " re-validate the run before approval or export"
        )
    try:
        seal = json.loads(seal_json)
    except (TypeError, ValueError) as exc:
        raise ConflictError(
            "Sealed evidence for the generated application is malformed"
        ) from exc
    if not isinstance(seal, dict) or seal.get("algorithm") != SEAL_ALGORITHM:
        raise ConflictError(
            "Sealed evidence uses an unsupported hashing algorithm"
        )
    recorded = seal.get("files")
    if not isinstance(recorded, dict):
        raise ConflictError(
            "Sealed evidence for the generated application is malformed"
        )

    actual = json.loads(compute_generated_seal(root))["files"]
    if actual != recorded:
        differing = (
            set(recorded) ^ set(actual)
        ) | {
            key
            for key in set(recorded) & set(actual)
            if recorded[key] != actual[key]
        }
        raise ConflictError(
            "Generated application bundle does not match its sealed"
            f" evidence ({len(differing)} file(s) differ after execution);"
            " re-validate the run before approval or export"
        )

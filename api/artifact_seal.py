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
  (chunked SHA-256, POSIX-relative keys); the seal is persisted with the
  run record (``runs.generated_seal``) by ``Store.set_generated_seal``.
  The lifecycle seals twice: an interim seal at generation and the
  authoritative seal at the end of validation — the validation lane's
  build/execute writes into the bundle (e.g. ``target/*.jar``), so only
  the post-validation seal reflects the bytes a customer approves and
  downloads;
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
from typing import Any

from api.errors import ConflictError, PayloadTooLargeError, ServiceError

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


def _parse_seal_files(seal_json: str | None) -> dict[str, str]:
    """Validate the seal document and return its recorded file→hash map."""
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
    return {str(k): str(v) for k, v in recorded.items()}


def read_verified_bundle(
    root: str | Path,
    seal_json: str | None,
    *,
    max_files: int | None = None,
    max_bytes: int | None = None,
) -> dict[str, bytes]:
    """Read the bundle exactly once and verify *those* bytes against the seal.

    Returns ``{posix_relative_path: bytes}`` — the same buffers a caller
    packages for export — so there is no window between verification and
    packaging in which the filesystem can be swapped (verify-then-zip
    TOCTOU).  Caps are enforced while reading so memory stays bounded;
    exceeding either cap raises ``PayloadTooLargeError`` (HTTP 413), a
    seal mismatch raises ``ConflictError`` (409), and an unreadable
    bundle raises ``ServiceError`` (400).  Every failure refuses the
    operation — a bundle that cannot be read-and-verified is never
    returned for export.
    """
    recorded = _parse_seal_files(seal_json)
    root_path = Path(root)
    if not root_path.is_dir():
        raise ServiceError("Generated application bundle is not available")

    try:
        paths = sorted(p for p in root_path.rglob("*") if p.is_file())
    except OSError as exc:
        raise ServiceError(
            "Generated application bundle could not be sealed (unreadable file)"
        ) from exc

    if max_files is not None and len(paths) > max_files:
        raise PayloadTooLargeError(
            f"Generated application has {len(paths)} files,"
            f" exceeding the {max_files} file download limit"
        )

    bundle: dict[str, bytes] = {}
    total_bytes = 0
    try:
        for path in paths:
            data = path.read_bytes()
            total_bytes += len(data)
            if max_bytes is not None and total_bytes > max_bytes:
                raise PayloadTooLargeError(
                    f"Generated application exceeds the {max_bytes} byte"
                    " download limit"
                )
            bundle[path.relative_to(root_path).as_posix()] = data
    except OSError as exc:
        raise ServiceError(
            "Generated application bundle could not be sealed (unreadable file)"
        ) from exc

    actual = {
        key: hashlib.sha256(data).hexdigest()
        for key, data in bundle.items()
    }
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
    return bundle

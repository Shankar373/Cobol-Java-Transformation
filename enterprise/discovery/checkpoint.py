"""Immutable source checkpoint (Stage 1 design, section 3).

A checkpoint freezes the *already validated* staging tree of an ingestion run
into a content-addressed, read-only directory, before any analysis happens.
Everything downstream reads the checkpoint, never the staging area.

Layout (``<store>`` is chosen by the operator)::

    <store>/checkpoints/<CP-id>/
        checkpoint.json     written once, never modified
        source/             the preserved tree, bytes exactly as ingested
        original/input.zip  ZIP inputs only: the uploaded archive verbatim

Guarantees:

* **Content-derived id.**  ``CP-`` plus 32 hex of
  ``sha256(kind NUL commit NUL source_digest)``.  Same bytes, same id.
* **Idempotent.**  An existing checkpoint is verified and reused
  (``reused=True``); a checkpoint that fails verification is *never* reused
  and *never* overwritten (``CHECKPOINT_TAMPERED``).
* **Atomic.**  The tree is built in ``checkpoints/.<id>.tmp-<random>`` and
  published with ``os.replace``; any failure removes the temporary tree, so a
  half-written checkpoint is never visible.  Concurrent creators of the same
  id are safe: the loser verifies the winner's result and reuses it.
* **Byte-faithful.**  Files are streamed, re-hashed while copying and compared
  with the hashes recorded at ingestion (``CHECKPOINT_COPY_MISMATCH``).
  Symlinks and junctions are refused, never followed.
* **Read-only.**  Files are ``0o444`` (the read-only attribute on Windows);
  directories are ``0o555`` on POSIX.  Windows has no per-directory
  write protection, so on Windows tamper *detection* (``verify_checkpoint``)
  is the control for directories.
* **Deterministic.**  ``checkpoint.json`` has sorted keys, LF endings and no
  wall-clock time, and never contains an absolute path.

``checkpoint.json`` follows section 3.2 of the design and additionally lists
``directories`` (every preserved directory, empty ones included) so removal or
insertion of a directory is detectable.

Seal and threat model.  ``checkpoint.json`` carries ``seal_kind`` and ``seal``:
a digest over the canonical serialisation of the whole document minus ``seal``,
so ``origin``, ``ref``, ``tree_id``, ``commit_timestamp``, ``archive_sha256``,
the counts and the directory list are all bound.

* **Keyed** (``SYSTEMAOPS_STORE_KEY`` set): HMAC-SHA256, ``seal_kind`` is
  ``hmac-sha256``.  Tampering by anyone *without the key* is detected, even
  when they rewrite ``checkpoint.json`` and the tree consistently.  A verifier
  without the key reports "sealed with a key that is not configured"; a
  verifier *with* a key refuses an unkeyed seal, which blocks a downgrade
  (switching ``seal_kind`` and recomputing a plain hash).
* **Unkeyed** (no key): plain SHA-256, ``seal_kind`` is ``sha256``.  This
  detects accidental or partial tampering only; an attacker who can write the
  checkpoint can recompute the seal.  The key is never stored in the store.

Enabling a key later makes earlier unkeyed checkpoints fail verification
(re-ingest to recreate them).  Same input and same key mode give a
byte-identical ``checkpoint.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Iterable

from .checkpoint_core import (
    CHECKPOINT_FILE,
    KINDS,
    SEAL_HMAC,
    SEAL_SHA256,
    ORIGINAL_ARCHIVE,
    ORIGINAL_DIR,
    SCHEMA_VERSION,
    SOURCE_DIR,
    VerificationReport,
    _COMMIT_RE,
    _ID_RE,
    _IS_WINDOWS,
    _Meta,
    _MetadataError,
    _SHA256_RE,
    _TIMESTAMP_RE,
    _err,
    _is_plain,
    _is_safe_relative,
    compute_seal,
    compute_source_digest,
    find_collision,
    make_checkpoint_id,
    store_key,
    valid_text,
)
from .checkpoint_verify import _read_metadata, _verify, verify_checkpoint
from .errors import IngestionError
from .hashing import sha256_file
from .model import IngestedFile, IngestionResult, rmtree_force

__all__ = [
    "SCHEMA_VERSION",
    "CheckpointInfo",
    "VerificationReport",
    "compute_source_digest",
    "make_checkpoint_id",
    "checkpoint_dir",
    "create_checkpoint",
    "verify_checkpoint",
    "load_checkpoint",
    "list_checkpoints",
    "release",
]


_CHUNK = 1024 * 1024
_PUBLISH_ATTEMPTS = 5
#: Directory names never considered when looking for *empty* directories: the
#: pipeline excludes VCS metadata from the inventory, so its folders are not
#: part of the preserved source.
_VCS_DIRS = frozenset({".git"})


# ---------------------------------------------------------------------------
# Public value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckpointInfo:
    """Identity and provenance of one checkpoint.

    ``path``, ``source_root`` and ``reused`` are runtime facts: they are never
    serialised, so artefacts cannot leak the store location.
    """

    checkpoint_id: str
    source_kind: str
    origin: str
    ref: str
    commit: str
    tree_id: str
    commit_timestamp: str
    archive_sha256: str
    source_digest: str
    file_count: int
    directory_count: int
    total_bytes: int
    path: Path
    source_root: Path
    reused: bool = False
    #: ``sha256`` or ``hmac-sha256``; a file-level field, never in ``as_dict``.
    seal_kind: str = ""

    def as_dict(self) -> dict[str, object]:
        """The ``checkpoint.json`` fields of design section 3.2 minus ``files``."""

        source: dict[str, object] = {
            "kind": self.source_kind,
            "origin": self.origin,
            "ref": self.ref,
            "commit": self.commit,
            "tree_id": self.tree_id,
            "commit_timestamp": self.commit_timestamp,
        }
        if self.archive_sha256:
            source["archive_sha256"] = self.archive_sha256
        return {
            "schema_version": SCHEMA_VERSION,
            "checkpoint_id": self.checkpoint_id,
            "source": source,
            "source_digest": self.source_digest,
            "file_count": self.file_count,
            "directory_count": self.directory_count,
            "total_bytes": self.total_bytes,
            "read_only": True,
        }




# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------



def checkpoint_dir(store: Path, checkpoint_id: str) -> Path:
    """Directory of *checkpoint_id*; the id is validated, never joined raw."""

    if not isinstance(checkpoint_id, str) or not _ID_RE.fullmatch(checkpoint_id):
        raise _err("CHECKPOINT_INVALID", "malformed checkpoint id")
    return Path(store) / "checkpoints" / checkpoint_id


def list_checkpoints(store: Path) -> list[str]:
    """Sorted ids of the published checkpoints in *store* (temp dirs ignored)."""

    root = Path(store) / "checkpoints"
    if not root.is_dir():
        return []
    found = [
        entry.name
        for entry in root.iterdir()
        if _ID_RE.fullmatch(entry.name) and entry.is_dir() and not entry.is_symlink()
    ]
    return sorted(found)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------



def _check_text(name: str, value: str, pattern: re.Pattern[str] | None = None) -> str:
    if not valid_text(value):
        raise _err("CHECKPOINT_INVALID", f"{name} is not a short printable string")
    if pattern is not None and not pattern.fullmatch(value):
        raise _err("CHECKPOINT_INVALID", f"{name} has an invalid format")
    return value


def _validated_files(ingestion: IngestionResult) -> list[IngestedFile]:
    seen: set[str] = set()
    for f in ingestion.files:
        if not _is_safe_relative(f.path):
            raise _err("CHECKPOINT_INVALID", "unsafe file path in ingestion", f.path)
        if f.path in seen:
            raise _err("CHECKPOINT_INVALID", "duplicate file path", f.path)
        if not _SHA256_RE.fullmatch(f.sha256) or f.size < 0:
            raise _err("CHECKPOINT_INVALID", "malformed file record", f.path)
        seen.add(f.path)
    clash = find_collision(seen)
    if clash is not None:
        raise _err("PATH_COLLISION", "paths collide under case or Unicode folding", clash)
    return sorted(ingestion.files, key=lambda f: f.path)


def _guard_labels(store: Path, staging: Path, origin: str) -> None:
    """Refuse an origin label that embeds the store or staging location."""

    _check_text("origin", origin)
    for location in {str(store), str(store.resolve()), str(staging.resolve())}:
        if location and location in origin:
            raise _err("CHECKPOINT_INVALID", "origin label contains a local path")
    try:
        store.resolve().relative_to(staging.resolve())
    except ValueError:
        return
    raise _err("CHECKPOINT_INVALID", "the store lies inside the staging tree")


# ---------------------------------------------------------------------------
# Staging inspection
# ---------------------------------------------------------------------------



def _walk_staging(root: Path) -> tuple[set[str], set[str]]:
    """Return ``(all directories, directories directly holding a file)``.

    Raises on a symlinked or redirected directory; VCS folders are pruned.
    """

    real_root = os.path.realpath(root)
    dirs: set[str] = set()
    with_files: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        rel_here = here.relative_to(root).as_posix()
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in _VCS_DIRS)
        for name in dirnames:
            rel = name if rel_here == "." else f"{rel_here}/{name}"
            if not _is_plain(real_root, here / name, rel):
                raise _err("CHECKPOINT_SYMLINK", "symlink or junction in staging", rel)
            dirs.add(rel)
        if filenames and rel_here != ".":
            with_files.add(rel_here)
    return dirs, with_files


def _with_ancestors(rel: str) -> Iterable[str]:
    parent = PurePosixPath(rel)
    while parent.as_posix() != ".":
        yield parent.as_posix()
        parent = parent.parent


def _plan_directories(root: Path, files: list[IngestedFile]) -> tuple[str, ...]:
    """Every directory to preserve: parents of files plus empty directories."""

    planned: set[str] = set()
    for f in files:
        planned.update(_with_ancestors(PurePosixPath(f.path).parent.as_posix()))
    all_dirs, with_files = _walk_staging(root)
    populated: set[str] = set()
    for rel in with_files:
        populated.update(_with_ancestors(rel))
    populated.update(planned)
    for rel in all_dirs - populated:
        planned.update(_with_ancestors(rel))
    return tuple(sorted(planned))


def _assert_regular(src: Path, rel: str) -> None:
    try:
        info = src.lstat()
    except OSError:
        raise _err("CHECKPOINT_COPY_MISMATCH", "file missing from staging", rel) from None
    if src.is_symlink():
        raise _err("CHECKPOINT_SYMLINK", "symlink in staging", rel)
    if (info.st_mode & 0o170000) != 0o100000:
        raise _err("CHECKPOINT_INVALID", "staged entry is not a regular file", rel)


# ---------------------------------------------------------------------------
# Copy and seal
# ---------------------------------------------------------------------------


def _copy_file_verified(src: Path, dst: Path, sha256: str, size: int, label: str) -> None:
    """Stream *src* to a new *dst*, proving the bytes match *sha256*/*size*."""

    digest = hashlib.sha256()
    copied = 0
    with src.open("rb") as reader, dst.open("xb") as writer:
        for chunk in iter(lambda: reader.read(_CHUNK), b""):
            copied += len(chunk)
            if copied > size:
                break
            digest.update(chunk)
            writer.write(chunk)
    if copied != size or digest.hexdigest() != sha256:
        raise _err(
            "CHECKPOINT_COPY_MISMATCH",
            "staged bytes differ from the ingested hash",
            label,
        )


def _make_read_only(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            (Path(dirpath) / name).chmod(0o444)
        if not _IS_WINDOWS:
            for name in dirnames:
                (Path(dirpath) / name).chmod(0o555)
    if not _IS_WINDOWS:
        root.chmod(0o555)


def release(path: Path) -> None:
    """Make a checkpoint tree writable again so an operator can delete it.

    OPERATOR USE ONLY.  The pipeline must never call this: it defeats the
    immutability guarantee.  After ``release`` a checkpoint is no longer
    trustworthy and should only be removed (``rmtree_force`` does the same
    permission reset implicitly).
    """

    path = Path(path)
    if not path.exists():
        return
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        for name in filenames:
            (Path(dirpath) / name).chmod(0o666)
        for name in dirnames:
            (Path(dirpath) / name).chmod(0o777)
    path.chmod(0o777)


def _metadata_document(meta: _Meta) -> bytes:
    source: dict[str, object] = {
        "kind": meta.kind,
        "origin": meta.origin,
        "ref": meta.ref,
        "commit": meta.commit,
        "tree_id": meta.tree_id,
        "commit_timestamp": meta.commit_timestamp,
    }
    if meta.archive_sha256:
        source["archive_sha256"] = meta.archive_sha256
    document = {
        "schema_version": SCHEMA_VERSION,
        "checkpoint_id": meta.checkpoint_id,
        "source": source,
        "source_digest": meta.source_digest,
        "file_count": meta.file_count,
        "directory_count": meta.directory_count,
        "total_bytes": meta.total_bytes,
        "directories": list(meta.directories),
        "files": [{"path": p, "sha256": s, "size": n} for p, s, n in meta.files],
        "read_only": True,
        "seal_kind": meta.seal_kind,
    }
    key = store_key() if meta.seal_kind == SEAL_HMAC else None
    if meta.seal_kind == SEAL_HMAC and key is None:
        raise _err("CHECKPOINT_INVALID", "the store key disappeared during creation")
    document["seal"] = compute_seal(document, key)
    text = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True)
    return (text + "\n").encode("ascii")


def _archive_sha(kind: str, archive: Path | None) -> str:
    if archive is None:
        return ""
    if kind != "zip":
        raise _err("CHECKPOINT_INVALID", "an original archive is only valid for zip input")
    if not archive.is_file() or archive.is_symlink():
        raise _err("CHECKPOINT_INVALID", "original archive is not a regular file")
    return sha256_file(archive)


def _populate(tmp: Path, root: Path, meta: _Meta, archive: Path | None) -> None:
    source = tmp / SOURCE_DIR
    source.mkdir(parents=True)
    for rel in meta.directories:
        source.joinpath(*rel.split("/")).mkdir(parents=True, exist_ok=True)
    for path, sha, size in meta.files:
        src = root.joinpath(*path.split("/"))
        _assert_regular(src, path)
        _copy_file_verified(src, source.joinpath(*path.split("/")), sha, size, path)
    if archive is not None:
        (tmp / ORIGINAL_DIR).mkdir()
        _copy_file_verified(
            archive, tmp / ORIGINAL_DIR / ORIGINAL_ARCHIVE,
            meta.archive_sha256, archive.stat().st_size, ORIGINAL_ARCHIVE,
        )
    (tmp / CHECKPOINT_FILE).write_bytes(_metadata_document(meta))
    _make_read_only(tmp)


def _publish(tmp: Path, final: Path) -> bool:
    """Atomically move *tmp* to *final*; False when another creator won."""

    for attempt in range(_PUBLISH_ATTEMPTS):
        try:
            os.replace(tmp, final)
            return True
        except OSError:
            if final.exists():
                return False
            time.sleep(0.05 * (attempt + 1))
    raise _err("CHECKPOINT_PUBLISH_FAILED", "could not publish the checkpoint")


def _reuse(final: Path, expected_digest: str) -> CheckpointInfo:
    try:
        info = load_checkpoint(final)
    except IngestionError as exc:
        if exc.code == "CHECKPOINT_INVALID":
            raise _err(
                "CHECKPOINT_TAMPERED", "existing checkpoint is unreadable: " + exc.message
            ) from None
        raise
    if info.source_digest != expected_digest:
        raise _err("CHECKPOINT_TAMPERED", "existing checkpoint holds different content than this input")
    return replace(info, reused=True)


def _info_from(meta: _Meta, final: Path) -> CheckpointInfo:
    return CheckpointInfo(
        checkpoint_id=meta.checkpoint_id,
        source_kind=meta.kind,
        origin=meta.origin,
        ref=meta.ref,
        commit=meta.commit,
        tree_id=meta.tree_id,
        commit_timestamp=meta.commit_timestamp,
        archive_sha256=meta.archive_sha256,
        source_digest=meta.source_digest,
        file_count=meta.file_count,
        directory_count=meta.directory_count,
        total_bytes=meta.total_bytes,
        path=final,
        source_root=final / SOURCE_DIR,
        seal_kind=meta.seal_kind,
    )


def create_checkpoint(
    ingestion: IngestionResult,
    store: Path,
    *,
    origin_label: str,
    ref: str = "",
    tree_id: str = "",
    original_archive: Path | None = None,
    source_digest_override: str | None = None,
) -> CheckpointInfo:
    """Freeze the validated staging tree of *ingestion* into *store*.

    ``source_digest_override`` is an *expected* digest (for example one the
    caller computed independently): it must equal the digest of
    ``ingestion.files`` or ``CHECKPOINT_COPY_MISMATCH`` is raised; it can never
    change what is recorded.  An existing checkpoint with the same id is
    verified and returned with ``reused=True`` (its original provenance
    labels are kept); a failed verification raises ``CHECKPOINT_TAMPERED``
    and nothing is overwritten.
    """

    store = Path(store)
    files = _validated_files(ingestion)
    kind = ingestion.kind
    if kind not in KINDS:
        raise _err("CHECKPOINT_INVALID", "unknown source kind")
    digest = compute_source_digest(files)
    if source_digest_override is not None and source_digest_override != digest:
        raise _err("CHECKPOINT_COPY_MISMATCH", "source digest differs from the expected value")
    commit = _check_text("commit", ingestion.commit or "", _COMMIT_RE)
    _check_text("ref", ref)
    _check_text("tree_id", tree_id, _COMMIT_RE)
    _check_text("commit_timestamp", ingestion.commit_timestamp, _TIMESTAMP_RE)
    _guard_labels(store, ingestion.staging_root, origin_label)

    cid = make_checkpoint_id(kind, commit, digest)
    final = checkpoint_dir(store, cid)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        return _reuse(final, digest)
    archive_sha = _archive_sha(kind, original_archive)
    root = ingestion.staging_root
    meta = _Meta(
        cid, kind, origin_label, ref, commit, tree_id, ingestion.commit_timestamp,
        archive_sha, digest, len(files), 0, sum(f.size for f in files),
        tuple((f.path, f.sha256, f.size) for f in files), (),
        SEAL_HMAC if store_key() else SEAL_SHA256,
    )
    directories = _plan_directories(root, files)
    meta = replace(meta, directories=directories, directory_count=len(directories))
    return _build_and_publish(root, meta, original_archive, final)


def _build_and_publish(
    root: Path, meta: _Meta, archive: Path | None, final: Path
) -> CheckpointInfo:
    tmp = final.parent / f".{meta.checkpoint_id}.tmp-{secrets.token_hex(8)}"
    try:
        _populate(tmp, root, meta, archive)
        won = _publish(tmp, final)
    except OSError as exc:
        rmtree_force(tmp)
        raise _err(
            "CHECKPOINT_COPY_FAILED",
            f"copying into the checkpoint failed ({type(exc).__name__}, errno={exc.errno})",
        ) from None
    except BaseException:
        rmtree_force(tmp)
        raise
    if not won:
        rmtree_force(tmp)
        return _reuse(final, meta.source_digest)
    return _info_from(meta, final)



def load_checkpoint(path: Path) -> CheckpointInfo:
    """Verify then load a checkpoint.

    Raises ``CHECKPOINT_INVALID`` when ``checkpoint.json`` is unusable and
    ``CHECKPOINT_TAMPERED`` when the preserved content deviates from it.
    """

    path = Path(path)
    try:
        meta = _read_metadata(path)
    except _MetadataError as exc:
        raise _err("CHECKPOINT_INVALID", str(exc)) from None
    report = _verify(path, meta)
    if not report.ok:
        detail = (
            f"{len(report.modified)} modified, {len(report.missing)} missing, "
            f"{len(report.extra)} extra"
        )
        if report.errors:
            detail += "; " + "; ".join(report.errors[:3])
        raise _err(
            "CHECKPOINT_TAMPERED",
            f"checkpoint {meta.checkpoint_id} failed verification ({detail})",
        )
    return _info_from(meta, path)

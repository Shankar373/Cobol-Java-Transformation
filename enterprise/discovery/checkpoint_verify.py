"""Parsing and verification of a checkpoint (read-only, never raises on tamper).

Split out of ``checkpoint``; the public entry points ``verify_checkpoint`` and
``load_checkpoint`` are re-exported from ``enterprise.discovery.checkpoint``.  Every message
produced here holds relative paths only.
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from .checkpoint_core import (
    CHECKPOINT_FILE,
    KINDS,
    SEAL_HMAC,
    SEAL_KINDS,
    ORIGINAL_ARCHIVE,
    ORIGINAL_DIR,
    SCHEMA_VERSION,
    SOURCE_DIR,
    VerificationReport,
    _COMMIT_RE,
    _ID_RE,
    _Meta,
    _MetadataError,
    _SHA256_RE,
    _TIMESTAMP_RE,
    _is_plain,
    _is_safe_relative,
    canonical_bytes,
    compute_source_digest,
    find_collision,
    make_checkpoint_id,
    seal_digest,
    store_key,
    valid_text,
)
from .hashing import sha256_file

_MAX_METADATA_BYTES = 64 * 1024 * 1024


def _int_field(doc: dict, key: str) -> int:
    value = doc.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _MetadataError(f"{key} must be a non-negative integer")
    return value


def _str_field(doc: dict, key: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str):
        raise _MetadataError(f"{key} must be a string")
    return value


def _parse_files(raw: object) -> tuple[tuple[str, str, int], ...]:
    if not isinstance(raw, list):
        raise _MetadataError("files must be a list")
    out: list[tuple[str, str, int]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise _MetadataError("file entry must be an object")
        path, sha = entry.get("path"), entry.get("sha256")
        size = entry.get("size")
        if not _is_safe_relative(path) or not isinstance(sha, str):
            raise _MetadataError("file entry has an unsafe path or hash")
        if not _SHA256_RE.fullmatch(sha) or isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise _MetadataError("file entry is malformed")
        out.append((path, sha, size))
    if len({p for p, _, _ in out}) != len(out):
        raise _MetadataError("duplicate file path")
    if find_collision(p for p, _, _ in out) is not None:
        raise _MetadataError("file paths collide under case or Unicode folding")
    return tuple(out)


def _parse_directories(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(_is_safe_relative(d) for d in raw):
        raise _MetadataError("directories must be a list of safe relative paths")
    if len(set(raw)) != len(raw):
        raise _MetadataError("duplicate directory")
    return tuple(raw)


def _parse_source(source: dict) -> tuple[str, str, str, str, str, str]:
    """Validated ``(origin, ref, commit, tree_id, commit_timestamp, archive)``."""

    values = tuple(
        _str_field(source, key)
        for key in ("origin", "ref", "commit", "tree_id", "commit_timestamp")
    )
    origin, ref, commit, tree_id, stamp = values
    archive = source.get("archive_sha256", "")
    checks = (
        valid_text(origin) and valid_text(ref),
        valid_text(commit, _COMMIT_RE) and valid_text(tree_id, _COMMIT_RE),
        valid_text(stamp, _TIMESTAMP_RE),
        valid_text(archive) and (archive == "" or _SHA256_RE.fullmatch(archive)),
    )
    if not all(checks):
        raise _MetadataError("a source provenance field is malformed")
    return origin, ref, commit, tree_id, stamp, archive


def _parse_seal(doc: dict) -> tuple[str, str]:
    kind, seal = doc.get("seal_kind"), doc.get("seal")
    if kind not in SEAL_KINDS or not isinstance(seal, str) or not _SHA256_RE.fullmatch(seal):
        raise _MetadataError("seal or seal_kind is missing or malformed")
    return kind, seal


def _parse_metadata(raw: bytes) -> _Meta:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise _MetadataError("checkpoint.json is not valid JSON") from None
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise _MetadataError("unsupported or missing schema_version")
    source = doc.get("source")
    if not isinstance(source, dict) or source.get("kind") not in KINDS:
        raise _MetadataError("source block is missing or has an unknown kind")
    cid = _str_field(doc, "checkpoint_id")
    digest = _str_field(doc, "source_digest")
    if not _ID_RE.fullmatch(cid) or not _SHA256_RE.fullmatch(digest):
        raise _MetadataError("malformed checkpoint_id or source_digest")
    if doc.get("read_only") is not True:
        raise _MetadataError("read_only must be true")
    origin, ref, commit, tree_id, stamp, archive = _parse_source(source)
    seal_kind, seal = _parse_seal(doc)
    return _Meta(
        cid, source["kind"], origin, ref, commit, tree_id, stamp, archive, digest,
        _int_field(doc, "file_count"), _int_field(doc, "directory_count"),
        _int_field(doc, "total_bytes"), _parse_files(doc.get("files")),
        _parse_directories(doc.get("directories")),
        seal_kind, seal, canonical_bytes(doc),
    )


def _read_metadata(path: Path) -> _Meta:
    target = path / CHECKPOINT_FILE
    try:
        if target.is_symlink() or not target.is_file():
            raise _MetadataError("checkpoint.json is missing")
        if target.stat().st_size > _MAX_METADATA_BYTES:
            raise _MetadataError("checkpoint.json is too large")
        raw = target.read_bytes()
    except OSError:
        raise _MetadataError("checkpoint.json is unreadable") from None
    return _parse_metadata(raw)


def _seal_errors(meta: _Meta) -> list[str]:
    """Check the seal over the whole document (constant-time comparison)."""

    key = store_key()
    keyed = meta.seal_kind == SEAL_HMAC
    if keyed and key is None:
        return ["sealed with a key that is not configured (SYSTEMAOPS_STORE_KEY)"]
    if not keyed and key is not None:
        return ["seal is unkeyed but SYSTEMAOPS_STORE_KEY is configured"]
    expected = seal_digest(meta.canonical, key if keyed else None)
    if not hmac.compare_digest(expected, meta.seal):
        return ["seal mismatch: checkpoint.json was modified"]
    return []


def _consistency_errors(meta: _Meta, dirname: str) -> list[str]:
    """Self-consistency of the recorded metadata (tamper of checkpoint.json)."""

    errors: list[str] = _seal_errors(meta)
    if compute_source_digest(meta.files) != meta.source_digest:
        errors.append("recorded file hashes do not match source_digest")
    if make_checkpoint_id(meta.kind, meta.commit, meta.source_digest) != meta.checkpoint_id:
        errors.append("checkpoint_id does not match kind, commit and source_digest")
    if dirname != meta.checkpoint_id:
        errors.append("directory name does not match checkpoint_id")
    if meta.file_count != len(meta.files):
        errors.append("file_count does not match the recorded files")
    if meta.total_bytes != sum(size for _, _, size in meta.files):
        errors.append("total_bytes does not match the recorded files")
    if meta.directory_count != len(meta.directories):
        errors.append("directory_count does not match the recorded directories")
    return errors


def _scan_source(source: Path, errors: list[str]) -> tuple[dict[str, Path], set[str], set[str]]:
    """On-disk ``(files, directories, extras)``; links are extras, never followed."""

    files: dict[str, Path] = {}
    dirs: set[str] = set()
    extra: set[str] = set()
    real_root = os.path.realpath(source)

    def _on_error(exc: OSError) -> None:
        errors.append("a source directory could not be read")

    for dirpath, dirnames, filenames in os.walk(source, onerror=_on_error):
        here = Path(dirpath)
        rel_here = here.relative_to(source).as_posix()
        prefix = "" if rel_here == "." else rel_here + "/"
        for name in list(dirnames):
            if _is_plain(real_root, here / name, prefix + name):
                dirs.add(prefix + name)
            else:
                extra.add(prefix + name + "/")
                dirnames.remove(name)
        for name in filenames:
            entry = here / name
            if entry.is_symlink() or not entry.is_file():
                extra.add(prefix + name)
            else:
                files[prefix + name] = entry
    return files, dirs, extra


def _hash_differences(
    recorded: dict[str, tuple[str, int]], disk: dict[str, Path], errors: list[str]
) -> tuple[list[str], list[tuple[str, str, int]]]:
    modified: list[str] = []
    actual: list[tuple[str, str, int]] = []
    for rel in sorted(set(recorded) & set(disk)):
        try:
            sha, size = sha256_file(disk[rel]), disk[rel].stat().st_size
        except OSError:
            errors.append("a source file could not be read")
            modified.append(rel)
            continue
        actual.append((rel, sha, size))
        if (sha, size) != recorded[rel]:
            modified.append(rel)
    return modified, actual


def _hash_unrecorded(
    disk: dict[str, Path], recorded: dict[str, tuple[str, int]], errors: list[str]
) -> list[tuple[str, str, int]]:
    """Hash on-disk files the metadata does not list (they poison the digest)."""

    out: list[tuple[str, str, int]] = []
    for rel in sorted(set(disk) - set(recorded)):
        try:
            out.append((rel, sha256_file(disk[rel]), disk[rel].stat().st_size))
        except OSError:
            errors.append("a source file could not be read")
    return out


def _check_original(path: Path, meta: _Meta, errors: list[str]) -> tuple[list[str], list[str], list[str]]:
    """``(modified, missing, extra)`` for the preserved original archive."""

    original = path / ORIGINAL_DIR
    wanted = f"{ORIGINAL_DIR}/{ORIGINAL_ARCHIVE}"
    if not meta.archive_sha256:
        return [], [], ([ORIGINAL_DIR + "/"] if os.path.lexists(original) else [])
    if original.is_symlink() or not original.is_dir():
        return [], [wanted], []
    extra = [f"{ORIGINAL_DIR}/{n}" for n in sorted(os.listdir(original)) if n != ORIGINAL_ARCHIVE]
    archive = original / ORIGINAL_ARCHIVE
    if archive.is_symlink() or not archive.is_file():
        return [], [wanted], extra
    try:
        same = sha256_file(archive) == meta.archive_sha256
    except OSError:
        errors.append("the original archive could not be read")
        same = False
    return ([] if same else [wanted]), [], extra


def _top_level_extras(path: Path, meta: _Meta) -> list[str]:
    allowed = {CHECKPOINT_FILE, SOURCE_DIR, ORIGINAL_DIR}
    try:
        names = os.listdir(path)
    except OSError:
        return []
    return [n + ("/" if (path / n).is_dir() else "") for n in sorted(names) if n not in allowed]


def _verify(path: Path, meta: _Meta) -> VerificationReport:
    errors = _consistency_errors(meta, path.name)
    recorded = {p: (s, n) for p, s, n in meta.files}
    source = path / SOURCE_DIR
    if source.is_symlink() or not source.is_dir():
        errors.append("source directory is missing")
        disk_files, disk_dirs, extra = {}, set(), set()
    else:
        disk_files, disk_dirs, extra = _scan_source(source, errors)
    modified, actual = _hash_differences(recorded, disk_files, errors)
    missing = {p for p in recorded if p not in disk_files}
    extra |= {p for p in disk_files if p not in recorded}
    wanted_dirs = set(meta.directories)
    missing |= {d + "/" for d in wanted_dirs - disk_dirs}
    extra |= {d + "/" for d in disk_dirs - wanted_dirs}
    orig_mod, orig_missing, orig_extra = _check_original(path, meta, errors)
    modified += orig_mod
    missing |= set(orig_missing)
    extra |= set(orig_extra) | set(_top_level_extras(path, meta))
    actual += _hash_unrecorded(disk_files, recorded, errors)
    digest_ok = compute_source_digest(actual) == meta.source_digest
    ok = digest_ok and not (modified or missing or extra or errors)
    return VerificationReport(
        ok, digest_ok, tuple(sorted(modified)), tuple(sorted(missing)),
        tuple(sorted(extra)), tuple(errors),
    )


def verify_checkpoint(path: Path) -> VerificationReport:
    """Re-hash the whole checkpoint and report every deviation.

    Never raises on tampering: a problem becomes ``modified`` / ``missing`` /
    ``extra`` / ``errors`` and ``ok=False``.  Messages hold relative paths only.
    """

    path = Path(path)
    try:
        meta = _read_metadata(path)
    except _MetadataError as exc:
        return VerificationReport(False, False, errors=(str(exc),))
    return _verify(path, meta)


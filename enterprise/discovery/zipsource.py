"""ZIP ingestion for discovery: the platform's hardened extractor wrapped in the discovery staging contract.

``enterprise.ingest.safe_extract`` does the untrusted work (names, symlinks, bombs, encrypted entries, duplicates,
limits enforced on bytes actually written).  This adapter maps its refusals to discovery's typed errors, preserves
empty directories the archive declares, refuses names that collide under case or Unicode folding, and hands the
staged tree to the shared :func:`model.ingest_directory` tail, so the same bytes give the same manifest whether they
arrived as a ZIP, a Git checkout or a directory.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from enterprise.ingest.safe_extract import ArchiveRefusal, ExtractLimits, _clean_name, extract_zip

from .checkpoint_core import find_collision
from .errors import DiagnosticSink, IngestionError, LimitExceededError
from .limits import DEFAULT_LIMITS, Limits
from .model import IngestionResult, ingest_directory, rmtree_force

__all__ = ["ingest_zip", "extract_limits"]

_LIMIT_CODES = frozenset({"ARCHIVE_TOO_MANY_FILES", "ARCHIVE_FILE_TOO_LARGE", "ARCHIVE_BOMB", "ARCHIVE_TOO_DEEP"})
_SUBDIR = "tree"
_STAGED_NAME = "input.zip"
_COPY_CHUNK = 1 << 20


def extract_limits(limits: Limits) -> ExtractLimits:
    """The extractor limits that correspond to discovery's :class:`Limits` (one source of truth)."""
    return ExtractLimits(
        max_files=limits.max_entries, max_expanded_bytes=limits.max_total_bytes, max_file_bytes=limits.max_entry_bytes,
        max_compression_ratio=int(limits.max_compression_ratio), max_depth=limits.max_path_depth,
        max_path_length=min(limits.max_path_length, 1024), symlinks="refuse")


def _declared_directories(archive: Path, limits: ExtractLimits) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        return sorted({_clean_name(info.filename.rstrip("/"), limits) for info in zf.infolist() if info.is_dir()})


def _stage_copy(source: Path, target: Path, max_bytes: int) -> Path:
    """Copy the caller's archive once; every later step (extract, directories, preservation) reads this copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            for block in iter(lambda: reader.read(_COPY_CHUNK), b""):
                copied += len(block)
                if copied > max_bytes:
                    raise LimitExceededError("archive is larger than the total size limit", code="ARCHIVE_BOMB")
                writer.write(block)
    except OSError:
        raise IngestionError("the archive could not be read", code="INPUT_UNREADABLE") from None
    return target


def ingest_zip(archive: Path, staging: Path, *, origin: str, limits: Limits = DEFAULT_LIMITS,
               sink: DiagnosticSink | None = None) -> IngestionResult:
    """Extract ``archive`` into ``staging`` (new directory) and inventory it; raises :class:`IngestionError`."""
    sink = sink or DiagnosticSink(limits.max_diagnostics)
    archive, staging = Path(archive), Path(staging)
    if not archive.is_file() or archive.is_symlink():
        raise IngestionError("archive is not a regular file", code="INPUT_NOT_FOUND")
    target = staging / _SUBDIR
    extract = extract_limits(limits)
    staged = _stage_copy(archive, staging / _STAGED_NAME, limits.max_total_bytes)
    try:
        extracted = extract_zip(staged, target, extract)
        for directory in _declared_directories(staged, extract):
            (target / directory).mkdir(parents=True, exist_ok=True)
    except ArchiveRefusal as refusal:
        rmtree_force(target)
        error = LimitExceededError if refusal.code in _LIMIT_CODES else IngestionError
        raise error(refusal.message, code=refusal.code) from None
    except OSError:
        rmtree_force(target)
        raise IngestionError("a file and a directory in the archive share a name", code="PATH_COLLISION") from None
    except BaseException:
        rmtree_force(target)
        raise
    clash = find_collision(item.path for item in extracted.files)
    if clash is not None:
        rmtree_force(target)
        raise IngestionError("paths collide under case or Unicode folding", code="PATH_COLLISION", path=clash)
    for path, reason in extracted.skipped:
        sink.warn("ARCHIVE_ENTRY_SKIPPED", f"{reason} entry not extracted", path=path)
    result = ingest_directory(target, origin=origin, kind="zip", sink=sink, limits=limits)
    result.original_archive = staged
    return result

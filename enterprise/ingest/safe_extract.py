"""Safe ZIP extraction for uploaded archives and GitHub snapshots.

Nothing in the archive is trusted: names, declared sizes, modes and headers are all checked, and the limits are enforced on
the bytes actually written, not on what the central directory claims. The archive is read with random access (never loaded
whole into memory), each file is streamed in chunks and hashed while it is written, and no archive content is ever executed.
Any refusal removes everything extracted so far and carries a stable code.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

CHUNK = 1 << 20
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)


class ArchiveRefusal(Exception):
    """The archive cannot be extracted safely; ``code`` is a stable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ExtractLimits:
    max_files: int = 50_000
    max_expanded_bytes: int = 4 * 1024**3
    max_file_bytes: int = 512 * 1024**2
    max_compression_ratio: int = 200  # declared size over compressed size, per file
    max_depth: int = 40
    max_path_length: int = 1024
    symlinks: str = "refuse"  # "refuse" fails the archive; "skip" leaves them out and records them


@dataclass(frozen=True)
class ExtractedFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ExtractionResult:
    files: tuple[ExtractedFile, ...]
    skipped: tuple[tuple[str, str], ...]  # (path, reason)
    expanded_bytes: int


def _clean_name(raw: str, limits: ExtractLimits) -> str:
    if not raw or len(raw) > limits.max_path_length:
        raise ArchiveRefusal("ARCHIVE_BAD_PATH", f"entry name length {len(raw)} is not allowed")
    if "\\" in raw or _CONTROL.search(raw) or _DRIVE.match(raw) or raw.startswith("/"):
        raise ArchiveRefusal("ARCHIVE_BAD_PATH", f"entry name {raw[:80]!r} is not a relative portable path")
    parts = PurePosixPath(raw).parts
    # PurePosixPath silently collapses "a//b" and "a/./b"; a name that is not already in normal form is refused.
    if "/".join(parts) != raw or any(part in ("", ".", "..") for part in parts):
        raise ArchiveRefusal("ARCHIVE_BAD_PATH", f"entry name {raw[:80]!r} escapes or is not normalised")
    if len(parts) > limits.max_depth:
        raise ArchiveRefusal("ARCHIVE_TOO_DEEP", f"entry {raw[:80]!r} is nested {len(parts)} levels deep")
    if any(_WINDOWS_RESERVED.match(part) or part.endswith((" ", ".")) for part in parts):
        raise ArchiveRefusal("ARCHIVE_BAD_PATH", f"entry name {raw[:80]!r} is not portable to Windows")
    return "/".join(parts)


def _kind(info: zipfile.ZipInfo) -> str:
    if info.is_dir():
        return "dir"
    file_type = stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)
    if file_type == stat.S_IFLNK:
        return "symlink"
    # No type bits means the writer recorded permissions only (or no Unix mode at all): an ordinary file.
    return "file" if file_type in (0, stat.S_IFREG) else "special"


def extract_zip(archive: Path, dest: Path, limits: ExtractLimits | None = None) -> ExtractionResult:
    """Extract ``archive`` into the new, empty directory ``dest``; returns the files written."""
    limits = limits or ExtractLimits()
    if dest.exists() and any(dest.iterdir()):
        raise ArchiveRefusal("ARCHIVE_DEST_NOT_EMPTY", "extraction target already holds files")
    dest.mkdir(parents=True, exist_ok=True)
    try:
        return _extract(archive, dest.resolve(), limits)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def _extract(archive: Path, root: Path, limits: ExtractLimits) -> ExtractionResult:
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveRefusal("ARCHIVE_INVALID", f"not a readable ZIP archive: {exc}") from None
    files: list[ExtractedFile] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    total = 0
    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_files:
            raise ArchiveRefusal("ARCHIVE_TOO_MANY_FILES", f"{len(infos)} entries exceed {limits.max_files}")
        for info in infos:
            name = _clean_name(info.filename.rstrip("/") if info.is_dir() else info.filename, limits)
            kind = _kind(info)
            if kind == "dir":
                continue
            if kind in ("symlink", "special"):
                if kind == "special" or limits.symlinks == "refuse":
                    raise ArchiveRefusal("ARCHIVE_" + kind.upper(), f"entry {name[:80]!r} is a {kind}")
                skipped.append((name, "symlink"))
                continue
            if info.flag_bits & 0x1:
                raise ArchiveRefusal("ARCHIVE_ENCRYPTED", f"entry {name[:80]!r} is encrypted")
            fold = name.casefold()
            if fold in seen:
                raise ArchiveRefusal("ARCHIVE_DUPLICATE_PATH", f"entry {name[:80]!r} repeats an earlier path")
            seen.add(fold)
            if info.file_size > limits.max_file_bytes:
                raise ArchiveRefusal("ARCHIVE_FILE_TOO_LARGE", f"entry {name[:80]!r} declares {info.file_size} bytes")
            if info.compress_size and info.file_size / info.compress_size > limits.max_compression_ratio:
                raise ArchiveRefusal("ARCHIVE_BOMB", f"entry {name[:80]!r} compresses more than "
                                     f"{limits.max_compression_ratio}:1")
            written, digest = _write(zf, info, root, name, limits, total)
            total += written
            files.append(ExtractedFile(name, written, digest))
    files.sort(key=lambda f: f.path)
    return ExtractionResult(tuple(files), tuple(sorted(skipped)), total)


def _write(zf: zipfile.ZipFile, info: zipfile.ZipInfo, root: Path, name: str, limits: ExtractLimits,
           total_so_far: int) -> tuple[int, str]:
    target = (root / name).resolve()
    if root not in target.parents:
        raise ArchiveRefusal("ARCHIVE_BAD_PATH", f"entry {name[:80]!r} resolves outside the target")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, written = hashlib.sha256(), 0
    try:
        with zf.open(info) as source, target.open("xb") as sink:  # "x": never overwrite
            for block in iter(lambda: source.read(CHUNK), b""):
                written += len(block)
                if written > limits.max_file_bytes:
                    raise ArchiveRefusal("ARCHIVE_FILE_TOO_LARGE", f"entry {name[:80]!r} expands past the limit")
                if total_so_far + written > limits.max_expanded_bytes:
                    raise ArchiveRefusal("ARCHIVE_BOMB", f"archive expands past {limits.max_expanded_bytes} bytes")
                digest.update(block)
                sink.write(block)
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, NotImplementedError) as exc:
        if isinstance(exc, FileExistsError):
            raise ArchiveRefusal("ARCHIVE_DUPLICATE_PATH", f"entry {name[:80]!r} repeats an earlier path") from None
        raise ArchiveRefusal("ARCHIVE_CORRUPT", f"entry {name[:80]!r} cannot be read: {exc}") from None
    if written != info.file_size:
        raise ArchiveRefusal("ARCHIVE_CORRUPT", f"entry {name[:80]!r} is {written} bytes, header says {info.file_size}")
    return written, digest.hexdigest()

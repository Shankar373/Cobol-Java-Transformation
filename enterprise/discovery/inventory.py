"""File and directory inventory records.

Every file in the checkpoint becomes one :class:`FileRecord`, scanned or not: a file the scanners cannot read is
inventoried with the reason (``blocker``), never dropped.  Every directory, including empty ones, becomes a
:class:`DirectoryEntry`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .findings import FileScan

__all__ = ["FileRecord", "DirectoryEntry", "list_directories"]


@dataclass
class FileRecord:
    path: str
    sha256: str
    size: int
    cls: str = "unknown"
    evidence: tuple[str, ...] = ()
    encoding: str = ""
    encoding_confidence: str = ""
    source_format: str = ""
    line_count: int = 0
    #: ``""`` when a scanner read the file (or none applies); otherwise why it was not scanned.
    blocker: str = ""
    scan: FileScan | None = field(default=None, repr=False)

    @property
    def stem(self) -> str:
        return self.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"class": self.cls, "classification_evidence": list(self.evidence), "path": self.path,
                                  "sha256": self.sha256, "size": self.size}
        if self.encoding:
            out["encoding"] = self.encoding
            out["encoding_confidence"] = self.encoding_confidence
        if self.source_format:
            out["source_format"] = self.source_format
        if self.line_count:
            out["lines"] = self.line_count
        if self.blocker:
            out["not_scanned"] = self.blocker
        return out


@dataclass(frozen=True)
class DirectoryEntry:
    path: str
    files: int
    directories: int
    total_files: int
    total_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {"directories": self.directories, "empty": self.total_files == 0 and self.directories == 0,
                "files": self.files, "path": self.path, "total_bytes": self.total_bytes, "total_files": self.total_files}


def list_directories(root: Path, files: list[FileRecord]) -> list[DirectoryEntry]:
    """Every directory under ``root`` (empty ones included), with direct and recursive counts; sorted by path."""
    directories: set[str] = set()
    for dirpath, dirnames, _ in os.walk(root):
        here = Path(dirpath).relative_to(root).as_posix()
        for name in dirnames:
            directories.add(name if here == "." else f"{here}/{name}")
    for record in files:
        parts = record.path.split("/")[:-1]
        directories.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    direct_files: dict[str, int] = {}
    total_files: dict[str, int] = {}
    total_bytes: dict[str, int] = {}
    direct_dirs: dict[str, int] = {}
    for record in files:
        parts = record.path.split("/")[:-1]
        if parts:
            parent = "/".join(parts)
            direct_files[parent] = direct_files.get(parent, 0) + 1
        for depth in range(1, len(parts) + 1):
            ancestor = "/".join(parts[:depth])
            total_files[ancestor] = total_files.get(ancestor, 0) + 1
            total_bytes[ancestor] = total_bytes.get(ancestor, 0) + record.size
    for directory in directories:
        if "/" in directory:
            parent = directory.rsplit("/", 1)[0]
            direct_dirs[parent] = direct_dirs.get(parent, 0) + 1
    return [DirectoryEntry(d, direct_files.get(d, 0), direct_dirs.get(d, 0), total_files.get(d, 0), total_bytes.get(d, 0))
            for d in sorted(directories)]

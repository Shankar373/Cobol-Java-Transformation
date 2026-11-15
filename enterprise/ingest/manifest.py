"""Deterministic source manifests: classify extracted files and derive a content-addressed manifest id.

The manifest lists every kept file (path, size, SHA-256, kind) and every ignored one with its reason, sorted by path, and its
``manifest_id`` is the SHA-256 of that canonical listing. The same archive therefore always yields the same manifest, and any
changed byte, added file or renamed path changes the id.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from enterprise.contracts import IgnoredFile, SourceFileEntry, SourceFileManifest
from enterprise.ingest.safe_extract import ExtractedFile

KIND_BY_EXTENSION = {
    ".cbl": "cobol", ".cob": "cobol", ".cobol": "cobol", ".pco": "cobol", ".sqlcbl": "cobol",
    ".cpy": "copybook", ".copy": "copybook", ".cbk": "copybook", ".inc": "copybook",
    ".jcl": "jcl", ".proc": "jcl", ".prc": "jcl", ".prm": "jcl",
    ".bms": "bms", ".sql": "sql", ".ddl": "sql", ".dcl": "sql",
    ".java": "java", ".py": "python", ".sh": "script", ".txt": "text", ".md": "doc", ".json": "data",
    ".xml": "data", ".yml": "data", ".yaml": "data", ".csv": "data", ".dat": "data",
}
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".idea", ".vscode", "target", "build", "dist", "vendor",
})
BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".class", ".jar", ".war", ".o", ".obj", ".a", ".lib", ".pyc", ".zip", ".gz",
    ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".bin", ".img",
})


def classify(path: str) -> tuple[str, str]:
    """``(kind, ignored_reason)``; the reason is empty for a file that belongs in the inventory."""
    pure = PurePosixPath(path)
    excluded = EXCLUDED_DIRECTORIES.intersection(pure.parts[:-1])
    if excluded:
        return "ignored", f"inside excluded directory {sorted(excluded)[0]}"
    suffix = pure.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return "ignored", f"binary or archive file type {suffix}"
    return KIND_BY_EXTENSION.get(suffix, "unknown"), ""


def common_root(files: Sequence[ExtractedFile]) -> str:
    """The single top-level directory every file sits under (GitHub archives have one), or ``""``."""
    firsts = {f.path.split("/", 1)[0] for f in files if "/" in f.path}
    if len(firsts) == 1 and all("/" in f.path for f in files) and files:
        return next(iter(firsts))
    return ""


def build_manifest(files: Sequence[ExtractedFile], root: str = "") -> SourceFileManifest:
    """Manifest of ``files`` with ``root`` stripped from every path; sorted, with a content-addressed id."""
    entries: list[SourceFileEntry] = []
    ignored: list[IgnoredFile] = []
    for item in sorted(files, key=lambda f: f.path):
        path = item.path[len(root) + 1:] if root else item.path
        kind, reason = classify(path)
        if reason:
            ignored.append(IgnoredFile(path=path, reason=reason))
        else:
            entries.append(SourceFileEntry(path=path, size=item.size, sha256=item.sha256, file_type=kind))
    canonical = json.dumps(
        {"files": [e.model_dump(mode="json") for e in entries], "ignored": [i.model_dump(mode="json") for i in ignored]},
        sort_keys=True, separators=(",", ":"))
    return SourceFileManifest(
        manifest_id=hashlib.sha256(canonical.encode("utf-8")).hexdigest(), files=tuple(entries), ignored=tuple(ignored))


def prune_ignored(workspace: Path, manifest: SourceFileManifest) -> None:
    """Delete ignored files from the workspace so only inventory files remain on disk."""
    for item in manifest.ignored:
        target = workspace / item.path
        if target.is_file():
            target.unlink()
    for directory in sorted((p for p in workspace.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            shutil.rmtree(directory, ignore_errors=True)

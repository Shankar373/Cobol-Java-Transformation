"""Shared SHA-256 source-tree hashing for adapter-level identity checks."""

from __future__ import annotations

import hashlib
from pathlib import Path

from engine.domain.identities import ContentHash


def compute_source_tree_hash(source_path: str) -> ContentHash:
    """Hash a file, or a directory tree as sorted relative path + bytes per file."""
    hasher = hashlib.sha256()
    path = Path(source_path)
    if path.is_file():
        hasher.update(path.read_bytes())
    elif path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file():
                # POSIX separators so identical trees hash identically on
                # every platform (str() would bake in "\" on Windows).
                hasher.update(f.relative_to(path).as_posix().encode())
                hasher.update(f.read_bytes())
    return ContentHash(digest=hasher.hexdigest())

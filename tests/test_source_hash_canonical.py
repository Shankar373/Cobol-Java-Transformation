"""BL-097: source-tree hashing must be platform-canonical.

``compute_source_tree_hash`` feeds adapter-level identity checks in
``engine/oracle/docker_adapter.py`` and ``engine/execution/docker_runner.py``.
It previously baked the OS path separator into the digest via
``str(f.relative_to(path))``, so an identical source tree hashed
differently on Windows (``src\\A.cob``) and Linux (``src/A.cob``) —
exactly the class of cross-platform divergence whose Windows-only
path-separator failures were just removed from the runtime-adapter
tests. Contract under test: relative paths contribute POSIX separators
on every platform; a single file still hashes to the bare content digest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from engine.source_hash import compute_source_tree_hash


class TestPosixCanonicalTreeHash:
    def test_directory_hash_uses_posix_relative_paths(self, tmp_path: Path):
        (tmp_path / "sub" / "inner").mkdir(parents=True)
        (tmp_path / "top.cob").write_bytes(b"top-level program")
        (tmp_path / "sub" / "inner" / "deep.cob").write_bytes(b"deep program")

        # Reference computation: identical algorithm, POSIX separators only.
        hasher = hashlib.sha256()
        for f in sorted(tmp_path.rglob("*")):
            if f.is_file():
                hasher.update(f.relative_to(tmp_path).as_posix().encode())
                hasher.update(f.read_bytes())
        expected = hasher.hexdigest()

        assert compute_source_tree_hash(str(tmp_path)).digest == expected

    def test_single_file_hash_is_content_digest(self, tmp_path: Path):
        src = tmp_path / "ONE.cob"
        src.write_bytes(b"       STOP RUN.")
        assert compute_source_tree_hash(str(src)).digest == hashlib.sha256(
            b"       STOP RUN."
        ).hexdigest()

    def test_empty_directory_hash_is_empty_sha256(self, tmp_path: Path):
        # No files contribute nothing; digest is the empty SHA-256.
        assert compute_source_tree_hash(str(tmp_path)).digest == hashlib.sha256(
            b""
        ).hexdigest()

"""Limits and collisions are enforced for Git and directory inputs.

Before this hardening only the ZIP path enforced ``max_entries``, path depth
and name/path length.  A repository (or a plain directory) is just as capable
of being a bomb, so the same bounds apply, and a commit that cannot be
materialised faithfully on a case-insensitive host is refused everywhere.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

import pytest

from tests.discovery.helpers import REPO_ROOT, codes_of, expect_refusal, make_zip, read_json, write_enterprise_app, write_tree  # noqa: F401

from enterprise.discovery.errors import IngestionError
from enterprise.discovery.gitingest import ingest_git
from enterprise.discovery.limits import Limits
from enterprise.discovery.model import ingest_directory, walk_files

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git is required")

COMMITTER = (
    "-c", "user.email=discovery@example.invalid",
    "-c", "user.name=P1",
    "-c", "commit.gpgsign=false",
)


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    proc = subprocess.run(
        [str(GIT), *COMMITTER, *args], cwd=str(repo), input=stdin,
        capture_output=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout.decode("utf-8").strip()


def _repo(tmp_path: Path, name: str = "origin") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    return repo


def _tree(repo: Path, lines: list[str]) -> str:
    data = "".join(f"{line}\n" for line in lines).encode("utf-8")
    return _git(repo, "mktree", stdin=data)


def _commit_tree(repo: Path, tree: str) -> str:
    sha = _git(repo, "commit-tree", tree, "-m", "plumbing")
    _git(repo, "update-ref", "refs/heads/main", sha)
    return sha


def _blob(repo: Path, content: bytes = b"") -> str:
    return _git(repo, "hash-object", "-w", "--stdin", stdin=content)


def _staging(tmp_path: Path, name: str = "stage") -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _file_count(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file())


def _index_commit(repo: Path, entries: dict[str, bytes]) -> None:
    """Commit *entries* through the index so case/Unicode twins can coexist."""

    for name, content in entries.items():
        blob = _blob(repo, content)
        _git(repo, "update-index", "--add", "--cacheinfo",
             f"100644,{blob},{name}")
    _git(repo, "commit", "-q", "-m", "twins")


# ---------------------------------------------------------------------------
# Git: tree bombs and bounds, checked from ls-tree before checkout
# ---------------------------------------------------------------------------


def test_tree_bomb_is_refused_quickly_and_leaves_no_large_tree(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    empty = _blob(repo)
    leaves = _tree(repo, [f"100644 blob {empty}\tf{i:02d}" for i in range(25)])
    level2 = _tree(repo, [f"040000 tree {leaves}\td{i:02d}" for i in range(25)])
    root = _tree(repo, [f"040000 tree {level2}\td{i:02d}" for i in range(25)])
    _commit_tree(repo, root)
    staging = _staging(tmp_path)

    started = time.monotonic()
    code = expect_refusal(ingest_git, str(repo), staging)
    elapsed = time.monotonic() - started

    assert code == "TOO_MANY_ENTRIES"
    assert elapsed < 30
    assert _file_count(staging / "repo") < 100, "checkout ran before the check"


def test_path_depth_is_enforced_for_git(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _index_commit(repo, {"a/b/c/d.pas": b"x"})
    code = expect_refusal(
        ingest_git, str(repo), _staging(tmp_path),
        limits=Limits(max_path_depth=3),
    )
    assert code == "UNSAFE_PATH"


def test_component_and_path_length_are_enforced_for_git(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _index_commit(repo, {"x" * 40 + ".pas": b"x"})
    assert expect_refusal(
        ingest_git, str(repo), _staging(tmp_path, "s1"),
        limits=Limits(max_name_length=20),
    ) == "UNSAFE_PATH"
    assert expect_refusal(
        ingest_git, str(repo), _staging(tmp_path, "s2"),
        limits=Limits(max_path_length=20),
    ) == "UNSAFE_PATH"


def test_blob_size_and_declared_total_are_enforced_for_git(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _index_commit(repo, {"a.pas": b"x" * 600, "b.pas": b"y" * 600})
    assert expect_refusal(
        ingest_git, str(repo), _staging(tmp_path, "s1"),
        limits=Limits(max_entry_bytes=500),
    ) == "ENTRY_TOO_LARGE"
    assert expect_refusal(
        ingest_git, str(repo), _staging(tmp_path, "s2"),
        limits=Limits(max_total_bytes=1000),
    ) == "TOTAL_TOO_LARGE"


def test_entry_count_counts_directories_too(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _index_commit(repo, {f"d{i}/f.pas": b"x" for i in range(4)})  # 4 + 4
    assert expect_refusal(
        ingest_git, str(repo), _staging(tmp_path),
        limits=Limits(max_entries=7),
    ) == "TOO_MANY_ENTRIES"


def test_a_repository_within_limits_is_unaffected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _index_commit(repo, {"d/f.pas": b"x", "g.pas": b"y"})
    result = ingest_git(
        str(repo), _staging(tmp_path), limits=Limits(max_entries=3)
    )
    assert sorted(f.path for f in result.files) == ["d/f.pas", "g.pas"]


# ---------------------------------------------------------------------------
# Git: case-folding and Unicode collisions
# ---------------------------------------------------------------------------


def test_case_twins_are_refused_on_every_host(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _index_commit(repo, {"A.pas": b"one", "a.pas": b"two"})
    assert expect_refusal(
        ingest_git, str(repo), _staging(tmp_path)
    ) == "PATH_COLLISION"


def test_unicode_normalisation_twins_are_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    composed = unicodedata.normalize("NFC", "café.pas")
    decomposed = unicodedata.normalize("NFD", "café.pas")
    assert composed != decomposed
    _index_commit(repo, {composed: b"one", decomposed: b"two"})
    assert expect_refusal(
        ingest_git, str(repo), _staging(tmp_path)
    ) == "PATH_COLLISION"


def test_file_and_directory_with_folding_names_collide(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _index_commit(repo, {"lib": b"file", "LIB/unit.pas": b"x"})
    assert expect_refusal(
        ingest_git, str(repo), _staging(tmp_path)
    ) == "PATH_COLLISION"


def test_distinct_names_do_not_collide(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _index_commit(repo, {"a.pas": b"one", "b.pas": b"two", "lib/a.pas": b"3"})
    assert len(ingest_git(str(repo), _staging(tmp_path)).files) == 3


# ---------------------------------------------------------------------------
# Directory inputs
# ---------------------------------------------------------------------------


def test_directory_entry_count_is_enforced_while_walking(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "d", {f"f{i}.pas": "x" for i in range(10)})
    with pytest.raises(IngestionError) as caught:
        walk_files(root, limits=Limits(max_entries=5))
    assert caught.value.code == "TOO_MANY_ENTRIES"


def test_directory_depth_and_name_length_are_enforced(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "d", {"a/b/c/d.pas": "x"})
    assert expect_refusal(
        ingest_directory, root, origin="x", limits=Limits(max_path_depth=3)
    ) == "UNSAFE_PATH"
    assert expect_refusal(
        ingest_directory, root, origin="x", limits=Limits(max_name_length=4)
    ) == "UNSAFE_PATH"
    assert expect_refusal(
        ingest_directory, root, origin="x", limits=Limits(max_path_length=5)
    ) == "UNSAFE_PATH"


def test_directory_entry_size_is_enforced(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "d", {"big.bin": b"x" * 600})
    assert expect_refusal(
        ingest_directory, root, origin="x", limits=Limits(max_entry_bytes=500)
    ) == "ENTRY_TOO_LARGE"


def test_directory_within_limits_is_unaffected(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "d", {"a/b.pas": "x", "c.pas": "y"})
    result = ingest_directory(root, origin="x", limits=Limits(max_entries=3))
    assert [f.path for f in result.files] == ["a/b.pas", "c.pas"]

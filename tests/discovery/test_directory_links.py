"""Directory inputs must be self-contained: links and junctions are refused.

Regression for a review finding: ``os.walk`` descends Windows junctions and
``Path.is_file`` follows file symlinks, so a link inside an allowed input
directory pulled out-of-tree bytes into the inventory (and the blueprint).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from enterprise.discovery.errors import IngestionError
from enterprise.discovery.model import ingest_directory, is_redirecting_entry, walk_files


@pytest.fixture()
def tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "a.pas").write_text("unit a;", encoding="utf-8")
    (outside / "secret.pas").write_text("unit secret;", encoding="utf-8")
    return root, outside


def _make_junction(link: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0 and link.exists()


def test_plain_tree_is_unaffected(tree) -> None:
    root, _ = tree
    assert [rel for rel, _ in walk_files(root)] == ["a.pas"]
    assert not is_redirecting_entry(root / "a.pas")


def test_junction_to_outside_directory_is_refused(tree) -> None:
    root, outside = tree
    if not _make_junction(root / "junc", outside):
        pytest.skip("junctions are only available on Windows")
    assert is_redirecting_entry(root / "junc")
    with pytest.raises(IngestionError) as caught:
        walk_files(root)
    assert caught.value.code == "SYMLINK_ENTRY"
    assert "secret" not in str(caught.value)


def test_junction_is_refused_by_ingest_directory(tree) -> None:
    root, outside = tree
    if not _make_junction(root / "junc", outside):
        pytest.skip("junctions are only available on Windows")
    with pytest.raises(IngestionError) as caught:
        ingest_directory(root, origin="x")
    assert caught.value.code == "SYMLINK_ENTRY"


def test_file_symlink_is_refused(tree) -> None:
    root, outside = tree
    try:
        os.symlink(outside / "secret.pas", root / "link.pas")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted here")
    with pytest.raises(IngestionError) as caught:
        walk_files(root)
    assert caught.value.code == "SYMLINK_ENTRY"


def test_directory_symlink_is_refused(tree) -> None:
    root, outside = tree
    try:
        os.symlink(outside, root / "linkdir", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted here")
    with pytest.raises(IngestionError):
        walk_files(root)


def test_skipped_prefix_is_not_inspected(tree) -> None:
    """A link inside an explicitly skipped directory (``.git``) is not walked."""

    root, outside = tree
    (root / ".git").mkdir()
    if not _make_junction(root / ".git" / "junc", outside):
        pytest.skip("junctions are only available on Windows")
    assert [rel for rel, _ in walk_files(root, skip=(".git",))] == ["a.pas"]

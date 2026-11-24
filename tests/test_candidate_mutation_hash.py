"""Layer 10: the before/after candidate source-tree hash detects a rewrite anywhere in the source, build outputs excepted.

The hash is recorded before and after build and execution (``source_tree_hash_before``/``_after``) and the evidence validator refuses a change.  Only the
top-level build-output directories are not source; a nested ``src/out/`` or ``src/build/`` is, so a rewrite there must move the hash.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine.pipeline import VerticalSlicePipeline


def _hash(root) -> str:
    pipeline = VerticalSlicePipeline.__new__(VerticalSlicePipeline)
    pipeline._config = SimpleNamespace(java_candidate_path=str(root), workload_id="w")
    return str(pipeline._candidate_source_tree_hash())


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "A.java").write_text("class A {}", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("nested", ["out", "build", "target", ".git", "node_modules", "__pycache__"])
def test_a_file_added_under_a_nested_directory_of_a_build_output_name_moves_the_hash(tree, nested):
    before = _hash(tree)
    (tree / "src" / nested).mkdir()
    (tree / "src" / nested / "Evil.java").write_text("class Evil {}", encoding="utf-8")
    assert _hash(tree) != before


@pytest.mark.parametrize("top", ["target", "build", "out", ".git"])
def test_the_top_level_build_output_directories_are_not_source(tree, top):
    before = _hash(tree)
    (tree / top).mkdir()
    (tree / top / "Artifact.class").write_bytes(b"\xca\xfe")
    assert _hash(tree) == before


def test_a_top_level_file_that_merely_has_a_build_output_name_is_source(tree):
    before = _hash(tree)
    (tree / "target").write_text("not a directory", encoding="utf-8")
    assert _hash(tree) != before


def test_editing_a_source_file_moves_the_hash(tree):
    before = _hash(tree)
    (tree / "src" / "A.java").write_text("class A { int x; }", encoding="utf-8")
    assert _hash(tree) != before


def test_the_hash_is_deterministic(tree):
    assert _hash(tree) == _hash(tree)

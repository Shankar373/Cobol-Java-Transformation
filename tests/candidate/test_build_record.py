"""Layer 10 L10-P2: the build-artifact record (content, rejection of anything but exactly one jar, binding to the generation)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from engine.candidate import build_record as br
from engine.modernization import generation_record as gr
from tests.test_candidate_generation_binding import generated

JAR = b"PK\x03\x04 a jar"


@pytest.fixture()
def project(tmp_path):
    return generated(tmp_path)


def test_the_record_names_the_jar_and_the_tree_it_was_built_from(project):
    record = dict(br.build_record({"app.jar": JAR}, project.generated_project_dir))
    assert sorted(record) == sorted(br.KEYS)
    assert record["artifact_digest"] == hashlib.sha256(JAR).hexdigest() and record["artifact_name"] == "app.jar"
    assert record["built_tree_digest"] == dict(project.generation_record)["output_digest"]
    assert br.shape_problems(tuple(record.items())) == []
    assert not br.disagrees_with_generation(tuple(record.items()), project.generation_record)


def test_a_built_project_still_derives_the_generated_tree(project):
    root = Path(project.generated_project_dir)
    (root / "target").mkdir()
    (root / "target" / "app.jar").write_bytes(JAR)
    assert dict(br.build_record({"app.jar": JAR}, root))["built_tree_digest"] == dict(project.generation_record)["output_digest"]


def test_the_record_is_deterministic_and_the_jar_bytes_move_it(project):
    first = br.build_record({"app.jar": JAR}, project.generated_project_dir)
    assert first == br.build_record({"app.jar": JAR}, project.generated_project_dir)
    assert first != br.build_record({"app.jar": JAR + b"!"}, project.generated_project_dir)


@pytest.mark.parametrize("class_files", [{}, {"Main.class": b"x"}, {"a.jar": JAR, "b.jar": JAR}, {"a.jar": JAR, "Main.class": b"x"},
                                         {"dir/app.jar": JAR}])
def test_anything_but_exactly_one_bare_jar_has_no_record(project, class_files):
    assert br.build_record(class_files, project.generated_project_dir) == ()


def test_an_unhashable_project_has_no_record(tmp_path):
    assert br.build_record({"app.jar": JAR}, tmp_path / "missing") == ()


def test_a_tree_other_than_the_recorded_generation_disagrees(project):
    victim = next(Path(project.generated_project_dir).rglob("*.java"))
    victim.write_text(victim.read_text(encoding="utf-8") + "// x\n", encoding="utf-8")
    record = br.build_record({"app.jar": JAR}, project.generated_project_dir)
    assert br.disagrees_with_generation(record, project.generation_record)
    assert not br.disagrees_with_generation(record, ())  # nothing recorded, nothing to disagree with


@pytest.mark.parametrize("override", [{"artifact_digest": "nope"}, {"built_tree_digest": "A" * 64}, {"artifact_name": "app.zip"},
                                      {"artifact_name": "../app.jar"}, {"artifact_name": "x\\app.jar"}, {"artifact_name": ""}])
def test_malformed_values_are_problems(project, override):
    record = dict(br.build_record({"app.jar": JAR}, project.generated_project_dir))
    record.update(override)
    assert br.shape_problems(tuple(sorted(record.items())))


@pytest.mark.parametrize("pairs", [(), (("artifact_name", "a.jar"),), (("extra", "x"),)])
def test_a_missing_or_extra_key_is_a_problem(pairs):
    assert br.shape_problems(pairs)


def test_the_build_record_reads_no_clock_and_uses_the_generation_tree_algorithm():
    text = Path(br.__file__).read_text(encoding="utf-8")
    assert "datetime" not in text and "tree_digest" in text and gr.BUILD_OUTPUT_DIRS == frozenset({"target"})

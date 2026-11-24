"""Layer 9 L9-P2: the Java generation record (content, binding to the plan record, verification, pipeline survival).

Real ``UniversalModernizationPipeline`` runs (generation only: no Docker, no oracle, no LLM) for every runtime target.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from engine.modernization import generation_record as gr
from engine.modernization import plan_record as pr
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.transformation.generation_authority import runtime_class_name
from engine.transformation.runtime_registry import RUNTIME_KEYS
from tests.application_ir.test_l9_generation_authority import prog

REPO = Path(__file__).resolve().parents[2]
SOURCES = {"a_sub.cob": prog("SUB"), "driver.cob": prog("DRIVER", ("SUB",))}


def run(tmp_path: Path, runtime: str = "plain_java", sources: dict[str, str] | None = None, entry: str = "DRIVER"):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    for name, text in (sources or SOURCES).items():
        (src / name).write_text(text, encoding="utf-8")
    config = ModernizationConfig(source_dir=str(src), output_dir=str(out), application_id="l9", entrypoint=entry,
                                 docker_available=True, target_runtime=runtime)
    return UniversalModernizationPipeline(config).execute()


def rows(report, runtime: str = "plain_java"):
    return [(p, runtime_class_name(runtime, p)) for p in report.generated_program_ids]


def verify(report, **override):
    args = {"application_id": "l9", "plan": report.transformation_plan, "plan_pairs": report.plan_record,
            "program_classes": rows(report), "entry_class": "Driver", "target_runtime": "plain_java",
            "project_dir": report.generated_project_dir}
    args.update(override)
    return gr.verify_record(report.generation_record, args["application_id"], args["plan"], args["plan_pairs"],
                            args["program_classes"], args["entry_class"], args["target_runtime"], args["project_dir"])


@pytest.fixture()
def report(tmp_path):
    result = run(tmp_path)
    assert result.generation_success, result.generation_errors
    return result


def test_the_record_has_exactly_the_documented_keys_and_valid_values(report):
    values = dict(report.generation_record)
    assert sorted(values) == sorted(gr.KEYS) and list(report.generation_record) == sorted(report.generation_record)
    assert gr.shape_problems(report.generation_record) == []
    assert values["entry_program"] == "DRIVER" and values["entry_class"] == "Driver" and values["target_runtime"] == "plain_java"


def test_the_record_names_the_same_plan_as_the_plan_record(report):
    assert gr.disagreements_with_plan(report.generation_record, report.plan_record) == []
    assert dict(report.generation_record)["plan_digest"] == pr.plan_digest_of(report.transformation_plan)


def test_a_correct_record_verifies(report):
    assert verify(report) == []
    assert report.to_dict()["generation_record"] == dict(report.generation_record)


def test_the_output_digest_is_the_generation_hash_tool_tree_digest(report):
    spec = importlib.util.spec_from_file_location("generation_hashes_tool", REPO / "tools" / "generation_hashes.py")
    tool = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tool  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(tool)
    assert dict(report.generation_record)["output_digest"] == tool.hash_tree(Path(report.generated_project_dir))["tree_sha256"]


@pytest.mark.parametrize("runtime", RUNTIME_KEYS)
def test_every_runtime_records_its_own_tree_but_one_program_map(tmp_path, runtime):
    result = run(tmp_path, runtime)
    assert result.generation_success, result.generation_errors
    record = dict(result.generation_record)
    assert record["target_runtime"] == runtime and gr.shape_problems(result.generation_record) == []
    assert gr.verify_record(result.generation_record, "l9", result.transformation_plan, result.plan_record,
                            rows(result, runtime), "Driver", runtime, result.generated_project_dir) == []
    assert record["program_map_digest"] == gr.program_map_digest_of([("SUB", "Sub"), ("DRIVER", "Driver")])


def test_the_record_is_reproducible_across_directories(tmp_path_factory):
    first = run(tmp_path_factory.mktemp("one"))
    second = run(tmp_path_factory.mktemp("two"))
    assert first.generation_record == second.generation_record


def test_a_changed_generated_file_moves_the_output_digest_and_is_named(report):
    victim = next(Path(report.generated_project_dir).rglob("Sub.java"))
    victim.write_text(victim.read_text(encoding="utf-8") + "// tampered\n", encoding="utf-8")
    assert any(p.startswith("output_digest") for p in verify(report))


def test_an_added_or_removed_file_moves_the_output_digest(report):
    root = Path(report.generated_project_dir)
    (root / "extra.txt").write_text("x", encoding="utf-8")
    assert any(p.startswith("output_digest") for p in verify(report))
    (root / "extra.txt").unlink()
    assert verify(report) == []
    next(root.rglob("Sub.java")).unlink()
    assert any(p.startswith("output_digest") for p in verify(report))


@pytest.mark.parametrize("key", gr.KEYS)
def test_tampering_with_any_recorded_value_is_named(report, key):
    forged = tuple((k, ("other" if k in ("application_id", "entry_class", "entry_program", "target_runtime") else "e" * 64)
                    if k == key else v) for k, v in report.generation_record)
    problems = gr.verify_record(forged, "l9", report.transformation_plan, report.plan_record, rows(report), "Driver",
                                "plain_java", report.generated_project_dir)
    assert problems and any(key in p for p in problems)


@pytest.mark.parametrize("pairs", [(), (("plan_id", "x"),), (("extra", "x"),)])
def test_a_malformed_or_missing_record_fails_verification(report, pairs):
    assert gr.verify_record(pairs, "l9", report.transformation_plan, report.plan_record, rows(report), "Driver",
                            "plain_java", report.generated_project_dir)


def test_no_input_means_no_record(report):
    base = (report.transformation_plan, report.plan_record, rows(report), "Driver", "plain_java", report.generated_project_dir)

    def build(*override):
        args = list(base)
        for index, value in override:
            args[index] = value
        return gr.build_record("l9", args[0], args[1], args[2], args[3], args[4], args[5])

    assert build() == report.generation_record
    assert build((0, None)) == () and build((1, ())) == () and build((2, [])) == () and build((3, "")) == ()
    assert build((4, "tomcat")) == () and build((5, report.generated_project_dir + "-missing")) == ()
    assert gr.build_record("", *base) == () and gr.build_record("other", *base) == ()


def test_programs_that_are_not_the_approved_programs_yield_no_record(report):
    assert gr.build_record("l9", report.transformation_plan, report.plan_record, rows(report)[:1], "Driver", "plain_java",
                           report.generated_project_dir) == ()
    assert gr.build_record("l9", report.transformation_plan, report.plan_record, rows(report) + [("GHOST", "Ghost")], "Driver",
                           "plain_java", report.generated_project_dir) == ()


def test_a_tree_holding_a_symlink_yields_no_digest(tmp_path):
    (tmp_path / "real.txt").write_text("x", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert gr.tree_digest(tmp_path) == ""


def test_a_failed_generation_carries_no_record(tmp_path):
    result = run(tmp_path, sources={"a.cob": prog("A"), "b.cob": prog("B")}, entry="")  # two roots, no entry
    assert not result.generation_success and result.generation_record == ()
    assert result.to_dict()["generation_record"] == {}


def test_a_discarded_project_carries_no_record(tmp_path, monkeypatch):
    from engine.modernization import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "fail_closed_symbols", lambda text: ["UNSUPPORTED_X$"])
    result = run(tmp_path)
    assert not result.generation_success and result.generation_record == ()
    assert not Path(result.generated_project_dir or "/nonexistent").exists()
    shutil.rmtree(tmp_path / "out", ignore_errors=True)


def test_the_generation_record_is_a_function_of_the_plan_record(report):
    other = tuple((k, "f" * 64 if k == "plan_digest" else v) for k, v in report.plan_record)
    assert gr.build_record("l9", report.transformation_plan, other, rows(report), "Driver", "plain_java",
                           report.generated_project_dir) != report.generation_record
    assert dataclasses.is_dataclass(report)

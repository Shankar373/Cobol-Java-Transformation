"""Layer 9 L9-P3: deterministic output, valid assembly, program identity and boundaries, and consistency across runtime targets.

Real pipeline generation over the fixture corpus (generation only: no Docker, no oracle, no LLM).  The compile tests run the host's
``javac`` over the dependency-free targets (plain Java and the Jakarta-marked jar) and are skipped when no JDK is installed; the
framework targets are asserted structurally (their program classes and entry launcher) because compiling them needs the framework jars.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from engine.modernization import generation_record as gr
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.transformation.entrypoint import normalise
from engine.transformation.generation_authority import runtime_class_name
from engine.transformation.runtime_registry import RUNTIME_KEYS

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = json.loads((REPO / "docs" / "audits" / "generation_hashes.json").read_text(encoding="utf-8"))
GENERATED = sorted(app for app, runtimes in SNAPSHOT["apps"].items()
                   if all(r.get("status") == "generated" for r in runtimes.values()))
PROGRAM_CLASS = re.compile(r"^\s*(?:public\s+)?(?:final\s+)?class\s+(\w+)", re.MULTILINE)
JAVAC = shutil.which("javac")
#: Fixtures whose generated Java is known not to compile, with the recorded reason.  Strict: if one starts compiling the test fails
#: until it is removed from this table (docs/reports/EXACT_HEAD_ENTERPRISE_BASELINE.md: build-phase exit 1, verdict UNAVAILABLE).
KNOWN_UNCOMPILABLE = {
    "workload-studentproc": "the source cuts a data name at column 72, so GnuCOBOL rejects it and the generated Java names an undefined variable",
}


def _tool():
    spec = importlib.util.spec_from_file_location("generation_hashes_tool", REPO / "tools" / "generation_hashes.py")
    tool = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tool  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(tool)
    return tool


def generate(app: str, runtime: str, scratch: Path):
    """The generation the hash tool performs (same staging, same entry resolution), returning the whole report."""
    tool = _tool()
    source, output = scratch / "src", scratch / "out"
    source.mkdir(parents=True)
    output.mkdir(parents=True)
    tool._stage_source(REPO / "fixtures" / app / "cobol", source)
    config = ModernizationConfig(source_dir=str(source), output_dir=str(output), application_id=f"e2e-{app}",
                                 entrypoint=tool._resolve_entry(source, f"e2e-{app}"), docker_available=True,
                                 target_runtime=runtime)
    return UniversalModernizationPipeline(config).execute()


def test_the_corpus_is_large_enough_to_mean_something():
    assert len(GENERATED) >= 40


@pytest.mark.parametrize("app", GENERATED)
def test_the_certified_snapshot_tree_digest_is_the_recorded_output_digest(app, tmp_path):
    """The Layer 9 record and the 110-hash snapshot are the same fact (tree digest) about the same generation."""
    report = generate(app, "plain_java", tmp_path)
    assert report.generation_success, report.generation_errors
    assert dict(report.generation_record)["output_digest"] == SNAPSHOT["apps"][app]["plain_java"]["tree_sha256"]


@pytest.mark.skipif(JAVAC is None, reason="no JDK on this host")
@pytest.mark.parametrize("app", GENERATED)
def test_the_plain_java_project_of_every_generated_application_compiles(app, tmp_path):
    report = generate(app, "plain_java", tmp_path / "gen")
    sources = sorted(str(p) for p in (Path(report.generated_project_dir) / "src" / "main" / "java").rglob("*.java"))
    assert sources
    classes = tmp_path / "classes"
    classes.mkdir()
    done = subprocess.run([JAVAC, "-proc:none", "-nowarn", "-d", str(classes), *sources], capture_output=True, text=True, timeout=240)
    if app in KNOWN_UNCOMPILABLE:
        assert done.returncode != 0, f"{app} now compiles: remove it from KNOWN_UNCOMPILABLE ({KNOWN_UNCOMPILABLE[app]})"
    else:
        assert done.returncode == 0, done.stderr[-1500:]


@pytest.mark.skipif(JAVAC is None, reason="no JDK on this host")
@pytest.mark.parametrize("app", [a for a in GENERATED[::6] if a not in KNOWN_UNCOMPILABLE])
def test_the_jakarta_marked_project_compiles_too(app, tmp_path):
    report = generate(app, "jakarta_ee", tmp_path / "gen")
    sources = sorted(str(p) for p in (Path(report.generated_project_dir) / "src" / "main" / "java").rglob("*.java"))
    classes = tmp_path / "classes"
    classes.mkdir()
    done = subprocess.run([JAVAC, "-proc:none", "-nowarn", "-d", str(classes), *sources], capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr[-1500:]


@pytest.mark.parametrize("runtime", RUNTIME_KEYS)
@pytest.mark.parametrize("app", GENERATED[::5])
def test_generation_is_byte_reproducible_for_every_runtime(app, runtime, tmp_path):
    first = generate(app, runtime, tmp_path / "one")
    second = generate(app, runtime, tmp_path / "two")
    assert first.generation_success and second.generation_success
    assert first.generation_record == second.generation_record
    assert dict(first.generation_record)["output_digest"] == dict(second.generation_record)["output_digest"]


def _declared_classes(project: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(project.rglob("*.java")):
        for name in PROGRAM_CLASS.findall(path.read_text(encoding="utf-8")):
            counts[name] = counts.get(name, 0) + 1
    return counts


@pytest.mark.parametrize("app", GENERATED[::4])
def test_every_runtime_preserves_each_programs_identity_and_boundary(app, tmp_path):
    """One class per COBOL program, named by the one program-id rule, declared once, in every runtime target."""
    for runtime in RUNTIME_KEYS:
        namer = lambda program, runtime=runtime: runtime_class_name(runtime, program)  # noqa: E731
        report = generate(app, runtime, tmp_path / runtime)
        assert report.generation_success, (runtime, report.generation_errors)
        declared = _declared_classes(Path(report.generated_project_dir))
        approved = [c.component_id for c in report.transformation_plan.components
                    if c.component_type == "PROGRAM" and c.action.value == "TRANSFORM"]
        for program in approved:
            assert declared.get(namer(program), 0) >= 1, (runtime, program)
        names = [namer(p) for p in approved]
        if len(set(names)) == len(names):
            assert all(declared[name] == 1 for name in names), (runtime, declared)


@pytest.mark.parametrize("app", GENERATED[::4])
def test_all_runtimes_are_generated_from_one_plan_and_one_entry(app, tmp_path):
    records = {}
    for runtime in RUNTIME_KEYS:
        report = generate(app, runtime, tmp_path / runtime)
        records[runtime] = (dict(report.generation_record), report.transformation_plan)
    entries = {normalise(r["entry_program"]) for r, _plan in records.values()}
    digests = {r["plan_digest"] for r, _plan in records.values()} - {""}
    assert len(entries) == 1
    # the plan's assembly target legitimately differs per runtime (it names the output type); nothing else may
    assert len({tuple((c.component_id, c.component_type, c.action.value, c.priority) for c in plan.components)
                for _r, plan in records.values()}) == 1
    assert len(digests) == len({plan.assembly.output_type for _r, plan in records.values()})
    program_ids = [c.component_id for c in next(iter(records.values()))[1].components if c.component_type == "PROGRAM"]
    for runtime, (record, _plan) in records.items():
        expected = gr.program_map_digest_of([(p, runtime_class_name(runtime, p)) for p in program_ids])
        assert record["program_map_digest"] == expected, runtime

"""Layer 10 L10-P1: the build lane validates only the project Layer 9 recorded.

Unit (the binding rule, build outputs excluded), mutation (a tampered, extended or truncated project) and end to end through the real
API service with the candidate lane doubled (the compile call is observed: a refused candidate is never handed to the builder).
"""

# ruff: noqa: F811  (the imported `service` fixture is redefined by each test parameter)
from __future__ import annotations

from pathlib import Path

import pytest

import api.service as service_module
from api.service import Service
from engine.modernization import generation_record as gr
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from tests.application_ir.test_l9_generation_authority import prog
from tests.comparison_doubles import Candidate, Oracle
from tests.test_library_order_profile_api import _application, _estate_root, _run, service  # the `service` fixture is imported, then used as a parameter


def generated(tmp_path: Path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    (src / "main.cob").write_text(prog("MAIN"), encoding="utf-8")
    report = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(src), output_dir=str(out), application_id="l10", entrypoint="MAIN", docker_available=True,
        target_runtime="plain_java")).execute()
    assert report.generation_success, report.generation_errors
    return report


# ---- unit ---------------------------------------------------------------------------------------------------------------------

def test_the_project_generation_recorded_is_bound(tmp_path):
    report = generated(tmp_path)
    assert gr.generation_binding_problem(report.generation_record, report.generated_project_dir) == ""


def test_there_is_nothing_to_bind_without_a_record(tmp_path):
    assert gr.generation_binding_problem((), tmp_path) == ""


def test_build_outputs_are_not_part_of_the_generated_tree(tmp_path):
    report = generated(tmp_path)
    target = Path(report.generated_project_dir) / "target" / "classes"
    target.mkdir(parents=True)
    (target / "Main.class").write_bytes(b"\xca\xfe")
    assert gr.generation_binding_problem(report.generation_record, report.generated_project_dir) == ""
    assert gr.tree_digest(report.generated_project_dir) != dict(report.generation_record)["output_digest"]  # unexcluded differs


@pytest.mark.parametrize("fault", ["edit", "add", "remove", "nested-target", "rename"])
def test_any_change_to_the_generated_project_is_refused(tmp_path, fault):
    report = generated(tmp_path)
    root = Path(report.generated_project_dir)
    java = next(root.rglob("*.java"))
    if fault == "edit":
        java.write_text(java.read_text(encoding="utf-8") + "// x\n", encoding="utf-8")
    elif fault == "add":
        (root / "Extra.java").write_text("class Extra {}", encoding="utf-8")
    elif fault == "remove":
        java.unlink()
    elif fault == "nested-target":  # only the TOP-LEVEL target directory is a build output
        (root / "src" / "target").mkdir()
        (root / "src" / "target" / "Sneaky.java").write_text("class Sneaky {}", encoding="utf-8")
    else:
        java.rename(java.with_name("Renamed.java"))
    problem = gr.generation_binding_problem(report.generation_record, report.generated_project_dir)
    assert problem.startswith("Candidate project does not match its recorded generation")


def test_a_missing_project_is_refused(tmp_path):
    report = generated(tmp_path)
    assert "cannot be hashed" in gr.generation_binding_problem(report.generation_record, tmp_path / "nowhere")


def test_a_symlink_in_the_project_is_refused(tmp_path):
    report = generated(tmp_path)
    root = Path(report.generated_project_dir)
    try:
        (root / "link.txt").symlink_to(next(root.rglob("*.java")))
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert "cannot be hashed" in gr.generation_binding_problem(report.generation_record, root)


# ---- end to end through the service --------------------------------------------------------------------------------------------

class SpyCandidate(Candidate):
    compiled = 0

    def compile(self, candidate_path, manifest):
        type(self).compiled += 1
        return super().compile(candidate_path, manifest)


def _validate(service, tmp_path, monkeypatch, tamper):
    app = _application(service, _estate_root(tmp_path))
    run = _run(service, app)
    project, entry = service._generate_application(app, run)
    if tamper:
        victim = next(Path(project).rglob("*.java"))
        victim.write_text(victim.read_text(encoding="utf-8") + "\n// tampered after generation\n", encoding="utf-8")
    SpyCandidate.compiled = 0

    class EntryOracle(Oracle):
        def execute(self, run_id, source_path, input_data=None, input_files=None, **_ignored):
            return super().execute(run_id, source_path, input_data, input_files)

    class Doubled(service_module.VerticalSlicePipeline):
        def __init__(self, config, candidate_adapter=None, registry=None):
            super().__init__(config, candidate_adapter=SpyCandidate(b"HI\n", None, 0), registry=registry)
            self._oracle_adapter = EntryOracle(b"HI\n", None, 0)

    monkeypatch.setattr(service_module, "VerticalSlicePipeline", Doubled)
    monkeypatch.setattr(Service, "_run_job_lane", lambda *a, **k: None)
    monkeypatch.setattr(Service, "_persist_integrated_proof", lambda *a, **k: None)
    service._run_validation(app, run, Path(project), entry)
    return service._store.get_run(run.id)


def test_an_untouched_project_reaches_the_builder(service, tmp_path, monkeypatch):
    run = _validate(service, tmp_path, monkeypatch, tamper=False)
    assert SpyCandidate.compiled == 1 and run.evidence_manifest.java_generation


def test_a_project_changed_after_generation_never_reaches_the_builder(service, tmp_path, monkeypatch):
    run = _validate(service, tmp_path, monkeypatch, tamper=True)
    assert SpyCandidate.compiled == 0
    assert run.verdict.state.value == "ERROR"  # an unverifiable candidate, never a comparison
    candidate = next(e for e in run.evidence_manifest.execution_evidence if e.execution_phase == "BUILD")
    assert candidate.termination_status == "error" and candidate.exit_code is None and candidate.execution_phase == "BUILD"

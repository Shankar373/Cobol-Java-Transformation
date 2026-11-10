"""Roadmap unit 40 oracle: the job lane runs pipeline-generated JCL runners against the GnuCOBOL reference driver.

``fixtures/enterprise/payroll-batch`` has four programs and five jobs: a nightly chain whose COND tests bypass one
step, a recovery job after a return code of 12 (a bypass, a run and an ``OLD,DELETE`` allocation), a copy job
(IEBGENER, a passed temporary dataset, inline ``DD *`` data), a job that fails with a JCL error (exit status 255) and a
job outside the certified subset (IF/THEN/ELSE: no runner, never verified). Each supported job runs for three Java
targets. Output, exit status and dataset bytes must equal the reference run on every one of them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from engine.jcl.job_lane import MISMATCH, UNAVAILABLE, VERIFIED, verify_jobs
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from tests.integration.test_jcl_orchestrator_oracle import _needs_docker

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "enterprise" / "payroll-batch"

EXPECTED = {
    "NIGHTLY": (VERIFIED, 4, [
        "JCL step STEP10 RC=0", "JCL step STEP20 RC=4", "JCL step STEP30 BYPASSED", "JCL step STEP40 RC=0",
        "JCL job NIGHTLY MAXRC=4"], ["PAY.IN", "PAY.OUT", "PAY.SEED"]),
    "RECOVER": (VERIFIED, 12, [
        "JCL step STEP1 RC=12", "JCL step STEP2 BYPASSED", "JCL step STEP3 RC=0", "JCL step STEP4 RC=0",
        "JCL job RECOVER MAXRC=12"], []),
    "COPYJOB": (VERIFIED, 0, [
        "JCL step CP1 RC=0", "JCL step RPT RC=0", "JCL step CP2 RC=0", "JCL step RPT2 RC=0",
        "JCL job COPYJOB MAXRC=0"], ["PAY.INLINE", "PAY.SEED"]),
    "BADREF": (VERIFIED, 255, [
        "JCL step S1 RC=0", "JCL ERROR dataset NO.SUCH.DATASET (DD INDD) not found"], ["PAY.SEED"]),
}


def _generate(tmp_path: Path, runtime: str):
    report = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(FIXTURE), output_dir=str(tmp_path / "out"), entrypoint="RPTPRT", target_runtime=runtime,
        docker_available=True)).execute()
    assert report.generation_success, report.generation_errors
    return report


@pytest.mark.parametrize("runtime", ["plain_java", "quarkus", "micronaut"])
def test_every_supported_job_matches_the_reference_run(tmp_path, runtime):
    _needs_docker()
    report = _generate(tmp_path, runtime)
    results = {r.job: r for r in verify_jobs(FIXTURE, report.generated_project_dir, report.jcl_jobs)}
    assert set(results) == set(EXPECTED) | {"UNSUPP"}
    for job, (verdict, status, steps, datasets) in EXPECTED.items():
        result = results[job]
        assert result.verdict == verdict, (job, result.reasons)
        assert (result.exit_status, list(result.steps), list(result.datasets)) == (status, steps, datasets), job
    # outside the certified subset: no runner, so nothing to verify and nothing claimed
    assert results["UNSUPP"].verdict == UNAVAILABLE and "IF/THEN/ELSE" in results["UNSUPP"].reasons[0]


def test_a_defective_runner_is_caught(tmp_path):
    _needs_docker()
    report = _generate(tmp_path, "plain_java")
    runner = Path(report.generated_project_dir) / "src" / "main" / "java" / "JobNightlyRunner.java"
    source = runner.read_text(encoding="utf-8")
    assert "case \"LT\": return code < rc;" in source
    runner.write_text(source.replace("case \"LT\": return code < rc;", "case \"LT\": return code > rc;"),
                      encoding="utf-8")
    results = {r.job: r for r in verify_jobs(FIXTURE, report.generated_project_dir, report.jcl_jobs)}
    assert results["NIGHTLY"].verdict == MISMATCH
    assert any("standard output differs" in reason for reason in results["NIGHTLY"].reasons)
    assert results["COPYJOB"].verdict == VERIFIED  # the other jobs do not use the defective test


def test_a_dataset_difference_is_caught(tmp_path):
    _needs_docker()
    source = tmp_path / "src"
    shutil.copytree(FIXTURE, source)
    report = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(source), output_dir=str(tmp_path / "out"), entrypoint="RPTPRT", target_runtime="plain_java",
        docker_available=True)).execute()
    runner = Path(report.generated_project_dir) / "src" / "main" / "java" / "JobCopyjobRunner.java"
    text = runner.read_text(encoding="utf-8")
    needle = "Files.copy(in, out, StandardCopyOption.REPLACE_EXISTING);\n                return 0;"
    assert needle in text
    runner.write_text(text.replace(needle, "Files.createFile(out.resolveSibling(out.getFileName() + \".x\"));\n"
                                   "                return 0;", 1), encoding="utf-8")
    result = {r.job: r for r in verify_jobs(source, report.generated_project_dir, report.jcl_jobs)}["COPYJOB"]
    assert result.verdict == MISMATCH

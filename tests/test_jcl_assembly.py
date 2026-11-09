"""Roadmap unit 39: JCL job runners are generated with the application (command-line runtimes)."""

from __future__ import annotations

import shutil
from pathlib import Path

from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "enterprise" / "app-jcl-job"


def _run(tmp_path: Path, source: Path, runtime: str, entry: str = "PRODUCER"):
    config = ModernizationConfig(
        source_dir=str(source), output_dir=str(tmp_path / "out"), entrypoint=entry, target_runtime=runtime,
        docker_available=True)
    return UniversalModernizationPipeline(config).execute()


def test_a_runnable_job_gets_a_runner_in_the_generated_project(tmp_path):
    report = _run(tmp_path, FIXTURE, "plain_java")
    assert report.generation_success, report.generation_errors
    (job,) = report.jcl_jobs
    assert job.job == "SEQJOB" and job.runnable and job.runner_class == "JobSeqjobRunner"
    runner = Path(report.generated_project_dir) / "src" / "main" / "java" / "JobSeqjobRunner.java"
    text = runner.read_text(encoding="utf-8")
    assert '"Producer"' in text and '"Consumer"' in text  # the generated main classes of the two programs
    assert report.to_dict()["assembly"]["jcl_jobs"][0]["runnable"] is True


def test_every_command_line_runtime_carries_the_runner(tmp_path):
    for runtime in ("quarkus", "micronaut"):
        report = _run(tmp_path / runtime, FIXTURE, runtime)
        assert report.generation_success and report.jcl_jobs[0].runnable, runtime


def test_spring_boot_reports_that_it_has_no_runner(tmp_path):
    report = _run(tmp_path, FIXTURE, "spring_boot")
    assert report.generation_success and report.jcl_jobs == ()
    assert any("JCL job runner is generated only" in text for text in report.limitations)


def test_a_job_outside_the_certified_subset_is_reported_with_its_refusals(tmp_path):
    source = tmp_path / "src"
    shutil.copytree(FIXTURE, source)
    (source / "jcl" / "BAD.jcl").write_text(
        "//BADJOB   JOB CLASS=A\n//S1       EXEC PGM=NOSUCH\n", encoding="utf-8")
    report = _run(tmp_path, source, "plain_java")
    by_name = {job.job: job for job in report.jcl_jobs}
    assert by_name["SEQJOB"].runnable
    assert not by_name["BADJOB"].runnable and by_name["BADJOB"].refusals
    assert any("JCL job BADJOB has no generated runner" in text for text in report.limitations)
    assert not (Path(report.generated_project_dir) / "src" / "main" / "java" / "JobBadjobRunner.java").exists()


def test_two_jobs_of_one_name_get_no_runner(tmp_path):
    source = tmp_path / "src"
    shutil.copytree(FIXTURE, source)
    shutil.copy(source / "jcl" / "SEQJOB.jcl", source / "jcl" / "COPY.jcl")
    report = _run(tmp_path, source, "plain_java")
    assert [job.runnable for job in report.jcl_jobs] == [False, False]
    assert all("defined more than once" in job.refusals[-1] for job in report.jcl_jobs)


def test_an_application_without_jcl_is_unchanged(tmp_path):
    source = tmp_path / "src"
    (source).mkdir()
    shutil.copy(FIXTURE / "cobol" / "PRODUCER.cob", source / "PRODUCER.cob")
    report = _run(tmp_path, source, "plain_java")
    assert report.generation_success and report.jcl_jobs == ()

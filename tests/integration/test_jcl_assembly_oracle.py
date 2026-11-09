"""Roadmap unit 39 oracle: the job runner the pipeline generates equals the GnuCOBOL reference run.

The pipeline assembles ``fixtures/enterprise/app-jcl-job`` (two programs and a three-step job with a COND bypass); the
generated project is compiled and its runner executed on a JVM; the same job runs as shell steps over the
GnuCOBOL-compiled programs. Output, the highest return code (exit status) and the dataset bytes must match.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from tests.integration.test_jcl_orchestrator_oracle import (
    JAVA_IMAGE,
    ORACLE_IMAGE,
    REFERENCE,
    _docker,
    _needs_docker,
    _prepare,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "enterprise" / "app-jcl-job"


def test_the_generated_runner_matches_the_reference_run(tmp_path):
    _needs_docker()
    report = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(FIXTURE), output_dir=str(tmp_path / "out"), entrypoint="PRODUCER",
        target_runtime="plain_java", docker_available=True)).execute()
    assert report.generation_success, report.generation_errors
    (job,) = report.jcl_jobs
    assert job.runnable, job.refusals

    cobol_dir, java_dir = tmp_path / "cobol", tmp_path / "java"
    _prepare(cobol_dir)
    _prepare(java_dir)
    for name in ("PRODUCER", "CONSUMER"):
        shutil.copy(FIXTURE / "cobol" / f"{name}.cob", cobol_dir / "src" / f"{name}.cob")
    (cobol_dir / "ref.sh").write_text(REFERENCE, encoding="utf-8", newline="\n")
    for source in (Path(report.generated_project_dir) / "src" / "main" / "java").glob("*.java"):
        shutil.copy(source, java_dir / "src" / source.name)

    cobol = _docker(
        ORACLE_IMAGE, cobol_dir,
        "cobc -x /w/src/PRODUCER.cob -o /tmp/producer && cobc -x /w/src/CONSUMER.cob -o /tmp/consumer"
        " && sh /w/ref.sh")
    java = _docker(
        JAVA_IMAGE, java_dir,
        f"mkdir -p /tmp/c && javac -nowarn -d /tmp/c /w/src/*.java && java -cp /tmp/c {job.runner_class} /w/data /tmp/c")
    assert cobol.returncode == 4 and java.returncode == 4, (cobol.stderr, java.stderr)
    assert java.stdout == cobol.stdout
    assert (java_dir / "data" / "HR.DATA").read_bytes() == (cobol_dir / "data" / "HR.DATA").read_bytes()
    assert os.environ.get("RUN_DOCKER_TESTS") == "1"

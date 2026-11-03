"""Shared steps for oracle-pinned semantic tests.

``run_generated_java`` transforms a COBOL source with the producer, compiles
and runs the Java (skipped without a JDK on the hermetic lane, a failure on
the Docker lane); ``run_gnucobol`` compiles and runs the source on the
GnuCOBOL 3.1.2 oracle image (Docker lane only).  Both return stdout.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.producer import TransformationProducer

ORACLE_IMAGE = "gnucobol-ocesql:latest"


def run_generated_java(source: str, program_id: str, tmp_path: Path) -> str:
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    result = TransformationProducer().transform(source, program_id)
    assert result.success is True, result.errors
    for generated in result.generated_files:
        (tmp_path / generated.filename).write_text(generated.source_code, encoding="utf-8")
    compiled = subprocess.run(
        ["javac", "-nowarn", "-d", str(tmp_path),
         *[str(tmp_path / g.filename) for g in result.generated_files]],
        capture_output=True, timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    run = subprocess.run(
        ["java", "-Dline.separator=\n", "-cp", str(tmp_path),
         result.generated_files[0].class_name],
        capture_output=True, timeout=60, cwd=tmp_path,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return run.stdout.decode()


def run_gnucobol(source: str, program_id: str, tmp_path: Path) -> str:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    (tmp_path / f"{program_id}.cob").write_text(source, encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src",
         ORACLE_IMAGE, "sh", "-c",
         f"cd /tmp && cobc -x /src/{program_id}.cob -o p && ./p"],
        capture_output=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return run.stdout.decode()

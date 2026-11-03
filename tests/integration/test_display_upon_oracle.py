"""DISPLAY ... UPON <device> (found while removing the legacy lanes, T5).

Only ``UPON STDERR`` was recognised. ``UPON SYSERR`` on the DISPLAY line
went to stdout, and on a continuation line became two operands (``UPON``,
``SYSERR``), so CLAIMS_SYSERR failed at javac only by accident. GnuCOBOL
3.1.2 sends STDERR and SYSERR to stderr and STDOUT, SYSOUT and CONSOLE to
stdout; any other device fails closed.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from engine.transformation.producer import TransformationProducer
from tests.oracle_java_helpers import ORACLE_IMAGE

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UPON.
       PROCEDURE DIVISION.
           DISPLAY "A-STDERR" UPON STDERR
           DISPLAY "B-SYSERR" UPON SYSERR
           DISPLAY "C-SYSOUT" UPON SYSOUT
           DISPLAY "D-CONSOLE" UPON CONSOLE
           DISPLAY "E-STDOUT" UPON STDOUT
           DISPLAY "F-CONT"
               UPON SYSERR
           STOP RUN.
"""

STDOUT = "C-SYSOUT\nD-CONSOLE\nE-STDOUT\n"
STDERR = "A-STDERR\nB-SYSERR\nF-CONT\n"


def test_generated_java_routes_each_device(tmp_path):
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    result = TransformationProducer().transform(SOURCE, "UPON")
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
    assert run.returncode == 0
    assert run.stdout.decode() == STDOUT
    assert run.stderr.decode() == STDERR


def test_oracle_agrees(tmp_path):
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    (tmp_path / "UPON.cob").write_text(SOURCE, encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src",
         ORACLE_IMAGE, "sh", "-c", "cd /tmp && cobc -x /src/UPON.cob -o p && ./p"],
        capture_output=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == STDOUT
    assert run.stderr.decode() == STDERR


@pytest.mark.parametrize("device", ["PRINTER", "SYSPUNCH"])
def test_unknown_device_fails_closed(device):
    source = SOURCE.replace("UPON SYSOUT", f"UPON {device}")
    result = TransformationProducer().transform(source, "UPON")
    assert result.success is False

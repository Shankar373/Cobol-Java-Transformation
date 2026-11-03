"""MOVE of space-padded digits into a numeric item (T5 parity, oracle-pinned).

UNSTRING leaves right-justified amounts such as ``"  200"`` in PIC X fields;
the claims program then MOVEs them into numeric items. The generated Java
aborted on any non-digit content. GnuCOBOL 3.1.2 reads leading spaces as
zeros (all spaces gives 0):

    [  200] N5=00200 N3=200 N7=0000200 D=200.00 T=0000200
    [    7] N5=00007 N3=007 N7=0000007 D=007.00 T=0000007
    [     ] N5=00000 N3=000 N7=0000000 D=000.00 T=0000000

Embedded or trailing spaces (``" 2 00"`` also gives 00200 on the oracle)
follow a rule this lowering does not reproduce and stay fail-closed.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from engine.transformation.producer import TransformationProducer
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SPMOV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-SRC     PIC X(5).
       01 WS-N5      PIC 9(5).
       01 WS-N3      PIC 9(3).
       01 WS-N7      PIC 9(7).
       01 WS-D       PIC 9(3)V99.
       01 WS-T       PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
           MOVE "  200" TO WS-SRC
           PERFORM SHOW
           MOVE "    7" TO WS-SRC
           PERFORM SHOW
           MOVE "12345" TO WS-SRC
           PERFORM SHOW
           MOVE "     " TO WS-SRC
           PERFORM SHOW
           STOP RUN.
       SHOW.
           MOVE WS-SRC TO WS-N5
           MOVE WS-SRC TO WS-N3
           MOVE WS-SRC TO WS-N7
           MOVE WS-SRC TO WS-D
           MOVE 0 TO WS-T
           ADD WS-N5 TO WS-T
           DISPLAY "[" WS-SRC "] N5=" WS-N5 " N3=" WS-N3 " N7=" WS-N7
               " D=" WS-D " T=" WS-T.
"""

EXPECTED = (
    "[  200] N5=00200 N3=200 N7=0000200 D=200.00 T=0000200\n"
    "[    7] N5=00007 N3=007 N7=0000007 D=007.00 T=0000007\n"
    "[12345] N5=12345 N3=345 N7=0012345 D=345.00 T=0012345\n"
    "[     ] N5=00000 N3=000 N7=0000000 D=000.00 T=0000000\n"
)


def test_generated_java_reads_leading_spaces_as_zeros(tmp_path):
    assert run_generated_java(SOURCE, "SPMOV", tmp_path) == EXPECTED


def test_oracle_agrees(tmp_path):
    assert run_gnucobol(SOURCE, "SPMOV", tmp_path) == EXPECTED


@pytest.mark.parametrize("content", ["2 00 ", " 2 00", "200  ", " -200", "  2A0"])
def test_other_content_still_aborts(tmp_path, content):
    if not (shutil.which("javac") and shutil.which("java")):
        pytest.skip("javac/java not on PATH")
    source = SOURCE.replace('MOVE "  200" TO WS-SRC', f'MOVE "{content}" TO WS-SRC')
    result = TransformationProducer().transform(source, "SPMOV")
    assert result.success is True, result.errors
    for generated in result.generated_files:
        (tmp_path / generated.filename).write_text(generated.source_code, encoding="utf-8")
    subprocess.run(
        ["javac", "-nowarn", "-d", str(tmp_path),
         *[str(tmp_path / g.filename) for g in result.generated_files]],
        check=True, capture_output=True, timeout=120,
    )
    run = subprocess.run(
        ["java", "-cp", str(tmp_path), result.generated_files[0].class_name],
        capture_output=True, timeout=60, cwd=tmp_path,
    )
    assert run.returncode != 0
    assert b"only leading spaces and digits are certified" in run.stderr

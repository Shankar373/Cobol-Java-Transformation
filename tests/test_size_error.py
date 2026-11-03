"""[NOT] ON SIZE ERROR on the arithmetic verbs (Phase 3, increment 8).

GnuCOBOL 3.1.2, measured (pins below; the Docker test re-derives them):

* a result needing more integer digits than the receiver — after ROUNDED,
  if given — is a size error: the receiver keeps its value and the
  ON SIZE ERROR body runs; otherwise the result is stored and the
  NOT ON SIZE ERROR body runs;
* a zero divisor is a size error;
* truncated fraction digits are not; a negative result stored into an
  unsigned receiver keeps its magnitude and is not one either.

The phrase used to be refused on every verb.  It is parsed into
``size_error_body`` / ``not_size_error_body`` (inline, on following lines,
up to END-<verb> or the period) and lowered by ``_emit_arithmetic``.

Building it exposed defects in the shared clause collector, fixed for the
file verbs too:

* ``AT END … NOT AT END …`` on one line put both bodies under AT END;
* a body statement followed by the scope terminator on the same line
  (``DISPLAY 'K' END-READ``) swallowed the terminator, and the scope ran on
  into the following statements;
* a DISPLAY in an ON SIZE ERROR body read the next ``NOT ON SIZE ERROR``
  line as four operands.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import CobolApplication, CobolProgramUnit
from engine.transformation.producer import TransformationProducer

ORACLE_IMAGE = "gnucobol-ocesql:latest"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIZEERR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X      PIC S9(4) VALUE 9990.
       01  WS-A      PIC 9(4) VALUE 5000.
       01  WS-B      PIC 9(4) VALUE 3.
       01  WS-R      PIC 9(4) VALUE 7.
       01  WS-Q      PIC 9(4) VALUE 7.
       01  WS-Z      PIC 9(4) VALUE 0.
       01  WS-D      PIC 9(3)V9 VALUE 0.
       01  WS-U      PIC 9(2) VALUE 5.
       01  WS-M      PIC 9(3) VALUE 400.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           ADD 20 TO WS-X
               ON SIZE ERROR DISPLAY 'S1 SIZE ' WS-X
               NOT ON SIZE ERROR DISPLAY 'S1 OK ' WS-X
           END-ADD
           ADD 5 TO WS-X
               ON SIZE ERROR DISPLAY 'S2 SIZE ' WS-X
               NOT ON SIZE ERROR DISPLAY 'S2 OK ' WS-X
           END-ADD
           COMPUTE WS-R = WS-A * WS-B
               ON SIZE ERROR DISPLAY 'S3 SIZE ' WS-R
           END-COMPUTE
           DIVIDE WS-A BY WS-Z GIVING WS-Q
               ON SIZE ERROR DISPLAY 'S4 SIZE ' WS-Q
               NOT ON SIZE ERROR DISPLAY 'S4 OK ' WS-Q
           END-DIVIDE
           COMPUTE WS-D = 12.345
               ON SIZE ERROR DISPLAY 'S5 SIZE ' WS-D
               NOT ON SIZE ERROR DISPLAY 'S5 OK ' WS-D
           END-COMPUTE
           COMPUTE WS-R ROUNDED = 9999.5
               ON SIZE ERROR DISPLAY 'S6 SIZE ' WS-R
               NOT ON SIZE ERROR DISPLAY 'S6 OK ' WS-R
           END-COMPUTE
           SUBTRACT 10 FROM WS-U
               ON SIZE ERROR DISPLAY 'S7 SIZE ' WS-U
               NOT ON SIZE ERROR DISPLAY 'S7 OK ' WS-U
           END-SUBTRACT
           MULTIPLY 3 BY WS-M
               ON SIZE ERROR DISPLAY 'S8 SIZE ' WS-M
               NOT ON SIZE ERROR DISPLAY 'S8 OK ' WS-M
           END-MULTIPLY
           SUBTRACT 1 FROM WS-B GIVING WS-R
               ON SIZE ERROR DISPLAY 'S9 SIZE ' WS-R
               NOT ON SIZE ERROR DISPLAY 'S9 OK ' WS-R
           END-SUBTRACT
           DIVIDE 7 INTO WS-A
               ON SIZE ERROR DISPLAY 'S10 SIZE ' WS-A
               NOT ON SIZE ERROR DISPLAY 'S10 OK ' WS-A
           END-DIVIDE
           ADD 1 TO WS-X ON SIZE ERROR DISPLAY 'S11 SIZE'.
           DISPLAY 'S11 AFTER ' WS-X
           ADD 1 TO WS-U SIZE ERROR DISPLAY 'S' NOT SIZE ERROR
               DISPLAY 'S12 ' WS-U END-ADD
           STOP RUN.
"""

EXPECTED = (
    "S1 SIZE +9990\n"
    "S2 OK +9995\n"
    "S3 SIZE 0007\n"
    "S4 SIZE 0007\n"
    "S5 OK 012.3\n"
    "S6 SIZE 0007\n"
    "S7 OK 05\n"
    "S8 SIZE 400\n"
    "S9 OK 0002\n"
    "S10 OK 0714\n"
    "S11 AFTER +9996\n"
    "S12 06\n"
)


#: Without the phrase (Phase 3, increment 9): a zero divisor anywhere in the
#: statement leaves every receiver unchanged — REMAINDER too — and the run
#: continues (GnuCOBOL 3.1.2); the generated Java threw ArithmeticException.
DIVIDE_BY_ZERO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIVZ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A      PIC 9(4) VALUE 100.
       01  WS-Z      PIC 9(4) VALUE 0.
       01  WS-DZ     PIC 9V99 VALUE 0.
       01  WS-Q      PIC 9(4) VALUE 7.
       01  WS-R      PIC 9(4) VALUE 8.
       01  WS-D      PIC 9(3)V99 VALUE 1.5.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DIVIDE WS-A BY WS-Z GIVING WS-Q
           DISPLAY 'D1 ' WS-Q
           DIVIDE WS-Z INTO WS-A
           DISPLAY 'D2 ' WS-A
           COMPUTE WS-Q = WS-A / WS-Z
           DISPLAY 'D3 ' WS-Q
           COMPUTE WS-Q = (WS-A / WS-Z) + 1
           DISPLAY 'D4 ' WS-Q
           COMPUTE WS-D = WS-A / WS-DZ
           DISPLAY 'D5 ' WS-D
           DIVIDE WS-A BY WS-Z GIVING WS-Q REMAINDER WS-R
           DISPLAY 'D6 ' WS-Q ' ' WS-R
           COMPUTE WS-Q = WS-A / 4
           DISPLAY 'D7 ' WS-Q
           STOP RUN.
"""
DIVIDE_BY_ZERO_EXPECTED = (
    "D1 0007\nD2 0100\nD3 0007\nD4 0007\nD5 001.50\nD6 0007 0008\nD7 0025\n"
)

CASES = {
    "size_error": (SOURCE, "SIZEERR", EXPECTED),
    "divide_by_zero_without_phrase": (DIVIDE_BY_ZERO, "DIVZ", DIVIDE_BY_ZERO_EXPECTED),
}


def _level(source: str) -> tuple[CapabilityLevel, str]:
    unit = CobolProgramUnit(program_id="S", source_path="S.cob",
                            program=CobolParser().parse(source), source_text=source)
    report = CapabilityAnalyzer(docker_available=True).analyze(
        CobolApplication(application_id="T", programs=(unit,)))
    program = next(c for c in report.components if c.component_type == "PROGRAM")
    return program.level, program.reason


def _statements(source: str):
    parser = CobolParser()
    program = parser.parse(source)
    return program.paragraphs[0].statements, parser.diagnostics.warnings


def _parts(body) -> list:
    return [getattr(s, "parts", type(s).__name__) for s in body]


class TestParsing:
    def test_bodies_are_attached_to_their_verbs(self) -> None:
        statements, warnings = _statements(SOURCE)
        assert warnings == []
        first = statements[0]
        assert _parts(first.size_error_body) == [("'S1 SIZE '", "WS-X")]
        assert _parts(first.not_size_error_body) == [("'S1 OK '", "WS-X")]
        assert _parts(statements[10].size_error_body) == [("'S11 SIZE'",)]

    def test_program_is_supported(self) -> None:
        level, reason = _level(SOURCE)
        assert level is CapabilityLevel.SUPPORTED, reason

    def test_unattached_phrase_stays_refused(self) -> None:
        source = SOURCE.replace("ADD 5 TO WS-X\n", "ADD 5 TO WS-X WS-U\n", 1)
        assert _level(source)[0] is not CapabilityLevel.SUPPORTED

    def test_remainder_with_size_error_fails_closed(self) -> None:
        source = SOURCE.replace(
            "DIVIDE WS-A BY WS-Z GIVING WS-Q\n",
            "DIVIDE WS-A BY WS-Z GIVING WS-Q REMAINDER WS-R\n", 1,
        )
        assert TransformationProducer().transform(source, "S").success is False


_FILE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. R.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO "F.TXT" ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  F-REC PIC X(4).
       WORKING-STORAGE SECTION.
       01  X PIC 9 VALUE 9.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT F
           READ F AT END DISPLAY 'E' NOT AT END DISPLAY 'R' END-READ
           READ F
               AT END DISPLAY 'E2' END-READ
           DISPLAY 'AFTER'
           CLOSE F
           STOP RUN.
"""


class TestClauseCollector:
    def test_inline_not_at_end_is_its_own_branch(self) -> None:
        statements, warnings = _statements(_FILE_PROGRAM)
        read = statements[1]
        assert _parts(read.at_end_body) == [("'E'",)]
        assert _parts(read.not_at_end_body) == [("'R'",)]
        assert warnings == []

    def test_terminator_after_a_body_statement_closes_the_scope(self) -> None:
        statements, _ = _statements(_FILE_PROGRAM)
        second = statements[2]
        assert _parts(second.at_end_body) == [("'E2'",)]
        assert [type(s).__name__ for s in statements[3:]] == [
            "DisplayStatement", "CloseStatement", "StopRunStatement",
        ]


@pytest.mark.parametrize("name", sorted(CASES))
def test_generated_java_matches_oracle(name: str, tmp_path: Path) -> None:
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    source, program_id, expected = CASES[name]
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
    assert run.stdout.decode() == expected


@pytest.mark.parametrize("name", sorted(CASES))
def test_oracle_pins(name: str, tmp_path: Path) -> None:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    source, program_id, expected = CASES[name]
    (tmp_path / f"{program_id}.cob").write_text(source, encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src",
         ORACLE_IMAGE, "sh", "-c",
         f"cd /tmp && cobc -x /src/{program_id}.cob -o s && ./s"],
        capture_output=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == expected

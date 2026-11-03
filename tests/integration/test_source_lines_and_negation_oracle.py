"""GnuCOBOL differential proof for audit T9-T11 (source lines and NOT).

* T9: ``IF NOT WS-A = 1`` was rendered ``!WS_A == 1`` (javac error).
* T11: fixed-format ``D`` (debugging) and ``/`` (page eject) lines in column
  7 reached the statement parser as "unsupported statements" whenever
  columns 1-6 held spaces, and an inline ``*>`` comment broke the
  statement it followed.  GnuCOBOL treats all three as comments (a ``D``
  line is code only WITH DEBUGGING MODE); a ``*>`` inside a literal is data.
* T10: reference modification gets a parser diagnostic (it has no lowering).
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCLINES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9 VALUE 1.
       01 WS-B PIC 9 VALUE 2.
       PROCEDURE DIVISION.
       MAIN.
           IF NOT WS-A = 1
               DISPLAY 'N1-T'
           ELSE
               DISPLAY 'N1-F'
           END-IF.
           IF NOT WS-B = 1
               DISPLAY 'N2-T'
           ELSE
               DISPLAY 'N2-F'
           END-IF.
           IF NOT WS-B > WS-A
               DISPLAY 'N3-T'
           ELSE
               DISPLAY 'N3-F'
           END-IF.
      D    DISPLAY 'DEBUG-ONLY'.
      /
           DISPLAY 'AFTER-EJECT'.
           DISPLAY 'INLINE'. *> trailing comment
           DISPLAY 'KEEP *> IN LITERAL'.
           STOP RUN.
"""

EXPECTED = ["N1-F", "N2-T", "N3-F", "AFTER-EJECT", "INLINE", "KEEP *> IN LITERAL"]


def test_no_unsupported_statement_diagnostics() -> None:
    parser = CobolParser()
    parser.parse(PROGRAM)
    messages = [d.message for d in parser.diagnostics.all]
    assert not [m for m in messages if "unsupported" in m.lower() or "did not parse" in m.lower()], messages


def test_reference_modification_is_diagnosed() -> None:
    parser = CobolParser()
    parser.parse(PROGRAM.replace(
        "           STOP RUN.\n",
        "           DISPLAY WS-A(1:1).\n           STOP RUN.\n",
    ))
    assert any("Reference modification" in d.message for d in parser.diagnostics.all)


def test_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    (tmp_path / "cobol").mkdir()
    (tmp_path / "java").mkdir()
    oracle = run_gnucobol(PROGRAM, "SRCLINES", tmp_path / "cobol")
    java = run_generated_java(PROGRAM, "SRCLINES", tmp_path / "java")
    assert oracle.splitlines() == EXPECTED, oracle
    assert java == oracle

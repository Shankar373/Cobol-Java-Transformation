"""GnuCOBOL differential proof: ADD with several sending operands (audit T16).

``ADD A B C TO D`` raised "Malformed or unsupported COBOL arithmetic
expression" (the operand list reached the expression mapper as one string).
The list is now summed: identifiers and numeric literals, separated by
spaces or commas, with and without GIVING.
"""

from __future__ import annotations

from pathlib import Path

from tests.oracle_java_helpers import run_generated_java, run_gnucobol

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADDLIST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(3) VALUE 1.
       01 WS-B PIC 9(3) VALUE 2.
       01 WS-C PIC 9(3) VALUE 3.
       01 WS-D PIC 9(3) VALUE 10.
       01 WS-E PIC 9(3) VALUE 100.
       01 WS-F PIC 9(3) VALUE 0.
       01 WS-G PIC 9(3) VALUE 5.
       01 WS-H PIC 9(3) VALUE 0.
       01 WS-S PIC 99 VALUE 95.
       PROCEDURE DIVISION.
       MAIN.
           ADD WS-A WS-B WS-C TO WS-D.
           DISPLAY "D=" WS-D.
           ADD 1 2 3 TO WS-E.
           DISPLAY "E=" WS-E.
           ADD WS-A WS-B GIVING WS-F.
           DISPLAY "F=" WS-F.
           ADD WS-A, WS-C TO WS-G.
           DISPLAY "G=" WS-G.
           ADD WS-A WS-B TO WS-C GIVING WS-H.
           DISPLAY "H=" WS-H.
           ADD 3 4 TO WS-S.
           DISPLAY "S=" WS-S.
           STOP RUN.
"""

# S: 95 + 3 + 4 = 102 truncated high-order to PIC 99 -> 02.
EXPECTED = ["D=016", "E=106", "F=003", "G=009", "H=006", "S=02"]


def test_add_source_list_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    (tmp_path / "cobol").mkdir()
    (tmp_path / "java").mkdir()
    oracle = run_gnucobol(PROGRAM, "ADDLIST", tmp_path / "cobol")
    java = run_generated_java(PROGRAM, "ADDLIST", tmp_path / "java")
    assert oracle.splitlines() == EXPECTED, oracle
    assert java == oracle

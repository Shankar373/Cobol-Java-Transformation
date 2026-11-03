"""GnuCOBOL differential proof: DIVIDE ... REMAINDER (audit 2026-11-03, T4).

GnuCOBOL computes the remainder from the *intermediate* quotient - truncated
to the quotient receiver's decimal places, but keeping its sign and every
integer digit. The mapper used the *stored* quotient, so a signed dividend
into an unsigned quotient (-5 / 2 -> REMAINDER -1) gave -9, and a quotient
truncated high-order (1000 / 3 GIVING PIC 99 -> REMAINDER 1) gave 901.
"""

from __future__ import annotations

from pathlib import Path

from tests.oracle_java_helpers import run_generated_java, run_gnucobol

SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIVREM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-S  PIC S9(3) VALUE -5.
       01 WS-Z  PIC 9(3) VALUE 0.
       01 WS-R  PIC S9(3) VALUE 0.
       01 Q2    PIC 99 VALUE 0.
       01 R3    PIC 999 VALUE 0.
       01 QDEC    PIC 9V9 VALUE 0.
       01 RDEC    PIC 9V99 VALUE 0.
       01 QS    PIC S9 VALUE 0.
       01 RS    PIC S9 VALUE 0.
       01 Q1    PIC 9 VALUE 0.
       01 R1    PIC 9 VALUE 0.
       01 DV    PIC 9V9 VALUE 7.5.
       01 NEG7  PIC S9 VALUE -7.
       PROCEDURE DIVISION.
       MAIN.
           DIVIDE WS-S BY 2 GIVING WS-Z REMAINDER WS-R.
           DISPLAY "C1 Q=" WS-Z " R=" WS-R.
           DIVIDE 1000 BY 3 GIVING Q2 REMAINDER R3.
           DISPLAY "C2 Q=" Q2 " R=" R3.
           DIVIDE DV BY 2 GIVING QDEC REMAINDER RDEC.
           DISPLAY "C3 Q=" QDEC " R=" RDEC.
           DIVIDE NEG7 BY 2 GIVING QS REMAINDER RS.
           DISPLAY "C4 Q=" QS " R=" RS.
           DIVIDE 17 BY 5 GIVING Q1 REMAINDER R1.
           DISPLAY "C5 Q=" Q1 " R=" R1.
           STOP RUN.
"""

EXPECTED = [
    "C1 Q=002 R=-001",
    "C2 Q=33 R=001",
    "C3 Q=3.7 R=0.10",
    "C4 Q=-3 R=-1",
    "C5 Q=3 R=2",
]


def test_divide_remainder_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    (tmp_path / "cobol").mkdir()
    (tmp_path / "java").mkdir()
    oracle = run_gnucobol(SRC, "DIVREM", tmp_path / "cobol")
    java = run_generated_java(SRC, "DIVREM", tmp_path / "java")
    assert oracle.splitlines() == EXPECTED, oracle
    assert java == oracle

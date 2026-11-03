"""GnuCOBOL differential proof for the REPLACE compiler directive (audit T6).

REPLACE used plain ``str.replace`` over every line: ``==CNT== BY ==TOTAL==``
rewrote the literal ``"CNT="`` and the longer name ``WS-CNTX``, and each new
REPLACE added to the active pairs instead of replacing them. Substitution is
now whole-word, literal-safe and a new REPLACE replaces the active set; the
generated Java must print exactly what GnuCOBOL prints.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

REPLACE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPLDIR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 CNT PIC 9(3) VALUE 1.
       01 TOTAL PIC 9(3) VALUE 2.
       01 WS-CNTX PIC 9(3) VALUE 3.
       01 WS-TOTALX PIC 9(3) VALUE 4.
       PROCEDURE DIVISION.
       MAIN.
       REPLACE ==CNT== BY ==TOTAL==.
           DISPLAY "CNT=" CNT.
           DISPLAY WS-CNTX.
       REPLACE ==TOTAL== BY ==WS-CNTX==.
           DISPLAY CNT.
           DISPLAY TOTAL.
       REPLACE OFF.
           DISPLAY TOTAL.
           STOP RUN.
"""

# "CNT=" keeps its literal text; WS-CNTX is not CNT; the second REPLACE
# replaces the first (CNT is no longer rewritten); OFF ends the scope.
EXPECTED = ["CNT=002", "003", "001", "003", "002"]


def test_replace_is_whole_word_and_not_cumulative_in_ir() -> None:
    from engine.transformation.java_generator import JavaGenerator

    java = JavaGenerator().generate(CobolParser().parse(REPLACE_PROGRAM))[0].source_code
    assert '"CNT="' in java and "WS_TOTALX" not in java.split("static", 5)[-1], java


def test_replace_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    (tmp_path / "cobol").mkdir()
    (tmp_path / "java").mkdir()
    oracle = run_gnucobol(REPLACE_PROGRAM, "REPLDIR", tmp_path / "cobol")
    java = run_generated_java(REPLACE_PROGRAM, "REPLDIR", tmp_path / "java")
    assert oracle.splitlines() == EXPECTED, oracle
    assert java == oracle

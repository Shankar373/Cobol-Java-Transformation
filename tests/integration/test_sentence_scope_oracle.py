"""GnuCOBOL differential proof: a period ends every open IF/EVALUATE scope.

Audit 2026-11-03 (T1): an IF or EVALUATE without its explicit terminator,
closed by a separator period on a *later* line, swallowed every following
sentence into its body (``DISPLAY 'ALWAYS'`` ran only when the condition
held), with no diagnostic.  COBOL ends the whole sentence at the period, so
the next sentence always runs.

The program below covers the shapes with data that drives both the true and
false paths; the generated Java must print exactly what GnuCOBOL prints.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

SENTENCE_SCOPES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SENTSC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9 VALUE 0.
       01 WS-B PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN.
           IF WS-A > 0
               DISPLAY 'A-POSITIVE'.
           DISPLAY 'AFTER-IF-1'.
           IF WS-B > 0
               DISPLAY 'B-POSITIVE'.
           DISPLAY 'AFTER-IF-2'.
           IF WS-A > 0
               DISPLAY 'A-YES'
           ELSE
               DISPLAY 'A-NO'.
           DISPLAY 'AFTER-IF-3'.
           IF WS-A > 0
               DISPLAY 'A-YES-2'
           ELSE DISPLAY 'A-NO-2'.
           DISPLAY 'AFTER-IF-4'.
           IF WS-B > 0
               IF WS-A > 0
                   DISPLAY 'NESTED-A'
               ELSE
                   DISPLAY 'NESTED-NOT-A'.
           DISPLAY 'AFTER-NESTED'.
           IF WS-A > 0
               IF WS-B > 0
                   DISPLAY 'NESTED-B'.
           DISPLAY 'AFTER-NESTED-2'.
           EVALUATE WS-A
               WHEN 1
                   DISPLAY 'EVAL-ONE'
               WHEN 0
                   DISPLAY 'EVAL-ZERO'.
           DISPLAY 'AFTER-EVAL-1'.
           EVALUATE WS-B
               WHEN 0 DISPLAY 'EB-ZERO'
               WHEN 1 DISPLAY 'EB-ONE'.
           DISPLAY 'AFTER-EVAL-2'.
           EVALUATE WS-A
               WHEN 5
                   DISPLAY 'EVAL-FIVE'.
           DISPLAY 'AFTER-EVAL-3'.
           STOP RUN.
"""

EXPECTED = [
    "AFTER-IF-1",
    "B-POSITIVE", "AFTER-IF-2",
    "A-NO", "AFTER-IF-3",
    "A-NO-2", "AFTER-IF-4",
    "NESTED-NOT-A", "AFTER-NESTED",
    "AFTER-NESTED-2",
    "EVAL-ZERO", "AFTER-EVAL-1",
    "EB-ONE", "AFTER-EVAL-2",
    "AFTER-EVAL-3",
]


def test_period_closes_scope_in_ir() -> None:
    """Hermetic: the sentence after a period-closed IF is not in its body."""
    program = CobolParser().parse(SENTENCE_SCOPES)
    statements = [s for p in program.paragraphs for s in p.statements]
    # 9 IF/EVALUATE sentences, each followed by its own AFTER-* DISPLAY,
    # then STOP RUN: 9 + 9 + 1 top-level statements.
    assert len(statements) == 19, [type(s).__name__ for s in statements]


def test_period_closes_scope_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    (tmp_path / "cobol").mkdir()
    (tmp_path / "java").mkdir()
    oracle = run_gnucobol(SENTENCE_SCOPES, "SENTSC", tmp_path / "cobol")
    java = run_generated_java(SENTENCE_SCOPES, "SENTSC", tmp_path / "java")
    assert oracle.splitlines() == EXPECTED, oracle
    assert java == oracle

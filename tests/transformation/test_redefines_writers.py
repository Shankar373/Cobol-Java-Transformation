"""Every non-MOVE writer of REDEFINES storage fails closed (audit T3).

Only an unsubscripted MOVE keeps the Java overlay fields in sync.  Before
the audit fix, INITIALIZE, ACCEPT, the MULTIPLY ... BY and SUBTRACT ...
FROM receivers, DIVIDE REMAINDER and CALL BY REFERENCE wrote a view (or its
base) with no diagnostic, so the other side of the overlay stayed stale and
the program was still classified as supported.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.redefines import write_targets

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. T.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-A PIC X(4) VALUE 'ABCD'.\n"
    "       01 WS-B REDEFINES WS-A PIC X(4).\n"
    "       01 WS-N PIC 9(4) VALUE 1234.\n"
    "       01 WS-M REDEFINES WS-N PIC 9(4).\n"
    "       01 WS-K PIC 9(4) VALUE 3.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN.\n"
)


def _redefines_diagnostics(statement: str) -> list[str]:
    parser = CobolParser()
    parser.parse(HEADER + f"           {statement}\n           STOP RUN.\n")
    return [
        d.message for d in parser.diagnostics.all
        if "REDEFINES member" in d.message
    ]


@pytest.mark.parametrize("statement", [
    "INITIALIZE WS-B.",
    "INITIALIZE WS-A.",
    "ACCEPT WS-B.",
    "MULTIPLY WS-K BY WS-M.",
    "SUBTRACT WS-K FROM WS-M.",
    "DIVIDE WS-K INTO WS-K GIVING WS-K REMAINDER WS-M.",
    "ADD 1 TO WS-N.",
    "CALL 'SUB' USING WS-B.",
    "STRING 'X' DELIMITED BY SIZE INTO WS-B.",
])
def test_non_move_writer_is_refused(statement: str) -> None:
    assert _redefines_diagnostics(statement), statement


@pytest.mark.parametrize("statement", [
    "MOVE 'WXYZ' TO WS-B.",
    "MOVE 'WXYZ' TO WS-A.",
    "DISPLAY WS-B.",
    "CALL 'SUB' USING BY CONTENT WS-B.",
    "ADD WS-M TO WS-K.",
])
def test_move_and_readers_stay_allowed(statement: str) -> None:
    assert _redefines_diagnostics(statement) == [], statement


def test_unknown_statement_class_is_treated_as_writing_every_name() -> None:
    @dataclass
    class FutureVerbStatement:
        receiver: str
        others: tuple[str, ...]

    assert set(write_targets(FutureVerbStatement("WS-B", ("WS-A",)))) == {"WS-B", "WS-A"}

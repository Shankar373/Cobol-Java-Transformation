"""The capability source scanner ignores what the compiler ignores (audit T13).

``_strip_literals_and_comments`` skipped only lines *starting* with ``*`` or
``/``: a fixed-format comment line with a sequence number (``000100* SORT``)
was scanned as code, as were ``D`` debugging lines, page ejects in column 7
and inline ``*>`` comments, and literals with COBOL's doubled-quote escape
were not recognised. Keywords there (SORT, GO TO, ...) wrongly classified a
program UNSUPPORTED.
"""

from __future__ import annotations

from engine.transformation.semantic_capability import scan_constructs

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. T.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN.\n"
)


def test_comments_debug_lines_and_literals_are_not_scanned() -> None:
    source = HEADER + (
        "000100* SORT THE FILE AND GO TO END\n"
        "      / page eject mentioning INSPECT\n"
        "      D    SORT X.\n"
        '           DISPLAY "A ""SORT"" B". *> GO TO later\n'
        "           STOP RUN.\n"
    )
    found = scan_constructs(source)
    assert not found & {"SORT", "GO TO", "INSPECT"}, found


def test_real_code_is_still_scanned() -> None:
    source = HEADER + (
        "           GO TO MAIN.\n"
        "           STOP RUN.\n"
    )
    assert "GO TO" in scan_constructs(source)

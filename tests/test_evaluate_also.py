"""Roadmap unit 37: EVALUATE ... ALSO, stacked WHEN clauses and the parenthesised ``if`` condition."""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_render import _wrapped_in_one_pair

HEAD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n       01 A PIC 9 VALUE 1.\n       01 B PIC 9 VALUE 2.\n"
    "       PROCEDURE DIVISION.\n       MAIN.\n"
)


def _java(body: str) -> str:
    source = HEAD + body + "\n           STOP RUN.\n"
    return JavaGenerator().generate(CobolParser().parse(source))[0].source_code


def test_also_matches_every_object_against_its_subject():
    code = _java(
        "           EVALUATE A ALSO B\n               WHEN 1 ALSO 2\n                   DISPLAY 'x'\n"
        "               WHEN ANY ALSO 3 THRU 5\n                   DISPLAY 'y'\n               WHEN OTHER\n"
        "                   DISPLAY 'z'\n           END-EVALUATE"
    )
    assert "(A == 1) && (B == 2)" in code.replace("((", "(").replace("))", ")")
    assert "UNSUPPORTED" not in code


def test_stacked_when_clauses_share_the_statements():
    code = _java(
        "           EVALUATE A\n               WHEN 1\n               WHEN 2\n                   DISPLAY 'x'\n"
        "               WHEN OTHER\n                   DISPLAY 'z'\n           END-EVALUATE"
    )
    assert "A == 1" in code and "A == 2" in code and "||" in code


def test_the_if_renderer_keeps_the_parentheses_that_do_not_wrap_the_whole_condition():
    assert _wrapped_in_one_pair("(a == 1)")
    assert _wrapped_in_one_pair("((a) || (b))")
    assert not _wrapped_in_one_pair("(a == 1) || (b == 2)")
    assert not _wrapped_in_one_pair("a == 1")
    assert _wrapped_in_one_pair("(s.equals(\")\"))")

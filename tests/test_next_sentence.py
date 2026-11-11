"""NEXT SENTENCE rewrite (hermetic); GnuCOBOL proof: tests/integration/test_next_sentence_oracle.py."""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.next_sentence import rewrite_next_sentence

P = "       PROCEDURE DIVISION."


def _r(*body):
    return rewrite_next_sentence([P, *body])


def test_next_sentence_ending_an_if_branch_becomes_continue():
    lines, problems = _r('           IF A = 1 NEXT SENTENCE ELSE DISPLAY "X".')
    assert problems == [] and lines[1].strip() == 'IF A = 1 CONTINUE ELSE DISPLAY "X".'
    lines, problems = _r("           IF A = 1", "               NEXT SENTENCE", "           ELSE", '               DISPLAY "X".')
    assert problems == [] and lines[2].strip() == "CONTINUE"


def test_a_quoted_next_sentence_is_text_not_a_statement():
    lines, problems = _r('           DISPLAY "NEXT SENTENCE".')
    assert problems == [] and lines[1].strip() == 'DISPLAY "NEXT SENTENCE".'


@pytest.mark.parametrize("body, why", [
    (["           IF A = 1", "               NEXT SENTENCE", "           ELSE", "               DISPLAY 1", "           END-IF",
      "           DISPLAY 2."], "explicit scope terminator"),
    (['           IF A = 1 NEXT SENTENCE DISPLAY "D".'], "followed by statements in its branch"),
    (["           EVALUATE A", "               WHEN 1 NEXT SENTENCE", '               WHEN OTHER DISPLAY "Y".'],
     "only a single IF"),
    (["           IF A = 1", "               IF B = 1 NEXT SENTENCE ELSE DISPLAY 1", "               ELSE DISPLAY 2."],
     "only a single IF"),
    (["           IF A = 1 NEXT", "               SENTENCE ELSE DISPLAY 1."], "split across lines"),
])
def test_other_shapes_are_refused_by_name_and_left_untouched(body, why):
    lines, problems = _r(*body)
    assert lines[1:] == body and len(problems) == 1 and why in problems[0], problems


def test_the_parser_reports_a_refused_shape_as_unsupported():
    src = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. NS.\n       DATA DIVISION.\n"
           "       WORKING-STORAGE SECTION.\n       01 A PIC 9 VALUE 1.\n       PROCEDURE DIVISION.\n"
           "           IF A = 1 NEXT SENTENCE DISPLAY \"D\".\n           STOP RUN.\n")
    parser = CobolParser()
    parser.parse(src)
    assert any("NEXT SENTENCE is recognised but not lowered" in d.message for d in parser.diagnostics.all)


def _parse(body: str):
    src = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CT.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
           "       01 A PIC 9 VALUE 1.\n       01 B PIC 9 VALUE 0.\n       PROCEDURE DIVISION.\n" + body
           + "           STOP RUN.\n")
    return CobolParser().parse(src).paragraphs[0].statements


def test_the_second_else_of_a_nested_if_belongs_to_the_outer_if():
    outer = _parse('           IF A = 1\n               IF B = 1\n                   CONTINUE\n               ELSE\n'
                   '                   DISPLAY "IN"\n               ELSE\n                   DISPLAY "OUT".\n')[0]
    inner = outer.then_body[0]
    assert len(inner.else_body) == 1 and len(outer.else_body) == 1


def test_a_continue_arm_of_an_evaluate_is_not_stacked_with_the_next_when():
    stmt = _parse('           EVALUATE A\n               WHEN 1 CONTINUE\n               WHEN OTHER DISPLAY "O".\n')[0]
    assert stmt.condition.startswith("A = 1") and stmt.then_body == () and len(stmt.else_body) == 1

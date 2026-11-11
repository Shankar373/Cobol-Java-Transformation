"""Roadmap unit 41: MOVE / ADD / SUBTRACT CORRESPONDING expand to one statement per corresponding elementary pair."""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.qualified_names import resolve_qualified_names

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GA.
          05 AMT PIC 9(3) VALUE 1.
          05 NAME1 PIC X(4) VALUE 'ab'.
          05 SUBG.
             10 QTY PIC 9(3) VALUE 5.
          05 ONLYA PIC 9.
       01 GB.
          05 NAME1 PIC X(6).
          05 AMT PIC 9(5) VALUE 0.
          05 SUBG.
             10 QTY PIC 9(4) VALUE 0.
          05 ONLYB PIC 9.
       PROCEDURE DIVISION.
       MAIN.
"""


def _program(body: str) -> str:
    return HEAD + body + "\n           STOP RUN.\n"


def _expanded(body: str):
    lines, problems = resolve_qualified_names(_program(body).splitlines())
    return [line.strip() for line in lines[lines.index("       MAIN.") + 1:]], problems


def _messages(body: str) -> list[str]:
    parser = CobolParser()
    parser.parse(_program(body))
    return [d.message for d in parser.diagnostics.all]


def test_move_corresponding_pairs_by_name_and_qualification_in_source_order():
    lines, problems = _expanded("           MOVE CORRESPONDING GA TO GB.")
    assert problems == []
    assert lines[:3] == ["MOVE AMT-OF-GA TO AMT-OF-GB", "MOVE NAME1-OF-GA TO NAME1-OF-GB",
                         "MOVE QTY-OF-SUBG-OF-GA TO QTY-OF-SUBG-OF-GB."]  # ONLYA / ONLYB do not correspond


def test_add_and_subtract_corresponding_use_the_numeric_pairs_only():
    lines, problems = _expanded("           ADD CORR GA TO GB.\n           SUBTRACT CORR GA FROM GB.")
    assert problems == []
    assert [line for line in lines if line.startswith("ADD")] == [
        "ADD AMT-OF-GA TO AMT-OF-GB", "ADD QTY-OF-SUBG-OF-GA TO QTY-OF-SUBG-OF-GB."]  # NAME1 is text: skipped
    assert [line for line in lines if line.startswith("SUBTRACT")][0] == "SUBTRACT AMT-OF-GA FROM AMT-OF-GB"


def test_the_expanded_program_has_no_diagnostic():
    assert _messages("           MOVE CORRESPONDING GA TO GB.\n           ADD CORR GA TO GB.") == []


def test_forms_that_are_not_lowered_fail_closed():
    for body in (
        "           MOVE CORRESPONDING GA\n               TO GB.",  # wrapped over two lines
        "           MOVE CORR GA TO GB ROUNDED.",
        "           IF AMT OF GA > 0 MOVE CORR GA TO GB.",  # nested in another statement
        "           MOVE CORR AMT OF GA TO GB.",  # an operand that is not a group
        "           MOVE CORR NOSUCH TO GB.",
    ):
        assert _messages(body), body


def test_a_group_and_an_elementary_item_of_one_name_are_refused():
    source = HEAD.replace("          05 SUBG.\n             10 QTY PIC 9(4) VALUE 0.\n", "          05 SUBG PIC 9(4).\n")
    parser = CobolParser()
    parser.parse(source + "           MOVE CORR GA TO GB.\n           STOP RUN.\n")
    assert any("group in one operand and elementary in the other" in d.message for d in parser.diagnostics.all)

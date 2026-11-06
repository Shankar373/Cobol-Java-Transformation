"""Hermetic tests for PERFORM VARYING ... AFTER and WITH TEST AFTER (roadmap unit 33); GnuCOBOL proof:
tests/integration/test_varying_oracle.py."""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import _varying_clauses
from engine.transformation.java_generator import JavaGenerator

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. VC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 VI PIC S99 VALUE 0.
       01 VJ PIC S99 VALUE 0.
       01 VK PIC S99 VALUE 0.
       01 AMT PIC 9V9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN.
"""


def _java(body: str) -> str:
    """The generated run-unit method (the support code around it is not under test)."""
    parser = CobolParser()
    program = parser.parse(HEAD + body + "           STOP RUN.\n")
    assert [d.message for d in parser.diagnostics.all if d.code.name == "UNSUPPORTED_CONSTRUCT"] == []
    source = JavaGenerator().generate(program)[0].source_code
    start = source.index("RUN_UNIT$ENTRY()")
    return source[start: source.index("public static void main", start)]


def test_clauses_are_split_at_after():
    assert _varying_clauses("VARYING I FROM 1 BY 2 UNTIL I > 5 AFTER J FROM I UNTIL J > 3") == [
        ("I", "1", "2", "I > 5"), ("J", "I", "1", "J > 3")]
    assert _varying_clauses("VARYING I FROM 1 BY 1 UNTIL I > 2") == [("I", "1", "1", "I > 2")]
    assert _varying_clauses("garbage") is None


def test_two_levels_lower_to_nested_loops_that_initialise_the_next_item():
    java = _java(
        "           PERFORM VARYING VI FROM 1 BY 1 UNTIL VI > 2\n               AFTER VJ FROM VI BY 1 UNTIL VJ > 3\n"
        "               DISPLAY VI VJ\n           END-PERFORM.\n")
    assert java.count("while (") == 2
    # start: both items; every iteration of the outer loop: the inner item; the outer step: the inner item again
    assert java.count("VJ = VI;") == 3
    assert "VI = (VI + 1);" in java and "VJ = (VJ + 1);" in java


def test_the_third_item_is_not_initialised_at_the_start():
    java = _java(
        "           PERFORM VARYING VI FROM 1 BY 1 UNTIL VI > 2\n               AFTER VJ FROM 1 BY 1 UNTIL VJ > 2\n"
        "               AFTER VK FROM 7 BY 1 UNTIL VK > 8\n               DISPLAY VK\n           END-PERFORM.\n")
    before_loop = java[: java.index("while (")]
    assert "VK = 7;" not in before_loop and "VJ = 1;" in before_loop and "VI = 1;" in before_loop
    assert "VK = 7;" in java  # inside the loops


def test_test_after_runs_the_body_then_tests_before_the_step():
    java = _java(
        "           PERFORM WITH TEST AFTER VARYING VI FROM 1 BY 1 UNTIL VI > 2\n               DISPLAY VI\n"
        "           END-PERFORM.\n")
    assert "while (true)" in java and "break;" in java
    assert java.index("break;") < java.index("VI = (VI + 1);")


def test_exit_perform_inside_a_varying_chain_is_refused_but_a_single_varying_may_use_it():
    chain = ("           PERFORM VARYING VI FROM 1 BY 1 UNTIL VI > 2\n               AFTER VJ FROM 1 BY 1 UNTIL VJ > 2\n"
             "               IF VJ = 2 EXIT PERFORM END-IF\n           END-PERFORM.\n")
    parser = CobolParser()
    parser.parse(HEAD + chain + "           STOP RUN.\n")
    assert any("EXIT PERFORM outside an inline PERFORM" in d.message for d in parser.diagnostics.all)
    single = ("           PERFORM VARYING VI FROM 1 BY 1 UNTIL VI > 2\n               IF VI = 2 EXIT PERFORM END-IF\n"
              "           END-PERFORM.\n")
    parser = CobolParser()
    parser.parse(HEAD + single + "           STOP RUN.\n")
    assert not [d for d in parser.diagnostics.all if d.code.name == "UNSUPPORTED_CONSTRUCT"]


@pytest.mark.parametrize("body", [
    "           PERFORM VARYING AMT FROM 1 BY 1 UNTIL AMT > 3\n               AFTER VJ FROM 1 BY 1 UNTIL VJ > 2\n"
    "               DISPLAY VJ\n           END-PERFORM.\n",
])
def test_a_decimal_control_item_in_a_chain_fails_closed(body):
    parser = CobolParser()
    program = parser.parse(HEAD + body + "           STOP RUN.\n")
    with pytest.raises(ValueError, match="control item must be a declared unsubscripted integer"):
        JavaGenerator().generate(program)

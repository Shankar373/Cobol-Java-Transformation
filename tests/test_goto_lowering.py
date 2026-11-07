"""Hermetic tests for GO TO lowering (roadmap unit 26); GnuCOBOL proof: tests/integration/test_goto_oracle.py."""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.control_flow import goto_plan_reasons
from engine.transformation.java_generator import JavaGenerator

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. GT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N PIC 99 VALUE 0.
       PROCEDURE DIVISION.
"""


def _parse(body: str):
    parser = CobolParser()
    program = parser.parse(HEAD + body)
    return program, [d.message for d in parser.diagnostics.all if d.code.name == "UNSUPPORTED_CONSTRUCT"]


RANGE_OK = """       MAIN-PARA.
           PERFORM A-PARA THRU A-EXIT.
           STOP RUN.
       A-PARA.
           IF N = 0
               GO TO A-EXIT
           END-IF.
           DISPLAY 'SKIPPED'.
       A-EXIT.
           EXIT.
"""


def test_goto_inside_a_perform_range_is_certified_and_lowered_through_cobolflow():
    program, diagnostics = _parse(RANGE_OK)
    assert diagnostics == []
    assert goto_plan_reasons(program.paragraphs) == []
    java = JavaGenerator().generate(program)[0].source_code
    assert "CobolFlow.range(1, 2, COBOL_PARAGRAPHS)" in java
    assert "CobolFlow.program(COBOL_PARAGRAPHS)" in java
    assert "throw new CobolFlow.Goto(\"2\")" in java and "final class CobolFlow" in java


def test_main_line_goto_and_stop_run_anywhere_are_certified():
    program, diagnostics = _parse(
        "       MAIN-PARA.\n           ADD 1 TO N.\n           IF N < 3\n               GO TO MAIN-PARA\n"
        "           END-IF.\n           IF N = 3\n               STOP RUN\n           END-IF.\n"
        "       NEXT-PARA.\n           DISPLAY N.\n")
    assert diagnostics == []
    assert goto_plan_reasons(program.paragraphs) == []


def test_jump_out_of_a_perform_range_is_refused():
    program, diagnostics = _parse(
        "       MAIN-PARA.\n           PERFORM A-PARA THRU A-EXIT.\n           STOP RUN.\n"
        "       A-PARA.\n           GO TO OUTSIDE.\n       A-EXIT.\n           EXIT.\n"
        "       OUTSIDE.\n           DISPLAY 'X'.\n")
    assert goto_plan_reasons(program.paragraphs) == ["RANGE"]
    assert any("GO TO is outside the certified subset (RANGE)" in d for d in diagnostics)


def test_goto_in_a_paragraph_performed_by_a_simple_perform_is_refused():
    program, _ = _parse(
        "       MAIN-PARA.\n           PERFORM A-PARA.\n           STOP RUN.\n"
        "       A-PARA.\n           GO TO A-PARA.\n")
    assert goto_plan_reasons(program.paragraphs) == ["PERFORM_FORM"]


def test_undefined_target_and_depending_form_are_refused():
    program, _ = _parse("       MAIN-PARA.\n           GO TO NOWHERE.\n")
    assert goto_plan_reasons(program.paragraphs) == ["TARGET"]
    # GO TO a b DEPENDING ON n is certified since roadmap unit 38 (an IF chain of plain GO TOs); an undefined target and
    # a subscripted selector stay refused
    program, _ = _parse("       MAIN-PARA.\n           GO TO A-PARA B-PARA DEPENDING ON N.\n"
                        "       A-PARA.\n           DISPLAY 'A'.\n       B-PARA.\n           DISPLAY 'B'.\n")
    assert goto_plan_reasons(program.paragraphs) == []
    program, _ = _parse("       MAIN-PARA.\n           GO TO A-PARA NOWHERE DEPENDING ON N.\n"
                        "       A-PARA.\n           DISPLAY 'A'.\n")
    assert goto_plan_reasons(program.paragraphs) == ["TARGET"]
    program, _ = _parse("       MAIN-PARA.\n           GO TO A-PARA DEPENDING ON N(1).\n"
                        "       A-PARA.\n           DISPLAY 'A'.\n")
    assert "FORM" in goto_plan_reasons(program.paragraphs)


def test_exit_program_with_goto_and_called_programs_are_refused():
    program, _ = _parse("       MAIN-PARA.\n           GO TO NEXT-PARA.\n       NEXT-PARA.\n           EXIT PROGRAM.\n")
    assert goto_plan_reasons(program.paragraphs) == ["EXIT_PROGRAM"]
    program, _ = _parse("       MAIN-PARA.\n           GO TO NEXT-PARA.\n       NEXT-PARA.\n           DISPLAY 'X'.\n")
    assert goto_plan_reasons(program.paragraphs, has_linkage=True) == ["LINKAGE"]


def test_program_without_goto_is_unchanged():
    program, diagnostics = _parse("       MAIN-PARA.\n           DISPLAY 'A'.\n           STOP RUN.\n")
    assert diagnostics == [] and goto_plan_reasons(program.paragraphs) == []
    java = JavaGenerator().generate(program)[0].source_code
    assert "CobolFlow" not in java


def test_plain_exit_is_a_no_op_but_exit_perform_stays_unsupported():
    _, diagnostics = _parse("       MAIN-PARA.\n           EXIT.\n           STOP RUN.\n")
    assert diagnostics == []
    _, diagnostics = _parse("       MAIN-PARA.\n           EXIT PERFORM.\n           STOP RUN.\n")
    assert any("EXIT PERFORM" in d for d in diagnostics)


def test_go_to_depending_lowers_to_an_if_chain_of_plain_go_tos():
    program, diagnostics = _parse("       MAIN-PARA.\n           GO TO A-PARA B-PARA\n               DEPENDING ON N.\n"
                                  "           DISPLAY 'FALL'.\n       A-PARA.\n           DISPLAY 'A'.\n"
                                  "       B-PARA.\n           DISPLAY 'B'.\n")
    assert diagnostics == []
    first = program.paragraphs[0].statements[0]
    assert first.condition == "N = 1" and first.then_body[0].target == "A-PARA"
    assert first.else_body[0].condition == "N = 2" and first.else_body[0].then_body[0].target == "B-PARA"
    assert len(program.paragraphs[0].statements) == 2  # the DISPLAY after it is the fall-through

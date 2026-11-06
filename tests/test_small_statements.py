"""Hermetic tests for CONTINUE, EXIT PERFORM and DISPLAY ... WITH NO ADVANCING (roadmap unit 31); GnuCOBOL proof:
tests/integration/test_small_statements_oracle.py."""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import DisplayStatement, ExitPerformStatement, IfStatement, PerformStatement
from engine.transformation.java_generator import JavaGenerator

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
"""


def _parse(body: str):
    parser = CobolParser()
    program = parser.parse(HEAD + body + "           STOP RUN.\n")
    diagnostics = [d.message for d in parser.diagnostics.all if d.code.name == "UNSUPPORTED_CONSTRUCT"]
    return program, diagnostics


def _statements(program):
    return [s for p in program.paragraphs for s in p.statements]


def test_display_no_advancing_is_parsed_in_every_position_and_prints_without_a_newline():
    program, diagnostics = _parse(
        "           DISPLAY 'A' WITH NO ADVANCING.\n           DISPLAY 'B' NO ADVANCING.\n"
        "           DISPLAY 'C' N WITH NO ADVANCING\n           END-DISPLAY.\n           DISPLAY 'D'.\n")
    displays = [s for s in _statements(program) if isinstance(s, DisplayStatement)]
    assert [d.no_advancing for d in displays] == [True, True, True, False][: len(displays)], diagnostics
    java = JavaGenerator().generate(program)[0].source_code
    assert java.count("System.out.print(") >= 2 and "System.out.println(" in java


def test_continue_inside_if_arms_is_a_no_op_not_a_condition():
    program, diagnostics = _parse(
        "           IF N = 0 CONTINUE ELSE DISPLAY 'X' END-IF.\n"
        "           IF N = 1\n               CONTINUE\n           ELSE\n               DISPLAY 'Y'\n           END-IF.\n")
    assert diagnostics == []
    ifs = [s for s in _statements(program) if isinstance(s, IfStatement)]
    assert [i.condition for i in ifs] == ["N = 0", "N = 1"]
    assert all(i.then_body == () and len(i.else_body) == 1 for i in ifs)


def test_exit_perform_is_one_statement_inside_an_inline_perform():
    program, diagnostics = _parse(
        "           PERFORM UNTIL N > 5\n               ADD 1 TO N\n               IF N = 3 EXIT PERFORM END-IF\n"
        "           END-PERFORM.\n")
    assert diagnostics == []
    loop = next(s for s in _statements(program) if isinstance(s, PerformStatement))
    inner = next(s for s in loop.body if isinstance(s, IfStatement))
    assert isinstance(inner.then_body[0], ExitPerformStatement)
    java = JavaGenerator().generate(program)[0].source_code
    assert "break;" in java


def test_exit_perform_outside_an_inline_perform_is_refused_by_name():
    for body in ("           EXIT PERFORM.\n",
                 "           PERFORM P2.\n       P2.\n           EXIT PERFORM.\n"):
        _, diagnostics = _parse(body)
        assert any("EXIT PERFORM outside an inline PERFORM" in d for d in diagnostics), (body, diagnostics)


def test_exit_perform_cycle_and_exit_paragraph_stay_unsupported():
    for body in ("           PERFORM UNTIL N > 1\n               EXIT PERFORM CYCLE\n           END-PERFORM.\n",
                 "           EXIT PARAGRAPH.\n"):
        _, diagnostics = _parse(body)
        assert diagnostics, body

"""Roadmap unit 36: qualified names are resolved to unique declarations; everything ambiguous fails closed."""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.qualified_names import resolve_qualified_names

SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC.
          05 A PIC 9(3) VALUE 1.
          05 SUB.
             10 B PIC 9(3) VALUE 2.
       01 REC2.
          05 A PIC 9(3) VALUE 3.
          05 SUB.
             10 B PIC 9(3) VALUE 4.
       PROCEDURE DIVISION.
       MAIN.
           MOVE A OF REC TO A IN REC2
           DISPLAY B OF SUB OF REC2 ' ' B OF REC
           STOP RUN.
"""


def _messages(source: str) -> list[str]:
    parser = CobolParser()
    parser.parse(source)
    return [d.message for d in parser.diagnostics.all]


def test_duplicated_names_become_unique_and_references_resolve():
    lines, problems = resolve_qualified_names(SOURCE.splitlines())
    text = "\n".join(lines)
    assert problems == []
    assert "05 A-OF-REC PIC" in text and "05 A-OF-REC2 PIC" in text
    assert "10 B-OF-SUB-OF-REC2 PIC" in text
    assert "MOVE A-OF-REC TO A-OF-REC2" in text
    assert "DISPLAY B-OF-SUB-OF-REC2 ' ' B-OF-SUB-OF-REC" in text


def test_the_resolved_program_has_no_diagnostic_and_generates():
    assert _messages(SOURCE) == []
    code = JavaGenerator().generate(CobolParser().parse(SOURCE))[0].source_code
    assert "A_OF_REC2" in code


def test_unqualified_and_unresolvable_references_fail_closed():
    assert any("declared more than once" in m for m in _messages(SOURCE.replace("MOVE A OF REC TO", "MOVE A TO")))
    assert any("designates 0" in m for m in _messages(SOURCE.replace("B OF REC\n", "B OF NOWHERE\n")))


def test_a_duplicated_name_in_a_data_clause_is_not_renamed():
    source = SOURCE.replace("05 SUB.", "05 SUB REDEFINES A.", 1)
    assert any("declared more than once" in m or "REDEFINES" in m for m in _messages(source))

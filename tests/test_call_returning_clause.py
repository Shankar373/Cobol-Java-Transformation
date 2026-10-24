"""CALL RETURNING visibility (Workstream E) — argument-count truth.

``CALL 'SUBP' USING A RETURNING B`` used to capture ``RETURNING`` and ``B``
as two extra USING arguments.  That fabricated arity can accidentally match a
callee's LINKAGE SECTION and produce a call that runs with the wrong data.
The clause is not transformed yet, so the contract is:

* it never contributes to ``arguments`` / ``passing_modes``;
* it is named by an ``UNSUPPORTED_CONSTRUCT`` diagnostic;
* it is captured on the IR so the mapper fails closed by name instead of
  silently discarding the returned value.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_statement
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.ir import CallStatement
from engine.transformation.java_ir import JavaAssignment, JavaVariableRef

HEADER = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. CTR.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(4) VALUE 5.
01 WS-R PIC 9(4) VALUE 0.
PROCEDURE DIVISION.
MAIN.
"""


def _call(body: str) -> tuple[CobolParser, CallStatement, object]:
    parser = CobolParser()
    program = parser.parse(HEADER + body + "    STOP RUN.\n")
    for para in program.paragraphs:
        for stmt in para.statements:
            if isinstance(stmt, CallStatement):
                return parser, stmt, program
    raise AssertionError("no CallStatement parsed")


class TestReturningIsNotAnArgument:
    def test_returning_excluded_from_arguments(self) -> None:
        parser, call, _ = _call(
            "    CALL 'SUBP' USING BY REFERENCE WS-A RETURNING WS-R.\n"
        )
        assert call.arguments == ("WS-A",)
        assert call.passing_modes == ("REFERENCE",)
        assert call.returning == "WS-R"

    def test_returning_is_diagnosed(self) -> None:
        parser, _, _ = _call(
            "    CALL 'SUBP' USING BY REFERENCE WS-A RETURNING WS-R.\n"
        )
        messages = [
            d.message
            for d in parser.diagnostics.all
            if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
        ]
        assert any("RETURNING" in m for m in messages), messages

    def test_plain_call_stays_quiet_and_unchanged(self) -> None:
        parser, call, _ = _call(
            "    CALL 'SUBP' USING BY REFERENCE WS-A.\n"
        )
        assert call.arguments == ("WS-A",)
        assert call.returning == ""
        messages = [
            d.message
            for d in parser.diagnostics.all
            if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
        ]
        assert not any("RETURNING" in m for m in messages), messages

    def test_mapper_fails_closed_by_name(self) -> None:
        _, call, program = _call(
            "    CALL 'SUBP' USING BY REFERENCE WS-A RETURNING WS-R.\n"
        )
        mapped = map_cobol_statement(call, program)
        symbols = [
            s.expression.name
            for s in mapped
            if isinstance(s, JavaAssignment)
            and isinstance(s.expression, JavaVariableRef)
        ]
        assert any(
            name.startswith("UNSUPPORTED_CALL$RETURNING") for name in symbols
        ), symbols

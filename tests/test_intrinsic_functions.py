"""Roadmap unit 35: certified intrinsic functions (DISPLAY operand / MOVE sender) and the fail-closed rest."""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.intrinsic import parse_function
from engine.transformation.java_generator import JavaGenerator

HEAD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n       01 S PIC X(5) VALUE 'abc'.\n       01 U PIC X(8).\n"
    "       01 N PIC 9(3).\n       01 Q PIC 9(3) VALUE 7.\n       PROCEDURE DIVISION.\n       MAIN.\n"
)


def _source(body: str) -> str:
    return HEAD + body + "\n           STOP RUN.\n"


def _java(body: str) -> str:
    return JavaGenerator().generate(CobolParser().parse(_source(body)))[0].source_code


def _messages(body: str) -> list[str]:
    parser = CobolParser()
    parser.parse(_source(body))
    return [d.message for d in parser.diagnostics.all]


def test_parse_function_recognises_the_certified_shapes():
    assert parse_function("FUNCTION UPPER-CASE(S)").name == "UPPER-CASE"
    trim = parse_function("FUNCTION TRIM(S LEADING)")
    assert (trim.argument, trim.trim) == ("S", "LEADING")
    assert parse_function("FUNCTION MIN(1, 2)") is None
    assert parse_function("FUNCTION-CODE") is None


@pytest.mark.parametrize("body", [
    "           DISPLAY FUNCTION UPPER-CASE(S).",
    "           MOVE FUNCTION REVERSE(S) TO U.",
    "           MOVE FUNCTION LENGTH(S) TO N.",
    "           DISPLAY FUNCTION TRIM(S TRAILING) FUNCTION LENGTH(S(1:2)).",
])
def test_certified_uses_lower_to_runtime_calls(body):
    assert _messages(body) == []
    code = _java(body)
    assert "FUNCTION +" not in code and "UNSUPPORTED" not in code


@pytest.mark.parametrize("body", [
    "           IF FUNCTION LENGTH(S) > 2 DISPLAY 'Y'.",
    "           COMPUTE N = FUNCTION LENGTH(S).",
    "           DISPLAY FUNCTION MIN(1, 2).",
    "           DISPLAY FUNCTION RANDOM.",
])
def test_every_other_use_fails_closed_with_a_diagnostic(body):
    assert any("ntrinsic" in m for m in _messages(body))


def test_a_numeric_argument_is_refused_by_the_generator_and_the_analyzer():
    from engine.transformation.cobol_to_java_mapping import function_problem

    program = CobolParser().parse(_source("           DISPLAY FUNCTION UPPER-CASE(Q)."))
    assert "alphanumeric" in function_problem("FUNCTION UPPER-CASE(Q)", program)
    assert function_problem("FUNCTION UPPER-CASE(S)", program) == ""

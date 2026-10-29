"""Regression tests for structured COMPUTE expression mapping."""

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.ir import ComputeStatement


def test_compute_uses_structured_expression_for_chained_arithmetic() -> None:
    source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPUTE-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TOTAL PIC 9(6) VALUE 90.
       01 WS-TAX PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
           COMPUTE WS-TAX = WS-TOTAL * 10 / 100.
           STOP RUN.
"""
    program = CobolParser().parse(source)
    stmt = next(
        s
        for s in program.paragraphs[0].statements
        if isinstance(s, ComputeStatement)
    )

    assert stmt.expression_expr is not None

    java = map_cobol_program_to_java(program)
    assignment = next(
        s
        for s in java.java_class.methods[0].body_statements
        if getattr(s, "target", "") == "WS_TAX"
    )

    expr = assignment.expression
    assert expr.operator == "/"
    assert expr.right.value == "100"
    assert expr.left.operator == "*"
    assert expr.left.left.name == "WS_TOTAL"
    assert expr.left.right.value == "10"

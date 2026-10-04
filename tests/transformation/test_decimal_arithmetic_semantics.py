"""Focused regression tests for numeric arithmetic precision/scale and rounding semantics."""

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.java_generator import JavaGenerator


def _parse_map(cobol: str):
    return map_cobol_program_to_java(CobolParser().parse(cobol))


def _assignment(java_program, target: str):
    for statement in java_program.java_class.methods[0].body_statements:
        if getattr(statement, "target", None) == target:
            return statement
    raise AssertionError(f"No assignment for {target}")


def test_decimal_receiver_promotes_integer_division_and_truncates_to_scale():
    cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 100.
01 WS-B PIC 9(5) VALUE 3.
01 WS-RESULT PIC S9(5)V99 VALUE 0.
PROCEDURE DIVISION.
MAIN.
    COMPUTE WS-RESULT = WS-A / WS-B.
    STOP RUN.
"""
    java = _parse_map(cobol)
    source = JavaGenerator()._stmt_to_string(_assignment(java, "WS_RESULT"))

    assert "(double)(WS_A)" in source
    assert "(double)(WS_B)" in source
    assert "setScale(2, java.math.RoundingMode.DOWN)" in source
    assert source.endswith(".doubleValue();")


def test_decimal_receiver_rounded_uses_half_up_and_narrows_to_integer():
    cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC-ROUND.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC S9(3)V9 VALUE 2.5.
01 WS-RESULT PIC S9(3) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    COMPUTE WS-RESULT ROUNDED = WS-A.
    STOP RUN.
"""
    java = _parse_map(cobol)
    assignment = _assignment(java, "WS_RESULT")
    source = JavaGenerator()._stmt_to_string(assignment)

    assert "setScale(0, java.math.RoundingMode.HALF_UP)" in source
    assert source.endswith(".intValueExact();")


def test_decimal_receiver_default_is_truncation_for_negative_values():
    cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC-NEG.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC S9(3)V999 VALUE -2.999.
01 WS-RESULT PIC S9(3)V99 VALUE 0.
PROCEDURE DIVISION.
MAIN.
    COMPUTE WS-RESULT = WS-A.
    STOP RUN.
"""
    java = _parse_map(cobol)
    source = JavaGenerator()._stmt_to_string(_assignment(java, "WS_RESULT"))
    assert "setScale(2, java.math.RoundingMode.DOWN)" in source


def test_arithmetic_parser_preserves_rounded_and_add_giving():
    cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC-FORMS.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(3) VALUE 1.
01 WS-B PIC 9(3) VALUE 2.
01 WS-C PIC 9(3) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    ADD WS-A TO WS-B GIVING WS-C ROUNDED.
    STOP RUN.
"""
    statement = CobolParser().parse(cobol).paragraphs[0].statements[0]
    assert statement.giving_target == "WS-C"
    assert statement.rounded is True


def test_divide_rounded_before_remainder_is_preserved():
    cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC-DIV.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC S9(3)V99 VALUE 10.00.
01 WS-B PIC S9(3) VALUE 3.
01 WS-C PIC S9(3)V99 VALUE 0.
01 WS-R PIC S9(3) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE WS-A BY WS-B GIVING WS-C ROUNDED REMAINDER WS-R.
    STOP RUN.
"""
    statement = CobolParser().parse(cobol).paragraphs[0].statements[0]
    assert statement.rounded is True
    assert statement.remainder == "WS-R"


def test_pure_integer_receiver_keeps_native_arithmetic():
    cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. INTEGER-ARITH.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 100.
01 WS-B PIC 9(5) VALUE 3.
01 WS-RESULT PIC 9(9) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    COMPUTE WS-RESULT = WS-A / WS-B.
    STOP RUN.
"""
    java = _parse_map(cobol)
    source = JavaGenerator()._stmt_to_string(_assignment(java, "WS_RESULT"))
    assert source == "WS_RESULT = (WS_A / WS_B);"

    
def test_signed_pic_metadata_is_preserved_and_integer_narrowing_is_exact():
    cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC-SIGNED.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-AMOUNT PIC S9(4)V99 VALUE -12.34.
01 WS-RESULT PIC S9(4) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    COMPUTE WS-RESULT ROUNDED = WS-AMOUNT.
    STOP RUN.
"""
    program = CobolParser().parse(cobol)
    amount = next(item for item in program.working_storage if item.name == "WS-AMOUNT")
    assert amount.signed is True
    java = _parse_map(cobol)
    source = JavaGenerator()._stmt_to_string(_assignment(java, "WS_RESULT"))
    assert source.endswith(".intValueExact();")

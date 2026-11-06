"""Hermetic tests for reference modification (roadmap unit 32); GnuCOBOL proof: tests/integration/test_refmod_oracle.py."""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.ref_support_template import COBOL_REF_JAVA
from engine.transformation.refmod import RefMod, parse_refmod, split_outside_parentheses

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. RM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TA PIC X(10) VALUE 'ABCDEFGHIJ'.
       01 TB PIC X(10).
       01 NUM PIC 9(6) VALUE 120345.
       01 SGN PIC S9(4) VALUE 12.
       01 VN PIC 99 VALUE 2.
       01 VL PIC 99 VALUE 3.
       01 TBL.
          05 ROW PIC X(4) OCCURS 3 TIMES.
       PROCEDURE DIVISION.
       MAIN.
"""


def _parse(body: str):
    parser = CobolParser()
    program = parser.parse(HEAD + body + "           STOP RUN.\n")
    return program, [d.message for d in parser.diagnostics.all if d.code.name == "UNSUPPORTED_CONSTRUCT"]


def _java(body: str) -> str:
    program, diagnostics = _parse(body)
    assert diagnostics == [], diagnostics
    return JavaGenerator().generate(program)[0].source_code


def test_parse_refmod_forms():
    assert parse_refmod("TA(1:3)") == RefMod("TA", "1", "3")
    assert parse_refmod("TA(VN + 1:VL)") == RefMod("TA", "VN + 1", "VL")
    assert parse_refmod("TA(4:)") == RefMod("TA", "4", "")
    assert parse_refmod("TA(1)") is None and parse_refmod("TA") is None and parse_refmod("1:3") is None
    assert split_outside_parentheses("TA(VN + 1:VL) TB TC(2:2)") == ["TA(VN + 1:VL)", "TB", "TC(2:2)"]


def test_move_display_and_if_lower_through_the_cobolref_helper():
    java = _java(
        "           MOVE TA(1:3) TO TB.\n           MOVE 'XY' TO TA(2:2).\n           MOVE SPACES TO TB(VN:VL).\n"
        "           DISPLAY TA(VN + 1:VL).\n           IF TA(1:1) = 'A'\n               DISPLAY 'Y'\n           END-IF.\n")
    assert "CobolRef.sub(TA, 1, 3)" in java
    assert 'TA = CobolRef.put(TA, 2, 2, "XY")' in java
    assert 'TB = CobolRef.put(TB, VN, VL, CobolRef.repeat(" ", VL))' in java
    assert "CobolRef.sub(TA, (VN + 1), VL)" in java
    assert 'CobolRef.compare(CobolRef.sub(TA, 1, 1), "A") == 0' in java
    assert "final class CobolRef" in java


def test_a_numeric_item_is_addressed_by_its_digits():
    java = _java("           MOVE NUM(2:3) TO TB.\n")
    assert 'String.format("%06d", NUM)' in java


@pytest.mark.parametrize("statement", [
    "           ADD TA(1:1) TO VN.\n",
    "           COMPUTE VN = TA(1:1).\n",
    "           STRING TA(1:2) DELIMITED BY SIZE INTO TB.\n",
    "           INSPECT TA(1:3) TALLYING VN FOR ALL 'A'.\n",
])
def test_other_statements_are_refused_by_name(statement):
    _, diagnostics = _parse(statement)
    assert any("only certified in MOVE, DISPLAY and IF / WHEN / UNTIL conditions" in d for d in diagnostics), diagnostics


@pytest.mark.parametrize("body, why", [
    ("           MOVE TA(1:2) TO NUM.\n", "a numeric receiver is not certified"),
    ("           MOVE SGN(1:2) TO TB.\n", "a signed, decimal or edited base is not certified"),
    ("           MOVE ROW(1)(1:2) TO TB.\n", "reference modification"),
    ("           MOVE TA(VN * 2:1) TO TB.\n", "start and length must be"),
    ("           MOVE 5 TO TA(1:2).\n", "the sender must be a literal"),
    ("           MOVE HIGH-VALUES TO TA(1:2).\n", "only SPACES, ZEROS and ALL literal"),
    ("           IF TA(1:1) = 5 DISPLAY 'X' END-IF.\n", "an operand of a relation is a quoted literal"),
])
def test_forms_outside_the_subset_fail_closed_at_generation(body, why):
    program, _ = _parse(body)
    with pytest.raises(ValueError) as error:
        JavaGenerator().generate(program)
    assert why in str(error.value) or "UNSUPPORTED" in str(error.value), str(error.value)


def test_the_runtime_refuses_a_reference_outside_the_item_instead_of_inventing_a_value():
    assert "IllegalStateException" in COBOL_REF_JAVA and "outside an item of" in COBOL_REF_JAVA
    for method in ("sub", "subRest", "put", "putRest", "compare", "fit", "repeat"):
        assert f"static " in COBOL_REF_JAVA and f" {method}(" in COBOL_REF_JAVA, method

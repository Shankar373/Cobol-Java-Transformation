"""OCCURS table lowering into Java arrays.

Pinned contract (previously the mapper emitted ``static int WS_ELEMENT = 0;``
and ``WS_ELEMENT(WS_INDEX) = ...`` — method-call syntax on a scalar, which does
not compile):

* a table item becomes a real Java array sized from ``OCCURS n TIMES``;
* every COBOL subscript is 1-based and lowers to ``[index - 1]``;
* a group with ``OCCURS`` lowers its elementary subordinates to parallel
  arrays (the IR flattens group members; this is the COBOL "table of records"
  view for flat subordinate structures);
* DISPLAY keeps the subscript attached to the item instead of tokenising
  ``WS-ELEMENT(WS-INDEX)`` into two operands;
* the numeric DISPLAY width still comes from the element PIC, not the array.
"""

from __future__ import annotations

import re

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import ComputeStatement, DisplayStatement
from engine.transformation.java_generator import JavaGenerator

ELEMENTARY_TABLE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. OCCURS-DEMO.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-TABLE.
    05  WS-ELEMENT      PIC 9(3) OCCURS 5 TIMES.
01  WS-INDEX          PIC 9(2) VALUE 0.
01  WS-SUM            PIC 9(4) VALUE 0.
PROCEDURE DIVISION.
MAIN-LOGIC.
    PERFORM VARYING WS-INDEX FROM 1 BY 1 UNTIL WS-INDEX > 5
        COMPUTE WS-ELEMENT(WS-INDEX) = WS-INDEX * 10
    END-PERFORM.
    ADD WS-ELEMENT(1) TO WS-SUM.
    DISPLAY "ELEMENT=" WS-ELEMENT(WS-INDEX).
    STOP RUN.
"""

ALPHANUMERIC_TABLE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. NAME-TABLE.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-NAMES.
    05  WS-NAME         PIC X(4) OCCURS 3 TIMES.
01  WS-I               PIC 9(1) VALUE 0.
PROCEDURE DIVISION.
MAIN-LOGIC.
    MOVE "AB" TO WS-NAME(1).
    DISPLAY "NAME=" WS-NAME(1) "|".
    STOP RUN.
"""

GROUP_OCCURS = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. GROUP-TABLE.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-STORE.
    05  WS-ITEM OCCURS 3 TIMES.
        10  WS-ID       PIC 9(2).
        10  WS-LABEL    PIC X(3).
01  WS-I               PIC 9(1) VALUE 0.
PROCEDURE DIVISION.
MAIN-LOGIC.
    MOVE 7 TO WS-ID(2).
    MOVE "XYZ" TO WS-LABEL(2).
    DISPLAY "ID=" WS-ID(2) " LABEL=" WS-LABEL(2).
    STOP RUN.
"""


def _parse(source: str):
    parser = CobolParser()
    return parser, parser.parse(source)


def _statements(program):
    """Every statement in source order, including nested clause bodies."""
    found = []

    def walk(statements):
        for stmt in statements:
            found.append(stmt)
            for attr in (
                "body", "then_body", "else_body", "at_end_body",
                "not_at_end_body", "invalid_key_body", "not_invalid_key_body",
            ):
                nested = getattr(stmt, attr, None)
                if nested:
                    walk(nested)

    for para in program.paragraphs:
        walk(para.statements)
    return found


def _source(source: str) -> str:
    _, program = _parse(source)
    return JavaGenerator().generate(program)[0].source_code


class TestParserKeepsSubscripts:
    def test_display_subscript_is_one_operand(self) -> None:
        parser, program = _parse(ELEMENTARY_TABLE)
        displays = [
            stmt
            for stmt in _statements(program)
            if isinstance(stmt, DisplayStatement)
        ]
        # No display metadata is lost to the generic "skipped" channel.
        assert not [
            d for d in parser.diagnostics.all
            if "DISPLAY" in d.message.upper()
        ]
        assert any(
            part == "WS-ELEMENT(WS-INDEX)"
            for stmt in displays
            for part in stmt.parts
        ), [stmt.parts for stmt in displays]

    def test_subscripted_target_is_preserved(self) -> None:
        _, program = _parse(ELEMENTARY_TABLE)
        computes = [
            stmt
            for stmt in _statements(program)
            if isinstance(stmt, ComputeStatement)
        ]
        assert computes[0].target == "WS-ELEMENT(WS-INDEX)"


class TestArrayDeclaration:
    def test_elementary_table_becomes_array(self) -> None:
        source = _source(ELEMENTARY_TABLE)
        assert "int[] WS_ELEMENT = new int[5];" in source, source
        assert not re.search(r"\bstatic\s+int\s+WS_ELEMENT\s*=", source)

    def test_alphanumeric_table_becomes_string_array(self) -> None:
        source = _source(ALPHANUMERIC_TABLE)
        assert "String[] WS_NAME" in source, source
        # PIC X(4) entries are blank-filled, never Java null.
        assert "WS_NAME = " in source
        assert "new String[3]" in source or "nCopies(3" in source, source

    def test_group_occurs_lowers_subordinates_to_arrays(self) -> None:
        source = _source(GROUP_OCCURS)
        assert "int[] WS_ID = new int[3];" in source, source
        assert "String[] WS_LABEL" in source, source


class TestSubscriptLowering:
    def test_assignment_uses_zero_based_index(self) -> None:
        source = _source(ELEMENTARY_TABLE)
        assert "WS_ELEMENT[(WS_INDEX - 1)] = (WS_INDEX * 10);" in source, source

    def test_expression_uses_zero_based_index(self) -> None:
        source = _source(ELEMENTARY_TABLE)
        # ADD ... TO ... lowers through fixed-point truncation, but the
        # subscript must still be zero-based.
        assert "WS_SUM = " in source, source
        assert "WS_ELEMENT[(1 - 1)]" in source, source
        assert "WS_ELEMENT[1]" not in source, source

    def test_display_keeps_element_format(self) -> None:
        source = _source(ELEMENTARY_TABLE)
        assert 'String.format("%03d", WS_ELEMENT[(WS_INDEX - 1)])' in source, source
        # The old bug emitted a second formatted (or bare) index operand.
        assert 'String.format("%02d", WS_INDEX) + String.format("%02d"' not in source

    def test_alphanumeric_subscripted_move(self) -> None:
        source = _source(ALPHANUMERIC_TABLE)
        assert 'WS_NAME[(1 - 1)]' in source, source

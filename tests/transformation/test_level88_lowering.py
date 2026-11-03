"""Level-88 condition-name lowering and ``SET ... TO TRUE``.

Pinned contract (previously the mapper emitted ``TRUE = STAT-OK`` and
``if ("GENDER_MALE")`` — neither compiles — and dropped
``SET STAT-OK TO TRUE`` with no diagnostic):

* an 88 condition name resolves to a comparison on its parent data item;
* numeric parents compare their numeric value (``VALUE 00`` is decimal 0,
  never Java octal);
* ``VALUE a THRU b`` becomes a closed range;
* alphanumeric parents use content equality, not Java reference identity;
* ``EVALUATE TRUE WHEN <condition-name>`` (lowered by the parser to
  ``TRUE = <name>``) resolves to the same comparison;
* ``SET <condition-name> TO TRUE`` assigns the parent the value that
  satisfies the condition, with the parent's PIC width/semantics;
* no ``UNSUPPORTED_CONSTRUCT`` diagnostic remains for the certified forms.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.ir import SetConditionStatement
from engine.transformation.java_generator import JavaGenerator

LEVEL88 = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. LEVEL88-DEMO.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-STATUS         PIC 9(2) VALUE 10.
    88  STAT-OK            VALUE 00.
    88  STAT-WARNING       VALUE 01 THRU 09.
    88  STAT-ERROR         VALUE 10 THRU 99.
01  WS-GENDER         PIC X VALUE 'M'.
    88  GENDER-MALE        VALUE 'M'.
    88  GENDER-FEMALE      VALUE 'F'.
01  WS-RESULT         PIC X(20) VALUE SPACES.
PROCEDURE DIVISION.
MAIN-LOGIC.
    EVALUATE TRUE
        WHEN STAT-OK
            MOVE "STATUS OK" TO WS-RESULT
        WHEN STAT-WARNING
            MOVE "STATUS WARNING" TO WS-RESULT
        WHEN STAT-ERROR
            MOVE "STATUS ERROR" TO WS-RESULT
    END-EVALUATE.
    DISPLAY "STATUS CHECK: " WS-RESULT.
    IF GENDER-MALE
        DISPLAY "GENDER IS MALE"
    ELSE
        DISPLAY "GENDER IS FEMALE"
    END-IF.
    SET STAT-OK TO TRUE.
    SET GENDER-FEMALE TO TRUE.
    STOP RUN.
"""


def _parse(source: str):
    parser = CobolParser()
    return parser, parser.parse(source)


def _source(source: str) -> str:
    _, program = _parse(source)
    return JavaGenerator().generate(program)[0].source_code


class TestParserRepresentsConditionSet:
    def test_set_to_true_parses_into_ir(self) -> None:
        parser, program = _parse(LEVEL88)
        sets = [
            stmt
            for para in program.paragraphs
            for stmt in para.statements
            if isinstance(stmt, SetConditionStatement)
        ]
        assert [s.target for s in sets] == ["STAT-OK", "GENDER-FEMALE"]

    def test_certified_set_forms_are_not_diagnosed_as_unsupported(self) -> None:
        parser, _ = _parse(LEVEL88)
        messages = [
            d.message
            for d in parser.diagnostics.all
            if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
        ]
        assert not [m for m in messages if "SET" in m.upper()], messages


class TestConditionNameResolution:
    def test_numeric_single_value(self) -> None:
        source = _source(LEVEL88)
        # VALUE 00 must be decimal zero, never the octal literal 00.
        assert "if (WS_STATUS == 0)" in source, source

    def test_numeric_thru_range(self) -> None:
        source = _source(LEVEL88)
        assert (
            "((WS_STATUS >= 1) && (WS_STATUS <= 9))" in source
        ), source

    def test_alphanumeric_uses_content_equality(self) -> None:
        source = _source(LEVEL88)
        assert 'if ("M".equals(WS_GENDER))' in source, source


class TestSetConditionToTrue:
    def test_numeric_condition_sets_parent_value(self) -> None:
        source = _source(LEVEL88)
        assert "WS_STATUS = 0;" in source, source

    def test_alphanumeric_condition_sets_parent_value(self) -> None:
        source = _source(LEVEL88)
        assert 'WS_GENDER = "F";' in source, source


class TestNoStaleReferences:
    def test_no_condition_name_becomes_a_bare_identifier(self) -> None:
        source = _source(LEVEL88)
        for name in ("STAT_OK", "STAT_WARNING", "STAT_ERROR",
                     "GENDER_MALE", "GENDER_FEMALE"):
            assert name not in source, (name, source)
        assert "TRUE ==" not in source


PADDED = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. PADDED.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-CODE           PIC X(3) VALUE 'A'.
    88  CODE-A            VALUE 'A'.
    88  CODE-BLANK        VALUE SPACES.
PROCEDURE DIVISION.
MAIN-LOGIC.
    IF CODE-A
        DISPLAY "A"
    END-IF.
    SET CODE-BLANK TO TRUE.
    DISPLAY "CODE=" WS-CODE "|".
    STOP RUN.
"""

UNSUPPORTED_VALUE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. BADVALUE.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-LIMIT          PIC 9(2) VALUE 9.
01  WS-STATUS         PIC 9(2) VALUE 10.
    88  STAT-OK           VALUE WS-LIMIT.
PROCEDURE DIVISION.
MAIN-LOGIC.
    SET STAT-OK TO TRUE.
    STOP RUN.
"""


class TestAlphanumericWidthSemantics:
    def test_condition_literal_is_padded_to_parent_width(self) -> None:
        source = _source(PADDED)
        assert '"A  ".equals(WS_CODE)' in source, source

    def test_set_spaces_fills_parent_width(self) -> None:
        source = _source(PADDED)
        assert 'WS_CODE = "   ";' in source, source


class TestUnsupportedValueFormsFailClosed:
    def test_bare_identifier_value_is_reported(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            condition_name_problems,
        )

        parser = CobolParser()
        program = parser.parse(UNSUPPORTED_VALUE)
        problems = condition_name_problems(program)
        assert "STAT-OK" in problems, problems
        assert "WS-LIMIT" in problems["STAT-OK"]

    def test_set_of_unsupported_condition_emits_fail_closed_symbol(self) -> None:
        source = _source(UNSUPPORTED_VALUE)
        assert "WS_STATUS = UNSUPPORTED_SET$CONDITION$STAT_OK;" in source, source
        # The condition name itself is never turned into an assignment target.
        assert "STAT_OK = " not in source, source
        # The parent keeps its declared VALUE; no guessed value is written.
        body = source.split("public static void MAIN_LOGIC", 1)[1]
        assert "WS_STATUS = 10;" not in body, source


class TestSourceDetection:
    def test_certified_set_is_not_generic_set(self) -> None:
        from engine.transformation.semantic_capability import scan_constructs

        found = scan_constructs("SET STAT-OK TO TRUE.")
        assert "SET CONDITION TO TRUE" in found, found
        assert "SET" not in found, found

    def test_generic_set_still_detected(self) -> None:
        from engine.transformation.semantic_capability import scan_constructs

        for clause in ("SET WS-I TO 2.", "SET WS-I UP BY 1."):
            found = scan_constructs(clause)
            assert "SET" in found, (clause, found)
            assert "SET CONDITION TO TRUE" not in found, (clause, found)

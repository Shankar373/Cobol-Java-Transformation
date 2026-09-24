"""Tests for arithmetic GIVING operations.

Verifies:
  1. Parser correctly parses SUBTRACT...GIVING, MULTIPLY...GIVING, DIVIDE...GIVING
  2. Mapping produces correct Java IR for GIVING vs in-place forms
  3. Semantic difference between GIVING (target unchanged) and in-place (target mutated)
  4. Semantic correctness: SUBTRACT A FROM B GIVING C means C = B - A
  5. Semantic correctness: MULTIPLY A BY B GIVING C means C = A * B
  6. Semantic correctness: DIVIDE A BY B GIVING C means C = A / B (integer)
"""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.ir import (
    AddStatement,
    SubtractStatement,
    MultiplyStatement,
    DivideStatement,
)


@pytest.fixture
def parser() -> CobolParser:
    return CobolParser()


# ============================================================
# Parser Tests
# ============================================================

class TestSubtractGivingParser:
    """SUBTRACT A FROM B GIVING C parser tests."""

    def test_subtract_giving_parsed(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A FROM WS-B GIVING WS-C.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, SubtractStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "WS-A"
        assert stmt.from_field == "WS-B"
        assert stmt.to_field == "WS-C"

    def test_subtract_inplace_parsed(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A FROM WS-B.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, SubtractStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "WS-A"
        assert stmt.from_field == "WS-B"
        assert stmt.to_field is None

    def test_subtract_literal_giving(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT 10 FROM WS-B GIVING WS-C.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, SubtractStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "10"
        assert stmt.from_field == "WS-B"
        assert stmt.to_field == "WS-C"


class TestMultiplyGivingParser:
    """MULTIPLY A BY B GIVING C parser tests."""

    def test_multiply_giving_parsed(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, MultiplyStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "WS-A"
        assert stmt.multiplicand == "WS-B"
        assert stmt.target == "WS-C"

    def test_multiply_inplace_parsed(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY WS-A BY WS-B.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, MultiplyStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "WS-A"
        assert stmt.multiplicand == "WS-B"
        assert stmt.target is None

    def test_multiply_literal_giving(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY 4 BY WS-B GIVING WS-C.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, MultiplyStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "4"
        assert stmt.multiplicand == "WS-B"
        assert stmt.target == "WS-C"


class TestDivideGivingParser:
    """DIVIDE A BY B GIVING C parser tests."""

    def test_divide_giving_parsed(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, DivideStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "WS-A"
        assert stmt.divisor == "WS-B"
        assert stmt.target == "WS-C"
        assert stmt.remainder == ""

    def test_divide_giving_remainder_parsed(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
01 WS-R PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE WS-A BY WS-B GIVING WS-C REMAINDER WS-R.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, DivideStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "WS-A"
        assert stmt.divisor == "WS-B"
        assert stmt.target == "WS-C"
        assert stmt.remainder == "WS-R"

    def test_divide_literal_giving(self, parser: CobolParser):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE 100 BY WS-B GIVING WS-C.
    STOP RUN.
"""
        program = parser.parse(cobol)
        main = next(p for p in program.paragraphs if p.name == "MAIN")
        stmts = [s for s in main.statements if isinstance(s, DivideStatement)]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.source == "100"
        assert stmt.divisor == "WS-B"
        assert stmt.target == "WS-C"


# ============================================================
# Mapping Tests
# ============================================================

class TestSubtractGivingMapping:
    """SUBTRACT A FROM B GIVING C -> Java IR mapping tests."""

    def _parse_and_map(self, cobol: str):
        parser = CobolParser()
        program = parser.parse(cobol)
        return map_cobol_program_to_java(program)

    def test_giving_target_is_result(self):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A FROM WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        stmts = [s for s in java.java_class.methods[0].body_statements
                 if hasattr(s, 'target') and s.target == 'WS_C']
        assert len(stmts) == 1
        expr = stmts[0].expression
        assert expr.operator == "-"
        assert hasattr(expr.left, 'name') and expr.left.name == 'WS_B'
        assert hasattr(expr.right, 'name') and expr.right.name == 'WS_A'

    def test_inplace_target_is_from_field(self):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A FROM WS-B.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        stmts = [s for s in java.java_class.methods[0].body_statements
                 if hasattr(s, 'target') and s.target == 'WS_B']
        assert len(stmts) == 1
        expr = stmts[0].expression
        assert expr.operator == "-"
        assert hasattr(expr.left, 'name') and expr.left.name == 'WS_B'
        assert hasattr(expr.right, 'name') and expr.right.name == 'WS_A'

    def test_from_field_unchanged_after_giving(self):
        """GIVING must not mutate the FROM field."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A FROM WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        # WS_B should not have any assignment from the SUBTRACT statement
        ws_b_assigns = [s for s in java.java_class.methods[0].body_statements
                       if hasattr(s, 'target') and s.target == 'WS_B']
        # No assignments to WS_B at all (no MOVE, no SUBTRACT target)
        assert len(ws_b_assigns) == 0


class TestMultiplyGivingMapping:
    """MULTIPLY A BY B GIVING C -> Java IR mapping tests."""

    def _parse_and_map(self, cobol: str):
        parser = CobolParser()
        program = parser.parse(cobol)
        return map_cobol_program_to_java(program)

    def test_giving_target_is_result(self):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        stmts = [s for s in java.java_class.methods[0].body_statements
                 if hasattr(s, 'target') and s.target == 'WS_C']
        assert len(stmts) == 1
        expr = stmts[0].expression
        assert expr.operator == "*"
        assert hasattr(expr.left, 'name') and expr.left.name == 'WS_A'
        assert hasattr(expr.right, 'name') and expr.right.name == 'WS_B'

    def test_inplace_target_is_multiplicand(self):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY WS-A BY WS-B.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        stmts = [s for s in java.java_class.methods[0].body_statements
                 if hasattr(s, 'target') and s.target == 'WS_B']
        assert len(stmts) == 1
        expr = stmts[0].expression
        assert expr.operator == "*"

    def test_both_operands_unchanged_after_giving(self):
        """GIVING must not mutate A or B."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        # WS_A and WS_B should not have any assignment from the MULTIPLY statement
        ws_a_assigns = [s for s in java.java_class.methods[0].body_statements
                       if hasattr(s, 'target') and s.target == 'WS_A']
        ws_b_assigns = [s for s in java.java_class.methods[0].body_statements
                       if hasattr(s, 'target') and s.target == 'WS_B']
        assert len(ws_a_assigns) == 0
        assert len(ws_b_assigns) == 0


class TestDivideGivingMapping:
    """DIVIDE A BY B GIVING C -> Java IR mapping tests."""

    def _parse_and_map(self, cobol: str):
        parser = CobolParser()
        program = parser.parse(cobol)
        return map_cobol_program_to_java(program)

    def test_giving_target_is_quotient(self):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        stmts = [s for s in java.java_class.methods[0].body_statements
                 if hasattr(s, 'target') and s.target == 'WS_C']
        assert len(stmts) == 1
        expr = stmts[0].expression
        assert expr.operator == "/"
        assert hasattr(expr.left, 'name') and expr.left.name == 'WS_A'
        assert hasattr(expr.right, 'name') and expr.right.name == 'WS_B'

    def test_remainder_produces_modulo(self):
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
01 WS-R PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE WS-A BY WS-B GIVING WS-C REMAINDER WS-R.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        remainder_stmts = [s for s in java.java_class.methods[0].body_statements
                          if hasattr(s, 'target') and s.target == 'WS_R']
        assert len(remainder_stmts) == 1
        expr = remainder_stmts[0].expression
        assert expr.operator == "%"

    def test_both_operands_unchanged_after_giving(self):
        """GIVING must not mutate A or B."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        ws_a_assigns = [s for s in java.java_class.methods[0].body_statements
                       if hasattr(s, 'target') and s.target == 'WS_A']
        ws_b_assigns = [s for s in java.java_class.methods[0].body_statements
                       if hasattr(s, 'target') and s.target == 'WS_B']
        assert len(ws_a_assigns) == 0
        assert len(ws_b_assigns) == 0


# ============================================================
# Semantic Correctness Tests (GIVING vs in-place)
# ============================================================

class TestGivingVsInPlaceSemantics:
    """Verify semantic difference between GIVING and in-place forms."""

    def _parse_and_map(self, cobol: str):
        parser = CobolParser()
        program = parser.parse(cobol)
        return map_cobol_program_to_java(program)

    def test_subtract_giving_does_not_mutate_from(self):
        """SUBTRACT A FROM B GIVING C: B must not be reassigned."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A FROM WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        targets = [s.target for s in java.java_class.methods[0].body_statements
                  if hasattr(s, 'target')]
        # Only WS_C should be assigned the subtraction result
        assert "WS_C" in targets
        assert targets.count("WS_B") == 0  # B should not be reassigned

    def test_subtract_inplace_mutates_from(self):
        """SUBTRACT A FROM B: B must be reassigned."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A FROM WS-B.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        targets = [s.target for s in java.java_class.methods[0].body_statements
                  if hasattr(s, 'target')]
        assert "WS_B" in targets

    def test_multiply_giving_does_not_mutate_operands(self):
        """MULTIPLY A BY B GIVING C: neither A nor B should be reassigned."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        targets = [s.target for s in java.java_class.methods[0].body_statements
                  if hasattr(s, 'target')]
        assert "WS_C" in targets
        assert targets.count("WS_A") == 0
        assert targets.count("WS_B") == 0

    def test_multiply_inplace_mutates_multiplicand(self):
        """MULTIPLY A BY B: B must be reassigned."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY WS-A BY WS-B.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        targets = [s.target for s in java.java_class.methods[0].body_statements
                  if hasattr(s, 'target')]
        assert "WS_B" in targets

    def test_divide_giving_does_not_mutate_operands(self):
        """DIVIDE A BY B GIVING C: neither A nor B should be reassigned."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        targets = [s.target for s in java.java_class.methods[0].body_statements
                  if hasattr(s, 'target')]
        assert "WS_C" in targets
        assert targets.count("WS_A") == 0
        assert targets.count("WS_B") == 0


# ============================================================
# COBOL Semantic Correctness Tests
# ============================================================

class TestCobolSemanticCorrectness:
    """Verify COBOL semantic rules are correctly mapped."""

    def _parse_and_map(self, cobol: str):
        parser = CobolParser()
        program = parser.parse(cobol)
        return map_cobol_program_to_java(program)

    def _get_assignment(self, java, target_name):
        """Get the JavaAssignment for a target variable."""
        for s in java.java_class.methods[0].body_statements:
            if hasattr(s, 'target') and s.target == target_name:
                return s
        return None

    def test_subtract_giving_c_equals_b_minus_a(self):
        """SUBTRACT A FROM B GIVING C means C = B - A (NOT A - B)."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    SUBTRACT WS-A FROM WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        assignment = self._get_assignment(java, "WS_C")
        assert assignment is not None
        expr = assignment.expression
        # C = B - A: left=B, right=A
        assert expr.operator == "-"
        assert hasattr(expr.left, 'name') and expr.left.name == 'WS_B'
        assert hasattr(expr.right, 'name') and expr.right.name == 'WS_A'

    def test_multiply_giving_c_equals_a_times_b(self):
        """MULTIPLY A BY B GIVING C means C = A * B."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    MULTIPLY WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        assignment = self._get_assignment(java, "WS_C")
        assert assignment is not None
        expr = assignment.expression
        assert expr.operator == "*"
        assert hasattr(expr.left, 'name') and expr.left.name == 'WS_A'
        assert hasattr(expr.right, 'name') and expr.right.name == 'WS_B'

    def test_divide_giving_c_equals_a_div_b(self):
        """DIVIDE A BY B GIVING C means C = A / B (integer)."""
        cobol = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(5) VALUE 0.
01 WS-B PIC 9(5) VALUE 0.
01 WS-C PIC 9(5) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DIVIDE WS-A BY WS-B GIVING WS-C.
    STOP RUN.
"""
        java = self._parse_and_map(cobol)
        assignment = self._get_assignment(java, "WS_C")
        assert assignment is not None
        expr = assignment.expression
        assert expr.operator == "/"
        assert hasattr(expr.left, 'name') and expr.left.name == 'WS_A'
        assert hasattr(expr.right, 'name') and expr.right.name == 'WS_B'

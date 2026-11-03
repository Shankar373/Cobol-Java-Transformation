"""Tests for Task 6: COBOL Semantic Foundation.

Verifies:
- IR construction tests (structured expressions and conditions)
- Domain-neutral tests
- Lexical false-positive tests
- Mutation tests
- Negative tests
- Determinism tests

The capability-equivalence, lexical-false-positive and capability negative
tests were removed with ``derive_capabilities`` (audit T5): capabilities only
selected the deleted template lanes.
"""

from __future__ import annotations

import hashlib

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import (
    AddStatement,
    BinaryExpression,
    BooleanCondition,
    CobolProgram,
    Comparison,
    Condition,
    DataItem,
    DisplayStatement,
    DivideStatement,
    Expression,
    FieldReference,
    FileDefinition,
    IfStatement,
    Literal,
    LogicalCondition,
    MoveStatement,
    NegatedCondition,
    Paragraph,
    PerformStatement,
    PicType,
    ReadStatement,
    StopRunStatement,
    StringStatement,
    UnaryExpression,
    UnstringStatement,
    WriteStatement,
)
from engine.transformation.java_generator import JavaGenerator


# ============================================================
# A. IR Construction Tests
# ============================================================

class TestExpressionIR:
    """Verify structured expression IR construction."""

    def test_literal_numeric(self):
        """Numeric literal becomes Literal with is_numeric=True."""
        lit = Literal(value="42", is_numeric=True)
        assert lit.value == "42"
        assert lit.is_numeric is True

    def test_literal_string(self):
        """String literal becomes Literal with is_numeric=False."""
        lit = Literal(value="HELLO", is_numeric=False)
        assert lit.value == "HELLO"
        assert lit.is_numeric is False

    def test_field_reference(self):
        """Field name becomes FieldReference."""
        ref = FieldReference(name="CUSTOMER-ID")
        assert ref.name == "CUSTOMER-ID"

    def test_binary_expression(self):
        """Binary operation becomes BinaryExpression."""
        expr = BinaryExpression(
            left=FieldReference(name="A"),
            operator="+",
            right=Literal(value="10", is_numeric=True),
        )
        assert expr.left.name == "A"
        assert expr.operator == "+"
        assert expr.right.value == "10"

    def test_unary_expression(self):
        """Unary NOT becomes UnaryExpression."""
        expr = UnaryExpression(
            operator="NOT",
            operand=FieldReference(name="flag"),
        )
        assert expr.operator == "NOT"
        assert expr.operand.name == "flag"

    def test_nested_binary_expression(self):
        """Nested binary operations create tree structure."""
        expr = BinaryExpression(
            left=BinaryExpression(
                left=FieldReference(name="A"),
                operator="+",
                right=FieldReference(name="B"),
            ),
            operator="*",
            right=Literal(value="2", is_numeric=True),
        )
        assert expr.left.left.name == "A"
        assert expr.left.operator == "+"
        assert expr.left.right.name == "B"
        assert expr.operator == "*"
        assert expr.right.value == "2"


class TestConditionIR:
    """Verify structured condition IR construction."""

    def test_comparison(self):
        """Comparison becomes Comparison condition."""
        cond = Comparison(
            left=FieldReference(name="AMOUNT"),
            operator=">",
            right=Literal(value="1000", is_numeric=True),
        )
        assert cond.left.name == "AMOUNT"
        assert cond.operator == ">"
        assert cond.right.value == "1000"

    def test_logical_and(self):
        """AND combination becomes LogicalCondition."""
        cond = LogicalCondition(
            left=Comparison(
                left=FieldReference(name="A"),
                operator=">",
                right=Literal(value="1", is_numeric=True),
            ),
            operator="AND",
            right=Comparison(
                left=FieldReference(name="B"),
                operator="<",
                right=Literal(value="10", is_numeric=True),
            ),
        )
        assert cond.operator == "AND"
        assert cond.left.operator == ">"
        assert cond.right.operator == "<"

    def test_logical_or(self):
        """OR combination becomes LogicalCondition."""
        cond = LogicalCondition(
            left=Comparison(
                left=FieldReference(name="X"),
                operator="=",
                right=Literal(value="Y"),
            ),
            operator="OR",
            right=Comparison(
                left=FieldReference(name="Z"),
                operator="=",
                right=Literal(value="N"),
            ),
        )
        assert cond.operator == "OR"

    def test_negated_condition(self):
        """NOT condition becomes NegatedCondition."""
        cond = NegatedCondition(
            condition=Comparison(
                left=FieldReference(name="A"),
                operator=">",
                right=FieldReference(name="B"),
            )
        )
        assert cond.condition.operator == ">"

    def test_boolean_condition(self):
        """Boolean field becomes BooleanCondition."""
        cond = BooleanCondition(field=FieldReference(name="flag"))
        assert cond.field.name == "flag"
        assert cond.is_negated is False


class TestParserExpressionBuilding:
    """Verify parser builds structured expressions from COBOL text."""

    def test_build_literal(self):
        """Parser builds Literal from numeric text."""
        parser = CobolParser()
        expr = parser._build_expression("42")
        assert isinstance(expr, Literal)
        assert expr.value == "42"
        assert expr.is_numeric is True

    def test_build_field_reference(self):
        """Parser builds FieldReference from field name."""
        parser = CobolParser()
        expr = parser._build_expression("CUSTOMER-ID")
        assert isinstance(expr, FieldReference)
        assert expr.name == "CUSTOMER-ID"

    def test_build_binary_add(self):
        """Parser builds BinaryExpression for addition."""
        parser = CobolParser()
        expr = parser._build_expression("A + B")
        assert isinstance(expr, BinaryExpression)
        assert expr.left.name == "A"
        assert expr.operator == "+"
        assert expr.right.name == "B"

    def test_build_unary_not(self):
        """Parser builds UnaryExpression for NOT."""
        parser = CobolParser()
        expr = parser._build_expression("NOT flag")
        assert isinstance(expr, UnaryExpression)
        assert expr.operator == "NOT"
        assert expr.operand.name == "flag"

    def test_build_arithmetic_respects_precedence_and_associativity(self):
        """COBOL arithmetic preserves precedence and left associativity."""
        parser = CobolParser()
        expr = parser._build_expression("WS-TOTAL * 10 / 100")
        assert isinstance(expr, BinaryExpression)
        assert expr.operator == "/"
        assert isinstance(expr.left, BinaryExpression)
        assert expr.left.operator == "*"
        assert expr.left.left.name == "WS-TOTAL"
        assert expr.left.right.value == "10"
        assert expr.right.value == "100"

    def test_build_comparison(self):
        """Parser builds Comparison from comparison text."""
        parser = CobolParser()
        cond = parser._build_condition("AMOUNT > 1000")
        assert isinstance(cond, Comparison)
        assert cond.left.name == "AMOUNT"
        assert cond.operator == ">"
        assert cond.right.value == "1000"

    def test_build_logical_and(self):
        """Parser builds LogicalCondition for AND."""
        parser = CobolParser()
        cond = parser._build_condition("A > 1 AND B < 10")
        assert isinstance(cond, LogicalCondition)
        assert cond.operator == "AND"
        assert cond.left.operator == ">"
        assert cond.right.operator == "<"

    def test_build_negated(self):
        """Parser builds NegatedCondition for NOT."""
        parser = CobolParser()
        cond = parser._build_condition("NOT (X = Y)")
        assert isinstance(cond, NegatedCondition)
        assert cond.condition.operator == "="


class TestParserStructuredIR:
    """Verify parser populates structured IR fields."""

    def test_move_has_structured_source(self):
        """MOVE statement gets structured source expression."""
        parser = CobolParser()
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           MOVE 100 TO LIMIT.
           STOP RUN."""
        program = parser.parse(cobol)
        stmt = program.paragraphs[0].statements[0]
        assert isinstance(stmt, MoveStatement)
        assert stmt.source == "100"
        assert stmt.source_expr is not None
        assert isinstance(stmt.source_expr, Literal)
        assert stmt.target_ref is not None
        assert stmt.target_ref.name == "LIMIT"

    def test_if_has_structured_condition(self):
        """IF statement gets structured condition."""
        parser = CobolParser()
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           IF AMOUNT > 1000
               DISPLAY "HIGH"
           END-IF.
           STOP RUN."""
        program = parser.parse(cobol)
        stmt = program.paragraphs[0].statements[0]
        assert isinstance(stmt, IfStatement)
        assert stmt.structured_condition is not None
        assert isinstance(stmt.structured_condition, Comparison)

    def test_perform_has_structured_condition(self):
        """PERFORM UNTIL gets structured condition."""
        parser = CobolParser()
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           PERFORM PROCESS-DATA UNTIL WS-EOF = 'Y'.
           STOP RUN."""
        program = parser.parse(cobol)
        stmt = program.paragraphs[0].statements[0]
        assert isinstance(stmt, PerformStatement)
        assert stmt.structured_condition is not None
        assert isinstance(stmt.structured_condition, Comparison)

# ============================================================
# D. Mutation Tests
# ============================================================

class TestMutationMatrix:
    """Verify mutations produce correct IR changes."""


    def test_literal_mutation_changes_ir(self):
        """Changing literal value changes structured IR."""
        parser = CobolParser()
        expr_a = parser._build_expression("100")
        expr_b = parser._build_expression("200")

        assert expr_a.value != expr_b.value

# ============================================================
# F. Determinism Tests
# ============================================================

class TestDeterminism:
    """Verify deterministic generation."""

    def test_same_source_same_ir(self):
        """Same COBOL source produces identical IR."""
        parser = CobolParser()
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           MOVE 100 TO LIMIT.
           DISPLAY "DONE".
           STOP RUN."""
        program1 = parser.parse(cobol)
        program2 = parser.parse(cobol)

        assert program1.paragraphs[0].statements[0].source == \
               program2.paragraphs[0].statements[0].source
        assert program1.paragraphs[0].statements[0].target == \
               program2.paragraphs[0].statements[0].target

    def test_same_source_same_java(self):
        """Same COBOL source produces identical Java."""
        parser = CobolParser()
        gen = JavaGenerator()
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           MOVE 100 TO LIMIT.
           DISPLAY "DONE".
           STOP RUN."""

        hashes = []
        for _ in range(3):
            program = parser.parse(cobol)
            files = gen.generate(program)
            h = hashlib.md5(files[0].source_code.encode()).hexdigest()
            hashes.append(h)

        assert len(set(hashes)) == 1

    def test_workload_determinism(self):
        """Workload produces deterministic output."""
        from pathlib import Path
        parser = CobolParser()
        gen = JavaGenerator()
        cobol = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()

        hashes = []
        for _ in range(3):
            program = parser.parse(cobol)
            files = gen.generate(program)
            h = hashlib.md5(files[0].source_code.encode()).hexdigest()
            hashes.append(h)

        assert len(set(hashes)) == 1


# ============================================================
# G. DataItem Hierarchy Tests
# ============================================================

class TestDataItemHierarchy:
    """Verify DataItem hierarchy support."""

    def test_dataitem_level(self):
        """DataItem supports level numbers."""
        item = DataItem(name="CUSTOMER-ID", level=5, pic_type=PicType.ALPHANUMERIC, pic_length=10)
        assert item.level == 5
        assert item.is_elementary is True
        assert item.is_group is False

    def test_dataitem_group(self):
        """DataItem with children is a group."""
        child1 = DataItem(name="ID", level=10, pic_type=PicType.ALPHANUMERIC, pic_length=5)
        child2 = DataItem(name="NAME", level=10, pic_type=PicType.ALPHANUMERIC, pic_length=20)
        group = DataItem(name="RECORD", level=1, children=(child1, child2))
        assert group.is_group is True
        assert group.is_elementary is False
        assert len(group.children) == 2

    def test_dataitem_88_level(self):
        """88-level is a condition name."""
        item = DataItem(name="HIGH-FLAG", level=88, value="Y")
        assert item.is_condition_name is True

    def test_dataitem_occurs(self):
        """DataItem with OCCURS is a table."""
        item = DataItem(name="TABLE-ARRAY", level=5, pic_type=PicType.NUMERIC, pic_length=5, occurs=10)
        assert item.is_table is True

    def test_dataitem_redefines(self):
        """DataItem supports REDEFINES."""
        item = DataItem(name="ALT-RECORD", level=1, redefines="MAIN-RECORD")
        assert item.redefines == "MAIN-RECORD"


# ============================================================
# H. Forensic Search Tests
# ============================================================

class TestForensicSearch:
    """Verify no domain coupling in architecture."""

    def test_no_decisionlogic_class(self):
        """DecisionLogic class must not exist."""
        with pytest.raises(ImportError):
            from engine.transformation.ir import DecisionLogic

    def test_no_settlementlogic_class(self):
        """SettlementLogic class must not exist."""
        with pytest.raises(ImportError):
            from engine.transformation.ir import SettlementLogic

    def test_no_paymentlookup_class(self):
        """PaymentLookup class must not exist."""
        with pytest.raises(ImportError):
            from engine.transformation.ir import PaymentLookup

    def test_no_settlement_logic_field(self):
        """CobolProgram must not have settlement_logic field."""
        program = CobolProgram(program_id="TEST")
        assert not hasattr(program, 'settlement_logic')

    def test_parser_no_decisionlogic(self):
        """Parser must not construct DecisionLogic."""
        parser = CobolParser()
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           MOVE 100 TO LIMIT.
           STOP RUN."""
        program = parser.parse(cobol)
        assert not hasattr(program, 'settlement_logic')

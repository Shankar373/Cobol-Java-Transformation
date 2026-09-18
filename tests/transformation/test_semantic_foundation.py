"""Tests for Task 6: COBOL Semantic Foundation.

Verifies:
- IR construction tests (structured expressions and conditions)
- Domain-neutral tests
- Lexical false-positive tests
- Mutation tests
- Negative tests
- Determinism tests
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
    derive_capabilities,
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
# B. Domain-Neutral Tests
# ============================================================

class TestDomainNeutralEquivalence:
    """Verify equivalent COBOL semantics produce equivalent IR."""

    def test_account_vs_order_equivalence(self):
        """ACCOUNT-PROCESSOR and ORDER-PROCESSOR with same structure produce same capabilities."""
        def make_account():
            return CobolProgram(
                program_id="ACCOUNT-PROCESSOR",
                file_definitions=(
                    FileDefinition(name="ACCOUNT-FILE", container_path="/app/input/accounts.dat", record_name="ACCOUNT-REC"),
                ),
                paragraphs=(
                    Paragraph(name="MAIN", statements=(
                        ReadStatement(
                            file_name="ACCOUNT-FILE", record_name="ACCOUNT-REC",
                            at_end_body=(),
                            not_at_end_body=(
                                IfStatement(
                                    condition="BALANCE > LIMIT",
                                    then_body=(MoveStatement(source="HIGH", target="CATEGORY"),),
                                    else_body=(MoveStatement(source="NORMAL", target="CATEGORY"),),
                                ),
                                DisplayStatement(parts=("CATEGORY",), destination="STDOUT"),
                            ),
                        ),
                    )),
                ),
            )

        def make_order():
            return CobolProgram(
                program_id="ORDER-PROCESSOR",
                file_definitions=(
                    FileDefinition(name="ORDER-FILE", container_path="/app/input/orders.dat", record_name="ORDER-REC"),
                ),
                paragraphs=(
                    Paragraph(name="MAIN", statements=(
                        ReadStatement(
                            file_name="ORDER-FILE", record_name="ORDER-REC",
                            at_end_body=(),
                            not_at_end_body=(
                                IfStatement(
                                    condition="AMOUNT > LIMIT",
                                    then_body=(MoveStatement(source="LARGE", target="SIZE"),),
                                    else_body=(MoveStatement(source="SMALL", target="SIZE"),),
                                ),
                                DisplayStatement(parts=("SIZE",), destination="STDOUT"),
                            ),
                        ),
                    )),
                ),
            )

        account = make_account()
        order = make_order()

        caps_a = derive_capabilities(account)
        caps_b = derive_capabilities(order)

        assert caps_a == caps_b
        assert caps_a.decision is True
        assert caps_a.file_input is True
        assert caps_a.display is True
        assert caps_a.assignment is True

    def test_customer_processor_equivalence(self):
        """CUSTOMER-PROCESSOR with same structure as ACCOUNT produces same capabilities."""
        customer = CobolProgram(
            program_id="CUSTOMER-PROCESSOR",
            file_definitions=(
                FileDefinition(name="CUSTOMER-FILE", container_path="/app/input/customers.dat", record_name="CUSTOMER-REC"),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    ReadStatement(
                        file_name="CUSTOMER-FILE", record_name="CUSTOMER-REC",
                        at_end_body=(),
                        not_at_end_body=(
                            IfStatement(
                                condition="BALANCE > LIMIT",
                                then_body=(MoveStatement(source="HIGH", target="CATEGORY"),),
                                else_body=(MoveStatement(source="NORMAL", target="CATEGORY"),),
                            ),
                            DisplayStatement(parts=("CATEGORY",), destination="STDOUT"),
                        ),
                    ),
                )),
            ),
        )

        account = CobolProgram(
            program_id="ACCOUNT-PROCESSOR",
            file_definitions=(
                FileDefinition(name="ACCOUNT-FILE", container_path="/app/input/accounts.dat", record_name="ACCOUNT-REC"),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    ReadStatement(
                        file_name="ACCOUNT-FILE", record_name="ACCOUNT-REC",
                        at_end_body=(),
                        not_at_end_body=(
                            IfStatement(
                                condition="BALANCE > LIMIT",
                                then_body=(MoveStatement(source="HIGH", target="CATEGORY"),),
                                else_body=(MoveStatement(source="NORMAL", target="CATEGORY"),),
                            ),
                            DisplayStatement(parts=("CATEGORY",), destination="STDOUT"),
                        ),
                    ),
                )),
            ),
        )

        caps_c = derive_capabilities(customer)
        caps_a = derive_capabilities(account)

        assert caps_c == caps_a


# ============================================================
# C. Lexical False-Positive Tests
# ============================================================

class TestLexicalFalsePositives:
    """Verify domain names in identifiers do NOT activate semantics."""

    def test_claim_name_no_decision(self):
        """CLAIM in program name does not activate decision capability."""
        program = CobolProgram(
            program_id="CLAIM-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=("Hello",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False
        assert caps.lookup is False
        assert caps.record_output is False
        assert caps.summary_output is False

    def test_settlement_name_no_semantics(self):
        """SETTLEMENT in program name does not activate any capability."""
        program = CobolProgram(
            program_id="SETTLEMENT-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="A", target="B"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False
        assert caps.lookup is False

    def test_payment_name_no_lookup(self):
        """PAYMENT in program name does not activate lookup capability."""
        program = CobolProgram(
            program_id="PAYMENT-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=("X",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.lookup is False

    def test_account_name_no_special_mode(self):
        """ACCOUNT in program name does not activate special mode."""
        program = CobolProgram(
            program_id="ACCOUNT-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=("X",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False

    def test_order_name_no_special_mode(self):
        """ORDER in program name does not activate special mode."""
        program = CobolProgram(
            program_id="ORDER-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=("X",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False


# ============================================================
# D. Mutation Tests
# ============================================================

class TestMutationMatrix:
    """Verify mutations produce correct IR changes."""

    def test_threshold_value_mutation(self):
        """Changing threshold value changes IR but not capability."""
        program_a = CobolProgram(
            program_id="TEST",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="AMOUNT < 500",
                        then_body=(MoveStatement(source="LOW", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_b = CobolProgram(
            program_id="TEST",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="AMOUNT < 5000",
                        then_body=(MoveStatement(source="LOW", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )

        caps_a = derive_capabilities(program_a)
        caps_b = derive_capabilities(program_b)

        assert caps_a.decision == caps_b.decision
        assert program_a.paragraphs[0].statements[0].condition != \
               program_b.paragraphs[0].statements[0].condition

    def test_field_name_mutation(self):
        """Changing field name changes IR but not capability."""
        program_a = CobolProgram(
            program_id="TEST",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="A > 100",
                        then_body=(MoveStatement(source="HIGH", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_b = CobolProgram(
            program_id="TEST",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="B > 100",
                        then_body=(MoveStatement(source="HIGH", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )

        caps_a = derive_capabilities(program_a)
        caps_b = derive_capabilities(program_b)

        assert caps_a.decision == caps_b.decision
        assert program_a.paragraphs[0].statements[0].condition != \
               program_b.paragraphs[0].statements[0].condition

    def test_operator_mutation(self):
        """Changing operator changes IR but not capability."""
        program_a = CobolProgram(
            program_id="TEST",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="A > 100",
                        then_body=(MoveStatement(source="HIGH", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_b = CobolProgram(
            program_id="TEST",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="A >= 100",
                        then_body=(MoveStatement(source="HIGH", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )

        caps_a = derive_capabilities(program_a)
        caps_b = derive_capabilities(program_b)

        assert caps_a.decision == caps_b.decision

    def test_if_removal_removes_decision(self):
        """Removing IF statement removes decision capability."""
        program_with = CobolProgram(
            program_id="TEST",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="A = B",
                        then_body=(MoveStatement(source="X", target="Y"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_without = CobolProgram(
            program_id="TEST",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=("X",), destination="STDOUT"),
                )),
            ),
        )

        caps_with = derive_capabilities(program_with)
        caps_without = derive_capabilities(program_without)

        assert caps_with.decision is True
        assert caps_without.decision is False

    def test_literal_mutation_changes_ir(self):
        """Changing literal value changes structured IR."""
        parser = CobolParser()
        expr_a = parser._build_expression("100")
        expr_b = parser._build_expression("200")

        assert expr_a.value != expr_b.value


# ============================================================
# E. Negative Tests
# ============================================================

class TestNegative:
    """Verify edge cases and limitations."""

    def test_empty_program_has_no_capabilities(self):
        """Empty program has no capabilities."""
        program = CobolProgram(program_id="EMPTY")
        caps = derive_capabilities(program)
        assert caps.decision is False
        assert caps.lookup is False
        assert caps.assignment is False

    def test_display_only_no_decision(self):
        """DISPLAY-only program has no decision capability."""
        program = CobolProgram(
            program_id="DISPLAY-ONLY",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=("Hello",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False

    def test_move_only_no_decision(self):
        """MOVE-only program has no decision capability."""
        program = CobolProgram(
            program_id="MOVE-ONLY",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="A", target="B"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False
        assert caps.assignment is True


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

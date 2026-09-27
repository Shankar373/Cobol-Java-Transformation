"""Regression tests for the canonical semantic foundation."""

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import BinaryExpression, CobolType, DecisionNode, FieldReference, IfStatement, InputRecordMapping, PicType


def test_data_item_has_canonical_type_and_provenance():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TYPES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC 9(5)V99.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="types.cob")
    item = next(i for i in program.working_storage if i.name == "WS-AMOUNT")
    assert item.semantic_type == CobolType(PicType.NUMERIC, 7, 2, False, "DISPLAY")
    assert item.provenance.source_name == "types.cob"
    assert item.provenance.line == 5


def test_nested_if_exposes_structural_decision_tree_and_default_branch():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DECISION.
       PROCEDURE DIVISION.
       MAIN.
           IF STATUS = 'R'
               MOVE 'REJECTED' TO RESULT
           ELSE
               IF STATUS = 'P'
                   MOVE 'PENDING' TO RESULT
               ELSE
                   IF AMOUNT < 500
                       MOVE 'REJECTED' TO RESULT
                   ELSE
                       MOVE 'APPROVED' TO RESULT
                   END-IF
               END-IF
           END-IF
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="decision.cob")
    outer = next(s for s in program.paragraphs[0].statements if isinstance(s, IfStatement))
    tree = outer.decision_tree
    assert isinstance(tree, DecisionNode)
    assert tree.explicit_else
    nested = next(s for s in tree.else_body if isinstance(s, IfStatement))
    nested2 = next(s for s in nested.else_body if isinstance(s, IfStatement))
    default_move = nested2.else_body[0]
    assert default_move.source == "'APPROVED'"
    assert default_move.target == "RESULT"
    assert outer.provenance.line == 5


def test_expression_reference_is_bound_to_source_type_and_provenance():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXPR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC 9(5).
       PROCEDURE DIVISION.
       MAIN.
           COMPUTE WS-AMOUNT = WS-AMOUNT * 2 / 4
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="expr.cob")
    stmt = program.paragraphs[0].statements[0]
    expr = stmt.expression_expr
    assert isinstance(expr, BinaryExpression)
    assert expr.operator == "/"
    assert isinstance(expr.left, BinaryExpression)
    assert expr.left.operator == "*"
    ref = expr.left.left
    assert isinstance(ref, FieldReference)
    assert ref.semantic_type is not None
    assert ref.semantic_type.pic_type == PicType.NUMERIC
    assert ref.provenance is not None
    assert ref.provenance.field_name == "WS-AMOUNT"


def test_input_mapping_exposes_field_provenance_shape():
    mapping = InputRecordMapping("CLAIM-REC", "CLAIMS-FILE", "|", ("ID", "STATUS", "AMOUNT"))
    assert mapping.field_provenance == ()

"""Regression tests for the canonical semantic foundation."""

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.ir import BinaryExpression, CobolType, DecisionNode, EvaluateStatement, FieldReference, IfStatement, InputRecordMapping, PicType


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


def test_signed_pic_preserves_canonical_signed_type():
    source = """\\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIGNEDTYPE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-BALANCE PIC S9(5)V99.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="signed-type.cob")
    item = next(i for i in program.working_storage if i.name == "WS-BALANCE")

    assert item.semantic_type == CobolType(PicType.NUMERIC, 7, 2, True, "DISPLAY")
    assert item.semantic_type.signed is True
    assert item.provenance.source_name == "signed-type.cob"


def test_file_record_preserves_canonical_pic_metadata():
    source = """\\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILETYPE.
       DATA DIVISION.
       FILE SECTION.
       FD INPUT-FILE.
       01 INPUT-REC PIC S9(5)V99.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC S9(5)V99.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="filetype.cob")
    item = program.file_definitions[0].record_items[0]

    assert item.semantic_type == CobolType(PicType.NUMERIC, 7, 2, True, "DISPLAY")
    assert item.provenance.source_name == "filetype.cob"
    assert item.level == 1


def test_comp3_usage_preserves_canonical_storage_metadata_across_data_paths():
    source = """\\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. USAGETYPE.
       DATA DIVISION.
       FILE SECTION.
       FD INPUT-FILE.
       01 INPUT-REC PIC S9(5)V99 COMP-3.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC S9(5)V99 USAGE COMP-3.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="usage.cob")

    file_item = program.file_definitions[0].record_items[0]
    working_item = next(
        item for item in program.working_storage if item.name == "WS-AMOUNT"
    )

    assert file_item.semantic_type == CobolType(PicType.NUMERIC, 7, 2, True, "COMP-3")
    assert working_item.semantic_type == CobolType(PicType.NUMERIC, 7, 2, True, "COMP-3")
    assert file_item.provenance.source_name == "usage.cob"
    assert working_item.provenance.source_name == "usage.cob"


def test_file_record_child_preserves_level_and_canonical_pic_metadata():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILEGROUP.
       DATA DIVISION.
       FILE SECTION.
       FD INPUT-FILE.
       01 INPUT-REC.
           05 INPUT-AMOUNT PIC S9(5)V99.
       WORKING-STORAGE SECTION.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="filegroup.cob")
    record = program.file_definitions[0].record_items[0]
    item = record.children[0]

    assert record.name == "INPUT-REC"
    assert record.level == 1
    assert item.name == "INPUT-AMOUNT"
    assert item.level == 5
    assert item.semantic_type == CobolType(PicType.NUMERIC, 7, 2, True, "DISPLAY")
    assert item.provenance.source_name == "filegroup.cob"
    assert item.provenance.line == 7



def test_file_control_metadata_merges_with_record_schema():
    source = """\\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILEMERGE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INPUT-FILE ASSIGN TO "input.dat".
       DATA DIVISION.
       FILE SECTION.
       FD INPUT-FILE.
       01 INPUT-REC PIC S9(5)V99.
       WORKING-STORAGE SECTION.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="filemerge.cob")
    file_def = program.file_definitions[0]
    item = file_def.record_items[0]

    assert file_def.name == "INPUT-FILE"
    assert file_def.container_path == "input.dat"
    assert item.name == "INPUT-REC"
    assert item.semantic_type == CobolType(PicType.NUMERIC, 7, 2, True, "DISPLAY")
    assert item.provenance.source_name == "filemerge.cob"



def test_evaluate_preserves_structured_when_and_other_branches():
    source = """\\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALUATESEM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 STATUS PIC 9(2).
       01 RESULT PIC X(10).
       PROCEDURE DIVISION.
       MAIN.
           EVALUATE STATUS
               WHEN 1
                   MOVE 'ONE' TO RESULT
               WHEN 2 THRU 3
                   MOVE 'TWO-THREE' TO RESULT
               WHEN OTHER
                   MOVE 'OTHER' TO RESULT
           END-EVALUATE
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="evaluate.cob")
    evaluate = next(
        statement
        for statement in program.paragraphs[0].statements
        if isinstance(statement, EvaluateStatement)
    )

    assert evaluate.provenance.source_name == "evaluate.cob"
    assert len(evaluate.arms) == 3
    assert evaluate.arms[0].conditions[0].right.value == "1"
    assert evaluate.arms[1].conditions[0].operator == "AND"
    assert evaluate.arms[2].other is True

    java_program = map_cobol_program_to_java(program)
    java_ifs = [
        statement
        for method in java_program.java_class.methods
        for statement in method.body_statements
        if statement.__class__.__name__ == "JavaIf"
    ]
    assert len(java_ifs) == 1
    assert java_ifs[0].else_body


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



def test_nested_read_decision_preserves_default_outcome_for_mapping():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEDDECISION.
       DATA DIVISION.
       FILE SECTION.
       FD INPUT-FILE.
       01 INPUT-REC PIC X(20).
       WORKING-STORAGE SECTION.
       01 STATUS PIC X(1).
       01 AMOUNT PIC 9(5).
       01 RESULT PIC X(10).
       PROCEDURE DIVISION.
       MAIN.
           READ INPUT-FILE
               NOT AT END
                   IF STATUS = 'R'
                       MOVE 'REJECTED' TO RESULT
                   ELSE
                       IF AMOUNT < 500
                           MOVE 'REJECTED' TO RESULT
                       ELSE
                           MOVE 'APPROVED' TO RESULT
                       END-IF
                   END-IF
           END-READ
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="nested-decision.cob")
    java_program = map_cobol_program_to_java(program)
    assert java_program.default_status_label == "APPROVED"


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


def test_mapping_uses_structured_numeric_else_branch_for_default():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GENERIC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 STATUS PIC X(1).
       01 AMOUNT PIC 9(5).
       01 RESULT PIC X(10).
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
    program = CobolParser().parse(source, source_name="generic.cob")
    java_program = map_cobol_program_to_java(program)
    assert java_program.default_status_label == "APPROVED"


def test_structured_condition_mapping_preserves_logical_tree():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONDITION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9(3).
       01 B PIC 9(3).
       01 C PIC 9(3).
       01 RESULT PIC X(1).
       PROCEDURE DIVISION.
       MAIN.
           IF A > 1 AND B < 10 OR NOT C = 0
               MOVE 'Y' TO RESULT
           ELSE
               MOVE 'N' TO RESULT
           END-IF
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="condition.cob")
    java_program = map_cobol_program_to_java(program)
    java_class = java_program.java_class
    statement = next(
        statement
        for method in java_class.methods
        for statement in method.body_statements
        if getattr(statement, "condition", None) is not None
    )
    condition = statement.condition
    assert condition.operator == "||"
    assert condition.left.operator == "&&"
    assert condition.right.operator == "!"


def test_mapping_prefers_structured_expression_over_raw_expression_text():
    source = """\\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXPRESSION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9(3).
       01 B PIC 9(3).
       01 RESULT PIC 9(3).
       PROCEDURE DIVISION.
       MAIN.
           MOVE (A + B) TO RESULT
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="expression.cob")
    java_program = map_cobol_program_to_java(program)
    assignment = next(
        statement
        for method in java_program.java_class.methods
        for statement in method.body_statements
        if getattr(statement, "target", "") == "RESULT"
    )
    assert assignment.expression.__class__.__name__ == "JavaBinaryOp"
    assert assignment.expression.operator == "+"
    assert assignment.expression.left.name == "A"
    assert assignment.expression.right.name == "B"


def test_input_field_provenance_survives_ir_to_java_mapping():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INPUTPROV.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INFILE ASSIGN TO "input.dat".
       DATA DIVISION.
       FILE SECTION.
       FD INFILE.
       01 IN-REC PIC X(20).
       WORKING-STORAGE SECTION.
       01 WS-ID PIC X(5).
       PROCEDURE DIVISION.
       MAIN.
           UNSTRING IN-REC DELIMITED BY "|" INTO WS-ID
           MOVE WS-ID TO WS-ID
           STOP RUN.
"""
    program = CobolParser().parse(source, source_name="inputprov.cob")
    mapping = program.input_record_mappings[0]
    assert mapping.field_provenance[0].file_name == "INFILE"
    assert mapping.field_provenance[0].record_name == "IN-REC"
    assert mapping.field_provenance[0].field_name == "WS-ID"
    assert mapping.field_provenance[0].input_position == 0

    move = next(
        statement
        for statement in program.paragraphs[0].statements
        if getattr(statement, "target", "") == "WS-ID"
    )
    assert move.source_expr.provenance.file_name == "INFILE"
    assert move.source_expr.provenance.record_name == "IN-REC"
    assert move.source_expr.provenance.input_position == 0

    java_program = map_cobol_program_to_java(program)
    java_field = next(field for field in java_program.java_class.fields if field.name == "WS_ID")
    assert java_field.source_provenance is not None
    assert java_field.source_provenance.file_name == "INFILE"
    assert java_field.source_provenance.record_name == "IN-REC"
    assert java_field.source_provenance.input_position == 0

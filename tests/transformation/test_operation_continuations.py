"""Physical line wrapping cannot discard MOVE, ADD or IF operands."""
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import MoveStatement, AddStatement, IfStatement


def test_wrapped_operations_keep_all_operands():
    program = CobolParser().parse('''       IDENTIFICATION DIVISION.
       PROGRAM-ID. WRAPPED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 AMOUNT PIC 9(4) VALUE 0.
       01 LABEL-FIELD PIC X(8).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 'APPROVED'
               TO LABEL-FIELD.
           ADD 12
               TO AMOUNT.
           IF AMOUNT
               = 12
               DISPLAY LABEL-FIELD
           END-IF.
           STOP RUN.
''')
    move, add, condition = program.paragraphs[0].statements[:3]
    assert isinstance(move, MoveStatement)
    assert (move.source, move.target) == ("'APPROVED'", "LABEL-FIELD")
    assert isinstance(add, AddStatement)
    assert (add.source, add.target) == ("12", "AMOUNT")
    assert isinstance(condition, IfStatement)
    assert condition.condition == "AMOUNT = 12"
    assert len(condition.then_body) == 1

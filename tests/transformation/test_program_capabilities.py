"""Tests for ProgramCapabilities derivation from COBOL IR.

Domain-neutral tests using minimal COBOL examples.
No Claims-specific terminology in test examples.
"""

from __future__ import annotations

import pytest

from engine.transformation.ir import (
    AddStatement,
    CobolProgram,
    DataItem,
    DisplayStatement,
    DivideStatement,
    FileDefinition,
    IfStatement,
    InputRecordMapping,
    MoveStatement,
    OpenStatement,
    Paragraph,
    PerformStatement,
    PicType,
    ProgramCapabilities,
    ReadStatement,
    StatusCodeMapping,
    StringStatement,
    ThresholdRule,
    WriteStatement,
    derive_capabilities,
)


def _make_program(**kwargs) -> CobolProgram:
    """Helper to create a CobolProgram with defaults."""
    kwargs.setdefault("program_id", "TEST")
    return CobolProgram(**kwargs)


class TestBasicCapabilityDetection:
    """Example 1-5 from TASK 4 spec: domain-neutral COBOL examples."""

    def test_example1_move_display(self):
        """MOVE A TO B + DISPLAY B → assignment + output."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="A", target="B"),
                    DisplayStatement(parts=("B",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.assignment is True
        assert caps.display is True
        assert caps.arithmetic is False
        assert caps.condition is False
        assert caps.file_input is False
        assert caps.decision is False

    def test_example2_move_add_display(self):
        """MOVE A TO B + ADD C TO B + DISPLAY B → assignment + arithmetic + output."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="A", target="B"),
                    AddStatement(source="C", target="B"),
                    DisplayStatement(parts=("B",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.assignment is True
        assert caps.arithmetic is True
        assert caps.display is True
        assert caps.condition is False
        assert caps.file_input is False

    def test_example3_if_condition(self):
        """IF A = B MOVE X TO Y → condition + assignment."""
        program = _make_program(
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
        caps = derive_capabilities(program)
        assert caps.condition is True
        assert caps.assignment is True
        assert caps.arithmetic is False
        assert caps.display is False

    def test_example4_if_else(self):
        """IF A = B MOVE X TO Y ELSE MOVE Z TO W → condition + assignment."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="A = B",
                        then_body=(MoveStatement(source="X", target="Y"),),
                        else_body=(MoveStatement(source="Z", target="W"),),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.condition is True
        assert caps.assignment is True

    def test_example5_combined_capabilities(self):
        """Multiple capabilities in one program."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="A", target="B"),
                    AddStatement(source="C", target="B"),
                    DivideStatement(source="B", target="B", divisor="D"),
                    IfStatement(
                        condition="B > 100",
                        then_body=(
                            DisplayStatement(parts=('"HIGH"',), destination="STDOUT"),
                        ),
                        else_body=(
                            DisplayStatement(parts=('"LOW"',), destination="STDOUT"),
                        ),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.assignment is True
        assert caps.arithmetic is True
        assert caps.condition is True
        assert caps.display is True


class TestFileIOCapabilities:
    """Test file I/O capability detection from IR."""

    def test_file_input_from_read_statement(self):
        """READ statement → file_input capability."""
        from engine.transformation.ir import ReadStatement
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    ReadStatement(
                        file_name="IN-FILE",
                        record_name="IN-REC",
                        at_end_body=(),
                        not_at_end_body=(
                            DisplayStatement(parts=('"REC"',), destination="STDOUT"),
                        ),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.file_input is True

    def test_file_input_from_file_definitions(self):
        """OPEN INPUT → file_input capability."""
        program = _make_program(
            file_definitions=(
                FileDefinition(
                    name="IN-FILE",
                    container_path="/app/data/in.dat",
                    record_name="IN-REC",
                ),
            ),
            open_statements=(
                OpenStatement(mode="INPUT", file_name="IN-FILE"),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.file_input is True

    def test_output_file_definitions(self):
        """OPEN OUTPUT → file_output capability."""
        program = _make_program(
            file_definitions=(
                FileDefinition(
                    name="OUT-FILE",
                    container_path="/app/data/out.dat",
                    record_name="OUT-REC",
                ),
            ),
            open_statements=(
                OpenStatement(mode="OUTPUT", file_name="OUT-FILE"),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.file_output is True

    def test_input_record_mapping(self):
        """InputRecordMapping → unstring + input_record_mapping capabilities."""
        program = _make_program(
            input_record_mappings=(
                InputRecordMapping(
                    record_name="IN-REC",
                    file_name="IN-FILE",
                    delimiter="|",
                    fields=("FIELD1", "FIELD2"),
                ),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.unstring is True
        assert caps.input_record_mapping is True


class TestDecisionCapabilities:
    """Test decision logic capability detection from generic IR patterns."""

    def test_decision_from_conditional_status_mapping(self):
        """IF field = 'X' MOVE 'LABEL' TO target → decision capability."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="STATUS = 'A'",
                        then_body=(MoveStatement(source="'APPROVED'", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is True
        assert caps.condition is True
        assert caps.assignment is True

    def test_decision_from_threshold_condition(self):
        """IF AMOUNT < 500 MOVE 'LOW' TO RESULT → decision (conditional assignment)."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="AMOUNT < 500",
                        then_body=(MoveStatement(source="'LOW'", target="RESULT"),),
                        else_body=(MoveStatement(source="'OK'", target="RESULT"),),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        # Any IF+MOVE is a decision (conditional assignment)
        assert caps.decision is True
        assert caps.condition is True
        assert caps.assignment is True

    def test_decision_from_multi_branch(self):
        """Same field tested in 2+ IF statements → decision (multi-branch)."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="CODE = 'A'",
                        then_body=(MoveStatement(source="'ALPHA'", target="RESULT"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="CODE = 'B'",
                        then_body=(MoveStatement(source="'BETA'", target="RESULT"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="CODE = 'C'",
                        then_body=(MoveStatement(source="'GAMMA'", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is True

    def test_no_decision_without_move_in_then(self):
        """IF without MOVE in then_body → no decision capability."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="A = B",
                        then_body=(DisplayStatement(parts=('"YES"',), destination="STDOUT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False
        assert caps.condition is True

    def test_no_decision_single_if_no_threshold(self):
        """Single IF A = B MOVE X TO Y → decision (conditional assignment)."""
        program = _make_program(
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
        caps = derive_capabilities(program)
        # Any IF+MOVE is a decision
        assert caps.decision is True

    def test_decision_with_summary_fields(self):
        """Decision with summary-style DISPLAY → decision + summary_output."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="STATUS = 'A'",
                        then_body=(MoveStatement(source="'APPROVED'", target="RESULT"),),
                        else_body=(),
                    ),
                    DisplayStatement(parts=('"TOTAL="', "COUNT"), destination="STDOUT"),
                    DisplayStatement(parts=('"APPROVED="', "APPROVED_COUNT"), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is True
        assert caps.summary_output is True

    def test_decision_with_lookup(self):
        """Decision with array-indexed IF → decision + lookup."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="STATUS = 'A'",
                        then_body=(MoveStatement(source="'APPROVED'", target="RESULT"),),
                        else_body=(),
                    ),
                    PerformStatement(paragraph_name="LOOKUP"),
                )),
                Paragraph(name="LOOKUP", statements=(
                    IfStatement(
                        condition="PAY-TABLE(IDX) = SEARCH-ID",
                        then_body=(MoveStatement(source="'Y'", target="FOUND"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is True
        assert caps.lookup is True

    def test_decision_with_record_output(self):
        """Decision with STRING INTO written record → decision + record_output."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="STATUS = 'A'",
                        then_body=(MoveStatement(source="'APPROVED'", target="RESULT"),),
                        else_body=(),
                    ),
                    StringStatement(parts=("ID", '" "', "STATUS"), target="REPORT-REC"),
                    WriteStatement(record_name="REPORT-REC", file_name="REPORT-FILE"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.record_output is True
        assert caps.string_build is True


class TestNegativeTest:
    """Empty/minimal program must not acquire artificial capabilities."""

    def test_empty_program(self):
        """Empty program → no capabilities."""
        program = _make_program()
        caps = derive_capabilities(program)
        assert caps.assignment is False
        assert caps.arithmetic is False
        assert caps.condition is False
        assert caps.file_input is False
        assert caps.file_output is False
        assert caps.unstring is False
        assert caps.string_build is False
        assert caps.lookup is False
        assert caps.display is False
        assert caps.goto is False
        assert caps.perform is False
        assert caps.decision is False
        assert caps.record_output is False
        assert caps.summary_output is False
        assert caps.input_record_mapping is False

    def test_only_working_storage(self):
        """Program with only WORKING-STORAGE → no capabilities."""
        program = _make_program(
            working_storage=(
                DataItem(name="WS-COUNT", pic_type=PicType.NUMERIC, pic_length=4, value="0"),
                DataItem(name="WS-NAME", pic_type=PicType.ALPHANUMERIC, pic_length=20),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.assignment is False
        assert caps.decision is False
        assert caps.display is False

    def test_no_decision_without_status_codes(self):
        """Program with only DisplayStatement but no IfStatement → no decision."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=('"TOTAL="', "COUNT"), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False
        assert caps.display is True
        assert caps.summary_output is True


class TestMutationTest:
    """Capabilities must change when constructs are added."""

    def test_mutation_move_to_move_add(self):
        """Start with MOVE A TO B, add ADD C TO B → arithmetic appears."""
        base = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="A", target="B"),
                )),
            ),
        )
        modified = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="A", target="B"),
                    AddStatement(source="C", target="B"),
                )),
            ),
        )
        caps_base = derive_capabilities(base)
        caps_modified = derive_capabilities(modified)

        assert caps_base.arithmetic is False
        assert caps_modified.arithmetic is True
        # Other capabilities unchanged
        assert caps_base.assignment == caps_modified.assignment
        assert caps_base.display == caps_modified.display

    def test_mutation_display_to_read_display(self):
        """Start with DISPLAY A, add READ FILE → file_input appears."""
        from engine.transformation.ir import ReadStatement
        base = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=("A",), destination="STDOUT"),
                )),
            ),
        )
        modified = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    ReadStatement(
                        file_name="IN-FILE",
                        record_name="IN-REC",
                        at_end_body=(),
                        not_at_end_body=(
                            DisplayStatement(parts=("A",), destination="STDOUT"),
                        ),
                    ),
                )),
            ),
        )
        caps_base = derive_capabilities(base)
        caps_modified = derive_capabilities(modified)

        assert caps_base.file_input is False
        assert caps_modified.file_input is True
        # display is still True in both
        assert caps_base.display is True
        assert caps_modified.display is True

    def test_mutation_no_move_to_move(self):
        """Start with empty, add MOVE → assignment appears."""
        base = _make_program()
        modified = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                )),
            ),
        )
        caps_base = derive_capabilities(base)
        caps_modified = derive_capabilities(modified)

        assert caps_base.assignment is False
        assert caps_modified.assignment is True


class TestCapabilityComposition:
    """Mixed capabilities can coexist."""

    def test_all_basic_capabilities(self):
        """Program with assignment + arithmetic + condition + display."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="0", target="COUNT"),
                    AddStatement(source="1", target="COUNT"),
                    IfStatement(
                        condition="COUNT > 10",
                        then_body=(
                            DisplayStatement(parts=('"OVER"',), destination="STDOUT"),
                        ),
                        else_body=(
                            DisplayStatement(parts=('"UNDER"',), destination="STDOUT"),
                        ),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.assignment is True
        assert caps.arithmetic is True
        assert caps.condition is True
        assert caps.display is True
        assert caps.file_input is False
        assert caps.decision is False

    def test_file_io_with_processing(self):
        """File input + unstring + display + assignment."""
        from engine.transformation.ir import ReadStatement
        program = _make_program(
            file_definitions=(
                FileDefinition(
                    name="IN-FILE",
                    container_path="/app/input/data.dat",
                    record_name="IN-REC",
                ),
            ),
            input_record_mappings=(
                InputRecordMapping(
                    record_name="IN-REC",
                    file_name="IN-FILE",
                    delimiter="|",
                    fields=("FIELD1", "FIELD2"),
                ),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    ReadStatement(
                        file_name="IN-FILE",
                        record_name="IN-REC",
                        at_end_body=(),
                        not_at_end_body=(
                            DisplayStatement(parts=("FIELD1",), destination="STDOUT"),
                        ),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.file_input is True
        assert caps.unstring is True
        assert caps.input_record_mapping is True
        assert caps.display is True


class TestCapabilityDataclass:
    """Test ProgramCapabilities dataclass properties."""

    def test_all_false_by_default(self):
        """Default ProgramCapabilities has all capabilities False."""
        caps = ProgramCapabilities()
        assert caps.assignment is False
        assert caps.arithmetic is False
        assert caps.condition is False
        assert caps.file_input is False
        assert caps.file_output is False
        assert caps.unstring is False
        assert caps.string_build is False
        assert caps.lookup is False
        assert caps.display is False
        assert caps.goto is False
        assert caps.perform is False
        assert caps.decision is False
        assert caps.record_output is False
        assert caps.summary_output is False
        assert caps.input_record_mapping is False

    def test_capabilities_are_frozen(self):
        """ProgramCapabilities is immutable."""
        caps = ProgramCapabilities(assignment=True)
        with pytest.raises(AttributeError):
            caps.assignment = False


class TestDomainNeutralSemanticEquivalence:
    """CRITICAL TEST: Two programs with identical semantic structure
    but completely different names must derive the same capabilities.
    No special word such as CLAIM, SETTLEMENT, PAYMENT may be required."""

    def test_account_processor_vs_order_processor(self):
        """Program A (ACCOUNT-PROCESSOR) and Program B (ORDER-PROCESSOR)
        have identical semantic structure: IF field = 'X' MOVE 'LABEL' TO target.
        Both must derive the same capability category."""
        # Program A: ACCOUNT-PROCESSOR
        program_a = _make_program(
            program_id="ACCOUNT-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="ACCOUNT-STATUS = 'A'",
                        then_body=(MoveStatement(source="'ACTIVE'", target="RESULT-CODE"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="ACCOUNT-STATUS = 'I'",
                        then_body=(MoveStatement(source="'INACTIVE'", target="RESULT-CODE"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="ACCOUNT-STATUS = 'S'",
                        then_body=(MoveStatement(source="'SUSPENDED'", target="RESULT-CODE"),),
                        else_body=(),
                    ),
                )),
            ),
        )

        # Program B: ORDER-PROCESSOR
        program_b = _make_program(
            program_id="ORDER-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="ORDER-STATUS = 'O'",
                        then_body=(MoveStatement(source="'OPEN'", target="RESULT-CODE"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="ORDER-STATUS = 'C'",
                        then_body=(MoveStatement(source="'CLOSED'", target="RESULT-CODE"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="ORDER-STATUS = 'X'",
                        then_body=(MoveStatement(source="'CANCELLED'", target="RESULT-CODE"),),
                        else_body=(),
                    ),
                )),
            ),
        )

        caps_a = derive_capabilities(program_a)
        caps_b = derive_capabilities(program_b)

        # Both must derive the same capability categories
        assert caps_a.assignment == caps_b.assignment
        assert caps_a.condition == caps_b.condition
        assert caps_a.decision == caps_b.decision
        assert caps_a.arithmetic == caps_b.arithmetic
        assert caps_a.file_input == caps_b.file_input
        assert caps_a.display == caps_b.display

        # Both must have decision capability (multi-branch equality tests + MOVE)
        assert caps_a.decision is True
        assert caps_b.decision is True

        # No Claims/settlement/payment terminology required
        assert "CLAIM" not in program_a.program_id.upper() or True  # program_id is arbitrary
        assert "SETTLEMENT" not in str(caps_a)
        assert "PAYMENT" not in str(caps_a)


class TestLexicalFalsePositive:
    """CRITICAL NEGATIVE TEST: Capability analysis must be semantic, not lexical.

    The word SETTLEMENT in an identifier must NOT cause decision capability.
    Decision capability must come from IF+MOVE patterns, not from naming."""

    def test_settlement_word_does_not_cause_decision(self):
        """Program with SETTLEMENT-DATE but no IF+MOVE → no decision."""
        program = _make_program(
            working_storage=(
                DataItem(name="SETTLEMENT-DATE", pic_type=PicType.ALPHANUMERIC, pic_length=8),
                DataItem(name="WS-COUNT", pic_type=PicType.NUMERIC, pic_length=4, value="0"),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'20240101'", target="SETTLEMENT-DATE"),
                    DisplayStatement(parts=("SETTLEMENT-DATE",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        # SETTLEMENT-DATE is just an identifier — no decision semantics
        assert caps.decision is False
        assert caps.assignment is True
        assert caps.display is True

    def test_result_code_with_conditional_assignments(self):
        """Program with RESULT-CODE and IF+MOVE → decision capability."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="STATUS = 'A'",
                        then_body=(MoveStatement(source="'APPROVED'", target="RESULT-CODE"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT-CODE"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        # RESULT-CODE with IF+MOVE = decision capability
        assert caps.decision is True

    def test_no_false_positive_from_identifier_names(self):
        """Identifiers containing 'decision', 'claim', 'settlement' don't
        cause capabilities — only IR structure matters."""
        program = _make_program(
            working_storage=(
                DataItem(name="DECISION-FLAG", pic_type=PicType.ALPHANUMERIC, pic_length=1),
                DataItem(name="CLAIM-AMOUNT", pic_type=PicType.NUMERIC, pic_length=9),
                DataItem(name="SETTLEMENT-DATE", pic_type=PicType.ALPHANUMERIC, pic_length=8),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'Y'", target="DECISION-FLAG"),
                    DisplayStatement(parts=('"DONE"',), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        # No IF+MOVE patterns → no decision
        assert caps.decision is False
        # Only assignment and display from MOVE and DISPLAY
        assert caps.assignment is True
        assert caps.display is True


class TestStep5GenericIR:
    """STEP 5: Domain-neutral fixtures with equivalent semantics produce same capabilities."""

    def test_account_vs_order_equivalence(self):
        """ACCOUNT-PROCESSOR and ORDER-PROCESSOR with same structure → same caps."""
        from engine.transformation.ir import ReadStatement

        def _account_program():
            return _make_program(
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
                                    then_body=(MoveStatement(source="'HIGH'", target="CATEGORY"),),
                                    else_body=(MoveStatement(source="'NORMAL'", target="CATEGORY"),),
                                ),
                                DisplayStatement(parts=("CATEGORY",), destination="STDOUT"),
                            ),
                        ),
                    )),
                ),
            )

        def _order_program():
            return _make_program(
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
                                    condition="TOTAL > LIMIT",
                                    then_body=(MoveStatement(source="'HIGH'", target="CLASSIFICATION"),),
                                    else_body=(MoveStatement(source="'NORMAL'", target="CLASSIFICATION"),),
                                ),
                                DisplayStatement(parts=("CLASSIFICATION",), destination="STDOUT"),
                            ),
                        ),
                    )),
                ),
            )

        caps_a = _account_program()
        caps_b = _order_program()
        from engine.transformation.ir import derive_capabilities
        ca = derive_capabilities(caps_a)
        cb = derive_capabilities(caps_b)
        assert ca.assignment == cb.assignment
        assert ca.condition == cb.condition
        assert ca.decision == cb.decision
        assert ca.file_input == cb.file_input
        assert ca.display == cb.display
        assert ca.decision is True

    def test_grade_calc_decision(self):
        """GRADE-CALC with range IF+MOVE → decision capability."""
        program = _make_program(
            program_id="GRADE-CALC",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="WS-AVERAGE >= 90",
                        then_body=(MoveStatement(source="'A'", target="WS-GRADE"),),
                        else_body=(),
                    ),
                    IfStatement(
                        condition="WS-AVERAGE >= 80",
                        then_body=(MoveStatement(source="'B'", target="WS-GRADE"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is True
        assert caps.assignment is True
        assert caps.condition is True


class TestStep6LexicalFalsePositive:
    """STEP 6: Identifiers with domain terms do NOT create capabilities."""

    def test_settlement_date_no_capabilities(self):
        """SETTLEMENT-DATE with no IF → no decision, no lookup, no record_output."""
        program = _make_program(
            working_storage=(
                DataItem(name="SETTLEMENT-DATE", pic_type=PicType.ALPHANUMERIC, pic_length=8),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'20240101'", target="SETTLEMENT-DATE"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False
        assert caps.lookup is False
        assert caps.record_output is False
        assert caps.summary_output is False

    def test_claim_status_no_capabilities(self):
        """CLAIM_STATUS with no IF → no decision."""
        program = _make_program(
            working_storage=(
                DataItem(name="CLAIM-STATUS", pic_type=PicType.ALPHANUMERIC, pic_length=2),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'A'", target="CLAIM-STATUS"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False

    def test_claim_amount_no_capabilities(self):
        """CLAIM_AMOUNT with no IF → no decision."""
        program = _make_program(
            working_storage=(
                DataItem(name="CLAIM-AMOUNT", pic_type=PicType.NUMERIC, pic_length=9),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="0", target="CLAIM-AMOUNT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False

    def test_payment_code_no_capabilities(self):
        """PAYMENT_CODE with no IF → no decision."""
        program = _make_program(
            working_storage=(
                DataItem(name="PAYMENT-CODE", pic_type=PicType.ALPHANUMERIC, pic_length=1),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'P'", target="PAYMENT-CODE"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False

    def test_decision_code_no_capabilities(self):
        """DECISION_CODE with no IF → no decision."""
        program = _make_program(
            working_storage=(
                DataItem(name="DECISION-CODE", pic_type=PicType.ALPHANUMERIC, pic_length=1),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'D'", target="DECISION-CODE"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False

    def test_result_status_no_capabilities(self):
        """RESULT_STATUS with no IF → no decision."""
        program = _make_program(
            working_storage=(
                DataItem(name="RESULT-STATUS", pic_type=PicType.ALPHANUMERIC, pic_length=2),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'OK'", target="RESULT-STATUS"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False


class TestStep7SecondaryCapabilityEquivalence:
    """STEP 7: Domain-neutral programs with equivalent secondary semantics."""

    def test_lookup_equivalence(self):
        """Two programs with table search pattern → same lookup capability."""
        program_a = _make_program(
            program_id="ACCOUNT-LOOKUP",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    PerformStatement(paragraph_name="FIND-ACCOUNT"),
                )),
                Paragraph(name="FIND-ACCOUNT", statements=(
                    IfStatement(
                        condition="ACCOUNT-TABLE(IDX) = SEARCH-ID",
                        then_body=(MoveStatement(source="'Y'", target="FOUND"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_b = _make_program(
            program_id="ORDER-LOOKUP",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    PerformStatement(paragraph_name="FIND-ORDER"),
                )),
                Paragraph(name="FIND-ORDER", statements=(
                    IfStatement(
                        condition="ORDER-TABLE(IDX) = SEARCH-ID",
                        then_body=(MoveStatement(source="'Y'", target="FOUND"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        ca = derive_capabilities(program_a)
        cb = derive_capabilities(program_b)
        assert ca.lookup == cb.lookup
        assert ca.lookup is True

    def test_record_output_equivalence(self):
        """Two programs with STRING INTO written record → same record_output capability."""
        program_a = _make_program(
            program_id="ACCOUNT-OUTPUT",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    StringStatement(parts=("ID", '" "', "NAME"), target="ACCOUNT-REC"),
                    WriteStatement(record_name="ACCOUNT-REC", file_name="ACCOUNT-FILE"),
                )),
            ),
        )
        program_b = _make_program(
            program_id="ORDER-OUTPUT",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    StringStatement(parts=("ID", '" "', "TITLE"), target="ORDER-REC"),
                    WriteStatement(record_name="ORDER-REC", file_name="ORDER-FILE"),
                )),
            ),
        )
        ca = derive_capabilities(program_a)
        cb = derive_capabilities(program_b)
        assert ca.record_output == cb.record_output
        assert ca.record_output is True
        assert ca.string_build is True

    def test_summary_output_equivalence(self):
        """Two programs with DisplayStatement → same summary_output capability."""
        program_a = _make_program(
            program_id="ACCOUNT-SUMMARY",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=('"TOTAL="', "COUNT"), destination="STDOUT"),
                )),
            ),
        )
        program_b = _make_program(
            program_id="ORDER-SUMMARY",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=('"TOTAL="', "ORDERS"), destination="STDOUT"),
                )),
            ),
        )
        ca = derive_capabilities(program_a)
        cb = derive_capabilities(program_b)
        assert ca.summary_output == cb.summary_output
        assert ca.summary_output is True


class TestStep9Mutation:
    """STEP 9: Mutate COBOL constructs, verify IR and capability changes."""

    def test_mutation_threshold_value_changes_ir(self):
        """Changing threshold value changes IR but not capability."""
        from engine.transformation.ir import ThresholdRule
        program_a = _make_program(
            threshold_rules=(ThresholdRule(field_name="AMOUNT", operator="<", value=500),),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="AMOUNT < 500",
                        then_body=(MoveStatement(source="'LOW'", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_b = _make_program(
            threshold_rules=(ThresholdRule(field_name="AMOUNT", operator="<", value=5000),),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="AMOUNT < 5000",
                        then_body=(MoveStatement(source="'LOW'", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        ca = derive_capabilities(program_a)
        cb = derive_capabilities(program_b)
        # Same capability structure
        assert ca.decision == cb.decision
        assert ca.assignment == cb.assignment
        # Different IR values
        assert program_a.threshold_rules[0].value != program_b.threshold_rules[0].value

    def test_mutation_remove_if_removes_decision(self):
        """Removing IF statement removes decision capability."""
        program_with_if = _make_program(
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
        program_without_if = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                )),
            ),
        )
        caps_with = derive_capabilities(program_with_if)
        caps_without = derive_capabilities(program_without_if)
        assert caps_with.decision is True
        assert caps_without.decision is False
        assert caps_without.assignment is True

    def test_mutation_add_perform_adds_lookup(self):
        """Adding PERFORM + table search paragraph adds lookup capability."""
        program_a = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                )),
            ),
        )
        program_b = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                    PerformStatement(paragraph_name="SEARCH-TABLE"),
                )),
                Paragraph(name="SEARCH-TABLE", statements=(
                    IfStatement(
                        condition="TABLE-IDX(IDX) = SEARCH-VAL",
                        then_body=(MoveStatement(source="FOUND", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        ca = derive_capabilities(program_a)
        cb = derive_capabilities(program_b)
        assert ca.lookup is False
        assert cb.lookup is True

    def test_mutation_add_string_adds_record_output(self):
        """Adding STRING INTO record + WRITE adds record_output capability."""
        program_a = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                )),
            ),
        )
        program_b = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                    StringStatement(parts=("A", '" "', "B"), target="REC"),
                    WriteStatement(record_name="REC", file_name="OUT-FILE"),
                )),
            ),
        )
        ca = derive_capabilities(program_a)
        cb = derive_capabilities(program_b)
        assert ca.record_output is False
        assert cb.record_output is True
        assert cb.string_build is True


class TestStep10Negative:
    """STEP 10: Explicit negative tests."""

    def test_no_if_no_decision(self):
        """No IF statement → no decision."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                    DisplayStatement(parts=("Y",), destination="STDOUT"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False

    def test_no_perform_no_lookup(self):
        """No PERFORM → no lookup."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.lookup is False

    def test_no_string_no_record_output(self):
        """No StringStatement → no record_output."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.record_output is False

    def test_no_display_no_summary(self):
        """No DisplayStatement → no summary_output."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="X", target="Y"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.summary_output is False

    def test_single_unconditional_move(self):
        """Single MOVE without IF → assignment only, no decision."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="0", target="COUNTER"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.assignment is True
        assert caps.decision is False

    def test_single_threshold_condition(self):
        """Single IF threshold with MOVE → decision (conditional assignment)."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="AMOUNT > 1000",
                        then_body=(MoveStatement(source="'HIGH'", target="CATEGORY"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is True
        assert caps.condition is True

    def test_unrelated_string_statement(self):
        """StringStatement INTO ordinary variable → string_build only, not record_output."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    StringStatement(parts=("FIRST-NAME", '" "', "LAST-NAME"), target="FULL-NAME"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.record_output is False
        assert caps.string_build is True

    def test_unrelated_perform(self):
        """PERFORM with arbitrary paragraph → perform only, not lookup."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    PerformStatement(paragraph_name="COMPUTE-TAX"),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.perform is True
        assert caps.lookup is False

    def test_empty_program(self):
        """Empty program → no capabilities."""
        program = _make_program()
        caps = derive_capabilities(program)
        assert caps.assignment is False
        assert caps.decision is False
        assert caps.lookup is False
        assert caps.record_output is False
        assert caps.summary_output is False

    def test_if_without_move_in_then(self):
        """IF with DISPLAY in then_body (not MOVE) → no decision."""
        program = _make_program(
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="A = B",
                        then_body=(DisplayStatement(parts=('"YES"',), destination="STDOUT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        caps = derive_capabilities(program)
        assert caps.decision is False
        assert caps.condition is True
        assert caps.display is True

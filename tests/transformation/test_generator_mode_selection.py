"""Tests for generator mode selection using generic capabilities only.

Verifies that the generator selects modes based exclusively on
ProgramCapabilities (caps.decision, caps.input_record_mapping),
NOT on any domain-shaped container.

Domain-neutral tests using ACCOUNT-PROCESSOR, ORDER-PROCESSOR,
STUDENT-PROCESSOR, GRADE-CALC.
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
    Paragraph,
    PerformStatement,
    PicType,
    ReadStatement,
    StatusCodeMapping,
    StringStatement,
    ThresholdRule,
    WriteStatement,
    derive_capabilities,
)
from engine.transformation.java_generator import JavaGenerator


def _make_program(
    program_id: str = "TEST-PROGRAM",
    file_definitions: tuple = (),
    working_storage: tuple = (),
    paragraphs: tuple = (),
    input_record_mappings: tuple = (),
    status_codes: tuple = (),
    output_formats: tuple = (),
    lookup_operations: tuple = (),
    match_outcome_labels: tuple = (),
    summary_fields: tuple = (),
    report_header: str = "",
) -> CobolProgram:
    return CobolProgram(
        program_id=program_id,
        file_definitions=file_definitions,
        working_storage=working_storage,
        paragraphs=paragraphs,
        input_record_mappings=input_record_mappings,
        status_codes=status_codes,
        output_formats=output_formats,
        lookup_operations=lookup_operations,
        match_outcome_labels=match_outcome_labels,
        summary_fields=summary_fields,
        report_header=report_header,
    )


# ============================================================
# STEP 4: Generator mode tests (domain-neutral)
# ============================================================

class TestGeneratorModeSelection:
    """Generator mode selection uses capabilities, not domain names."""

    def test_same_capabilities_same_mode(self):
        """ACCOUNT-PROCESSOR and ORDER-PROCESSOR with same structure
        produce the same generator mode (same template path)."""
        gen = JavaGenerator()

        program_a = _make_program(
            program_id="ACCOUNT-PROCESSOR",
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
        program_b = _make_program(
            program_id="ORDER-PROCESSOR",
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

        caps_a = derive_capabilities(program_a)
        caps_b = derive_capabilities(program_b)
        assert caps_a.decision == caps_b.decision
        assert caps_a.input_record_mapping == caps_b.input_record_mapping

        files_a = gen.generate(program_a)
        files_b = gen.generate(program_b)
        # Same capabilities → same generation path (both minimal, both decision, etc.)
        # Source code structure should be equivalent (same template)
        assert "public static void main" in files_a[0].source_code
        assert "public static void main" in files_b[0].source_code
        # Both fall back to minimal (no status codes)
        assert "class Account_Processor" in files_a[0].source_code
        assert "class Order_Processor" in files_b[0].source_code

    def test_rename_domain_identifiers_same_mode(self):
        """Renaming domain identifiers does not change generator mode."""
        gen = JavaGenerator()

        program_original = _make_program(
            program_id="CLAIM-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_renamed = _make_program(
            program_id="ORDER-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )

        caps_original = derive_capabilities(program_original)
        caps_renamed = derive_capabilities(program_renamed)
        assert caps_original.decision == caps_renamed.decision

        files_original = gen.generate(program_original)
        files_renamed = gen.generate(program_renamed)
        # Same capabilities → both produce valid Java
        assert len(files_original[0].source_code) > 0
        assert len(files_renamed[0].source_code) > 0

    def test_remove_decision_changes_mode(self):
        """Removing IF+MOVE removes decision capability, changes mode."""
        gen = JavaGenerator()

        program_with = _make_program(
            program_id="PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_without = _make_program(
            program_id="PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'OK'", target="RESULT"),
                )),
            ),
        )

        caps_with = derive_capabilities(program_with)
        caps_without = derive_capabilities(program_without)
        assert caps_with.decision is True
        assert caps_without.decision is False

        files_with = gen.generate(program_with)
        files_without = gen.generate(program_without)
        # Different capabilities → different source length
        assert len(files_with[0].source_code) != len(files_without[0].source_code)

    def test_add_decision_changes_mode(self):
        """Adding IF+MOVE adds decision capability, changes mode."""
        gen = JavaGenerator()

        program_before = _make_program(
            program_id="PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'OK'", target="RESULT"),
                )),
            ),
        )
        program_after = _make_program(
            program_id="PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="'OK'", target="RESULT"),
                    IfStatement(
                        condition="STATUS = 'R'",
                        then_body=(MoveStatement(source="'REJECTED'", target="RESULT"),),
                        else_body=(),
                    ),
                )),
            ),
        )

        caps_before = derive_capabilities(program_before)
        caps_after = derive_capabilities(program_after)
        assert caps_before.decision is False
        assert caps_after.decision is True

        files_before = gen.generate(program_before)
        files_after = gen.generate(program_after)
        # Different capabilities → different source
        assert files_before[0].source_code != files_after[0].source_code

    def test_decision_with_no_status_codes(self):
        """Decision capability with NO status_codes → valid generic mode.
        MANDATORY TEST: Generator must handle decision=True + empty status_codes."""
        gen = JavaGenerator()

        program = _make_program(
            program_id="ACCOUNT-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="BALANCE > LIMIT",
                        then_body=(MoveStatement(source="'HIGH'", target="CATEGORY"),),
                        else_body=(MoveStatement(source="'NORMAL'", target="CATEGORY"),),
                    ),
                )),
            ),
        )

        caps = derive_capabilities(program)
        assert caps.decision is True
        assert len(program.status_codes) == 0

        # Generator must NOT crash
        files = gen.generate(program)
        assert len(files) == 1
        assert len(files[0].source_code) > 0
        # Falls back to minimal generation
        assert "class Account_Processor" in files[0].source_code


# ============================================================
# STEP 5: Negative test
# ============================================================

class TestGeneratorNegative:
    """Generator handles edge cases without crashing."""

    def test_decision_true_empty_status_codes(self):
        """caps.decision=True + empty status_codes → valid output."""
        gen = JavaGenerator()

        program = _make_program(
            program_id="ORDER-PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="AMOUNT > 1000",
                        then_body=(MoveStatement(source="'LARGE'", target="CLASS"),),
                        else_body=(MoveStatement(source="'SMALL'", target="CLASS"),),
                    ),
                    DisplayStatement(parts=('"CLASS="', "CLASS"), destination="STDOUT"),
                )),
            ),
        )

        caps = derive_capabilities(program)
        assert caps.decision is True
        assert len(program.status_codes) == 0

        files = gen.generate(program)
        assert len(files) == 1
        assert "class Order_Processor" in files[0].source_code
        # Must not crash, must produce valid Java
        assert "public static void main" in files[0].source_code

    def test_empty_program(self):
        """Empty program → minimal mode."""
        gen = JavaGenerator()
        program = _make_program()
        files = gen.generate(program)
        assert len(files) == 1
        assert len(files[0].source_code) > 0


# ============================================================
# STEP 6: Mutation test
# ============================================================

class TestGeneratorMutation:
    """Semantic mutations change mode; lexical renames do not."""

    def test_semantic_mutation_changes_mode(self):
        """Removing IF+MOVE changes capabilities and generator output."""
        gen = JavaGenerator()

        program_a = _make_program(
            program_id="PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="BALANCE > LIMIT",
                        then_body=(MoveStatement(source="'HIGH'", target="CATEGORY"),),
                        else_body=(),
                    ),
                    DisplayStatement(parts=('"RESULT="', "CATEGORY"), destination="STDOUT"),
                )),
            ),
        )
        program_b = _make_program(
            program_id="PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    DisplayStatement(parts=('"RESULT="', "CATEGORY"), destination="STDOUT"),
                )),
            ),
        )

        caps_a = derive_capabilities(program_a)
        caps_b = derive_capabilities(program_b)
        assert caps_a.decision is True
        assert caps_b.decision is False

        files_a = gen.generate(program_a)
        files_b = gen.generate(program_b)
        assert files_a[0].source_code != files_b[0].source_code

    def test_lexical_rename_preserves_mode(self):
        """Renaming BALANCE→CLAIM-BALANCE, CATEGORY→SETTLEMENT-CATEGORY
        does not change capabilities or generator mode."""
        gen = JavaGenerator()

        program_original = _make_program(
            program_id="PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="BALANCE > LIMIT",
                        then_body=(MoveStatement(source="'HIGH'", target="CATEGORY"),),
                        else_body=(),
                    ),
                )),
            ),
        )
        program_renamed = _make_program(
            program_id="PROCESSOR",
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    IfStatement(
                        condition="CLAIM-BALANCE > LIMIT",
                        then_body=(MoveStatement(source="'HIGH'", target="SETTLEMENT-CATEGORY"),),
                        else_body=(),
                    ),
                )),
            ),
        )

        caps_original = derive_capabilities(program_original)
        caps_renamed = derive_capabilities(program_renamed)
        assert caps_original.decision == caps_renamed.decision
        assert caps_original.assignment == caps_renamed.assignment
        assert caps_original.condition == caps_renamed.condition

        files_original = gen.generate(program_original)
        files_renamed = gen.generate(program_renamed)
        # Same capabilities → same mode → same class name (same program_id)
        assert files_original[0].class_name == files_renamed[0].class_name
        # Same capabilities → both produce valid Java
        assert len(files_original[0].source_code) > 0
        assert len(files_renamed[0].source_code) > 0
        # Both fall back to minimal (no status codes)
        assert "class Processor" in files_original[0].source_code
        assert "class Processor" in files_renamed[0].source_code

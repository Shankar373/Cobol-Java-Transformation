"""Task 7A.1 — Domain-Neutral Proof Tests + Negative + Mutation.

Verifies that the Java Application Model is genuinely semantic and
domain-independent. No field-name heuristics, no path-based inference,
no hardcoded delimiters, no Claims-specific logic.

Tests of the removed decision-template helpers (file roles, summary
formatting, missing-filename refusal) and of ``derive_capabilities`` were
deleted with the template lanes (audit T5).
"""

from __future__ import annotations

import pytest

from engine.transformation.ir import (
    CobolProgram,
    DataItem,
    FileDefinition,
    FileOrganization,
    FileAccessMode,
    InputRecordMapping,
    OpenStatement,
    Paragraph,
    PicType,
    MoveStatement,
    AddStatement,
    IfStatement,
    StopRunStatement,
    DisplayStatement,
    StatusCodeMapping,
    ThresholdRule,
)

from engine.transformation.java_ir import (
    JavaApplication,
    JavaFileAccessMode,
    JavaFileResource,
    JavaProgram,
)

from engine.transformation.cobol_to_java_mapping import (
    map_cobol_file_to_resource,
    map_cobol_program_to_java,
    map_cobol_programs_to_application,
    map_pic_to_java_type,
    map_pic_to_java_default,
)

from engine.transformation.java_generator import JavaGenerator


# ============================================================
# CASE A — Amount-like field: PIC-derived formatting
# ============================================================

class TestCaseA_PicDerivedFormatting:
    """FIELD-A PIC 9(6) and FIELD-B PIC 9(2) should format by PIC, not name."""

    def test_pic_9_6_width(self):
        item = DataItem(name="FIELD-A", pic_type=PicType.NUMERIC, pic_length=6)
        assert item.format_width == 6
        assert not item.is_decimal

    def test_pic_9_2_width(self):
        item = DataItem(name="FIELD-B", pic_type=PicType.NUMERIC, pic_length=2)
        assert item.format_width == 2
        assert not item.is_decimal

    def test_pic_9_6_v99_width(self):
        # PIC 9(6)V99 has 8 digit positions (6 integer + 2 fractional).
        # pic_length counts every digit position, so format_width must not
        # add decimal_places a second time (that was the double-count bug).
        item = DataItem(name="FIELD-C", pic_type=PicType.NUMERIC, pic_length=8, decimal_places=2)
        assert item.format_width == 8
        assert item.integer_digits == 6
        assert item.is_decimal

    def test_no_amt_in_name(self):
        """Neither field name contains AMT — formatting must come from PIC."""
        item_no_amt = DataItem(name="TOTAL-VALUE", pic_type=PicType.NUMERIC, pic_length=6)
        item_with_amt = DataItem(name="TOTAL-AMOUNT", pic_type=PicType.NUMERIC, pic_length=6)
        # Both should have the same format width — PIC-driven, not name-driven
        assert item_no_amt.format_width == item_with_amt.format_width == 6


# ============================================================
# CASE B — Primary record: positional, not name-based
# ============================================================

class TestCaseB_PrimaryRecord:
    """RECORD-A and RECORD-B without STATUS/CATEGORY — use positional ordering."""

    def test_primary_record_is_first(self):
        """First InputRecordMapping is primary — no STATUS/CATEGORY detection."""
        irm1 = InputRecordMapping(
            record_name="RECORD-A",
            file_name="FILE-A",
            delimiter="|",
            fields=("FIELD-X", "FIELD-Y"),
        )
        irm2 = InputRecordMapping(
            record_name="RECORD-B",
            file_name="FILE-B",
            delimiter="|",
            fields=("FIELD-P", "FIELD-Q"),
        )
        program = CobolProgram(
            program_id="TEST",
            input_record_mappings=(irm1, irm2),
        )
        # Primary record should be the first one, regardless of field names
        assert program.input_record_mappings[0].record_name == "RECORD-A"

    def test_no_status_category_in_fields(self):
        """Fields without STATUS/CATEGORY — positional ordering still works."""
        irm = InputRecordMapping(
            record_name="RECORD-X",
            file_name="FILE-X",
            delimiter="|",
            fields=("FIELD-1", "FIELD-2", "FIELD-3"),
        )
        program = CobolProgram(
            program_id="TEST",
            input_record_mappings=(irm,),
        )
        # All fields are positionally accessible
        assert program.input_record_mappings[0].fields[0] == "FIELD-1"
        assert program.input_record_mappings[0].fields[1] == "FIELD-2"
        assert program.input_record_mappings[0].fields[2] == "FIELD-3"


# ============================================================
# CASE C — Delimiter mutation
# ============================================================

class TestCaseC_DelimiterMutation:
    """STRING delimiter changes must propagate to Java IR."""

    def test_delimiter_from_input_record_mapping(self):
        irm = InputRecordMapping(
            record_name="REC",
            file_name="FILE1",
            delimiter="|",
            fields=("A", "B"),
        )
        fd = FileDefinition(
            name="FILE1",
            container_path="/data/file1.dat",
            record_name="REC",
        )
        resource = map_cobol_file_to_resource(fd, (irm,))
        assert resource.record_delimiter == "|"

    def test_delimiter_space(self):
        irm = InputRecordMapping(
            record_name="REC",
            file_name="FILE1",
            delimiter=" ",
            fields=("A", "B"),
        )
        fd = FileDefinition(
            name="FILE1",
            container_path="/data/file1.dat",
            record_name="REC",
        )
        resource = map_cobol_file_to_resource(fd, (irm,))
        assert resource.record_delimiter == " "

    def test_no_delimiter_when_no_mapping(self):
        fd = FileDefinition(
            name="FILE1",
            container_path="/data/file1.dat",
            record_name="REC",
        )
        resource = map_cobol_file_to_resource(fd, ())
        assert resource.record_delimiter is None

    def test_delimiter_mutation_changes_resource(self):
        """Changing delimiter from | to ; must change the Java resource."""
        irm_pipe = InputRecordMapping(
            record_name="REC", file_name="F", delimiter="|", fields=("A",),
        )
        irm_semi = InputRecordMapping(
            record_name="REC", file_name="F", delimiter=";", fields=("A",),
        )
        fd = FileDefinition(name="F", container_path="/d/f.dat", record_name="REC")
        res_pipe = map_cobol_file_to_resource(fd, (irm_pipe,))
        res_semi = map_cobol_file_to_resource(fd, (irm_semi,))
        assert res_pipe.record_delimiter != res_semi.record_delimiter


# ============================================================
# CASE D — Path mutation: /input/ → /archive/ must not change architecture
# ============================================================

class TestCaseD_PathMutation:
    """Changing container path must not change semantic architecture."""

    def test_path_change_preserves_program_structure(self):
        prog1 = CobolProgram(
            program_id="TEST",
            file_definitions=(
                FileDefinition(
                    name="DATA-FILE",
                    container_path="/input/data.dat",
                    record_name="DATA-REC",
                ),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(StopRunStatement(),)),
            ),
        )
        prog2 = CobolProgram(
            program_id="TEST",
            file_definitions=(
                FileDefinition(
                    name="DATA-FILE",
                    container_path="/archive/data.dat",
                    record_name="DATA-REC",
                ),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(StopRunStatement(),)),
            ),
        )
        java1 = map_cobol_program_to_java(prog1)
        java2 = map_cobol_program_to_java(prog2)
        # Same program structure — only path metadata differs
        assert java1.program_id == java2.program_id
        assert java1.java_class.name == java2.java_class.name
        assert len(java1.java_class.methods) == len(java2.java_class.methods)


# ============================================================
# CASE E — Domain rename: rename all business-looking identifiers
# ============================================================

class TestCaseE_DomainRename:
    """Renaming domain identifiers must not change semantic architecture."""

    def test_rename_preserves_structure(self):
        """COBOL program with generic names → same Java structure as with business names."""
        generic = CobolProgram(
            program_id="GEN-PROG",
            working_storage=(
                DataItem(name="GEN-COUNT", pic_type=PicType.NUMERIC, pic_length=4),
            ),
            paragraphs=(
                Paragraph(name="GEN-PARA", statements=(
                    MoveStatement(source="1", target="GEN-COUNT"),
                    StopRunStatement(),
                )),
            ),
        )
        business = CobolProgram(
            program_id="CLAIM-PROCESSOR",
            working_storage=(
                DataItem(name="CLAIM-COUNT", pic_type=PicType.NUMERIC, pic_length=4),
            ),
            paragraphs=(
                Paragraph(name="PROCESS-CLAIMS", statements=(
                    MoveStatement(source="1", target="CLAIM-COUNT"),
                    StopRunStatement(),
                )),
            ),
        )
        java_generic = map_cobol_program_to_java(generic)
        java_business = map_cobol_program_to_java(business)
        # Same structural output — different names, same architecture
        assert len(java_generic.java_class.fields) == len(java_business.java_class.fields)
        assert len(java_generic.java_class.methods) == len(java_business.java_class.methods)
        # Both have same method names (derived from paragraph names)
        assert java_generic.java_class.methods[0].name == "GEN_PARA"
        assert java_business.java_class.methods[0].name == "PROCESS_CLAIMS"

# ============================================================
# Mutation matrix
# ============================================================

class TestMutationMatrix:
    """Verify Java IR changes when COBOL semantics change."""

    def test_pic_width_mutation(self):
        """Changing PIC width changes format_width."""
        item1 = DataItem(name="X", pic_type=PicType.NUMERIC, pic_length=4)
        item2 = DataItem(name="X", pic_type=PicType.NUMERIC, pic_length=8)
        assert item1.format_width != item2.format_width

    def test_decimal_places_mutation(self):
        """Widening a PIC to add implied decimals changes format_width and is_decimal."""
        # PIC 9(6) vs PIC 9(6)V99 (8 digit positions, 6 integer + 2 fractional).
        # pic_length counts every digit position, so the V99 variant is 8, not 6.
        item1 = DataItem(name="X", pic_type=PicType.NUMERIC, pic_length=6)
        item2 = DataItem(name="X", pic_type=PicType.NUMERIC, pic_length=8, decimal_places=2)
        assert item1.format_width != item2.format_width
        assert not item1.is_decimal
        assert item2.is_decimal

    def test_delimiter_mutation(self):
        """Changing delimiter changes JavaFileResource."""
        fd = FileDefinition(name="F", container_path="/d/f.dat", record_name="R")
        res1 = map_cobol_file_to_resource(fd, (InputRecordMapping(
            record_name="R", file_name="F", delimiter="|", fields=("A",),
        ),))
        res2 = map_cobol_file_to_resource(fd, (InputRecordMapping(
            record_name="R", file_name="F", delimiter=";", fields=("A",),
        ),))
        assert res1.record_delimiter != res2.record_delimiter


    def test_open_mode_mutation(self):
        """Changing the OPEN mode changes the file resource's access mode."""
        fd = FileDefinition(name="F", container_path="/d/f.dat", record_name="R")
        as_input = map_cobol_file_to_resource(fd, (), (OpenStatement(mode="INPUT", file_name="F"),))
        as_output = map_cobol_file_to_resource(fd, (), (OpenStatement(mode="OUTPUT", file_name="F"),))
        assert as_input.access_mode == JavaFileAccessMode.READ
        assert as_output.access_mode == JavaFileAccessMode.WRITE

    def test_program_dependency_mutation(self):
        """Adding a CALL dependency changes application graph."""
        p1 = CobolProgram(program_id="A", called_programs=("B",))
        p2 = CobolProgram(program_id="A")
        app1 = map_cobol_programs_to_application((p1,))
        app2 = map_cobol_programs_to_application((p2,))
        assert len(app1.dependencies) > len(app2.dependencies)


# ============================================================
# Determinism
# ============================================================

class TestDeterminism:
    """Same input → same output."""

    def test_same_source_same_java(self):
        gen = JavaGenerator()
        program = CobolProgram(
            program_id="TEST",
            working_storage=(
                DataItem(name="WS-COUNT", pic_type=PicType.NUMERIC, pic_length=4),
            ),
            paragraphs=(
                Paragraph(name="MAIN", statements=(
                    MoveStatement(source="1", target="WS-COUNT"),
                    StopRunStatement(),
                )),
            ),
        )
        java1 = gen.generate(program)
        java2 = gen.generate(program)
        assert java1 == java2

    def test_same_mapping_same_resource(self):
        fd = FileDefinition(name="F", container_path="/d/f.dat", record_name="R")
        irm = InputRecordMapping(record_name="R", file_name="F", delimiter="|", fields=("A",))
        res1 = map_cobol_file_to_resource(fd, (irm,))
        res2 = map_cobol_file_to_resource(fd, (irm,))
        assert res1 == res2

"""Tests for intermediate representation."""

from __future__ import annotations

import pytest

from engine.transformation.ir import (
    AddStatement,
    CobolProgram,
    DataItem,
    DisplayStatement,
    FileDefinition,
    GoToStatement,
    IfStatement,
    MoveStatement,
    OpenStatement,
    Paragraph,
    PerformStatement,
    PicType,
    ReadStatement,
    StopRunStatement,
    StringStatement,
    UnstringStatement,
    WriteStatement,
)


class TestDataItem:
    """Test DataItem IR node."""

    def test_alphanumeric_field(self):
        item = DataItem(
            name="WS-EOF-CLAIMS",
            pic_type=PicType.ALPHANUMERIC,
            pic_length=1,
            value="'N'",
        )
        assert item.is_alphanumeric
        assert not item.is_numeric
        assert not item.is_table
        assert item.pic_length == 1

    def test_numeric_field(self):
        item = DataItem(
            name="WS-CLAIM-COUNT",
            pic_type=PicType.NUMERIC,
            pic_length=2,
            value="0",
        )
        assert item.is_numeric
        assert not item.is_alphanumeric
        assert item.pic_length == 2

    def test_table_field(self):
        item = DataItem(
            name="WS-PAY-TABLE",
            pic_type=PicType.ALPHANUMERIC,
            pic_length=0,
            occurs=20,
        )
        assert item.is_table
        assert item.occurs == 20


class TestFileDefinition:
    """Test FileDefinition IR node."""

    def test_file_definition(self):
        fd = FileDefinition(
            name="CLAIMS-FILE",
            container_path="/workspace/input/claims.dat",
            record_name="CLAIM-REC",
        )
        assert fd.name == "CLAIMS-FILE"
        assert fd.container_path == "/workspace/input/claims.dat"

    def test_input_vs_output(self):
        input_fd = FileDefinition(
            name="CLAIMS-FILE",
            container_path="/workspace/input/claims.dat",
            record_name="CLAIM-REC",
        )
        output_fd = FileDefinition(
            name="REPORT-FILE",
            container_path="/workspace/output/report.txt",
            record_name="REPORT-REC",
        )
        assert "/input/" in input_fd.container_path
        assert "/output/" in output_fd.container_path


class TestStatements:
    """Test statement IR nodes."""

    def test_open_statement(self):
        stmt = OpenStatement(mode="INPUT", file_name="CLAIMS-FILE")
        assert stmt.mode == "INPUT"
        assert stmt.file_name == "CLAIMS-FILE"

    def test_read_statement(self):
        stmt = ReadStatement(
            file_name="CLAIMS-FILE",
            record_name="CLAIM-REC",
            at_end_body=(MoveStatement(source="'Y'", target="WS-EOF-CLAIMS"),),
        )
        assert stmt.file_name == "CLAIMS-FILE"
        assert len(stmt.at_end_body) == 1

    def test_write_statement(self):
        stmt = WriteStatement(record_name="REPORT-REC", file_name="REPORT-FILE")
        assert stmt.record_name == "REPORT-REC"

    def test_move_statement(self):
        stmt = MoveStatement(source="'REJECTED'", target="WS-SETTLEMENT-STATUS")
        assert stmt.source == "'REJECTED'"
        assert stmt.target == "WS-SETTLEMENT-STATUS"

    def test_add_statement(self):
        stmt = AddStatement(source="WS-CLAIM-AMOUNT", target="WS-TOTAL-CLAIMS")
        assert stmt.source == "WS-CLAIM-AMOUNT"
        assert stmt.target == "WS-TOTAL-CLAIMS"

    def test_if_statement(self):
        stmt = IfStatement(
            condition="WS-CR-STATUS = 'R'",
            then_body=(MoveStatement(source="'REJECTED'", target="WS-SETTLEMENT-STATUS"),),
            else_body=(),
        )
        assert "WS-CR-STATUS" in stmt.condition
        assert len(stmt.then_body) == 1
        assert len(stmt.else_body) == 0

    def test_perform_statement(self):
        stmt = PerformStatement(paragraph_name="LOAD-PAYMENTS")
        assert stmt.paragraph_name == "LOAD-PAYMENTS"

    def test_perform_until(self):
        stmt = PerformStatement(
            paragraph_name="PROCESS-CLAIMS",
            until_condition="WS-EOF-CLAIMS = 'Y'",
        )
        assert stmt.until_condition is not None

    def test_unstring_statement(self):
        stmt = UnstringStatement(
            source="PAYMENT-REC",
            delimiter="|",
            targets=("WS-PR-PAY-ID", "WS-PR-CLAIM-ID"),
        )
        assert stmt.source == "PAYMENT-REC"
        assert len(stmt.targets) == 2

    def test_string_statement(self):
        stmt = StringStatement(
            parts=('WS-CR-CLAIM-ID', '" "', 'WS-CR-PATIENT-NAME'),
            target="REPORT-REC",
        )
        assert len(stmt.parts) == 3
        assert stmt.target == "REPORT-REC"

    def test_display_statement(self):
        stmt = DisplayStatement(
            parts=('"TOTAL_CLAIMS="', "WS-CLAIM-COUNT"),
            destination="STDOUT",
        )
        assert stmt.destination == "STDOUT"

    def test_display_stderr(self):
        stmt = DisplayStatement(
            parts=('"REJECT:"', "WS-CR-CLAIM-ID"),
            destination="STDERR",
        )
        assert stmt.destination == "STDERR"

    def test_goto_statement(self):
        stmt = GoToStatement(target="LOAD-PAYMENTS")
        assert stmt.target == "LOAD-PAYMENTS"

    def test_stop_run(self):
        stmt = StopRunStatement()
        assert stmt is not None


class TestParagraph:
    """Test Paragraph IR node."""

    def test_paragraph(self):
        para = Paragraph(
            name="MAIN-LOGIC",
            statements=(
                OpenStatement(mode="INPUT", file_name="CLAIMS-FILE"),
                StopRunStatement(),
            ),
        )
        assert para.name == "MAIN-LOGIC"
        assert len(para.statements) == 2


class TestCobolProgram:
    """Test CobolProgram IR node."""

    def test_program(self):
        program = CobolProgram(
            program_id="CLAIMS",
            file_definitions=(
                FileDefinition(
                    name="CLAIMS-FILE",
                    container_path="/workspace/input/claims.dat",
                    record_name="CLAIM-REC",
                ),
            ),
            working_storage=(
                DataItem(name="WS-EOF-CLAIMS", pic_type=PicType.ALPHANUMERIC, pic_length=1),
            ),
            paragraphs=(
                Paragraph(name="MAIN-LOGIC", statements=(StopRunStatement(),)),
            ),
        )
        assert program.program_id == "CLAIMS"
        assert len(program.file_definitions) == 1
        assert len(program.working_storage) == 1
        assert len(program.paragraphs) == 1

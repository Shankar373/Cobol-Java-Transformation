"""Tests for COBOL parser."""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser, CobolParseError
from engine.transformation.ir import (
    AddStatement,
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
    UnstringStatement,
    WriteStatement,
)


@pytest.fixture
def parser() -> CobolParser:
    return CobolParser()


SAMPLE_CLAIMS_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLAIMS.
       AUTHOR. VALIDATION-PLATFORM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
        SELECT CLAIMS-FILE ASSIGN TO "/workspace/input/claims.dat"
            ORGANIZATION IS LINE SEQUENTIAL.
        SELECT PAYMENTS-FILE ASSIGN TO "/workspace/input/payments.dat"
            ORGANIZATION IS LINE SEQUENTIAL.
        SELECT REPORT-FILE ASSIGN TO "/workspace/output/report.txt"
            ORGANIZATION IS LINE SEQUENTIAL.
        SELECT SETTLE-FILE ASSIGN TO "/workspace/output/settlement.dat"
            ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  CLAIMS-FILE.
       01  CLAIM-REC             PIC X(60).

       FD  PAYMENTS-FILE.
       01  PAYMENT-REC           PIC X(60).

       FD  REPORT-FILE.
       01  REPORT-REC            PIC X(80).

       FD  SETTLE-FILE.
       01  SETTLE-REC            PIC X(80).

       WORKING-STORAGE SECTION.
       01  WS-EOF-CLAIMS         PIC X(1) VALUE 'N'.
       01  WS-EOF-PAYMENTS       PIC X(1) VALUE 'N'.
       01  WS-CLAIM-COUNT        PIC 9(2) VALUE 0.
       01  WS-APPROVED-COUNT     PIC 9(2) VALUE 0.
       01  WS-REJECTED-COUNT     PIC 9(2) VALUE 0.
       01  WS-PENDING-COUNT      PIC 9(2) VALUE 0.
       01  WS-PAID-COUNT         PIC 9(2) VALUE 0.
       01  WS-UNPAID-COUNT       PIC 9(2) VALUE 0.
       01  WS-TOTAL-CLAIMS       PIC 9(6) VALUE 0.
       01  WS-TOTAL-PAYMENTS     PIC 9(6) VALUE 0.
       01  WS-CLAIM-AMOUNT       PIC 9(5) VALUE 0.
       01  WS-PAY-MATCH-AMOUNT   PIC 9(5) VALUE 0.
       01  WS-PAY-MATCH-FOUND    PIC X(1) VALUE 'N'.
       01  WS-SETTLEMENT-STATUS  PIC X(13).

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT CLAIMS-FILE
           OPEN INPUT PAYMENTS-FILE
           OPEN OUTPUT REPORT-FILE
           OPEN OUTPUT SETTLE-FILE
           DISPLAY "TOTAL_CLAIMS=" WS-CLAIM-COUNT
           STOP RUN.
"""


class TestCobolParserBasic:
    """Test basic parsing functionality."""

    def test_parse_program_id(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        assert program.program_id == "CLAIMS"

    def test_parse_file_definitions(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        assert len(program.file_definitions) == 4
        names = [fd.name for fd in program.file_definitions]
        assert "CLAIMS-FILE" in names
        assert "PAYMENTS-FILE" in names
        assert "REPORT-FILE" in names
        assert "SETTLE-FILE" in names

    def test_parse_file_paths(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        claims_fd = next(fd for fd in program.file_definitions if fd.name == "CLAIMS-FILE")
        assert claims_fd.container_path == "/workspace/input/claims.dat"

    def test_parse_working_storage(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        assert len(program.working_storage) > 0
        names = [item.name for item in program.working_storage]
        assert "WS-EOF-CLAIMS" in names
        assert "WS-CLAIM-COUNT" in names

    def test_parse_pic_types(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        eof = next(item for item in program.working_storage if item.name == "WS-EOF-CLAIMS")
        assert eof.pic_type == PicType.ALPHANUMERIC
        assert eof.pic_length == 1

        count = next(item for item in program.working_storage if item.name == "WS-CLAIM-COUNT")
        assert count.pic_type == PicType.NUMERIC
        assert count.pic_length == 2

    def test_parse_paragraphs(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        assert len(program.paragraphs) > 0
        names = [p.name for p in program.paragraphs]
        assert "MAIN-LOGIC" in names

    def test_parse_main_logic_statements(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        main = next(p for p in program.paragraphs if p.name == "MAIN-LOGIC")
        assert len(main.statements) > 0
        # Should have OPEN, DISPLAY, STOP RUN
        stmt_types = [type(s).__name__ for s in main.statements]
        assert "OpenStatement" in stmt_types
        assert "DisplayStatement" in stmt_types
        assert "StopRunStatement" in stmt_types


class TestCobolParserFileControl:
    """Test FILE-CONTROL parsing."""

    def test_select_assign(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        for fd in program.file_definitions:
            assert fd.container_path.startswith("/workspace/")

    def test_report_file_path(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        report_fd = next(fd for fd in program.file_definitions if fd.name == "REPORT-FILE")
        assert report_fd.container_path == "/workspace/output/report.txt"


class TestCobolParserWorkingStorage:
    """Test WORKING-STORAGE parsing."""

    def test_all_counters_present(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        expected = [
            "WS-CLAIM-COUNT", "WS-APPROVED-COUNT", "WS-REJECTED-COUNT",
            "WS-PENDING-COUNT", "WS-PAID-COUNT", "WS-UNPAID-COUNT",
        ]
        names = [item.name for item in program.working_storage]
        for e in expected:
            assert e in names, f"Missing {e}"

    def test_numeric_values(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        count = next(item for item in program.working_storage if item.name == "WS-CLAIM-COUNT")
        assert count.value == "0"

    def test_alphanumeric_values(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        eof = next(item for item in program.working_storage if item.name == "WS-EOF-CLAIMS")
        assert eof.value == "'N'" or eof.value == "N"


class TestCobolParserStatements:
    """Test statement parsing."""

    def test_open_statements(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        main = next(p for p in program.paragraphs if p.name == "MAIN-LOGIC")
        opens = [s for s in main.statements if isinstance(s, OpenStatement)]
        assert len(opens) == 4

    def test_display_statement(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        main = next(p for p in program.paragraphs if p.name == "MAIN-LOGIC")
        displays = [s for s in main.statements if isinstance(s, DisplayStatement)]
        assert len(displays) >= 1

    def test_stop_run(self, parser: CobolParser):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        main = next(p for p in program.paragraphs if p.name == "MAIN-LOGIC")
        stops = [s for s in main.statements if isinstance(s, StopRunStatement)]
        assert len(stops) == 1



    def test_named_paragraph_does_not_create_empty_synthetic_main(self, parser: CobolParser):
        """A named paragraph is the first procedure paragraph, not a second MAIN."""
        source = """\\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
       MAIN.
           MOVE 100 TO LIMIT.
           IF LIMIT > 0
               DISPLAY "POSITIVE"
           END-IF.
           PERFORM WORK UNTIL LIMIT = 0.
           STOP RUN.
       WORK.
           MOVE 0 TO LIMIT.
"""
        program = parser.parse(source)

        assert [paragraph.name for paragraph in program.paragraphs] == ["MAIN", "WORK"]
        main = program.paragraphs[0]
        assert len(main.statements) == 4
        assert isinstance(main.statements[0], MoveStatement)
        assert isinstance(main.statements[1], IfStatement)
        assert isinstance(main.statements[2], PerformStatement)
        assert isinstance(main.statements[3], StopRunStatement)
        assert main.statements[0].source_expr is not None
        assert main.statements[1].structured_condition is not None
        assert main.statements[2].structured_condition is not None

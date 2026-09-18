"""Tests for Java code generator."""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator, GeneratedFile
from engine.transformation.ir import (
    CobolProgram,
    DataItem,
    FileDefinition,
    Paragraph,
    PicType,
    StopRunStatement,
)


@pytest.fixture
def generator() -> JavaGenerator:
    return JavaGenerator()


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


class TestJavaGeneratorBasic:
    """Test basic Java generation."""

    def test_generates_single_file(self, parser: CobolParser, generator: JavaGenerator):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        files = generator.generate(program)
        assert len(files) == 1
        assert files[0].filename == "Claims.java"

    def test_class_name(self, parser: CobolParser, generator: JavaGenerator):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        files = generator.generate(program)
        assert files[0].class_name == "Claims"

    def test_has_main_method(self, parser: CobolParser, generator: JavaGenerator):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        files = generator.generate(program)
        assert "public static void main(String[] args)" in files[0].source_code

    def test_has_class_declaration(self, parser: CobolParser, generator: JavaGenerator):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        files = generator.generate(program)
        assert "public class Claims" in files[0].source_code

    def test_imports_java_io(self, parser: CobolParser, generator: JavaGenerator):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        files = generator.generate(program)
        # Minimal mode (no status codes) uses PrintStream
        assert "import java.io.PrintStream;" in files[0].source_code

    def test_imports_java_util(self, parser: CobolParser, generator: JavaGenerator):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        files = generator.generate(program)
        # Minimal mode (no status codes) has no java.util imports
        assert "public static void main" in files[0].source_code

    def test_no_cobol_runtime(self, parser: CobolParser, generator: JavaGenerator):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        files = generator.generate(program)
        source = files[0].source_code
        assert "cobol" not in source.lower() or "cobol" in "Claims.java"
        assert "gnucobol" not in source.lower()
        assert "subprocess" not in source.lower()


class TestJavaGeneratorFileIO:
    """Test Java file I/O generation (settlement mode)."""

    def _parse_real_claims(self, parser: CobolParser):
        """Parse the real CLAIMS.cob fixture."""
        from pathlib import Path
        cobol = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        return parser.parse(cobol)

    def test_reads_input_files(self, parser: CobolParser, generator: JavaGenerator):
        program = self._parse_real_claims(parser)
        files = generator.generate(program)
        source = files[0].source_code
        assert "claims.dat" in source
        assert "payments.dat" in source

    def test_writes_output_files(self, parser: CobolParser, generator: JavaGenerator):
        program = self._parse_real_claims(parser)
        files = generator.generate(program)
        source = files[0].source_code
        assert "report.txt" in source
        assert "settlement.dat" in source

    def test_has_readInput_method(self, parser: CobolParser, generator: JavaGenerator):
        program = self._parse_real_claims(parser)
        files = generator.generate(program)
        assert "static List<String[]> readInput" in files[0].source_code

    def test_has_padRight_method(self, parser: CobolParser, generator: JavaGenerator):
        program = self._parse_real_claims(parser)
        files = generator.generate(program)
        assert "static String padRight" in files[0].source_code


class TestJavaGeneratorVariables:
    """Test working storage variable generation (settlement mode)."""

    def _parse_real_claims(self, parser: CobolParser):
        """Parse the real CLAIMS.cob fixture."""
        from pathlib import Path
        cobol = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        return parser.parse(cobol)

    def test_counter_variables(self, parser: CobolParser, generator: JavaGenerator):
        program = self._parse_real_claims(parser)
        files = generator.generate(program)
        source = files[0].source_code
        assert "totalClaims" in source
        assert "approved" in source
        assert "rejected" in source
        assert "pending" in source
        assert "paid" in source
        assert "unpaid" in source

    def test_amount_variables(self, parser: CobolParser, generator: JavaGenerator):
        program = self._parse_real_claims(parser)
        files = generator.generate(program)
        source = files[0].source_code
        assert "totalClaimAmt" in source
        assert "totalPayAmt" in source


class TestJavaGeneratorDeterminism:
    """Test deterministic generation."""

    def test_same_input_same_output(self, parser: CobolParser, generator: JavaGenerator):
        program = parser.parse(SAMPLE_CLAIMS_COBOL)
        files1 = generator.generate(program)
        files2 = generator.generate(program)
        assert files1[0].source_code == files2[0].source_code

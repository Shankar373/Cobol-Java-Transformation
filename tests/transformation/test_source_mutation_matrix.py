"""Source mutation matrix: verify mutations in each category produce different Java.

Categories:
A. Status values (IF/MOVE patterns)
B. Threshold values (IF amount < N)
C. Assignment values (MOVE N TO field)
D. Arithmetic values (ADD N TO field)
E. Output formatting (DISPLAY labels)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.producers.internal_native import (
    InternalNativeJavaProducer,
)


CLAIMS_COBOL = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
MINIMAL_COBOL = Path("fixtures/workload-minimal/cobol/SIMPLE-CALC.cob").read_text()


class TestStatusValueMutation:
    """Category A: Status value mutations propagate to Java."""

    def test_status_r_to_x(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(CLAIMS_COBOL, program_id="CLAIMS")
        java1 = result1.generated_files[0].source_code

        mutated = CLAIMS_COBOL.replace("= 'R'", "= 'X'")
        result2 = producer.transform(mutated, program_id="CLAIMS")
        java2 = result2.generated_files[0].source_code

        assert java1 != java2
        assert '.equals("R")' in java1
        assert '.equals("X")' in java2

    def test_status_p_to_q(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(CLAIMS_COBOL, program_id="CLAIMS")
        java1 = result1.generated_files[0].source_code

        mutated = CLAIMS_COBOL.replace("= 'P'", "= 'Q'")
        result2 = producer.transform(mutated, program_id="CLAIMS")
        java2 = result2.generated_files[0].source_code

        assert java1 != java2
        assert '.equals("P")' in java1
        assert '.equals("Q")' in java2


class TestThresholdMutation:
    """Category B: Threshold value mutations propagate to Java."""

    def test_threshold_500_to_1000(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(CLAIMS_COBOL, program_id="CLAIMS")
        java1 = result1.generated_files[0].source_code

        mutated = CLAIMS_COBOL.replace("< 500", "< 1000")
        result2 = producer.transform(mutated, program_id="CLAIMS")
        java2 = result2.generated_files[0].source_code

        assert java1 != java2
        assert "THRESHOLD = 500" in java1
        assert "THRESHOLD = 1000" in java2

    def test_threshold_minimal_200_to_100(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
        java1 = result1.generated_files[0].source_code

        mutated = MINIMAL_COBOL.replace("VALUE 200", "VALUE 100")
        result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
        java2 = result2.generated_files[0].source_code

        assert java1 != java2


class TestAssignmentMutation:
    """Category C: Assignment value mutations propagate to Java."""

    def test_move_100_to_200(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
        java1 = result1.generated_files[0].source_code

        mutated = MINIMAL_COBOL.replace("MOVE 100 TO WS-RESULT", "MOVE 200 TO WS-RESULT")
        result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
        java2 = result2.generated_files[0].source_code

        assert java1 != java2
        assert "WS_RESULT = 100;" in java1
        assert "WS_RESULT = 200;" in java2

    def test_move_string_literal(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
        java1 = result1.generated_files[0].source_code

        mutated = MINIMAL_COBOL.replace("MOVE 'APPROVED' TO WS-STATUS", "MOVE 'APPROVED' TO WS-STATUS")
        # Same mutation should produce same result
        result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
        java2 = result2.generated_files[0].source_code
        assert java1 == java2


class TestArithmeticMutation:
    """Category D: Arithmetic value mutations propagate to Java."""

    def test_add_50_to_75(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
        java1 = result1.generated_files[0].source_code

        mutated = MINIMAL_COBOL.replace("ADD 50 TO WS-RESULT", "ADD 75 TO WS-RESULT")
        result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
        java2 = result2.generated_files[0].source_code

        assert java1 != java2
        assert "WS_RESULT += 50;" in java1 or "WS_RESULT = (WS_RESULT + 50)" in java1
        assert "WS_RESULT += 75;" in java2 or "WS_RESULT = (WS_RESULT + 75)" in java2

    def test_add_25_to_10(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
        java1 = result1.generated_files[0].source_code

        mutated = MINIMAL_COBOL.replace("ADD 25 TO WS-COUNTER", "ADD 10 TO WS-COUNTER")
        result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
        java2 = result2.generated_files[0].source_code

        assert java1 != java2
        assert "WS_COUNTER += 25;" in java1 or "WS_COUNTER = (WS_COUNTER + 25)" in java1
        assert "WS_COUNTER += 10;" in java2 or "WS_COUNTER = (WS_COUNTER + 10)" in java2


class TestOutputMutation:
    """Category E: Output formatting mutations propagate to Java."""

    def test_display_label_change(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
        java1 = result1.generated_files[0].source_code

        mutated = MINIMAL_COBOL.replace('DISPLAY "RESULT="', 'DISPLAY "OUTPUT="')
        result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
        java2 = result2.generated_files[0].source_code

        assert java1 != java2
        assert '"RESULT="' in java1
        assert '"OUTPUT="' in java2


class TestDeterminism:
    """Verify identical source produces identical Java."""

    def test_identical_source_identical_java(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(CLAIMS_COBOL, program_id="CLAIMS")
        result2 = producer.transform(CLAIMS_COBOL, program_id="CLAIMS")

        java1 = result1.generated_files[0].source_code
        java2 = result2.generated_files[0].source_code
        assert java1 == java2

    def test_identical_minimal_identical_java(self):
        producer = InternalNativeJavaProducer()
        result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
        result2 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")

        java1 = result1.generated_files[0].source_code
        java2 = result2.generated_files[0].source_code
        assert java1 == java2

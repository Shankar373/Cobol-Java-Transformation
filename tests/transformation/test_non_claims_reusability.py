"""Non-Claims reusability proof: SIMPLE-CALC fixture.

Proves the generator is not Claims-specific by generating, compiling,
and running Java from a non-Claims COBOL program.
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


FIXTURE_DIR = Path("fixtures/workload-minimal")
COBOL_FILE = FIXTURE_DIR / "cobol" / "SIMPLE-CALC.cob"


@pytest.fixture
def cobol_source() -> str:
    return COBOL_FILE.read_text()


class TestNonClaimsReusability:
    """Prove the generator handles non-Claims COBOL programs."""

    def test_simple_calc_compiles(self, cobol_source: str):
        """SIMPLE-CALC compiles to valid Java."""
        producer = InternalNativeJavaProducer()
        result = producer.transform(cobol_source, program_id="SIMPLE-CALC")

        assert len(result.generated_files) == 1
        java_code = result.generated_files[0].source_code

        with tempfile.TemporaryDirectory() as td:
            java_path = Path(td) / "Simple_Calc.java"
            java_path.write_text(java_code)
            proc = subprocess.run(
                ["javac", str(java_path)],
                capture_output=True,
                text=True,
            )
            assert proc.returncode == 0, f"javac failed: {proc.stderr}"

    def test_simple_calc_executes_correctly(self, cobol_source: str):
        """SIMPLE-CALC Java output matches COBOL semantics."""
        producer = InternalNativeJavaProducer()
        result = producer.transform(cobol_source, program_id="SIMPLE-CALC")

        java_code = result.generated_files[0].source_code

        with tempfile.TemporaryDirectory() as td:
            java_path = Path(td) / "Simple_Calc.java"
            java_path.write_text(java_code)

            # Compile
            compile_proc = subprocess.run(
                ["javac", str(java_path)],
                capture_output=True,
                text=True,
            )
            assert compile_proc.returncode == 0

            # Run
            run_proc = subprocess.run(
                ["java", "-cp", td, "Simple_Calc"],
                capture_output=True,
                text=True,
            )
            assert run_proc.returncode == 0
            output = run_proc.stdout

            # COBOL logic: MOVE 100 TO WS-RESULT, ADD 50 -> 150 (PIC 9(5) -> 00150)
            assert "RESULT=00150" in output
            # COBOL logic: ADD 25 TO WS-COUNTER -> 25 (PIC 9(3) -> 025)
            assert "COUNTER=025" in output
            # COBOL logic: 150 > 200 is FALSE -> REJECTED
            assert "STATUS=REJECTED" in output

    def test_simple_calc_mutation_changes_output(self, cobol_source: str):
        """Mutating SIMPLE-CALC source changes generated Java output."""
        producer = InternalNativeJavaProducer()

        # Original: WS-AMOUNT = 150, WS-THRESHOLD = 200 -> REJECTED
        result1 = producer.transform(cobol_source, program_id="SIMPLE-CALC")
        java1 = result1.generated_files[0].source_code

        # Mutate threshold from 200 to 100
        mutated = cobol_source.replace("VALUE 200", "VALUE 100")
        result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
        java2 = result2.generated_files[0].source_code

        # Different threshold -> different generated Java
        assert java1 != java2
        assert "THRESHOLD = 200" in java1 or "200" in java1
        assert "THRESHOLD = 100" not in java1

    def test_simple_calc_has_no_cobol_runtime(self, cobol_source: str):
        """Generated Java has no COBOL runtime dependency."""
        producer = InternalNativeJavaProducer()
        result = producer.transform(cobol_source, program_id="SIMPLE-CALC")

        java_code = result.generated_files[0].source_code
        assert "cobol" not in java_code.lower() or "cobol" in "Simple_Calc.java"
        assert "gnucobol" not in java_code.lower()
        assert "subprocess" not in java_code.lower()

    def test_simple_calc_is_standalone(self, cobol_source: str):
        """Generated Java is standalone (no external dependencies)."""
        producer = InternalNativeJavaProducer()
        result = producer.transform(cobol_source, program_id="SIMPLE-CALC")

        assert result.metadata.get("standalone_java") is True
        assert result.metadata.get("cobol_runtime_required") is False

    def test_simple_calc_no_status_codes_in_ir(self, cobol_source: str):
        """SIMPLE-CALC has no settlement logic (no status codes in COBOL)."""
        parser = CobolParser()
        program = parser.parse(cobol_source)

        # No IF/MOVE status patterns -> no status codes
        assert len(program.status_codes) == 0

    def test_simple_calc_minimal_mode(self, cobol_source: str):
        """SIMPLE-CALC generates in minimal mode (no settlement template)."""
        generator = JavaGenerator()
        parser = CobolParser()
        program = parser.parse(cobol_source)

        files = generator.generate(program)
        java_code = files[0].source_code

        # Minimal mode: no readInput, no padRight, no lookupMap
        assert "readInput" not in java_code
        assert "padRight" not in java_code
        assert "lookupMap" not in java_code
        assert "static final int THRESHOLD" not in java_code

    def test_simple_calc_move_and_add(self, cobol_source: str):
        """Generated Java has MOVE and ADD statements."""
        generator = JavaGenerator()
        parser = CobolParser()
        program = parser.parse(cobol_source)

        files = generator.generate(program)
        java_code = files[0].source_code

        # MOVE 100 TO WS-RESULT
        assert "WS_RESULT = 100;" in java_code
        # ADD 50 TO WS-RESULT → WS_RESULT += 50 or WS_RESULT = (WS_RESULT + 50)
        assert "WS_RESULT += 50;" in java_code or "WS_RESULT = (WS_RESULT + 50)" in java_code
        # ADD 25 TO WS-COUNTER → WS_COUNTER += 25 or WS_COUNTER = (WS_COUNTER + 25)
        assert "WS_COUNTER += 25;" in java_code or "WS_COUNTER = (WS_COUNTER + 25)" in java_code

    def test_simple_calc_if_else(self, cobol_source: str):
        """Generated Java has IF/ELSE for condition."""
        generator = JavaGenerator()
        parser = CobolParser()
        program = parser.parse(cobol_source)

        files = generator.generate(program)
        java_code = files[0].source_code

        assert "if (WS_AMOUNT > WS_THRESHOLD)" in java_code
        assert 'WS_STATUS = "APPROVED"' in java_code
        assert 'WS_STATUS = "REJECTED"' in java_code

    def test_simple_calc_display(self, cobol_source: str):
        """Generated Java has DISPLAY statements with PIC formatting."""
        generator = JavaGenerator()
        parser = CobolParser()
        program = parser.parse(cobol_source)

        files = generator.generate(program)
        java_code = files[0].source_code

        # PIC 9(5) -> String.format("%05d", WS_RESULT)
        assert 'String.format("%05d", WS_RESULT)' in java_code
        # PIC 9(3) -> String.format("%03d", WS_COUNTER)
        assert 'String.format("%03d", WS_COUNTER)' in java_code
        # PIC X(10) alphanumeric -> no formatting
        assert 'println("STATUS=" + WS_STATUS' in java_code

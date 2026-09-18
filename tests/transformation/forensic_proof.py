"""Phase 5F.2 Forensic Behavioral Proofs.

Proves source-driven semantics with compilation + runtime evidence.
"""

import subprocess
import tempfile
from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.producers.internal_native import InternalNativeJavaProducer

CLAIMS_COBOL = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
MINIMAL_COBOL = Path("fixtures/workload-minimal/cobol/SIMPLE-CALC.cob").read_text()
CLAIMS_INPUT = Path("fixtures/workload-claims/input/claims.dat").read_text()
CLAIMS_PAYMENTS = Path("fixtures/workload-claims/input/payments.dat").read_text()


def compile_and_run(java_code, class_name, input_dir=None, timeout=10):
    """Compile Java and run it. Returns (stdout, stderr, returncode)."""
    with tempfile.TemporaryDirectory() as td:
        java_path = Path(td) / f"{class_name}.java"
        java_path.write_text(java_code)
        r = subprocess.run(
            ["javac", str(java_path)],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return None, r.stderr, r.returncode

        args = ["java", "-cp", str(td), class_name]
        if input_dir:
            out_dir = Path(td) / "output"
            out_dir.mkdir()
            args.extend([str(input_dir), str(out_dir)])
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout, r.stderr, r.returncode


def run_claims_java(java_code, claims_input, payments_input, td):
    """Run generated Claims Java with given inputs. Returns output dir."""
    td.mkdir(parents=True, exist_ok=True)
    input_dir = td / "input"
    input_dir.mkdir(exist_ok=True)
    (input_dir / "claims.dat").write_text(claims_input)
    (input_dir / "payments.dat").write_text(payments_input)

    out_dir = td / "output"
    out_dir.mkdir(exist_ok=True)

    java_path = Path(td) / "Claims.java"
    java_path.write_text(java_code)
    subprocess.run(["javac", str(java_path)], capture_output=True, timeout=10)
    subprocess.run(
        ["java", "-cp", str(td), "Claims", str(input_dir), str(out_dir)],
        capture_output=True, text=True, timeout=10,
    )
    return out_dir


def test_status_code_proof():
    """STATUS CODE PROOF: R->X mutation changes runtime behavior."""
    print("=== STATUS CODE PROOF ===")
    producer = InternalNativeJavaProducer()

    result1 = producer.transform(CLAIMS_COBOL, program_id="CLAIMS")
    java1 = result1.generated_files[0].source_code

    mutated = CLAIMS_COBOL.replace("'R'", "'X'")
    result2 = producer.transform(mutated, program_id="CLAIMS")
    java2 = result2.generated_files[0].source_code

    # String presence
    assert '.equals("R")' in java1, "Original should have R"
    assert '.equals("X")' in java2, "Mutated should have X"
    assert java1 != java2, "Mutated should be different from original"
    print("  String evidence: PASS")

    # Behavioral proof
    with tempfile.TemporaryDirectory() as td:
        out1 = run_claims_java(java1, CLAIMS_INPUT, CLAIMS_PAYMENTS, Path(td) / "run1")
        out2 = run_claims_java(java2, CLAIMS_INPUT, CLAIMS_PAYMENTS, Path(td) / "run2")

        report1 = (out1 / "report.txt").read_text() if (out1 / "report.txt").exists() else ""
        report2 = (out2 / "report.txt").read_text() if (out2 / "report.txt").exists() else ""

        print("  Original report has REJECTED:", "REJECTED" in report1)
        print("  Mutated report has REJECTED:", "REJECTED" in report2)
        print("  Reports differ:", report1 != report2)
        assert report1 != report2, "Reports should differ"
    print("  Behavioral evidence: PASS")
    print()


def test_threshold_proof():
    """THRESHOLD PROOF: 500->1000 changes approval for amount=750."""
    print("=== THRESHOLD PROOF ===")
    producer = InternalNativeJavaProducer()

    result1 = producer.transform(CLAIMS_COBOL, program_id="CLAIMS")
    java1 = result1.generated_files[0].source_code

    mutated = CLAIMS_COBOL.replace("< 500", "< 1000")
    result2 = producer.transform(mutated, program_id="CLAIMS")
    java2 = result2.generated_files[0].source_code

    assert "THRESHOLD = 500" in java1
    assert "THRESHOLD = 1000" in java2
    print("  String evidence: PASS")

    # Behavioral: amount=750 with threshold 500 vs 1000
    with tempfile.TemporaryDirectory() as td:
        out1 = run_claims_java(java1, "C003|John|20240103|750|A|G\n", "P003|C003|20240103|750\n", Path(td) / "run1")
        out2 = run_claims_java(java2, "C003|John|20240103|750|A|G\n", "P003|C003|20240103|750\n", Path(td) / "run2")

        settle1 = (out1 / "settlement.dat").read_text() if (out1 / "settlement.dat").exists() else ""
        settle2 = (out2 / "settlement.dat").read_text() if (out2 / "settlement.dat").exists() else ""

        print("  Threshold 500, amount=750 -> settlement:", settle1.strip())
        print("  Threshold 1000, amount=750 -> settlement:", settle2.strip())
        assert settle1 != settle2, "Settlement should differ"
    print("  Behavioral evidence: PASS")
    print()


def test_assignment_proof():
    """ASSIGNMENT PROOF: MOVE 100->200 changes runtime result."""
    print("=== ASSIGNMENT PROOF ===")
    producer = InternalNativeJavaProducer()

    result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
    java1 = result1.generated_files[0].source_code

    mutated = MINIMAL_COBOL.replace("MOVE 100 TO WS-RESULT", "MOVE 200 TO WS-RESULT")
    result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
    java2 = result2.generated_files[0].source_code

    assert "WS_RESULT = 100;" in java1
    assert "WS_RESULT = 200;" in java2
    print("  String evidence: PASS")

    stdout1, _, rc1 = compile_and_run(java1, "Simple_Calc")
    stdout2, _, rc2 = compile_and_run(java2, "Simple_Calc")
    assert rc1 == 0 and rc2 == 0
    print("  Original output:", stdout1.strip())
    print("  Mutated output:", stdout2.strip())
    assert "RESULT=150" in stdout1  # 100 + 50
    assert "RESULT=250" in stdout2  # 200 + 50
    print("  Behavioral evidence: PASS")
    print()


def test_arithmetic_proof():
    """ARITHMETIC PROOF: ADD 50->75 changes runtime result."""
    print("=== ARITHMETIC PROOF ===")
    producer = InternalNativeJavaProducer()

    result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
    java1 = result1.generated_files[0].source_code

    mutated = MINIMAL_COBOL.replace("ADD 50 TO WS-RESULT", "ADD 75 TO WS-RESULT")
    result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
    java2 = result2.generated_files[0].source_code

    assert "WS_RESULT += 50;" in java1
    assert "WS_RESULT += 75;" in java2
    print("  String evidence: PASS")

    stdout1, _, rc1 = compile_and_run(java1, "Simple_Calc")
    stdout2, _, rc2 = compile_and_run(java2, "Simple_Calc")
    assert rc1 == 0 and rc2 == 0
    print("  Original output:", stdout1.strip())
    print("  Mutated output:", stdout2.strip())
    assert "RESULT=150" in stdout1  # 100 + 50
    assert "RESULT=175" in stdout2  # 100 + 75
    print("  Behavioral evidence: PASS")
    print()


def test_output_format_proof():
    """OUTPUT FORMAT PROOF: DISPLAY literal mutation changes stdout."""
    print("=== OUTPUT FORMAT PROOF ===")
    producer = InternalNativeJavaProducer()

    result1 = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
    java1 = result1.generated_files[0].source_code

    mutated = MINIMAL_COBOL.replace('DISPLAY "RESULT="', 'DISPLAY "OUTPUT="')
    result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
    java2 = result2.generated_files[0].source_code

    assert '"RESULT="' in java1
    assert '"OUTPUT="' in java2
    print("  String evidence: PASS")

    stdout1, _, rc1 = compile_and_run(java1, "Simple_Calc")
    stdout2, _, rc2 = compile_and_run(java2, "Simple_Calc")
    assert rc1 == 0 and rc2 == 0
    print("  Original output:", stdout1.strip())
    print("  Mutated output:", stdout2.strip())
    assert "RESULT=" in stdout1
    assert "OUTPUT=" in stdout2
    assert "RESULT=" not in stdout2
    print("  Behavioral evidence: PASS")
    print()


def test_simple_calc_reusability():
    """SIMPLE-CALC: non-Claims COBOL -> minimal Java -> correct output."""
    print("=== SIMPLE-CALC REUSABILITY PROOF ===")
    producer = InternalNativeJavaProducer()
    result = producer.transform(MINIMAL_COBOL, program_id="SIMPLE-CALC")
    java = result.generated_files[0].source_code

    # Must NOT be settlement mode
    assert "readInput" not in java
    assert "paymentMap" not in java
    assert "THRESHOLD" not in java
    print("  Not settlement mode: PASS")

    stdout, stderr, rc = compile_and_run(java, "Simple_Calc")
    assert rc == 0, f"Failed: {stderr}"
    assert "RESULT=150" in stdout
    assert "COUNTER=25" in stdout
    assert "STATUS=REJECTED" in stdout
    print("  Output correct: PASS")

    # Mutate threshold
    mutated = MINIMAL_COBOL.replace("VALUE 200", "VALUE 100")
    result2 = producer.transform(mutated, program_id="SIMPLE-CALC")
    java2 = result2.generated_files[0].source_code
    stdout2, _, rc2 = compile_and_run(java2, "Simple_Calc")
    assert rc2 == 0
    print("  Mutated output:", stdout2.strip())
    assert "STATUS=APPROVED" in stdout2  # 150 > 100
    print("  Behavioral mutation: PASS")
    print()


if __name__ == "__main__":
    test_status_code_proof()
    test_threshold_proof()
    test_assignment_proof()
    test_arithmetic_proof()
    test_output_format_proof()
    test_simple_calc_reusability()
    print("=" * 60)
    print("ALL BEHAVIORAL PROOFS PASSED")

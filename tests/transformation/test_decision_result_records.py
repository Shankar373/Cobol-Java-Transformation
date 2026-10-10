"""Computed outcomes reach the source receiving field before STRING writes."""
from pathlib import Path
import subprocess

import pytest
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.java_generator import JavaGenerator


@pytest.mark.parametrize("target", ["WS-SETTLEMENT-STATUS", "DECISION-TEXT"])
def test_outcome_is_stored_in_source_field_and_written(tmp_path, target):
    source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text().replace("WS-SETTLEMENT-STATUS", target)
    program = CobolParser().parse(source)
    java = map_cobol_program_to_java(program)
    assert java.decision_result_field == target.replace("-", "_")
    assert java.decision_result_width == 13
    generated = JavaGenerator().generate(program)[0]
    path = tmp_path / generated.filename
    path.write_text(generated.source_code, encoding="utf-8")
    input_dir, output_dir = tmp_path / "input", tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    (input_dir / "claims.dat").write_text("C001|John Doe|20240115|1200|A|GEN|\n")
    (input_dir / "payments.dat").write_text("P001|C001|20240201|1200|BANK\n")
    built = subprocess.run(["javac", str(path)], capture_output=True)
    assert built.returncode == 0, built.stderr
    executed = subprocess.run(["java", "-cp", str(tmp_path), generated.class_name,
                               str(input_dir), str(output_dir)], capture_output=True)
    assert executed.returncode == 0, executed.stderr
    for filename in ("report.txt", "settlement.dat"):
        content = (output_dir / filename).read_bytes()
        assert b"C001" in content
        assert "PAID_IN_FULL".ljust(java.decision_result_width).encode() in content

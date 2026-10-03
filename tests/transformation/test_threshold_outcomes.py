"""Threshold success outcomes and counters follow the source ELSE branch."""
from pathlib import Path
import subprocess

import pytest
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.java_generator import JavaGenerator


@pytest.mark.parametrize("label", ["APPROVED", "ELIGIBLE"])
def test_threshold_pass_outcome_and_counter_are_source_derived(tmp_path, label):
    source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text().replace("APPROVED", label)
    program = CobolParser().parse(source)
    java = map_cobol_program_to_java(program)
    assert java.threshold_rules[0].pass_label == label
    assert java.threshold_rules[0].pass_counter_name == label.lower()
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
    assert f"{label}=01".encode() in executed.stdout.splitlines()
    assert b"PENDING=00" in executed.stdout.splitlines()

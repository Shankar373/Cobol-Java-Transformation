"""DISPLAY labels resolve width from the displayed data item, not the label."""
from pathlib import Path
import subprocess

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.java_generator import JavaGenerator


@pytest.mark.parametrize("width", [2, 4, 7])
def test_summary_alias_keeps_numeric_pic_width(tmp_path, width):
    source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
    source = source.replace("WS-CLAIM-COUNT", "RECORD-COUNTER")
    source = source.replace("RECORD-COUNTER        PIC 9(2)", f"RECORD-COUNTER        PIC 9({width})")
    program = CobolParser().parse(source)
    java = map_cobol_program_to_java(program)
    widths = {field.field_name: field.format_width for field in java.summary_fields}
    assert widths["TOTAL_CLAIMS"] == width
    assert widths["TOTAL_CLAIM_AMT"] == 6
    generated = JavaGenerator().generate(program)[0]
    path = tmp_path / generated.filename
    path.write_text(generated.source_code, encoding="utf-8")
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    (input_dir / "claims.dat").write_bytes(b"")
    (input_dir / "payments.dat").write_bytes(b"")
    built = subprocess.run(["javac", str(path)], capture_output=True)
    assert built.returncode == 0, built.stderr
    executed = subprocess.run(["java", "-cp", str(tmp_path), generated.class_name,
                               str(input_dir), str(output_dir)], capture_output=True)
    assert executed.returncode == 0, executed.stderr
    assert f"TOTAL_CLAIMS={'0' * width}".encode() in executed.stdout.splitlines()
    assert b"TOTAL_CLAIM_AMT=000000" in executed.stdout.splitlines()

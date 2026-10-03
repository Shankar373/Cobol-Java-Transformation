"""Decision inputs follow file and data-flow metadata rather than positions."""
from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import JavaApplication


@pytest.mark.parametrize("reverse_mappings", [False, True])
def test_primary_record_and_operand_roles_are_source_derived(tmp_path, reverse_mappings):
    source = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
    for old, new in (("WS-CR-AMOUNT-STR", "INPUT-NUMBER"),
                     ("WS-CR-STATUS", "INPUT-STATE"),
                     ("WS-CLAIM-AMOUNT", "WORK-AMOUNT")):
        source = source.replace(old, new)
    program = CobolParser().parse(source)
    if reverse_mappings:
        program = replace(program, input_record_mappings=tuple(reversed(program.input_record_mappings)))
    java = map_cobol_program_to_java(program)
    assert java.input_record_fields == (
        "WS_CR_CLAIM_ID", "WS_CR_PATIENT_NAME", "WS_CR_SERVICE_DATE",
        "INPUT_NUMBER", "INPUT_STATE", "WS_CR_CATEGORY",
    )
    assert java.input_amount_field == "INPUT_NUMBER"
    assert {code.field_name for code in java.status_codes} == {"INPUT_STATE"}
    generated = JavaGenerator().generate_from_java(JavaApplication(
        application_id="roles", programs=(java,),
    ))[0]
    path = tmp_path / generated.filename
    path.write_text(generated.source_code, encoding="utf-8")
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    (input_dir / "claims.dat").write_text("C001|John Doe|20240115|1200|A|GEN|\n")
    (input_dir / "payments.dat").write_text("P001|C001|20240201|1200|BANK\n")
    built = subprocess.run(["javac", str(path)], capture_output=True)
    assert built.returncode == 0, built.stderr
    executed = subprocess.run(["java", "-cp", str(tmp_path), generated.class_name,
                               str(input_dir), str(output_dir)], capture_output=True)
    assert executed.returncode == 0, executed.stderr
    assert b"TOTAL_CLAIMS=01" in executed.stdout.splitlines()
    assert (output_dir / "report.txt").is_file()
    assert (output_dir / "settlement.dat").is_file()

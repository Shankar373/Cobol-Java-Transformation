"""VALUE clauses must be tokens, not suffixes of data-item names."""
import subprocess

import pytest
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator


@pytest.mark.parametrize("initializer", [None, "123"])
def test_value_suffix_identifier_keeps_its_actual_initializer(tmp_path, initializer):
    clause = f" VALUE {initializer}" if initializer is not None else ""
    source = f'''       IDENTIFICATION DIVISION.
       PROGRAM-ID. KEYWORD-DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WORK-VALUE PIC 9(5){clause}.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY WORK-VALUE.
           STOP RUN.
'''
    program = CobolParser().parse(source)
    assert program.working_storage[0].value == initializer
    generated = JavaGenerator().generate(program)[0]
    path = tmp_path / generated.filename
    path.write_text(generated.source_code, encoding="utf-8")
    built = subprocess.run(["javac", str(path)], capture_output=True)
    assert built.returncode == 0, built.stderr
    executed = subprocess.run(["java", "-cp", str(tmp_path), generated.class_name], capture_output=True)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.replace(b"\r\n", b"\n") == f"{int(initializer or '0'):05d}\n".encode()


@pytest.mark.parametrize("initializer", [None, "321"])
def test_redefined_value_suffix_is_not_a_value_clause(initializer):
    clause = f" VALUE {initializer}" if initializer is not None else ""
    item = CobolParser().parse_data_description_lines([
        f"01 NEW-ITEM REDEFINES OLD-VALUE PIC 9(5){clause}.",
    ])[0]
    assert item.value == initializer
    assert item.redefines == "OLD-VALUE"

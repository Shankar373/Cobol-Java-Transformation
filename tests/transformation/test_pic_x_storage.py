"""PIC X storage survives parser, mapping, generation and JVM execution."""
import subprocess

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator


@pytest.mark.parametrize("width", [1, 5, 10])
def test_pic_x_value_and_move_have_receiving_width(tmp_path, width):
    source = f'''       IDENTIFICATION DIVISION.
       PROGRAM-ID. WIDTH-DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 FIELD-A PIC X({width}) VALUE "Q".
       01 FIELD-B PIC X({width}).
       01 FIELD-C PIC X({width}) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "[" FIELD-A "]".
           DISPLAY "[" FIELD-B "]".
           DISPLAY "[" FIELD-C "]".
           MOVE "Z" TO FIELD-A FIELD-B.
           DISPLAY "[" FIELD-A "][" FIELD-B "]".
           MOVE "ABCDEFGHIJK" TO FIELD-A.
           MOVE FIELD-A TO FIELD-B.
           DISPLAY "[" FIELD-B "]".
           STOP RUN.
'''
    program = CobolParser().parse(source)
    files = JavaGenerator().generate(program)
    paths = []
    for generated in files:
        path = tmp_path / generated.filename
        path.write_text(generated.source_code, encoding="utf-8")
        paths.append(str(path))
    built = subprocess.run(["javac", *paths], capture_output=True)
    assert built.returncode == 0, built.stderr
    executed = subprocess.run(
        ["java", "-cp", str(tmp_path), files[0].class_name], capture_output=True,
    )
    assert executed.returncode == 0, executed.stderr
    expected = (
        f"[{'Q'.ljust(width)}]\n[{' ' * width}]\n[{' ' * width}]\n"
        f"[{'Z'.ljust(width)}][{'Z'.ljust(width)}]\n"
        f"[{'ABCDEFGHIJK'[:width]}]\n"
    ).encode()
    assert executed.stdout.replace(b"\r\n", b"\n") == expected
    assert executed.stderr == b""

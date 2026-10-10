"""Continuation lines belong to the PERFORM header, not its body."""
import subprocess

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.ir import PerformStatement


@pytest.mark.parametrize("header", [
    "PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3",
    "PERFORM VARYING WS-I FROM 1 BY 1\n           UNTIL WS-I > 3",
    "PERFORM VARYING WS-I\n           FROM 1 BY 1\n           UNTIL WS-I > 3",
])
def test_varying_header_generates_a_finite_executable_loop(tmp_path, header):
    source = f'''       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARYING-DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I PIC 9(2) VALUE 0.
       01 WS-SUM PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           {header}
               ADD WS-I TO WS-SUM
           END-PERFORM.
           DISPLAY "SUM=" WS-SUM.
           STOP RUN.
'''
    program = CobolParser().parse(source)
    loop = next(s for s in program.paragraphs[0].statements if isinstance(s, PerformStatement))
    assert loop.until_condition == "VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3"
    files = JavaGenerator().generate(program)
    for generated in files:
        (tmp_path / generated.filename).write_text(generated.source_code, encoding="utf-8")
    built = subprocess.run(["javac", str(tmp_path / files[0].filename)], capture_output=True)
    assert built.returncode == 0, built.stderr
    executed = subprocess.run(["java", "-cp", str(tmp_path), files[0].class_name], capture_output=True, timeout=10)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.replace(b"\r\n", b"\n") == b"SUM=000006\n"
    assert executed.stderr == b""

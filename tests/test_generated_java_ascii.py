"""Generated Java must be pure ASCII.

A support class or program that carries a non-ASCII character (an em dash in a comment was the case) compiles
on a UTF-8 host and fails on one whose default code page differs (Windows cp1252 reads byte 0x97 as an
unmappable UTF-8 sequence).  Every emitted Java template and a program exercising each support class are
checked, so the property cannot regress silently.
"""

from __future__ import annotations

import pytest

from engine.jcl.orchestrator import _TEMPLATE as JCL_RUNNER_TEMPLATE
from engine.simulators.cics_java import SIMCICS_JAVA
from engine.simulators.dli_java import SIMDLI_JAVA
from engine.simulators.mq_java import SIMMQ_JAVA
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.file_io_support_template import COBOL_FILE_IO_JAVA
from engine.transformation.inspect_support_template import COBOL_INSPECT_JAVA
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.sql_support_template import COBOL_SQL_JAVA
from engine.transformation.stdin_support_template import COBOL_STDIN_JAVA

TEMPLATES = {
    "file io": COBOL_FILE_IO_JAVA, "stdin": COBOL_STDIN_JAVA, "inspect": COBOL_INSPECT_JAVA,
    "sql": COBOL_SQL_JAVA, "jcl runner": JCL_RUNNER_TEMPLATE, "SimMq": SIMMQ_JAVA, "SimDli": SIMDLI_JAVA,
    "SimCics": SIMCICS_JAVA,
}


def _offender(text: str) -> str:
    for line_number, line in enumerate(text.splitlines(), start=1):
        for character in line:
            if ord(character) > 127:
                return f"line {line_number}: U+{ord(character):04X} in {line.strip()[:60]!r}"
    return ""


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_java_template_is_ascii(name):
    assert _offender(TEMPLATES[name]) == ""


def test_a_program_using_every_support_class_is_ascii():
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. ALLSUP.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO 'in.dat'\n               ORGANIZATION IS LINE SEQUENTIAL.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD IN-FILE.\n       01 IN-REC PIC X(8).\n"
        "       WORKING-STORAGE SECTION.\n       01 WS-LINE PIC X(8).\n       01 WS-N PIC 9(3).\n"
        "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
        "       PROCEDURE DIVISION.\n       MAIN.\n"
        "           OPEN INPUT IN-FILE.\n           READ IN-FILE NEXT.\n           CLOSE IN-FILE.\n"
        "           ACCEPT WS-LINE.\n"
        '           INSPECT WS-LINE TALLYING WS-N FOR ALL "A".\n'
        "           EXEC SQL COMMIT END-EXEC.\n"
        "           STOP RUN.\n"
    )
    generated = JavaGenerator().generate(CobolParser().parse(source))[0].source_code
    for marker in ("CobolFileIo", "CobolStdin", "CobolInspect", "CobolSql"):
        assert marker in generated, marker
    assert _offender(generated) == ""

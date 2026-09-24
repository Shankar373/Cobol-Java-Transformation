"""Paragraph-less PROCEDURE DIVISION support (transformation lane).

Proves the generic shape:

    PROCEDURE DIVISION.
        <supported statement>
        ...

is represented without requiring a paragraph header:

    COBOL -> IR -> Java -> Spring Boot

with equivalent output. No fixture strings are special-cased; the marker
below is an arbitrary literal chosen by this test.
"""

from __future__ import annotations

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import (
    map_cobol_programs_to_application,
)
from engine.transformation.ir import DisplayStatement, StopRunStatement
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_to_spring_mapping import (
    map_java_application_to_spring_boot,
)
from engine.transformation.spring_boot_generator import SpringBootGenerator

MARKER = "PARAGRAPHLESS-PROBE-7Q3"

PARAGRAPHLESS_PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. SMOKE.\n"
    "       PROCEDURE DIVISION.\n"
    f'           DISPLAY "{MARKER}".\n'
    "           STOP RUN.\n"
)

PARAGRAPH_PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. PARA.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-LOGIC.\n"
    f'           DISPLAY "{MARKER}".\n'
    "           STOP RUN.\n"
)


def test_paragraphless_procedure_parses_statements():
    """Direct PROCEDURE DIVISION statements are not dropped."""
    program = CobolParser().parse(PARAGRAPHLESS_PROGRAM)
    assert program.program_id == "SMOKE"
    assert len(program.paragraphs) == 1
    stmts = program.paragraphs[0].statements
    assert len(stmts) == 2
    assert isinstance(stmts[0], DisplayStatement)
    assert stmts[0].parts == (f'"{MARKER}"',)
    assert isinstance(stmts[1], StopRunStatement)


def test_literal_display_survives_to_java():
    """COBOL -> IR -> Java keeps the literal DISPLAY output."""
    program = CobolParser().parse(PARAGRAPHLESS_PROGRAM)
    java_app = map_cobol_programs_to_application(programs=(program,))
    files = JavaGenerator().generate_from_java(java_app)
    assert files, "expected generated Java files"
    combined = "\n".join(f.source_code for f in files)
    assert MARKER in combined
    assert "System.out.println" in combined


def test_literal_display_survives_to_spring_boot():
    """COBOL -> IR -> Java -> Spring Boot keeps the literal DISPLAY output."""
    program = CobolParser().parse(PARAGRAPHLESS_PROGRAM)
    java_app = map_cobol_programs_to_application(programs=(program,))
    spring_app = map_java_application_to_spring_boot(java_app)
    assert not spring_app.validate()
    assert spring_app.services, "expected at least one service"
    assert spring_app.services[0].methods, "service must expose business logic"
    files = SpringBootGenerator().generate_project(spring_app)
    assert files
    combined = "\n".join(f.source_code for f in files)
    assert MARKER in combined
    assert "No business logic to execute." not in combined


def test_paragraphless_application_builds(tmp_path):
    """Discovery + per-program generation succeeds for a paragraph-less app."""
    src = tmp_path / "SMOKE.cob"
    src.write_text(PARAGRAPHLESS_PROGRAM, encoding="utf-8")
    app = ApplicationDiscovery().discover(str(tmp_path), application_id="smoke")
    assert len(app.programs) == 1
    result = ApplicationGenerator().generate(app)
    assert result.success, result.errors
    assert result.generated_files
    assert result.entrypoint
    assert result.java_application is not None


def test_paragraph_based_programs_unchanged():
    """Normal paragraph headers keep their names; no synthetic paragraph."""
    program = CobolParser().parse(PARAGRAPH_PROGRAM)
    assert [p.name for p in program.paragraphs] == ["MAIN-LOGIC"]
    assert len(program.paragraphs[0].statements) == 2


def test_generator_exposes_reusable_java_application(tmp_path):
    """ApplicationGenerator result carries the mapped JavaApplication.

    Contract for the API lane: reuse ``result.java_application`` for the
    Spring Boot mapping instead of invoking
    ``map_cobol_programs_to_application`` a second time.
    """
    src = tmp_path / "SMOKE.cob"
    src.write_text(PARAGRAPHLESS_PROGRAM, encoding="utf-8")
    app = ApplicationDiscovery().discover(str(tmp_path), application_id="smoke")
    result = ApplicationGenerator().generate(app)
    assert result.success, result.errors
    java_app = result.java_application
    assert java_app is not None
    assert [p.program_id for p in java_app.programs] == ["SMOKE"]
    # Reuse path: the exposed object feeds the Spring mapping directly.
    spring_app = map_java_application_to_spring_boot(java_app)
    assert not spring_app.validate()
    files = SpringBootGenerator().generate_project(spring_app)
    assert any(MARKER in f.source_code for f in files)

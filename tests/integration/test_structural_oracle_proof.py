"""GnuCOBOL oracle differential proof for structural COBOL features.

Proves, against a real GnuCOBOL 3.1.2 compiler and the eclipse-temurin JDK
image, that the deterministic structural lowering reproduces the oracle's
stdout byte for byte:

* fixed-size ``OCCURS`` tables (elementary and group record tables) with
  1-based subscripts;
* 88-level condition names in EVALUATE / IF, including THRU ranges and
  width-padded alphanumeric VALUE terms;
* ``SET <condition-name> TO TRUE`` assigns the first VALUE term exactly as
  GnuCOBOL does;
* ``OCCURS DEPENDING ON`` is rejected at parse time and the generated Java
  fails closed instead of silently using a fixed size.

Every test is Docker-gated: the deterministic unit contracts in
``tests/transformation/test_occurs_lowering.py`` and
``tests/transformation/test_level88_lowering.py`` always run.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.java_generator import JavaGenerator

GNUCobol_IMAGE = "gnucobol-ocesql:latest"
JAVA_IMAGE = "eclipse-temurin:21-jdk"


def _docker_images_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return False
        images = result.stdout.decode(errors="replace")
        return GNUCobol_IMAGE in images and JAVA_IMAGE in images
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(
    not _docker_images_available(),
    reason="docker and GnuCOBOL/temurin images unavailable",
)


def _run_gnucobol(tmp_path: Path, source_name: str, source: str) -> list[str]:
    (tmp_path / source_name).write_text(source, encoding="utf-8")
    exe = source_name[: -len(".cob")]
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-v", f"{tmp_path}:/src", "-w", "/src",
            GNUCobol_IMAGE,
            "bash", "-c", f"cobc -free -x -o {exe} {source_name} && ./{exe}",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout.decode(errors="replace").splitlines()


def _generate(source: str) -> tuple[str, str]:
    """Return (class name, source code) for the deterministic lowering."""
    program = CobolParser().parse(source)
    generated = JavaGenerator().generate(program)[0]
    match = re.search(r"public\s+class\s+(\w+)", generated.source_code)
    assert match, generated.source_code
    return match.group(1), generated.source_code


def _compile_generated(tmp_path: Path, class_name: str, source: str) -> subprocess.CompletedProcess:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir(exist_ok=True)
    (candidate_dir / f"{class_name}.java").write_text(source, encoding="utf-8")
    return subprocess.run(
        [
            "docker", "run", "--rm", "-v", f"{candidate_dir}:/app", "-w", "/app",
            JAVA_IMAGE,
            "bash", "-c", f"javac {class_name}.java && java {class_name}",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )


def _run_generated_java(tmp_path: Path, source: str) -> list[str]:
    class_name, source_code = _generate(source)
    build = _compile_generated(tmp_path, class_name, source_code)
    assert build.returncode == 0, build.stderr.decode(errors="replace")
    return build.stdout.decode(errors="replace").splitlines()


GROUP_OCCURS = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. GROUPTBL.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-STORE.
        05  WS-ITEM OCCURS 3 TIMES.
            10  WS-ID       PIC 9(2).
            10  WS-LABEL    PIC X(3).
    01  WS-I               PIC 9(1) VALUE 0.
    PROCEDURE DIVISION.
    MAIN-LOGIC.
        PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
            COMPUTE WS-ID(WS-I) = WS-I * 7
            MOVE "ABC" TO WS-LABEL(WS-I)
        END-PERFORM.
        DISPLAY "ID1=" WS-ID(1) " L1=" WS-LABEL(1) "|".
        DISPLAY "ID2=" WS-ID(2) " L2=" WS-LABEL(2) "|".
        DISPLAY "ID3=" WS-ID(3) " L3=" WS-LABEL(3) "|".
        STOP RUN.
    """
)

THRU_AND_SET = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. THRUSET.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-STATUS         PIC 9(2) VALUE 5.
        88  STAT-WARNING      VALUE 01 THRU 09.
        88  STAT-OK           VALUE 00.
    01  WS-CODE           PIC X(3) VALUE 'A'.
        88  CODE-A            VALUE 'A'.
        88  CODE-BLANK        VALUE SPACES.
    PROCEDURE DIVISION.
    MAIN-LOGIC.
        IF STAT-WARNING
            DISPLAY "WARNING"
        END-IF.
        IF CODE-A
            DISPLAY "CODE-A"
        END-IF.
        SET STAT-OK TO TRUE.
        DISPLAY "OK=" WS-STATUS.
        SET STAT-WARNING TO TRUE.
        DISPLAY "WARN=" WS-STATUS.
        SET CODE-BLANK TO TRUE.
        DISPLAY "BLANK=" WS-CODE "|".
        STOP RUN.
    """
)

SHIPPED_FIXTURES = (
    Path("fixtures/workload-occurs/cobol/MAIN.cob"),
    Path("fixtures/workload-level88/cobol/MAIN.cob"),
)


@needs_docker
@pytest.mark.parametrize(
    "fixture", SHIPPED_FIXTURES, ids=lambda p: p.parent.parent.name
)
def test_shipped_structural_fixture_byte_identical_to_gnucobol(tmp_path, fixture):
    source = fixture.read_text(encoding="utf-8")
    oracle = _run_gnucobol(tmp_path, fixture.name, source)
    assert oracle, f"oracle produced no output for {fixture}"
    generated = _run_generated_java(tmp_path, source)
    assert generated == oracle, (generated, oracle)


@needs_docker
def test_group_occurs_table_matches_gnucobol(tmp_path):
    oracle = _run_gnucobol(tmp_path, "group_tbl.cob", GROUP_OCCURS)
    assert oracle == [
        "ID1=07 L1=ABC|",
        "ID2=14 L2=ABC|",
        "ID3=21 L3=ABC|",
    ], oracle
    generated = _run_generated_java(tmp_path, GROUP_OCCURS)
    assert generated == oracle, (generated, oracle)


@needs_docker
def test_thru_range_and_set_semantics_match_gnucobol(tmp_path):
    oracle = _run_gnucobol(tmp_path, "thru_set.cob", THRU_AND_SET)
    # SET on a THRU condition assigns the first value of the range; an
    # alphanumeric VALUE is compared/padded at the parent width.
    assert oracle == [
        "WARNING",
        "CODE-A",
        "OK=00",
        "WARN=01",
        "BLANK=   |",
    ], oracle
    generated = _run_generated_java(tmp_path, THRU_AND_SET)
    assert generated == oracle, (generated, oracle)


ODO_SOURCE = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. ODOTBL.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-N              PIC 9(2) VALUE 5.
    01  WS-TABLE          PIC 9(3) OCCURS 1 TO 10 TIMES DEPENDING ON WS-N.
    PROCEDURE DIVISION.
    MAIN-LOGIC.
        MOVE 1 TO WS-TABLE(1).
        DISPLAY "V=" WS-TABLE(1).
        STOP RUN.
    """
)


def test_occurs_depending_on_is_rejected_not_silently_lowered():
    parser = CobolParser()
    program = parser.parse(ODO_SOURCE)
    messages = [
        d.message
        for d in parser.diagnostics.all
        if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
    ]
    assert any("DEPENDING ON" in m for m in messages), messages
    item = next(
        i for i in program.working_storage if i.name == "WS-TABLE"
    )
    assert item.occurs_depending_on == "WS-N"

    class_name, source_code = _generate(ODO_SOURCE)
    # No fixed-size array is declared for the variable-length table.
    assert "new int[10]" not in source_code, source_code
    assert "WS_TABLE" not in source_code.split("class ", 1)[1].split(
        "public static void", 1
    )[0], source_code


@needs_docker
def test_occurs_depending_on_generated_java_fails_closed(tmp_path):
    class_name, source_code = _generate(ODO_SOURCE)
    build = _compile_generated(tmp_path, class_name, source_code)
    assert build.returncode != 0, source_code
    stderr = build.stderr.decode(errors="replace")
    assert "cannot find symbol" in stderr, stderr


REDEFINES_OVERLAY = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. REDEFX.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-RECORD.
        05  WS-FULL   PIC X(10) VALUE 'ABCDEFGHIJ'.
        05  WS-HEAD   REDEFINES WS-FULL PIC X(4).
        05  WS-TAIL   REDEFINES WS-FULL PIC X(6).
        05  WS-ONE    REDEFINES WS-FULL PIC X(1).
    PROCEDURE DIVISION.
    MAIN-LOGIC.
        DISPLAY "FULL=" WS-FULL "|".
        DISPLAY "HEAD=" WS-HEAD "|".
        MOVE "XYZ" TO WS-HEAD.
        DISPLAY "FULL=" WS-FULL "|".
        DISPLAY "TAIL=" WS-TAIL "|".
        MOVE "123456" TO WS-TAIL.
        DISPLAY "FULL=" WS-FULL "|".
        MOVE "Q" TO WS-ONE.
        DISPLAY "FULL=" WS-FULL "|".
        MOVE "0123456789" TO WS-FULL.
        DISPLAY "HEAD=" WS-HEAD "|".
        DISPLAY "TAIL=" WS-TAIL "|".
        STOP RUN.
    """
)


@needs_docker
def test_certified_redefines_overlay_matches_gnucobol(tmp_path):
    oracle = _run_gnucobol(tmp_path, "redef_x.cob", REDEFINES_OVERLAY)
    assert oracle == [
        "FULL=ABCDEFGHIJ|",
        "HEAD=ABCD|",
        "FULL=XYZ EFGHIJ|",
        "TAIL=XYZ EF|",
        "FULL=123456GHIJ|",
        "FULL=Q23456GHIJ|",
        "HEAD=0123|",
        "TAIL=012345|",
    ], oracle
    generated = _run_generated_java(tmp_path, REDEFINES_OVERLAY)
    assert generated == oracle, (generated, oracle)


def test_numeric_redefines_view_fails_closed():
    from engine.transformation.diagnostics import DiagnosticCode

    source = textwrap.dedent(
        """\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REDEFN.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-RECORD.
            05  WS-NUM   PIC 9(6) VALUE 123456.
            05  WS-CHAR  REDEFINES WS-NUM PIC X(6).
        PROCEDURE DIVISION.
        MAIN-LOGIC.
            MOVE "ABCDEF" TO WS-CHAR.
            DISPLAY "N=" WS-NUM.
            STOP RUN.
        """
    )
    parser = CobolParser()
    program = parser.parse(source)
    messages = [
        d.message
        for d in parser.diagnostics.all
        if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
    ]
    assert any("numeric" in m for m in messages), messages
    class_name, source_code = _generate(source)
    assert "WS_CHAR" not in source_code.split("class ", 1)[1].split(
        "public static void", 1
    )[0], source_code


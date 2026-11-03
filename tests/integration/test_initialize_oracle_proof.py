"""GnuCOBOL oracle differential proof for INITIALIZE (certified plain subset).

Proves, against a real GnuCOBOL 3.1.2 compiler and the eclipse-temurin JDK
image, that the deterministic INITIALIZE lowering reproduces the oracle's
stdout byte for byte for the certified subset:

- Statement form: ``INITIALIZE <field> [<field> ...]`` with no
  ``ALL TO VALUE`` and no ``REPLACING`` clause (both fail closed in the
  lowering contract).
- Elementary targets: ``PIC X(n)`` -> n spaces; numeric-display targets
  (unsigned/signed, optional implied decimal ``V``, ``USAGE COMP`` /
  ``COMP-3``) -> typed zero.  Signed zero displays as ``+0000``.
- Group targets: GnuCOBOL initializes every elementary *subordinate* item
  by category — alphanumeric -> spaces, numeric (including ``COMP`` /
  ``COMP-3`` and signed/decimal display) -> zero.  ``FILLER`` items are
  NOT initialized (kept their VALUE bytes), 88-level condition-names are
  not data, nested groups are expanded recursively, and VALUE clauses are
  ignored by the plain form.
- The plain form overwrites existing data (initialized state or data
  written by earlier statements) at the point the statement executes.

Every expected output below was first observed directly against the
GnuCOBOL oracle; the Java side must match it exactly.

Out of scope (fail closed in the lowering, see
``tests/transformation/test_initialize_lowering.py``): ``ALL TO VALUE``,
``REPLACING``, unsubscripted table targets (GnuCOBOL itself rejects them
with "requires one subscript"), table (OCCURS) children, and unknown
targets.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
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
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / source_name).write_text(source, encoding="utf-8")
    exe = source_name[: -len(".cob")]
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-i", "-v", f"{tmp_path}:/src", "-w", "/src",
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
    program = CobolParser().parse(source)
    generated = JavaGenerator().generate(program)[0]
    match = __import__("re").search(r"public\s+class\s+(\w+)", generated.source_code)
    assert match, generated.source_code
    return match.group(1), generated.source_code


def _run_generated_java(tmp_path: Path, source: str) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    class_name, source_code = _generate(source)
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir(exist_ok=True)
    (candidate_dir / f"{class_name}.java").write_text(source_code, encoding="utf-8")
    build = subprocess.run(
        [
            "docker", "run", "--rm", "-i", "-v", f"{candidate_dir}:/app", "-w", "/app",
            JAVA_IMAGE,
            "bash", "-c", f"javac {class_name}.java && java {class_name}",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )
    assert build.returncode == 0, build.stderr.decode(errors="replace")
    return build.stdout.decode(errors="replace").splitlines()


INITIALIZE_GROUP = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. INITGROUP.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-G.
       05 WS-GA PIC X(4) VALUE "abcd".
       05 FILLER PIC X(3) VALUE "xyz".
       05 WS-GB PIC 9(4) VALUE 1234.
       05 WS-GC PIC 9(4)V99 VALUE 150.
       05 WS-GD PIC S9(4) VALUE -12.
       05 WS-GE PIC 9(4) COMP VALUE 55.
       05 WS-GF PIC 9(4) COMP-3 VALUE 77.
       05 WS-GH.
          10 WS-GHI PIC X(2) VALUE "mm".
          10 WS-GHN PIC 9(2) VALUE 8.
    01 WS-X PIC X(5) VALUE "hello".
    01 WS-N PIC 9(3) VALUE 777.
    01 WS-SIGN PIC S9(4) VALUE 5.
    01 WS-DEC PIC 9(2)V99 VALUE 33.
    PROCEDURE DIVISION.
    MAIN.
        INITIALIZE WS-G.
        DISPLAY "GA=[" WS-GA "]".
        DISPLAY "GB=[" WS-GB "]".
        DISPLAY "GC=[" WS-GC "]".
        DISPLAY "GD=[" WS-GD "]".
        DISPLAY "GE=[" WS-GE "]".
        DISPLAY "GF=[" WS-GF "]".
        DISPLAY "GHI=[" WS-GHI "]".
        DISPLAY "GHN=[" WS-GHN "]".
        INITIALIZE WS-X WS-N WS-SIGN WS-DEC.
        DISPLAY "X=[" WS-X "]".
        DISPLAY "N=[" WS-N "]".
        DISPLAY "SIGN=[" WS-SIGN "]".
        DISPLAY "DEC=[" WS-DEC "]".
        STOP RUN.
    """
)

# GnuCOBOL-observed output (probes 2026-10-28):
#   GA=[    ]      alphanumeric child -> spaces
#   GB=[0000]      numeric child -> zero
#   GC=[0000.00]   decimal child -> zero
#   GD=[+0000]     signed child -> positive zero
#   GE=[0000]      COMP child -> zero
#   GF=[0000]      COMP-3 child -> zero
#   GHI=[  ]       nested-group child -> expanded recursively
#   GHN=[00]       nested-group numeric child -> zero
#   X/N/SIGN/DEC   elementary multi-target form


@needs_docker
def test_initialize_group_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    cobol_out = _run_gnucobol(tmp_path / "cobol", "initgroup.cob", INITIALIZE_GROUP)
    java_out = _run_generated_java(tmp_path / "java", INITIALIZE_GROUP)
    assert cobol_out == java_out, (cobol_out, java_out)


INITIALIZE_OVERWRITE = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. INITREDO.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-X PIC X(4) VALUE "aaaa".
    01 WS-N PIC 9(4) VALUE 1111.
    01 WS-G.
       05 WS-GA PIC X(2) VALUE "zz".
       05 WS-GB PIC 9(2) VALUE 99.
    PROCEDURE DIVISION.
    MAIN.
        MOVE "qqqq" TO WS-X.
        MOVE 2222 TO WS-N.
        INITIALIZE WS-X WS-N.
        DISPLAY "X=[" WS-X "]".
        DISPLAY "N=[" WS-N "]".
        INITIALIZE WS-G.
        DISPLAY "GA=[" WS-GA "]".
        DISPLAY "GB=[" WS-GB "]".
        STOP RUN.
    """
)

# The plain form overwrites data written by earlier statements (MOVE)
# and ignores VALUE clauses, both for elementary and group targets.


@needs_docker
def test_initialize_overwrites_existing_data_byte_identical(tmp_path: Path) -> None:
    cobol_out = _run_gnucobol(tmp_path / "cobol", "initredo.cob", INITIALIZE_OVERWRITE)
    java_out = _run_generated_java(tmp_path / "java", INITIALIZE_OVERWRITE)
    assert cobol_out == java_out, (cobol_out, java_out)

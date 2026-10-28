"""GnuCOBOL oracle differential proof for ACCEPT (certified stdin subset).

Proves, against a real GnuCOBOL 3.1.2 compiler and the eclipse-temurin JDK
image, that the deterministic ACCEPT lowering reproduces the oracle's stdout
byte for byte for the certified subset:

- Statement forms: ``ACCEPT <field>`` and ``ACCEPT <field> FROM
  CONSOLE|STDIN|SYSIN`` (all read one whole line from standard input,
  sequentially).  Every other FROM device (DATE/TIME/DAY/COMMAND-LINE/...)
  fails closed.
- Alphanumeric target ``PIC X(n)``: the first n characters of the line,
  space-padded when shorter; EOF acts as an empty line (n spaces).
- Unsigned numeric-display integer target ``PIC 9(n)`` (no S, no V,
  n <= 18): the GnuCOBOL alphanumeric-to-numeric move of the first n
  bytes — spaces removed, one leading or trailing sign tolerated (ignored
  for PIC 9), every remaining character a digit, anything else yields
  zero; EOF yields zero.  Signed/decimal/non-DISPLAY targets fail closed.

Every input line below was first observed directly against the GnuCOBOL
oracle; the Java side must match it exactly.
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


def _run_gnucobol(
    tmp_path: Path, source_name: str, source: str, stdin_text: str
) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / source_name).write_text(source, encoding="utf-8")
    exe = source_name[: -len(".cob")]
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-i", "-v", f"{tmp_path}:/src", "-w", "/src",
            GNUCobol_IMAGE,
            "bash", "-c", f"cobc -free -x -o {exe} {source_name} && ./{exe}",
        ],
        input=stdin_text.encode("utf-8"),
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


def _run_generated_java(
    tmp_path: Path, source: str, stdin_text: str
) -> list[str]:
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
        input=stdin_text.encode("utf-8"),
        capture_output=True,
        timeout=240,
        check=False,
    )
    assert build.returncode == 0, build.stderr.decode(errors="replace")
    return build.stdout.decode(errors="replace").splitlines()


ACCEPT_MIXED = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. ACCEPTMIX.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-ALPHA PIC X(10).
    01 WS-NUM PIC 9(4).
    01 WS-NUM2 PIC 9(4).
    PROCEDURE DIVISION.
    MAIN.
        ACCEPT WS-ALPHA.
        DISPLAY "A=[" WS-ALPHA "]".
        ACCEPT WS-NUM.
        DISPLAY "N=[" WS-NUM "]".
        ACCEPT WS-ALPHA.
        DISPLAY "B=[" WS-ALPHA "]".
        ACCEPT WS-NUM2.
        DISPLAY "M=[" WS-NUM2 "]".
        ACCEPT WS-ALPHA.
        DISPLAY "E=[" WS-ALPHA "]".
        STOP RUN.
    """
)

# Sequential reads (shared reader), padding, truncation to field width,
# numeric parse, and EOF: empty line -> spaces (X) / zero (9).
ACCEPT_MIXED_STDIN = "hello\n1234\nthis is a very long line\n12\n"


@needs_docker
def test_accept_mixed_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    cobol_out = _run_gnucobol(
        tmp_path / "cobol", "acceptmix.cob", ACCEPT_MIXED, ACCEPT_MIXED_STDIN
    )
    java_out = _run_generated_java(tmp_path / "java", ACCEPT_MIXED, ACCEPT_MIXED_STDIN)
    assert cobol_out == java_out, (cobol_out, java_out)


ACCEPT_NUMERIC_MATRIX = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. ACCEPTNUM.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-N1 PIC 9(4).
    01 WS-N2 PIC 9(4).
    01 WS-N3 PIC 9(4).
    01 WS-N4 PIC 9(4).
    01 WS-N5 PIC 9(4).
    01 WS-N6 PIC 9(4).
    01 WS-N7 PIC 9(4).
    01 WS-N8 PIC 9(4).
    01 WS-N9 PIC 9(4).
    01 WS-N10 PIC 9(4).
    01 WS-N11 PIC 9(4).
    01 WS-N12 PIC 9(4).
    01 WS-N13 PIC 9(4).
    01 WS-N14 PIC 9(4).
    01 WS-N15 PIC 9(4).
    01 WS-N16 PIC 9(4).
    PROCEDURE DIVISION.
    MAIN.
        ACCEPT WS-N1.
        DISPLAY "01=[" WS-N1 "]".
        ACCEPT WS-N2.
        DISPLAY "02=[" WS-N2 "]".
        ACCEPT WS-N3.
        DISPLAY "03=[" WS-N3 "]".
        ACCEPT WS-N4.
        DISPLAY "04=[" WS-N4 "]".
        ACCEPT WS-N5.
        DISPLAY "05=[" WS-N5 "]".
        ACCEPT WS-N6.
        DISPLAY "06=[" WS-N6 "]".
        ACCEPT WS-N7.
        DISPLAY "07=[" WS-N7 "]".
        ACCEPT WS-N8.
        DISPLAY "08=[" WS-N8 "]".
        ACCEPT WS-N9.
        DISPLAY "09=[" WS-N9 "]".
        ACCEPT WS-N10.
        DISPLAY "10=[" WS-N10 "]".
        ACCEPT WS-N11.
        DISPLAY "11=[" WS-N11 "]".
        ACCEPT WS-N12.
        DISPLAY "12=[" WS-N12 "]".
        ACCEPT WS-N13.
        DISPLAY "13=[" WS-N13 "]".
        ACCEPT WS-N14.
        DISPLAY "14=[" WS-N14 "]".
        ACCEPT WS-N15.
        DISPLAY "15=[" WS-N15 "]".
        ACCEPT WS-N16.
        DISPLAY "16=[" WS-N16 "]".
        STOP RUN.
    """
)

# The full GnuCOBOL-observed conversion matrix for unsigned PIC 9(4):
#   01 "1234"     -> 1234   all digits
#   02 "abcd"     -> 0000   letters are invalid
#   03 "0012abc"  -> 0012   first-4-bytes window drops the tail
#   04 "1a2"      -> 0000   embedded letter is invalid
#   05 " 12 "     -> 0012   spaces removed
#   06 "-12"      -> 0012   leading sign ignored for PIC 9
#   07 "+12"      -> 0012   leading plus ignored
#   08 "12345"    -> 1234   first 4 bytes, not value mod 10000
#   09 " 12345 "  -> 0123   window taken before space removal
#   10 "12-"      -> 0012   trailing sign ignored
#   11 "1 2"      -> 0012   internal space removed
#   12 "--12"     -> 0000   two signs invalid
#   13 "1-2"      -> 0000   mid-string sign invalid
#   14 "  "       -> 0000   nothing left after space removal
#   15 "12- "     -> 0012   trailing sign after space removal
#   16 "9 9"      -> 0099   internal space removed
ACCEPT_NUMERIC_STDIN = (
    "1234\nabcd\n0012abc\n1a2\n 12 \n-12\n+12\n12345\n"
    " 12345 \n12-\n1 2\n--12\n1-2\n  \n12- \n9 9\n"
)


@needs_docker
def test_accept_numeric_conversion_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    cobol_out = _run_gnucobol(
        tmp_path / "cobol", "acceptnum.cob", ACCEPT_NUMERIC_MATRIX, ACCEPT_NUMERIC_STDIN
    )
    java_out = _run_generated_java(
        tmp_path / "java", ACCEPT_NUMERIC_MATRIX, ACCEPT_NUMERIC_STDIN
    )
    assert cobol_out == java_out, (cobol_out, java_out)


ACCEPT_LONG_NUMERIC = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. ACCEPTBIG.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-BIG PIC 9(12).
    01 WS-BIG2 PIC 9(12).
    PROCEDURE DIVISION.
    MAIN.
        ACCEPT WS-BIG.
        DISPLAY "B=[" WS-BIG "]".
        ACCEPT WS-BIG2.
        DISPLAY "C=[" WS-BIG2 "]".
        STOP RUN.
    """
)

# long-typed field (12 digits > 9): full-width digits and a short value.
ACCEPT_LONG_STDIN = "999999999999\n123\n"


@needs_docker
def test_accept_long_numeric_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    cobol_out = _run_gnucobol(
        tmp_path / "cobol", "acceptbig.cob", ACCEPT_LONG_NUMERIC, ACCEPT_LONG_STDIN
    )
    java_out = _run_generated_java(
        tmp_path / "java", ACCEPT_LONG_NUMERIC, ACCEPT_LONG_STDIN
    )
    assert cobol_out == java_out, (cobol_out, java_out)


ACCEPT_FROM_DEVICES = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. ACCEPTDEV.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-F PIC X(4).
    PROCEDURE DIVISION.
    MAIN.
        ACCEPT WS-F FROM CONSOLE.
        DISPLAY "C=[" WS-F "]".
        ACCEPT WS-F FROM STDIN.
        DISPLAY "S=[" WS-F "]".
        ACCEPT WS-F FROM SYSIN.
        DISPLAY "Y=[" WS-F "]".
        STOP RUN.
    """
)

ACCEPT_FROM_STDIN = "aa\nbb\ncc\n"


@needs_docker
def test_accept_from_device_forms_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    cobol_out = _run_gnucobol(
        tmp_path / "cobol", "acceptdev.cob", ACCEPT_FROM_DEVICES, ACCEPT_FROM_STDIN
    )
    java_out = _run_generated_java(
        tmp_path / "java", ACCEPT_FROM_DEVICES, ACCEPT_FROM_STDIN
    )
    assert cobol_out == java_out, (cobol_out, java_out)

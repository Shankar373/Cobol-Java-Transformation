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
  zero; EOF yields zero.  (Superseded by the libcob move rule below,
  which also covers unsigned decimal ``PIC 9(i)V9(s)`` targets.)
  Signed/non-DISPLAY targets fail closed.

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


# ---------------------------------------------------------------------------
# Unsigned decimal targets PIC 9(i)V9(s) and the shared conversion rule
# ---------------------------------------------------------------------------
#
# GnuCOBOL 3.1.2 moves the first i+s bytes of the line into the field with
# its alphanumeric-to-numeric-display move: leading white space and one
# sign skipped, integer digits right-aligned (excess high-order digits
# dropped), white space and ',' ignored, the first '.' starts the decimals,
# and a bad character or second '.' met before the field is full zeroes the
# whole field (CobolStdin.digits).  Every case below was observed on the
# oracle first; the earlier integer rule disagreed with it on the
# INTEGER_REGRESSION_CASES (e.g. "1.5" is 0001, not 0000).


def _accept_matrix_program(program_id: str, pics: list[str]) -> str:
    """One ``ACCEPT`` + ``DISPLAY`` per PIC, in order (free format)."""
    lines = [
        "IDENTIFICATION DIVISION.",
        f"PROGRAM-ID. {program_id}.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        *(f"01 WS-F{i:03d} PIC {pic}." for i, pic in enumerate(pics, 1)),
        "PROCEDURE DIVISION.",
        "MAIN.",
    ]
    for i in range(1, len(pics) + 1):
        lines.append(f"    ACCEPT WS-F{i:03d}.")
        lines.append(f'    DISPLAY "{i:03d}=[" WS-F{i:03d} "]".')
    lines.append("    STOP RUN.")
    return "\n".join(lines) + "\n"


DECIMAL_CASES = [("9(7)V99", s) for s in (
    "50000", "50000.50", "50000.5", ".5", "0.25", "1234567.89", "12345678",
    "1234567.891", "123.45.6", "abc", "", "  42.5  ", "-12.34", "12.34-",
    "+7.1", "1,5", "12a", "9999999.99", "123456789012", "5.", "5 . 5",
    "000000001", "1.2345", "  .  ", "0", "12345.6789", "1234567890",
    "12345678.9", "1e3", "  1234567.89 ", "12.3+", "+.5", "1.-", "..",
    "00050000.5", "1 000.5", "1.2.3", "1.2.", "1..2", ".5.", "12.3-", "12.-",
    "-.5", "-1.", "1.5 -", "- 1.5", "+ 1.5", "1,5.5", ",5", "5,", "1.5,2",
    "1.5a", "a1.5", "1.5e", "12+", "-12+", "1.2 3", "00.00", ".00", "1. 5",
    "1.5-", "1.5 +", "1,000.5", "1..", "1.5.", ".", "-", "+", "-.", "1.2345-",
    "12345678.-", "1234567.8-", "1.5+", "+1.5", "1.5 ", " 1.5", "1.,5",
    "1,.5", "12.34.56", "1.2a", "1.23a", "1.234a", "1234567.8a", "12345678a",
    "1.5--", "1.5-+", ".-", "5-.", "0.5-", "1.2-3", "1-.5", "1.5CR", "1.5DB",
    "\t1.5", "a12345678", "1a2345678",
)] + [("9(3)V99", s) for s in (
    "123.45", "1234.5", "12.345", "99999", "1.5", "123456", "12.3456",
)] + [("9V9(3)", s) for s in ("1.234", "12.3", "1.23456", ".1234")] + [
    ("9(4)V9", s) for s in ("1234.5", "12345.6")
]

INTEGER_REGRESSION_CASES = [("9(4)", s) for s in (
    "12+", "+12+", "-12-", "1,2", ",12", "1.5", "12.", ".5", "1..2", "1.2.3",
    "12 +", "1+", "+", "-", "12-3",
)]


def _differential(tmp_path: Path, program_id: str, cases: list[tuple[str, str]]) -> None:
    source = _accept_matrix_program(program_id, [pic for pic, _ in cases])
    stdin_text = "".join(line + "\n" for _, line in cases)
    name = f"{program_id.lower()}.cob"
    cobol_out = _run_gnucobol(tmp_path / "cobol", name, source, stdin_text)
    java_out = _run_generated_java(tmp_path / "java", source, stdin_text)
    assert len(cobol_out) == len(cases), cobol_out
    mismatches = [
        (pic, line, c, j)
        for (pic, line), c, j in zip(cases, cobol_out, java_out)
        if c != j
    ]
    assert not mismatches and len(java_out) == len(cobol_out), mismatches


@needs_docker
def test_accept_decimal_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    _differential(tmp_path, "ACCEPTDEC", DECIMAL_CASES)


@needs_docker
def test_accept_integer_regressions_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    _differential(tmp_path, "ACCEPTREG", INTEGER_REGRESSION_CASES)


def _fuzz_cases(count: int = 240) -> list[tuple[str, str]]:
    """Seeded (deterministic) lines over the characters the rule treats
    specially, cycled across integer and decimal field shapes."""
    import random

    rng = random.Random(20261103)
    alphabet = "0123456789" * 3 + "  ..,,+-a\t"
    pics = ["9(4)", "9(7)V99", "9(3)V99", "9V9(3)", "9(12)", "9(2)V9(4)"]
    return [
        (pics[i % len(pics)],
         "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 14))))
        for i in range(count)
    ]


@needs_docker
def test_accept_seeded_fuzz_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    _differential(tmp_path, "ACCEPTFZ", _fuzz_cases())

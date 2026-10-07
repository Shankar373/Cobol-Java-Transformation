"""GnuCOBOL oracle differential proof for numeric VALUE semantics.

Proves against a real GnuCOBOL (3.1.2) compiler that the deterministic
numeric contract (engine/transformation/numeric_semantics.py) recovers the
same *stored value* and the same integer DISPLAY output:

1. VALUE literal normalization: for each declared item the value recovered
   from a GnuCOBOL DISPLAY equals the pipeline-normalized literal
   (no octal ambiguity, fractional truncation not rounding, least-significant
   digits kept on overflow).
2. End-to-end integer lane: a generated Java program (compiled with the
   eclipse-temurin JDK image) produces byte-identical stdout to the same
   program compiled with GnuCOBOL.

Both lanes are Docker-gated and skipped when the images are unavailable, so
the deterministic unit contract in test_numeric_semantics.py always runs.
"""

import re
import subprocess
import textwrap
from decimal import Decimal

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_pic_to_java_default
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

_DISPLAY_PROGRAM = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. NUMPRF.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 INT-A PIC 9(3)  VALUE 007.
    01 INT-B PIC 9(3)  VALUE 009.
    01 INT-C PIC 9(3)  VALUE 1234.
    01 INT-E PIC S9(4) VALUE -12.
    01 DEC-A PIC 9(2)V99  VALUE 1.234.
    01 DEC-B PIC S9(3)V99 VALUE -1.239.
    01 DEC-C PIC 9(6)V99  VALUE 000123.4.
    PROCEDURE DIVISION.
    MAIN.
        DISPLAY INT-A.
        DISPLAY INT-B.
        DISPLAY INT-C.
        DISPLAY INT-E.
        DISPLAY DEC-A.
        DISPLAY DEC-B.
        DISPLAY DEC-C.
        STOP RUN.
    """
)

_ADD_PROGRAM = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. NUMCMP.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 D PIC 9(3) VALUE 007.
    01 E PIC 9(3) VALUE 009.
    01 G PIC 9(3) VALUE 12.
    01 ACC PIC 9(6) VALUE ZEROS.
    PROCEDURE DIVISION.
    MAIN.
        ADD D TO ACC.
        ADD E TO ACC.
        ADD G TO ACC.
        DISPLAY ACC.
        STOP RUN.
    """
)


@needs_docker
def test_oracle_recovered_values_match_normalized_literals(tmp_path):
    (tmp_path / "numeric_proof.cob").write_text(_DISPLAY_PROGRAM, encoding="utf-8")
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-v", f"{tmp_path}:/src", "-w", "/src",
            GNUCobol_IMAGE,
            "bash", "-c", "cobc -free -x -o prog numeric_proof.cob && ./prog",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    oracle_lines = result.stdout.decode(errors="replace").splitlines()
    assert len(oracle_lines) == 7

    program = CobolParser().parse(_DISPLAY_PROGRAM)
    items = {item.name: item for item in program.working_storage}

    def _value_from_display(line: str) -> Decimal:
        # Decimal() preserves numeric value across leading zeros and sign.
        return Decimal(line.strip())

    expected_by_line = [
        ("INT-A", "7"),
        ("INT-B", "9"),
        ("INT-C", "234"),
        ("INT-E", "-12"),
        ("DEC-A", "1.23"),
        ("DEC-B", "-1.23"),
        ("DEC-C", "123.40"),
    ]

    for i, (line, (name, normalized)) in enumerate(
        zip(oracle_lines, expected_by_line)
    ):
        assert _value_from_display(line) == Decimal(normalized)
        item = items[name]
        assert map_pic_to_java_default(item) == normalized
        # Java-literal safety: normalized text must not be octal-ambiguous.
        assert not re.match(r"^0[0-9]+", normalized)


@needs_docker
def test_integer_lane_oracle_vs_generated_java_stdout(tmp_path):
    (tmp_path / "numeric_add.cob").write_text(_ADD_PROGRAM, encoding="utf-8")
    oracle = subprocess.run(
        [
            "docker", "run", "--rm", "-v", f"{tmp_path}:/src", "-w", "/src",
            GNUCobol_IMAGE,
            "bash", "-c",
            "cobc -free -x -o numeric_add numeric_add.cob && ./numeric_add",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )
    assert oracle.returncode == 0, oracle.stderr.decode(errors="replace")
    oracle_stdout = oracle.stdout.decode(errors="replace").strip()
    assert oracle_stdout == "000028", oracle_stdout

    program = CobolParser().parse(_ADD_PROGRAM)
    generated = JavaGenerator().generate(program)[0]
    class_match = re.search(r"public\s+class\s+(\w+)", generated.source_code)
    assert class_match
    class_name = class_match.group(1)

    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir(exist_ok=True)
    (candidate_dir / f"{class_name}.java").write_text(
        generated.source_code, encoding="utf-8"
    )
    build = subprocess.run(
        [
            "docker", "run", "--rm", "-v", f"{candidate_dir}:/app", "-w", "/app",
            JAVA_IMAGE,
            "bash", "-c", f"javac {class_name}.java && java {class_name}",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )
    assert build.returncode == 0, build.stderr.decode(errors="replace")
    java_stdout = build.stdout.decode(errors="replace").strip()
    # Byte-identical stdout: the integer VALUE/DISPLAY lane matches GnuCOBOL.
    assert java_stdout == oracle_stdout
    assert java_stdout == "000028"
"""GnuCOBOL oracle differential proof for UNSTRING (certified subset).

Proves, against a real GnuCOBOL 3.1.2 compiler and the eclipse-temurin JDK
image, that the deterministic UNSTRING lowering reproduces the oracle's
stdout byte for byte for the certified delimited subset (single literal
delimiter, no pointer/overflow/varying/tallying/ALL/multiple-delimiter
clauses).
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
    program = CobolParser().parse(source)
    generated = JavaGenerator().generate(program)[0]
    match = __import__("re").search(r"public\s+class\s+(\w+)", generated.source_code)
    assert match, generated.source_code
    return match.group(1), generated.source_code


def _run_generated_java(tmp_path: Path, source: str) -> list[str]:
    import re
    tmp_path.mkdir(parents=True, exist_ok=True)
    class_name, source_code = _generate(source)
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir(exist_ok=True)
    (candidate_dir / f"{class_name}.java").write_text(source_code, encoding="utf-8")
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
    return build.stdout.decode(errors="replace").splitlines()


UNSTRING_BASIC = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. UNSTRTEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-SRC PIC X(20) VALUE 'A|B|C'.
    01 WS-A PIC X(5).
    01 WS-B PIC X(5).
    01 WS-C PIC X(5).
    PROCEDURE DIVISION.
    MAIN.
        UNSTRING WS-SRC DELIMITED BY '|' INTO WS-A WS-B WS-C.
        DISPLAY WS-A.
        DISPLAY WS-B.
        DISPLAY WS-C.
        STOP RUN.
    """
)


@needs_docker
def test_unstring_certified_subset_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    cobol_out = _run_gnucobol(tmp_path / "cobol", "unstr.cob", UNSTRING_BASIC)
    java_out = _run_generated_java(tmp_path / "java", UNSTRING_BASIC)
    assert cobol_out == java_out, (cobol_out, java_out)
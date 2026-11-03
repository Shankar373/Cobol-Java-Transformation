"""STRING of numeric items and LINE SEQUENTIAL WRITE (oracle-pinned).

Found by the Phase 2 end-to-end run (payroll fixture), where the generated
report files differed from GnuCOBOL 3.1.2:

* STRING copied a numeric sending item's Java number (``3``, ``600``)
  instead of its stored digits (``03``, ``00600``; ``PIC 9V99`` 1.25 is
  ``125`` — no decimal point);
* WRITE to a LINE SEQUENTIAL file kept the record's trailing spaces, which
  GnuCOBOL removes (an all-space record becomes an empty line).

Record SEQUENTIAL files (fixed-length records, no line terminator) are not
reproduced by the generated file runtime and fail closed.  The pins below
are GnuCOBOL output; the Docker lane re-derives them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.producer import TransformationProducer

ORACLE_IMAGE = "gnucobol-ocesql:latest"

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO "LS.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-REC PIC X(30).
       WORKING-STORAGE SECTION.
       01 WS-Y PIC 99 VALUE 3.
       01 WS-B PIC 9(5) VALUE 600.
       01 WS-P PIC 9V99 VALUE 1.25.
       01 WS-N PIC X(6) VALUE 'AL'.
       01 WS-L PIC X(30).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE SPACES TO WS-L
           STRING WS-N DELIMITED BY SPACE '|' DELIMITED BY SIZE
               WS-Y DELIMITED BY SIZE '|' DELIMITED BY SIZE
               WS-B DELIMITED BY SIZE '|' DELIMITED BY SIZE
               WS-P DELIMITED BY SIZE
               INTO WS-L
           END-STRING
           DISPLAY '[' WS-L ']'
           OPEN OUTPUT OUT-FILE
           MOVE WS-L TO OUT-REC
           WRITE OUT-REC
           MOVE SPACES TO OUT-REC
           WRITE OUT-REC
           MOVE '  LEAD' TO OUT-REC
           WRITE OUT-REC
           CLOSE OUT-FILE
           STOP RUN.
"""
EXPECTED_STDOUT = "[AL|03|00600|125               ]\n"
EXPECTED_FILE = b"AL|03|00600|125\n\n  LEAD\n"

#: The same program on a record SEQUENTIAL file (explicit, or no
#: ORGANIZATION clause): GnuCOBOL 3.1.2 writes the three 30-byte record
#: areas back to back, trailing spaces kept, no terminator.
_RECORD_SOURCES = {
    "explicit": _SOURCE.replace(
        "ORGANIZATION IS LINE SEQUENTIAL", "ORGANIZATION IS SEQUENTIAL"
    ),
    "default": _SOURCE.replace("\n               ORGANIZATION IS LINE SEQUENTIAL", ""),
}
RECORD_FILE = (
    b"AL|03|00600|125".ljust(30) + b" " * 30 + b"  LEAD".ljust(30)
)


def _transform(source: str):
    return TransformationProducer().transform(source, "PROBE")


@pytest.mark.parametrize(
    ("source", "expected_file"),
    [
        (_SOURCE, EXPECTED_FILE),
        (_RECORD_SOURCES["explicit"], RECORD_FILE),
        (_RECORD_SOURCES["default"], RECORD_FILE),
    ],
    ids=["line-sequential", "record-sequential", "no-organization"],
)
def test_generated_java_matches_oracle(tmp_path: Path, source: str, expected_file: bytes) -> None:
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    result = _transform(source)
    assert result.success is True, result.errors
    for generated in result.generated_files:
        (tmp_path / generated.filename).write_text(generated.source_code, encoding="utf-8")
    compiled = subprocess.run(
        ["javac", "-nowarn", "-d", str(tmp_path),
         *[str(tmp_path / g.filename) for g in result.generated_files]],
        capture_output=True, timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    run = subprocess.run(
        ["java", "-Dline.separator=\n", "-cp", str(tmp_path),
         result.generated_files[0].class_name],
        capture_output=True, timeout=60, cwd=tmp_path,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == EXPECTED_STDOUT
    assert (tmp_path / "LS.TXT").read_bytes() == expected_file


@pytest.mark.parametrize("variant", sorted(_RECORD_SOURCES))
def test_record_sequential_file_is_lowered(variant: str) -> None:
    """Record SEQUENTIAL is certified since Phase 3 increment 6 (it failed
    closed before); variable-length forms still fail closed
    (``tests/test_record_sequential_files.py``)."""
    result = _transform(_RECORD_SOURCES[variant])
    assert result.success is True, result.errors
    assert "CobolFileIo.writeRecord(" in result.generated_files[0].source_code


#: A signed STRING sender contributes its stored characters: -3 in PIC S99
#: is ``0s`` (last digit overpunched, GnuCOBOL 3.1.2) — refused before
#: Phase 3 increment 10 (tests/test_signed_storage_text.py).
_SIGNED_SOURCE = _SOURCE.replace("01 WS-Y PIC 99 VALUE 3.", "01 WS-Y PIC S99 VALUE -3.")
_SIGNED_STDOUT = "[AL|0s|00600|125               ]\n"


def test_signed_numeric_string_source_stores_overpunched_digit(tmp_path: Path) -> None:
    from tests.oracle_java_helpers import run_generated_java

    assert run_generated_java(_SIGNED_SOURCE, "PROBE", tmp_path) == _SIGNED_STDOUT


def test_signed_numeric_string_source_oracle_pin(tmp_path: Path) -> None:
    from tests.oracle_java_helpers import run_gnucobol

    assert run_gnucobol(_SIGNED_SOURCE, "PROBE", tmp_path) == _SIGNED_STDOUT


def test_comp_numeric_string_source_fails_closed() -> None:
    source = _SOURCE.replace("01 WS-Y PIC 99 VALUE 3.", "01 WS-Y PIC 99 COMP VALUE 3.")
    result = _transform(source)
    assert result.success is False


def test_oracle_pins_match_gnucobol(tmp_path: Path) -> None:
    """Docker lane: stdout and the written file are GnuCOBOL's."""
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    (tmp_path / "P.cob").write_text(_SOURCE, encoding="utf-8", newline="\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    os.chmod(run_dir, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none",
         "-v", f"{tmp_path}:/src", ORACLE_IMAGE, "sh", "-c",
         "cobc -x /src/P.cob -o /tmp/p && cd /src/run && /tmp/p"],
        capture_output=True, timeout=180,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == EXPECTED_STDOUT
    assert (run_dir / "LS.TXT").read_bytes() == EXPECTED_FILE

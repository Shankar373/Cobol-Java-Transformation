"""Doubled-quote escapes inside literals (Phase 3, oracle-pinned).

COBOL writes a quote inside a literal by doubling it: ``'IT''S'`` is
``IT'S``, and the same holds for doubled double quotes.  The generated Java used to
print ``ITS`` / ``A Q B`` for DISPLAY literals and keep ``IT''S`` doubled in
VALUE and MOVE — silently wrong output with a successful transformation.

The source text is now read in a canonical spelling: such a literal is
re-delimited with the other quote character (same value).  A literal whose
value holds both quote characters fails closed.  The pin is GnuCOBOL 3.1.2
output; the Docker lane re-derives it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.producer import TransformationProducer
from engine.transformation.source_format import compiler_visible_text

ORACLE_IMAGE = "gnucobol-ocesql:latest"

_SOURCE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. PROBE.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-A PIC X(12) VALUE 'IT''S'.\n"
    '       01 WS-B PIC X(12) VALUE "SAY ""HI""".\n'
    "       01 WS-C PIC X(12) VALUE 'A\"B'.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    "           DISPLAY 'IT''S' '|' WS-A '|'.\n"
    '           DISPLAY "A ""Q"" B" \'|\' WS-B \'|\' WS-C \'|\'.\n'
    "           MOVE 'DON''T' TO WS-A.\n"
    "           DISPLAY WS-A '|'.\n"
    "           IF WS-A = 'DON''T' DISPLAY 'EQ' END-IF.\n"
    "           STOP RUN.\n"
)
EXPECTED_STDOUT = (
    "IT'S|IT'S        |\n"
    'A "Q" B|SAY "HI"    |A"B         |\n'
    "DON'T       |\n"
    "EQ\n"
)


def _transform(source: str):
    return TransformationProducer().transform(source, "PROBE")


def test_doubled_quotes_are_re_delimited() -> None:
    text = compiler_visible_text(_SOURCE)
    assert "VALUE \"IT'S\"." in text
    assert "VALUE 'SAY \"HI\"'." in text
    assert "DISPLAY 'A \"Q\" B'" in text
    assert "VALUE 'A\"B'." in text  # no escape: left as written


def test_comment_lines_are_left_alone() -> None:
    comment = "      * DON''T TOUCH 'THIS''\n"
    assert compiler_visible_text(comment + _SOURCE).startswith(comment)


def test_generated_java_matches_oracle(tmp_path: Path) -> None:
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    result = _transform(_SOURCE)
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


def test_literal_with_both_quote_characters_fails_closed() -> None:
    source = _SOURCE.replace("VALUE 'A\"B'.", "VALUE 'A\"B''C'.")
    result = _transform(source)
    assert result.success is False
    assert any("both quote characters" in e for e in result.errors), result.errors


def test_oracle_pins_match_gnucobol(tmp_path: Path) -> None:
    """Docker lane: the pinned stdout is GnuCOBOL's."""
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    (tmp_path / "P.cob").write_text(_SOURCE, encoding="utf-8", newline="\n")
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none",
         "-v", f"{tmp_path}:/src", ORACLE_IMAGE, "sh", "-c",
         "cobc -x /src/P.cob -o /tmp/p && /tmp/p"],
        capture_output=True, timeout=180,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert run.stdout.decode() == EXPECTED_STDOUT

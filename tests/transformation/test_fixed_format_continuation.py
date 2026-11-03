"""Fixed-format continuation lines (``-`` in column 7), oracle-pinned.

Phase 3 coverage, and audit P0-2: a continuation line used to be read as
ordinary code, so ``VALUE 'ABCDEFGHIJ`` continued by ``-    'KLMNOP'.``
became the value ``"ABCDEFGHIJ -    "`` with no diagnostic.

GnuCOBOL 3.1.2 rules, as observed below:

* an alphanumeric literal still open at the end of a line runs through
  column 72 (trailing spaces are part of it); the continuation line resumes
  the literal after its first quote character;
* any other continued text (a data name, a numeric literal) joins the next
  line's first non-blank character with no space in between;
* a continuation may itself be continued.

The pins are GnuCOBOL output; the Docker lane re-derives them.
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

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(70) VALUE 'ABCDEFGHIJ
      -    'KLMNOP'.
       01 WS-ALPHA PIC X(5) VALUE "WORD!".
       01 WS-B PIC X(80).
       01 WS-N PIC 9(6) VALUE 123
      -    456.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY '[' WS-A ']'.
           MOVE WS-AL
      -    PHA TO WS-B.
           DISPLAY '[' WS-B ']'.
           DISPLAY 'IT''S A LONG LITERAL THAT IS CONTINUED ON THE NEXT
      -    'LINE AND ''QUOTED'' ' WS-N.
           MOVE "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVE
      -    "N TWELVE THIRTEEN FOURTEEN FIFTEEN SIXTEEN SEVENTEEN EIGHTE
      -    "EN" TO WS-B.
           DISPLAY '[' WS-B ']'.
           STOP RUN.
"""

EXPECTED_STDOUT = (
    "[ABCDEFGHIJ                              KLMNOP                        ]\n"
    "[WORD!                                                                           ]\n"
    "IT'S A LONG LITERAL THAT IS CONTINUED ON THE NEXT  LINE AND 'QUOTED' 123456\n"
    "[ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVE N TWELVE THIRTEEN FOURTEE]\n"
)


def _transform(source: str):
    return TransformationProducer().transform(source, "PROBE")


class TestSourceText:
    """The compiler-visible text joins continued lines (line count kept)."""

    def test_literal_runs_to_column_72(self) -> None:
        text = compiler_visible_text(_SOURCE)
        assert "VALUE 'ABCDEFGHIJ" + " " * 30 + "KLMNOP'." in text

    def test_word_and_numeric_join_without_space(self) -> None:
        text = compiler_visible_text(_SOURCE)
        assert "MOVE WS-ALPHA TO WS-B." in text
        assert "VALUE 123456." in text

    def test_line_numbers_are_preserved(self) -> None:
        assert compiler_visible_text(_SOURCE).count("\n") == _SOURCE.count("\n")

    def test_free_format_is_untouched(self) -> None:
        free = "IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\n-  odd line\n"
        assert compiler_visible_text(free) == free


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


def test_open_literal_not_resumed_by_a_quote_fails_closed() -> None:
    source = _SOURCE.replace("      -    'KLMNOP'.", "      -    KLMNOP'.")
    result = _transform(source)
    assert result.success is False
    assert any("continuation" in e for e in result.errors), result.errors


def test_continuation_with_nothing_to_continue_fails_closed() -> None:
    result = _transform("      -    'ORPHAN'.\n" + _SOURCE)
    assert result.success is False
    assert any("nothing to continue" in e for e in result.errors), result.errors


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


def test_discovery_reads_continued_and_escaped_literals_as_data() -> None:
    # Pairing quotes on the raw text loses track after a continued literal
    # (its first line has no closing quote) or a doubled quote, and literal
    # text such as "CALL YOUR" was then scanned as a CALL statement.
    from engine.transformation.application_discovery import ApplicationDiscovery

    source = (
        "       01 WS-H PIC X(30) VALUE 'ABC\n"
        "      -    'DEF'.\n"
        "       01 WS-M PIC X(30) VALUE 'PLEASE CALL YOUR DESK'.\n"
        "       PROCEDURE DIVISION.\n"
        "           CALL 'REAL-TARGET'.\n"
    )
    calls = ApplicationDiscovery()._extract_calls(source, "PROBE")
    assert [c.target for c in calls] == ["REAL-TARGET"]

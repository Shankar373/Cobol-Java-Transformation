"""Record SEQUENTIAL files, WRITE … FROM, OPEN EXTEND (Phase 3, increment 6).

ORGANIZATION SEQUENTIAL — explicit, or the default when a SELECT has no
ORGANIZATION clause — is the everyday batch file.  GnuCOBOL 3.1.2 writes a
file with one fixed-length record description as the bare record areas,
back to back: no terminator, trailing spaces kept.  With several record
descriptions of different lengths it switches to variable records, each
behind a 4-byte header (2-byte big-endian length, 2 zero bytes) — not
reproduced, so that fails closed, as do RECORD VARYING / CONTAINS n TO m,
RECORDING MODE, LINAGE, OPEN I-O, REWRITE, DELETE, START and any record
layout the group views do not certify (signed/scaled/COMP fields, FILLER,
OCCURS, REDEFINES).  These files used to fail closed altogether.

Found on the way and fixed (every organization):

* ``WRITE r FROM x`` wrote the record's previous fields; it is MOVE x TO r
  then WRITE r.  Into a group record the move copies x's stored bytes, so
  a signed numeric x arrives with its overpunched sign (``S9(5)`` -42 is
  ``0004r``) — reproduced only for unsigned DISPLAY integers;
* ``WRITE … AFTER/BEFORE [ADVANCING]`` and ``END-OF-PAGE`` were dropped
  without a diagnostic; they fail closed;
* OPEN EXTEND of a sequential file appends exactly as GnuCOBOL does and is
  no longer classified PARTIAL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.producer import TransformationProducer

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "fixtures" / "workload-record-sequential" / "cobol"
EXTRACT = (FIXTURE / "EXTRACT.cob").read_text()
ORACLE_IMAGE = "gnucobol-ocesql:latest"


def _program(program_id: str, select: str, fd: str, procedure: str, ws: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {program_id}.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        f"{select}"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        f"{fd}"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-EOF               PIC X VALUE 'N'.\n"
        f"{ws}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        f"{procedure}"
        "           STOP RUN.\n"
    )


_LINE_EXTEND = _program(
    "LEXT",
    '           SELECT L-FILE ASSIGN TO "LEXT.TXT"\n'
    "               ORGANIZATION IS LINE SEQUENTIAL\n"
    "               FILE STATUS IS WS-ST.\n",
    "       FD  L-FILE.\n"
    "       01  L-REC                PIC X(8).\n",
    "           OPEN OUTPUT L-FILE\n"
    "           MOVE 'FIRST' TO L-REC\n"
    "           WRITE L-REC\n"
    "           CLOSE L-FILE\n"
    "           OPEN EXTEND L-FILE\n"
    "           DISPLAY 'EXTEND ' WS-ST\n"
    "           MOVE 'SECOND  ' TO L-REC\n"
    "           WRITE L-REC\n"
    "           MOVE SPACES TO L-REC\n"
    "           WRITE L-REC\n"
    "           CLOSE L-FILE\n"
    "           OPEN INPUT L-FILE\n"
    "           PERFORM UNTIL WS-EOF = 'Y'\n"
    "               READ L-FILE\n"
    "                   AT END MOVE 'Y' TO WS-EOF\n"
    "                   NOT AT END DISPLAY '[' L-REC ']'\n"
    "               END-READ\n"
    "           END-PERFORM\n"
    "           CLOSE L-FILE\n",
    "       01  WS-ST                PIC XX.\n",
)

_WRITE_FROM = _program(
    "WFROM",
    '           SELECT L-FILE ASSIGN TO "WFROM.TXT"\n'
    "               ORGANIZATION IS LINE SEQUENTIAL.\n",
    "       FD  L-FILE.\n"
    "       01  L-REC.\n"
    "           05  L-A              PIC X(4).\n"
    "           05  L-B              PIC X(6).\n",
    "           OPEN OUTPUT L-FILE\n"
    "           MOVE 'OLD' TO L-A\n"
    "           WRITE L-REC FROM WS-NUM\n"
    "           DISPLAY '[' L-A '|' L-B ']'\n"
    "           WRITE L-REC FROM WS-TEXT\n"
    "           DISPLAY '[' L-A '|' L-B ']'\n"
    "           WRITE L-REC FROM WS-G\n"
    "           DISPLAY '[' L-A '|' L-B ']'\n"
    "           WRITE L-REC FROM 'LIT'\n"
    "           DISPLAY '[' L-A '|' L-B ']'\n"
    "           CLOSE L-FILE\n",
    "       01  WS-NUM               PIC 9(5) VALUE 42.\n"
    "       01  WS-TEXT              PIC X(12) VALUE 'ABCDEFGHIJKL'.\n"
    "       01  WS-G.\n"
    "           05  WS-G1            PIC X(3) VALUE 'XYZ'.\n"
    "           05  WS-G2            PIC 9(3) VALUE 7.\n",
)

# name -> (source, stdout, {file: bytes}), all GnuCOBOL 3.1.2 output
CASES: dict[str, tuple[str, str, dict[str, bytes]]] = {
    "record_sequential_extract": (EXTRACT, (
        "OPEN OUTPUT 00\n"
        "OPEN EXTEND 00\n"
        "AFTER FROM A00900 0000250\n"
        "A00100|BOS|0001500|SMITH     |\n"
        "A00200|CHI|0000027|O'BRIEN   |\n"
        "A00900|NYC|0000250|ADJUSTMENT|\n"
        "READ STATUS 10\n"
        "RECORDS 0003 TOTAL 000001777\n"
    ), {
        "EXTRACT.DAT": b"A00100BOS0001500SMITH     A00200CHI0000027O'BRIEN   "
                       b"A00900NYC0000250ADJUSTMENT",
        "SUMMARY.DAT": b"RECORDS=0003 TOTAL=000001777  ",
    }),
    "line_sequential_extend": (_LINE_EXTEND, (
        "EXTEND 00\n[FIRST   ]\n[SECOND  ]\n[        ]\n"
    ), {"LEXT.TXT": b"FIRST\nSECOND\n\n"}),
    "write_from": (_WRITE_FROM, (
        "[0004|2     ]\n[ABCD|EFGHIJ]\n[XYZ0|07    ]\n[LIT |      ]\n"
    ), {"WFROM.TXT": b"00042\nABCDEFGHIJ\nXYZ007\nLIT\n"}),
}


def _transform(source: str):
    return TransformationProducer().transform(source, "PROBE")


# ---------------------------------------------------------------------------
# Parsing and fail-closed rules
# ---------------------------------------------------------------------------

def _record_file(select_tail: str = ".\n", fd_clause: str = "",
                 record: str = "       01  R-REC                PIC X(6).\n",
                 procedure: str = "           OPEN OUTPUT R-FILE\n"
                                  "           MOVE 'ABC' TO R-REC\n"
                                  "           WRITE R-REC\n"
                                  "           CLOSE R-FILE\n") -> str:
    return _program(
        "RF",
        f'           SELECT R-FILE ASSIGN TO "R.DAT"{select_tail}',
        f"       FD  R-FILE{fd_clause}.\n{record}",
        procedure,
    )


class TestOrganization:
    @pytest.mark.parametrize(
        ("select_tail", "expected"),
        [
            (".\n", True),
            ("\n               ORGANIZATION IS SEQUENTIAL.\n", True),
            ("\n               ORGANIZATION IS LINE SEQUENTIAL.\n", False),
        ],
    )
    def test_record_sequential_flag(self, select_tail: str, expected: bool) -> None:
        program = CobolParser().parse(_record_file(select_tail))
        assert program.file_definitions[0].record_sequential is expected

    def test_fixed_records_are_lowered(self) -> None:
        result = _transform(_record_file())
        assert result.success is True, result.errors
        java = result.generated_files[0].source_code
        assert 'CobolFileIo.writeRecord("R.DAT", CobolFileIo.pad(' in java

    def test_fixture_application_is_supported(self) -> None:
        app = ApplicationDiscovery().discover(FIXTURE)
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        program = next(c for c in report.components if c.component_type == "PROGRAM")
        assert program.level is CapabilityLevel.SUPPORTED, program.reason

    @pytest.mark.parametrize(
        ("kwargs", "reason"),
        [
            ({"record": "       01  R-REC   PIC X(6).\n       01  R-ALT   PIC X(3).\n"},
             "several"),
            ({"fd_clause": " RECORD IS VARYING IN SIZE FROM 1 TO 6"}, "variable-length"),
            ({"fd_clause": " RECORD CONTAINS 1 TO 6 CHARACTERS"}, "variable-length"),
            ({"fd_clause": " RECORDING MODE IS V"}, "variable-length"),
            ({"record": "       01  R-REC.\n           05  R-A PIC X(3).\n"
                        "           05  R-N PIC S9(3).\n"}, "not a certified layout"),
            ({"record": "       01  R-REC.\n           05  R-A PIC X(3).\n"
                        "           05  FILLER PIC X(3).\n"}, "not a certified layout"),
            ({"procedure": "           OPEN I-O R-FILE\n           CLOSE R-FILE\n"}, "OPEN I-O"),
            ({"procedure": "           OPEN I-O R-FILE\n           READ R-FILE\n"
                           "           REWRITE R-REC\n           CLOSE R-FILE\n"}, "OPEN I-O"),
        ],
    )
    def test_unreproduced_forms_fail_closed(self, kwargs, reason: str) -> None:
        result = _transform(_record_file(**kwargs))
        assert result.success is False
        assert any("record SEQUENTIAL" in e and reason in e for e in result.errors), result.errors


class TestWriteClauses:
    @pytest.mark.parametrize(
        "write",
        ["WRITE R-REC AFTER ADVANCING 2 LINES", "WRITE R-REC BEFORE PAGE",
         "WRITE R-REC AFTER 1"],
    )
    def test_line_and_page_control_fail_closed(self, write: str) -> None:
        source = _record_file(
            "\n               ORGANIZATION IS LINE SEQUENTIAL.\n",
            procedure=f"           OPEN OUTPUT R-FILE\n           {write}\n"
                      "           CLOSE R-FILE\n",
        )
        result = _transform(source)
        assert result.success is False
        assert any("ADVANCING" in e for e in result.errors), result.errors

    def test_write_from_comp_numeric_into_group_fails_closed(self) -> None:
        source = _WRITE_FROM.replace("PIC 9(5) VALUE 42", "PIC 9(5) COMP VALUE 42")
        result = _transform(source)
        assert result.success is False
        assert any("binary encoding" in e for e in result.errors), result.errors


#: WRITE FROM a signed item into a group record copies its stored
#: characters: -42 in S9(5) is ``0004r`` (GnuCOBOL 3.1.2; refused before
#: Phase 3 increment 10).
_SIGNED_WRITE_FROM = _WRITE_FROM.replace("PIC 9(5) VALUE 42", "PIC S9(5) VALUE -42")
_SIGNED_WRITE_FROM_STDOUT = (
    "[0004|r     ]\n[ABCD|EFGHIJ]\n[XYZ0|07    ]\n[LIT |      ]\n"
)


def test_signed_write_from_matches_oracle(tmp_path: Path) -> None:
    from tests.oracle_java_helpers import run_generated_java

    assert run_generated_java(_SIGNED_WRITE_FROM, "WFROM", tmp_path) == _SIGNED_WRITE_FROM_STDOUT


def test_signed_write_from_oracle_pin(tmp_path: Path) -> None:
    from tests.oracle_java_helpers import run_gnucobol

    assert run_gnucobol(_SIGNED_WRITE_FROM, "WFROM", tmp_path) == _SIGNED_WRITE_FROM_STDOUT


# ---------------------------------------------------------------------------
# Generated Java vs the pinned oracle output (needs a JDK)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(CASES))
def test_generated_java_matches_oracle(name: str, tmp_path: Path) -> None:
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")
    source, stdout, files = CASES[name]
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
    assert run.stdout.decode() == stdout
    for file_name, content in files.items():
        assert (tmp_path / file_name).read_bytes() == content, file_name


# ---------------------------------------------------------------------------
# Docker lane: the oracle itself
# ---------------------------------------------------------------------------

def _gnucobol(source: str, script: str, tmp_path: Path) -> subprocess.CompletedProcess:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    (tmp_path / "P.cob").write_text(source, encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src",
         ORACLE_IMAGE, "sh", "-c",
         f"cd /tmp && cobc -x /src/P.cob -o p && {script}"],
        capture_output=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return run


@pytest.mark.parametrize("name", sorted(CASES))
def test_oracle_pins(name: str, tmp_path: Path) -> None:
    source, stdout, files = CASES[name]
    copies = " && ".join(f"cp {f} /src/{f}" for f in files)
    run = _gnucobol(source, f"./p && {copies} && chmod a+r /src/*", tmp_path)
    assert run.stdout.decode() == stdout
    for file_name, content in files.items():
        assert (tmp_path / file_name).read_bytes() == content, file_name


def test_oracle_varies_records_for_several_record_descriptions(tmp_path: Path) -> None:
    """Why several record descriptions fail closed: a 4-byte header per record."""
    source = _record_file(
        record="       01  R-LONG   PIC X(8).\n       01  R-SHORT  PIC X(3).\n",
        procedure="           OPEN OUTPUT R-FILE\n"
                  "           MOVE 'LONGLONG' TO R-LONG\n"
                  "           WRITE R-LONG\n"
                  "           MOVE 'SHT' TO R-SHORT\n"
                  "           WRITE R-SHORT\n"
                  "           CLOSE R-FILE\n",
    )
    _gnucobol(source, "./p && cp R.DAT /src/ && chmod a+r /src/R.DAT", tmp_path)
    assert (tmp_path / "R.DAT").read_bytes() == (
        b"\x00\x08\x00\x00LONGLONG\x00\x03\x00\x00SHT"
    )

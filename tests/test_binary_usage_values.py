"""Binary/packed items used by value, and the numeric lowerings they need (Phase 3).

GnuCOBOL 3.1.2 with its default configuration (``binary-truncate: yes``)
gives a COMP / BINARY / COMP-4 / COMP-3 / PACKED-DECIMAL item exactly the
value semantics of a DISPLAY item of the same PIC: the binary-values
application prints identical output with and without its USAGE clauses
(truncation at both ends, wrap, ROUNDED, negative into unsigned, MOVE to
and from PIC X).  The generated Java stores such an item as a number like
a DISPLAY item, so a COMP/COMP-3 item whose bytes nothing can observe is
SUPPORTED; COMP-5 (no truncation) and COMP-1/COMP-2 (floating) stay
PARTIAL, and so does any item a statement could see as bytes.

The application also exposed numeric lowerings that were wrong for DISPLAY
items as well (each pinned below against GnuCOBOL):

* MOVE numeric -> PIC X moves the unsigned digits at the sender's PIC
  digit count (``S9(4)`` -37 gives ``0037``), not Java's rendering;
* MOVE PIC X -> numeric reads digit-only content as an unsigned integer
  (low-order digits kept); other content aborts the Java run;
* a decimal operand inside a compound condition compares with
  ``compareTo``;
* an expression that can outgrow the Java type it is evaluated in is
  computed exactly (``Math.toIntExact`` threw where COBOL truncates);
* MOVE / DISPLAY of an FD record group is a view over its fields (it was
  an undeclared Java name); any other use of a record name fails closed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import CobolApplication, CobolProgramUnit
from engine.transformation.producer import TransformationProducer

REPO = Path(__file__).resolve().parents[1]
BINVAL = (REPO / "fixtures" / "workload-binary-values" / "cobol" / "BINVAL.cob").read_text()
ORACLE_IMAGE = "gnucobol-ocesql:latest"

_USAGE_CLAUSE = re.compile(r" (COMP-3|COMP-4|COMPUTATIONAL|COMP|BINARY|PACKED-DECIMAL)( VALUE|\.)")


def _program(program_id: str, data: str, procedure: str, environment: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {program_id}.\n"
        f"{environment}"
        "       DATA DIVISION.\n"
        f"{data}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-LOGIC.\n"
        f"{procedure}"
        "           STOP RUN.\n"
    )


_MOVES = _program("MOVES2", (
    "       WORKING-STORAGE SECTION.\n"
    "       01  N-NEG     PIC S9(4) VALUE -37.\n"
    "       01  N-POS     PIC 9(6) VALUE 1234.\n"
    "       01  N-BIN     PIC S9(4) COMP VALUE -37.\n"
    "       01  N-PK      PIC S9(5) COMP-3 VALUE -1234.\n"
    "       01  N-BIG     PIC 9(12) VALUE 123456789012.\n"
    "       01  X-SHORT   PIC X(3).\n"
    "       01  X-LONG    PIC X(14).\n"
    "       01  A-DIG     PIC X(4) VALUE '0042'.\n"
    "       01  A-LONG    PIC X(8) VALUE '12345678'.\n"
    "       01  A-SHORT   PIC X(2) VALUE '07'.\n"
    "       01  R-4       PIC 9(4).\n"
    "       01  R-S4      PIC S9(4).\n"
    "       01  R-DEC     PIC 9(3)V99.\n"
    "       01  R-BIN     PIC 9(4) COMP.\n"
    "       01  R-BIG     PIC 9(11).\n"
), (
    "           MOVE N-NEG TO X-LONG\n           DISPLAY '1[' X-LONG ']'\n"
    "           MOVE N-NEG TO X-SHORT\n           DISPLAY '2[' X-SHORT ']'\n"
    "           MOVE N-POS TO X-SHORT\n           DISPLAY '3[' X-SHORT ']'\n"
    "           MOVE N-BIN TO X-LONG\n           DISPLAY '4[' X-LONG ']'\n"
    "           MOVE N-PK TO X-LONG\n           DISPLAY '5[' X-LONG ']'\n"
    "           MOVE N-BIG TO X-LONG\n           DISPLAY '6[' X-LONG ']'\n"
    "           MOVE -12 TO X-LONG\n           DISPLAY '7[' X-LONG ']'\n"
    "           MOVE 0012 TO X-LONG\n           DISPLAY '8[' X-LONG ']'\n"
    "           MOVE A-DIG TO R-4\n           DISPLAY '9[' R-4 ']'\n"
    "           MOVE A-LONG TO R-4\n           DISPLAY '10[' R-4 ']'\n"
    "           MOVE A-SHORT TO R-4\n           DISPLAY '11[' R-4 ']'\n"
    "           MOVE A-DIG TO R-S4\n           DISPLAY '12[' R-S4 ']'\n"
    "           MOVE A-LONG TO R-DEC\n           DISPLAY '13[' R-DEC ']'\n"
    "           MOVE A-DIG TO R-BIN\n           DISPLAY '14[' R-BIN ']'\n"
    "           MOVE A-LONG TO R-BIG\n           DISPLAY '15[' R-BIG ']'\n"
    "           MOVE '0099' TO R-4\n           DISPLAY '16[' R-4 ']'\n"
    "           MOVE '123456' TO R-DEC\n           DISPLAY '17[' R-DEC ']'\n"
))

_FILE_CONTROL = (
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    '           SELECT OUT-FILE ASSIGN TO "FDREC.DAT"\n'
    "               ORGANIZATION IS LINE SEQUENTIAL.\n"
)


def _file_program(program_id: str, record: str, procedure: str) -> str:
    return _program(program_id, (
        "       FILE SECTION.\n"
        "       FD  OUT-FILE.\n"
        f"{record}"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-COPY             PIC X(15).\n"
    ), procedure, _FILE_CONTROL)


_RECORD = (
    "       01  OUT-REC.\n"
    "           05  OUT-CODE        PIC X(4).\n"
    "           05  OUT-NAME        PIC X(8).\n"
)

_FDREC = _file_program("FDREC", _RECORD, (
    "           OPEN OUTPUT OUT-FILE\n"
    "           MOVE 'A001ALPHA' TO OUT-REC\n"
    "           WRITE OUT-REC\n"
    "           MOVE 'B002BRAVO-LONGER-THAN-RECORD' TO OUT-REC\n"
    "           WRITE OUT-REC\n"
    "           CLOSE OUT-FILE\n"
    "           OPEN INPUT OUT-FILE\n"
    "           READ OUT-FILE\n"
    "           DISPLAY '[' OUT-REC '] [' OUT-CODE '] [' OUT-NAME ']'\n"
    "           MOVE OUT-REC TO WS-COPY\n"
    "           DISPLAY '[' WS-COPY ']'\n"
    "           READ OUT-FILE\n"
    "           DISPLAY '[' OUT-REC ']'\n"
    "           CLOSE OUT-FILE\n"
))

_WIDE = _program("WIDE", (
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-LARGE  PIC 9(10) VALUE 9000000123.\n"
    "       01  WS-A      PIC 9(9) VALUE 900000000.\n"
    "       01  WS-B      PIC 9(9) VALUE 900000000.\n"
    "       01  WS-C      PIC 9(9) VALUE 900000000.\n"
    "       01  WS-R      PIC 9(9) VALUE 0.\n"
    "       01  WS-L      PIC 9(12) VALUE 0.\n"
    "       01  WS-D      PIC 9(9) VALUE 123456789.\n"
    "       01  WS-E      PIC 9(9) VALUE 987654321.\n"
    "       01  WS-P      PIC 9(5) VALUE 99999.\n"
    "       01  WS-Q      PIC 9(5) VALUE 99999.\n"
    "       01  WS-S      PIC 9(5) VALUE 0.\n"
), (
    "           MOVE WS-LARGE TO WS-R\n"
    "           DISPLAY 'MOVE ' WS-R\n"
    "           COMPUTE WS-R = WS-A + WS-B + WS-C\n"
    "           DISPLAY 'SUM ' WS-R\n"
    "           MULTIPLY WS-P BY WS-Q GIVING WS-S\n"
    "           DISPLAY 'MUL ' WS-S\n"
    "           COMPUTE WS-L = WS-D * WS-E\n"
    "           DISPLAY 'LONG ' WS-L\n"
))

# name -> (source, stdout), all GnuCOBOL 3.1.2 output (exit status 0)
CASES: dict[str, tuple[str, str]] = {
    "binary_values": (BINVAL, (
        "INIT -0100 0500 07\n"
        "INIT +123456789 +000000000000000 -00987.65\n"
        "INIT +0000 012.5 0000\n"
        "TRUNC +2345 +2345 0005 50\n"
        "PACK +23456.78\n"
        "ROUND +00003.33\n"
        "TRUNCQ -00003.33\n"
        "FRAC +0007\n"
        "WRAP +0010\n"
        "TINY 00\n"
        "BIG +000123456788996\n"
        "LONG +333332207\n"
        "TEXT [0010    ]\n"
        "FROMX 0042\n"
        "XFER +00042 +0042\n"
        "DIV 0009 +0002\n"
        "LOOP 0005 +0010\n"
        "EQUAL\n"
        "SIGNS OK\n"
        "NEGZERO +00000.00\n"
        "INITIALIZED +000000000\n"
    )),
    "numeric_alphanumeric_moves": (_MOVES, (
        "1[0037          ]\n"
        "2[003]\n"
        "3[001]\n"
        "4[0037          ]\n"
        "5[01234         ]\n"
        "6[123456789012  ]\n"
        "7[12            ]\n"
        "8[0012          ]\n"
        "9[0042]\n"
        "10[5678]\n"
        "11[0007]\n"
        "12[+0042]\n"
        "13[678.00]\n"
        "14[0042]\n"
        "15[00012345678]\n"
        "16[0099]\n"
        "17[456.00]\n"
    )),
    "wide_integer_results": (_WIDE, (
        "MOVE 000000123\n"
        "SUM 700000000\n"
        "MUL 00001\n"
        "LONG 631112635269\n"
    )),
    "file_record_group": (_FDREC, (
        "[A001ALPHA   ] [A001] [ALPHA   ]\n"
        "[A001ALPHA      ]\n"
        "[B002BRAVO-LO]\n"
    )),
}


def _level(source: str) -> tuple[CapabilityLevel, str]:
    unit = CobolProgramUnit(
        program_id="P", source_path="P.cob",
        program=CobolParser().parse(source), source_text=source,
    )
    report = CapabilityAnalyzer(docker_available=True).analyze(
        CobolApplication(application_id="T", programs=(unit,))
    )
    program = next(c for c in report.components if c.component_type == "PROGRAM")
    return program.level, program.reason


def _usage_program(declaration: str, procedure: str, extra: str = "") -> str:
    return _program("P", (
        "       WORKING-STORAGE SECTION.\n"
        f"       01  WS-N    {declaration}.\n"
        "       01  WS-T    PIC X(8) VALUE SPACES.\n"
        f"{extra}"
    ), procedure)


# ---------------------------------------------------------------------------
# Capability: which items are value-only
# ---------------------------------------------------------------------------

class TestValueOnlyItems:
    @pytest.mark.parametrize("usage", ["COMP", "BINARY", "COMP-4", "COMPUTATIONAL", "COMP-3", "PACKED-DECIMAL"])
    def test_value_only_item_is_supported(self, usage: str) -> None:
        source = _usage_program(f"PIC S9(4) {usage} VALUE 5", (
            "           ADD 1 TO WS-N\n"
            "           DISPLAY WS-N\n"
            "           MOVE WS-N TO WS-T\n"
            "           IF WS-N > 3 DISPLAY 'BIG' END-IF\n"
            "           PERFORM VARYING WS-N FROM 1 BY 1 UNTIL WS-N > 2\n"
            "               DISPLAY WS-N\n"
            "           END-PERFORM\n"
            "      *    CALL 'X' USING WS-N  (a comment is not a reference)\n"
            "           DISPLAY 'CALL WS-N'\n"
        ))
        level, reason = _level(source)
        assert level is CapabilityLevel.SUPPORTED, reason

    def test_every_fixture_application_is_supported(self) -> None:
        for app in ("workload-binary-values", "workload-comp", "workload-comp3",
                    "workload-relative", "workload-relative-file"):
            path = next((REPO / "fixtures" / app / "cobol").glob("*.cob"))
            level, reason = _level(path.read_text())
            assert level is CapabilityLevel.SUPPORTED, (app, reason)

    @pytest.mark.parametrize("usage", ["COMP-5", "COMP-1", "COMP-2"])
    def test_other_usages_stay_partial(self, usage: str) -> None:
        pic = "" if usage in ("COMP-1", "COMP-2") else "PIC S9(4) "
        level, _ = _level(_usage_program(f"{pic}{usage}", "           DISPLAY WS-N\n"))
        assert level is not CapabilityLevel.SUPPORTED

    @pytest.mark.parametrize(
        ("procedure", "extra"),
        [
            ("           CALL 'SUB' USING WS-N\n", ""),
            ("           MOVE WS-N(1:1) TO WS-T\n", ""),
            ("           STRING WS-N DELIMITED BY SIZE INTO WS-T\n", ""),
            ("           INSPECT WS-N TALLYING WS-I FOR ALL '1'\n", "       01  WS-I PIC 9.\n"),
            ("           MOVE LENGTH OF WS-N TO WS-I\n", "       01  WS-I PIC 9.\n"),
            ("           COMPUTE WS-I = FUNCTION LENGTH(WS-N)\n", "       01  WS-I PIC 9.\n"),
            ("           ACCEPT WS-N\n", ""),
            ("           SET WS-I TO WS-N\n", "       01  WS-I PIC 9.\n"),
            ("           DISPLAY WS-N\n", "       01  WS-X REDEFINES WS-N PIC X(2).\n"),
            ("           DISPLAY WS-N\n", "       COPY EXTRA.\n"),
        ],
    )
    def test_byte_level_use_stays_partial(self, procedure: str, extra: str) -> None:
        level, _ = _level(_usage_program("PIC S9(4) COMP", procedure, extra))
        assert level is not CapabilityLevel.SUPPORTED

    def test_item_inside_a_group_stays_partial(self) -> None:
        source = _program("P", (
            "       WORKING-STORAGE SECTION.\n"
            "       01  WS-G.\n"
            "           05  WS-N    PIC S9(4) COMP.\n"
        ), "           DISPLAY WS-N\n")
        assert _level(source)[0] is not CapabilityLevel.SUPPORTED


# ---------------------------------------------------------------------------
# Transformation: lowering shapes and fail-closed cases
# ---------------------------------------------------------------------------

def _transform(source: str):
    return TransformationProducer().transform(source, "PROBE")


def _java(source: str) -> str:
    result = _transform(source)
    assert result.success is True, result.errors
    return result.generated_files[0].source_code


class TestLowering:
    def test_numeric_to_alphanumeric_moves_unsigned_digits(self) -> None:
        java = _java(_MOVES)
        assert 'String.format("%04d", Math.abs(N_NEG))' in java
        assert 'String.format("%-14s", "12")' in java  # MOVE -12: sign dropped

    def test_alphanumeric_to_numeric_accepts_only_digits(self) -> None:
        # Leading spaces read as zeros since 2026-11-03 (T5 parity,
        # tests/integration/test_space_padded_move_oracle.py).
        java = _java(_MOVES)
        assert 'A_DIG.matches(" *[0-9]*")' in java
        assert "R_4 = 99;" in java  # MOVE '0099': checked at generation

    def test_non_digit_literal_into_numeric_fails_closed(self) -> None:
        source = _usage_program("PIC 9(4)", "           MOVE 'A1' TO WS-N\n")
        assert _transform(source).success is False

    def test_decimal_operand_in_compound_condition_uses_compare_to(self) -> None:
        assert "WS_PACKED.compareTo(" in _java(BINVAL)

    def test_result_wider_than_java_type_is_exact(self) -> None:
        java = _java(BINVAL)
        assert "toIntExact" not in java
        assert "subtract(java.math.BigDecimal.valueOf(WS_LONG))" in java

    def test_file_record_group_is_a_view(self) -> None:
        java = _java(_FDREC)
        assert "OUT_REC" not in java
        assert "OUT_CODE = " in java and "OUT_NAME = " in java

    @pytest.mark.parametrize(
        ("record", "procedure"),
        [
            (  # two records share one record area
                _RECORD + "       01  OUT-ALT PIC X(12).\n",
                "           MOVE 'X' TO OUT-REC\n",
            ),
            (  # FILLER: a READ overwrites it
                "       01  OUT-REC.\n"
                "           05  OUT-CODE PIC X(4).\n"
                "           05  FILLER   PIC X(8).\n",
                "           MOVE 'X' TO OUT-REC\n",
            ),
            (  # OCCURS continued on the next line: a table, not two fields
                "       01  OUT-REC.\n"
                "           05  OUT-CODE PIC X(4)\n"
                "               OCCURS 3.\n",
                "           MOVE 'X' TO OUT-REC\n",
            ),
            (_RECORD, "           INITIALIZE OUT-REC\n"),
            (_RECORD, "           IF OUT-REC = SPACES DISPLAY 'E' END-IF\n"),
        ],
    )
    def test_uncertified_file_record_use_fails_closed(self, record: str, procedure: str) -> None:
        result = _transform(_file_program("BAD", record, procedure))
        assert result.success is False
        assert any("OUT-REC" in e for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# Generated Java vs the pinned oracle output (needs a JDK)
# ---------------------------------------------------------------------------

def _run_java(source: str, tmp_path: Path) -> subprocess.CompletedProcess:
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
    return subprocess.run(
        ["java", "-Dline.separator=\n", "-cp", str(tmp_path),
         result.generated_files[0].class_name],
        capture_output=True, timeout=60, cwd=tmp_path,
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_generated_java_matches_oracle(name: str, tmp_path: Path) -> None:
    source, stdout = CASES[name]
    run = _run_java(source, tmp_path)
    assert run.stdout.decode() == stdout
    assert run.returncode == 0, run.stderr.decode(errors="replace")


def test_non_digit_content_aborts_the_java_run(tmp_path: Path) -> None:
    """GnuCOBOL gives '4A2B' -> 0000 and '42  ' -> 0042 by rules the Java
    does not reproduce: it must stop, never store a guess. (Leading spaces
    are certified; trailing ones are not.)"""
    source = _usage_program("PIC 9(4)", (
        "           MOVE '42  ' TO WS-T\n"
        "           MOVE WS-T TO WS-N\n"
        "           DISPLAY WS-N\n"
    ))
    run = _run_java(source, tmp_path)
    assert run.returncode != 0
    assert run.stdout == b""
    assert b"only leading spaces and digits are certified" in run.stderr


# ---------------------------------------------------------------------------
# Docker lane: the oracle itself
# ---------------------------------------------------------------------------

def _gnucobol(sources: dict[str, str], script: str, tmp_path: Path) -> str:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    for name, text in sources.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src",
         ORACLE_IMAGE, "sh", "-c", f"cd /tmp && cp /src/*.cob . && {script}"],
        capture_output=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return run.stdout.decode()


def test_binary_and_packed_values_equal_display_on_gnucobol(tmp_path: Path) -> None:
    display = _USAGE_CLAUSE.sub(r"\2", BINVAL)
    assert not re.search(r"\b(COMP|BINARY|PACKED-DECIMAL)", display.split("PROCEDURE")[0])
    out = _gnucobol(
        {"BINVAL.cob": BINVAL, "DISP.cob": display.replace("PROGRAM-ID. BINVAL", "PROGRAM-ID. DISP")},
        "cobc -x BINVAL.cob && cobc -x DISP.cob && ./BINVAL > a && ./DISP > b"
        " && cmp a b && cat a",
        tmp_path,
    )
    assert out == CASES["binary_values"][1]


@pytest.mark.parametrize("name", sorted(CASES))
def test_oracle_pins(name: str, tmp_path: Path) -> None:
    source, stdout = CASES[name]
    entry = source.split("PROGRAM-ID. ", 1)[1].split(".", 1)[0]
    out = _gnucobol({f"{entry}.cob": source}, f"cobc -x {entry}.cob && ./{entry}", tmp_path)
    assert out == stdout

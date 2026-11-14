"""Differential for the remaining layout shapes (G-29): inline SIGN, nested OCCURS, a group REDEFINES, SYNC.

Same method as ``test_vsam_layout_oracle``: a COBOL program fills the record with known values, GnuCOBOL
writes it, and the layout derived from the *same source text* must find every value at its derived offset.
For ``SYNCHRONIZED`` the point is the opposite: GnuCOBOL's record is longer than the unsynchronised size, which
is the measured reason the layout refuses it.  Evidence class: GNUCOBOL_DIFFERENTIAL (default and -std=ibm
dialects), never IBM Enterprise COBOL.  Docker lane: RUN_DOCKER_TESTS=1.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import BinaryWidthModel, derive_file_layout

ORACLE_IMAGE = os.environ.get("VSAM_ORACLE_IMAGE", "gnucobol-ocesql:latest")  # override: same differential on another compiler image
MODELS = [("default", BinaryWidthModel.GNUCOBOL_1_2_4_8), ("ibm", BinaryWidthModel.IBM_2_4_8)]

RECORD = """\
       01 REC.
          05 SL    PIC S9(3) SIGN IS LEADING.
          05 ST    PIC S9(3) SIGN IS TRAILING.
          05 ROW OCCURS 2 TIMES.
             10 CELL PIC X(3) OCCURS 3 TIMES.
          05 GRP.
             10 A  PIC X(2).
             10 B  PIC 9(2) COMP-3.
          05 GALT REDEFINES GRP.
             10 WHOLE PIC X(4).
          05 TAIL  PIC X.
"""

STATEMENTS = [
    [("SL", "-123"), ("ST", "-123"), ("GRP-A", '"xy"'), ("GRP-B", "42")],
    [("SL", "45"), ("ST", "45"), ("GRP-A", '"pq"'), ("GRP-B", "7")],
]
CELLS = [["r1a", "r1b", "r1c", "r2a", "r2b", "r2c"], ["s1a", "s1b", "s1c", "s2a", "s2b", "s2c"]]


def program(record: str, body: list[str], fd_name: str = "F") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. LAYG.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        f'           SELECT {fd_name} ASSIGN TO "OUT.DAT" ORGANIZATION IS SEQUENTIAL.\n'
        f"       DATA DIVISION.\n       FILE SECTION.\n       FD {fd_name}.\n" + record +
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           OPEN OUTPUT F.\n"
        + "".join(f"           {line}\n" for line in body) + "           CLOSE F.\n           STOP RUN.\n")


def run_gnucobol(tmp_path: Path, source: str, std: str) -> bytes:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 with the gnucobol-ocesql image present")
    (tmp_path / "LAYG.cob").write_text(source, encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src", ORACLE_IMAGE, "sh", "-c",
         f"cd /tmp && cobc -x -std={std} /src/LAYG.cob -o p && ./p && cp OUT.DAT /src/ && chmod a+r /src/OUT.DAT"],
        capture_output=True, timeout=300)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return (tmp_path / "OUT.DAT").read_bytes()


def body() -> list[str]:
    lines: list[str] = []
    for record, cells in zip(STATEMENTS, CELLS):
        lines.append("MOVE SPACES TO REC.")
        for row in (1, 2):
            for col in (1, 2, 3):
                lines.append(f'MOVE "{cells[(row - 1) * 3 + col - 1]}" TO CELL({row} {col}).')
        for name, value in record:
            lines.append(f"MOVE {value} TO {name.replace('GRP-', '')}.")
        lines.append('MOVE "T" TO TAIL.')
        lines.append("WRITE REC.")
    return lines


def packed(chunk: bytes) -> int:
    nibbles = [n for byte in chunk for n in (byte >> 4, byte & 0xF)]
    return int("".join(str(n) for n in nibbles[:-1]))


@pytest.mark.parametrize("std,model", MODELS)
def test_inline_signs_nested_occurs_and_a_group_overlay_sit_where_the_layout_says(tmp_path, std, model):
    source = program(RECORD, body())
    written = run_gnucobol(tmp_path, source, std)
    fdef = CobolParser().parse(source).file_definitions[0]
    layout = derive_file_layout(fdef, binary_width_model=model, overlay_selection={"GRP": "GRP"})
    assert layout.supported, layout.diagnostics
    assert len(written) == 2 * layout.record_length, (len(written), layout.record_length)   # sizes agree with the compiler

    by_path = {f.path: f for f in layout.fields}
    for index, cells in enumerate(CELLS):
        record = written[index * layout.record_length:(index + 1) * layout.record_length]

        def raw(path: str) -> bytes:
            f = by_path[path]
            return record[f.offset:f.offset + f.length]

        # nested OCCURS: every cell at its derived element offset
        assert [raw(f"REC.ROW({r}).CELL({c})").decode() for r in (1, 2) for c in (1, 2, 3)] == cells
        # group overlay: the selected alternative reads the bytes COBOL wrote through the other one
        expect_a, expect_b = (("xy", 42), ("pq", 7))[index]
        assert raw("REC.GRP.A").decode() == expect_a
        assert packed(raw("REC.GRP.B")) == expect_b
        assert raw("REC.TAIL") == b"T"
    # inline signs occupy exactly their digits (no extra byte); the sign lives in a digit (overpunch)
    assert by_path["REC.SL"].length == 3 and by_path["REC.ST"].length == 3
    first = written[:layout.record_length]
    assert first[by_path["REC.SL"].offset:by_path["REC.SL"].offset + 3] != b"123"      # the negative sign is in there
    second = written[layout.record_length:2 * layout.record_length]
    assert second[by_path["REC.SL"].offset:by_path["REC.SL"].offset + 3] == b"045"     # positive: plain digits


@pytest.mark.parametrize("std,model", MODELS)
def test_the_other_overlay_alternative_reads_the_group_as_text(tmp_path, std, model):
    source = program(RECORD, body())
    written = run_gnucobol(tmp_path, source, std)
    layout = derive_file_layout(CobolParser().parse(source).file_definitions[0], binary_width_model=model,
                                overlay_selection={"GRP": "GALT"})
    assert layout.supported and len(written) == 2 * layout.record_length
    whole = next(f for f in layout.fields if f.path == "REC.GALT.WHOLE")
    assert written[whole.offset:whole.offset + 2] == b"xy" and whole.length == 4


@pytest.mark.parametrize("std", ["default", "ibm"])
def test_synchronized_adds_slack_in_the_real_compiler_which_is_why_the_layout_refuses_it(tmp_path, std):
    sync = "       01 REC.\n          05 A PIC X.\n          05 N PIC S9(4) COMP SYNC.\n"
    plain = "       01 REC.\n          05 A PIC X.\n          05 N PIC S9(4) COMP.\n"
    (tmp_path / "s").mkdir()
    (tmp_path / "p").mkdir()
    synced_len = len(run_gnucobol(tmp_path / "s", program(sync, ["MOVE SPACES TO REC.", "WRITE REC."]), std))
    plain_len = len(run_gnucobol(tmp_path / "p", program(plain, ["MOVE SPACES TO REC.", "WRITE REC."]), std))
    assert plain_len == 3 and synced_len > plain_len                       # slack bytes the layout does not model
    layout = derive_file_layout(CobolParser().parse(program(sync, [])).file_definitions[0],
                                binary_width_model=BinaryWidthModel.IBM_2_4_8)
    assert not layout.supported and "SYNCHRONIZED" in [d.code for d in layout.diagnostics]

"""Differential: the derived record layout, against what GnuCOBOL actually writes.

One COBOL program fills every field kind with known values and WRITEs two records to a
sequential file.  The layout is derived from the *same source text* by ``engine.vsam.layout``;
every field is then decoded at the offset and length the layout predicts and must equal the value
COBOL moved in.  That checks offsets, lengths and the binary width model against a real compiler:
``-std=default`` (binary-size 1-2-4-8) for ``GNUCOBOL_1_2_4_8`` and ``-std=ibm`` (binary-size 2-4-8)
for ``IBM_2_4_8``.  The converted data is then migrated and reconciled.

Evidence class: GNUCOBOL_DIFFERENTIAL for these shapes in those two GnuCOBOL dialects.  It is NOT
IBM runtime evidence: real Enterprise COBOL output has not been read.  Docker lane: set
RUN_DOCKER_TESTS=1 with the gnucobol-ocesql image present.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import BinaryWidthModel, derive_file_layout
from engine.vsam.migrate import migrate_dataset
from engine.vsam.model import DatasetDefinition, Encoding, Organization

ORACLE_IMAGE = os.environ.get("VSAM_ORACLE_IMAGE", "gnucobol-ocesql:latest")  # override: same differential on another compiler image

RECORD_DEFINITION = """\
       01 REC.
          05 ID-X     PIC X(4).
          05 AMT-D    PIC 9(5)V99.
          05 CNT2     PIC S9(2) COMP.
          05 CNT4     PIC S9(4) COMP.
          05 CNT9     PIC S9(9) COMP.
          05 CNT18    PIC S9(18) COMP.
          05 CNT5N    PIC S9(5) COMP-5.
          05 PK       PIC S9(7)V99 COMP-3.
          05 PK1      PIC S9(1) COMP-3.
          05 SEPL     PIC S9(3) SIGN IS LEADING SEPARATE.
          05 SEPT     PIC S9(3) SIGN IS TRAILING SEPARATE.
          05 FILLER   PIC X(2).
          05 TBL OCCURS 3 TIMES.
             10 TQ    PIC 9(2).
             10 TP    PIC S9(3) COMP-3.
          05 DATE-NUM PIC 9(8).
          05 DATE-PARTS REDEFINES DATE-NUM.
             10 YY    PIC 9(4).
             10 MM    PIC 9(2).
             10 DD    PIC 9(2).
"""

# (cobol statements that fill one record, expected decoded values by layout path)
RECORDS = [
    (
        ['MOVE "AB12" TO ID-X', "MOVE 1234.56 TO AMT-D", "MOVE 42 TO CNT2", "MOVE -1234 TO CNT4",
         "MOVE 123456789 TO CNT9", "MOVE 1234567890123456 TO CNT18", "MOVE -32100 TO CNT5N",
         "MOVE -1234567.89 TO PK", "MOVE -7 TO PK1", "MOVE -17 TO SEPL", "MOVE 120 TO SEPT",
         "MOVE 1 TO TQ(1)", "MOVE -111 TO TP(1)", "MOVE 2 TO TQ(2)", "MOVE -222 TO TP(2)",
         "MOVE 3 TO TQ(3)", "MOVE 333 TO TP(3)", "MOVE 20261113 TO DATE-NUM"],
        {"ID-X": "AB12", "AMT-D": "0123456", "CNT2": 42, "CNT4": -1234, "CNT9": 123456789,
         "CNT18": 1234567890123456, "CNT5N": -32100, "PK": -123456789, "PK1": -7, "SEPL": "-017",
         "SEPT": "120+", "FILLER": "  ", "TBL(1).TQ": "01", "TBL(1).TP": -111, "TBL(2).TQ": "02",
         "TBL(2).TP": -222, "TBL(3).TQ": "03", "TBL(3).TP": 333, "DATE-PARTS.YY": "2026",
         "DATE-PARTS.MM": "11", "DATE-PARTS.DD": "13"},
    ),
    (
        ['MOVE "Z9Y8" TO ID-X', "MOVE 0 TO AMT-D", "MOVE -5 TO CNT2", "MOVE 9999 TO CNT4",
         "MOVE -987654321 TO CNT9", "MOVE -1 TO CNT18", "MOVE 77 TO CNT5N", "MOVE 0.01 TO PK",
         "MOVE 9 TO PK1", "MOVE 5 TO SEPL", "MOVE -999 TO SEPT", "MOVE 9 TO TQ(1)", "MOVE 0 TO TP(1)",
         "MOVE 8 TO TQ(2)", "MOVE 999 TO TP(2)", "MOVE 7 TO TQ(3)", "MOVE -999 TO TP(3)",
         "MOVE 19991231 TO DATE-NUM"],
        {"ID-X": "Z9Y8", "AMT-D": "0000000", "CNT2": -5, "CNT4": 9999, "CNT9": -987654321, "CNT18": -1,
         "CNT5N": 77, "PK": 1, "PK1": 9, "SEPL": "+005", "SEPT": "999-", "FILLER": "  ",
         "TBL(1).TQ": "09", "TBL(1).TP": 0, "TBL(2).TQ": "08", "TBL(2).TP": 999, "TBL(3).TQ": "07",
         "TBL(3).TP": -999, "DATE-PARTS.YY": "1999", "DATE-PARTS.MM": "12", "DATE-PARTS.DD": "31"},
    ),
]


def program_source() -> str:
    head = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. LAY.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        '           SELECT F ASSIGN TO "OUT.DAT" ORGANIZATION IS SEQUENTIAL.\n'
        "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n" + RECORD_DEFINITION +
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           OPEN OUTPUT F.\n"
    )
    body = ""
    for statements, _ in RECORDS:
        body += "           MOVE SPACES TO REC.\n"
        body += "".join(f"           {s}.\n" for s in statements)
        body += "           WRITE REC.\n"
    return head + body + "           CLOSE F.\n           STOP RUN.\n"


def write_with_gnucobol(tmp_path: Path, std: str) -> bytes:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 with the gnucobol-ocesql image present")
    (tmp_path / "LAY.cob").write_text(program_source(), encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src", ORACLE_IMAGE, "sh", "-c",
         f"cd /tmp && cobc -x -std={std} /src/LAY.cob -o p && ./p && cp OUT.DAT /src/ && chmod a+r /src/OUT.DAT"],
        capture_output=True, timeout=300)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return (tmp_path / "OUT.DAT").read_bytes()


def decode_packed(chunk: bytes) -> int:
    nibbles = [n for byte in chunk for n in (byte >> 4, byte & 0xF)]
    digits = int("".join(str(n) for n in nibbles[:-1]) or "0")
    return -digits if nibbles[-1] == 0xD else digits


def decode(chunk: bytes, kind: str, usage: str = "") -> object:
    if kind == "PACKED":
        return decode_packed(chunk)
    if kind == "BINARY":
        # COMP is big-endian; COMP-5 is native byte order (little-endian on this x86-64 oracle)
        return int.from_bytes(chunk, "little" if usage == "COMP-5" else "big", signed=True)
    return chunk.decode("ascii")


@pytest.mark.parametrize("std,model", [("default", BinaryWidthModel.GNUCOBOL_1_2_4_8), ("ibm", BinaryWidthModel.IBM_2_4_8)])
def test_every_field_is_where_the_derived_layout_says_in_the_records_gnucobol_wrote(tmp_path, std, model):
    written = write_with_gnucobol(tmp_path, std)
    program = CobolParser().parse(program_source())
    layout = derive_file_layout(program.file_definitions[0], binary_width_model=model,
                                overlay_selection={"DATE-NUM": "DATE-PARTS"})
    assert layout.supported, layout.diagnostics

    # the compiler's record length is the layout's: the file holds exactly two such records
    assert len(written) == 2 * layout.record_length, (len(written), layout.record_length)

    for index, (_, expected) in enumerate(RECORDS):
        record = written[index * layout.record_length:(index + 1) * layout.record_length]
        decoded = {f.path.removeprefix("REC."): decode(record[f.offset:f.offset + f.length], f.kind.value, f.usage)
                   for f in layout.fields}
        assert decoded == expected, f"record {index + 1}"


def test_the_other_overlay_alternative_reads_the_same_bytes_as_a_number(tmp_path):
    written = write_with_gnucobol(tmp_path, "default")
    layout = derive_file_layout(CobolParser().parse(program_source()).file_definitions[0],
                                binary_width_model=BinaryWidthModel.GNUCOBOL_1_2_4_8,
                                overlay_selection={"DATE-NUM": "DATE-NUM"})
    record = written[:layout.record_length]
    field = next(f for f in layout.fields if f.path == "REC.DATE-NUM")
    assert record[field.offset:field.offset + field.length] == b"20261113"
    assert all(not f.path.startswith("REC.DATE-PARTS") for f in layout.fields)


def test_the_two_width_models_give_two_different_record_lengths_and_each_matches_its_dialect(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "i").mkdir()
    default_file = write_with_gnucobol(tmp_path / "d", "default")
    ibm_file = write_with_gnucobol(tmp_path / "i", "ibm")
    program = CobolParser().parse(program_source())
    lengths = {}
    for model in BinaryWidthModel:
        lengths[model] = derive_file_layout(program.file_definitions[0], binary_width_model=model,
                                            overlay_selection={"DATE-NUM": "DATE-PARTS"}).record_length
    assert len(default_file) // 2 == lengths[BinaryWidthModel.GNUCOBOL_1_2_4_8]
    assert len(ibm_file) // 2 == lengths[BinaryWidthModel.IBM_2_4_8]
    assert lengths[BinaryWidthModel.GNUCOBOL_1_2_4_8] != lengths[BinaryWidthModel.IBM_2_4_8]


_PLATFORM_OF = {"default": "GNUCOBOL_X86_DEFAULT", "ibm": "GNUCOBOL_X86_IBM_DIALECT"}


def layout_for_platform(name):
    from engine.vsam.platform import platform

    rep = platform(name)
    return rep, derive_file_layout(CobolParser().parse(program_source()).file_definitions[0],
                                   binary_width_model=rep.width_model,
                                   overlay_selection={"DATE-NUM": "DATE-PARTS"})


def test_converting_default_dialect_records_to_the_ibm_layout_equals_what_gnucobol_writes_in_that_dialect(tmp_path):
    """The strongest check: the converter's output is compared with the compiler's own output.

    The same values are written by GnuCOBOL twice (-std=default: 1-byte COMP S9(2); -std=ibm: 2-byte).
    Converting the first file to the second layout must give the second file byte for byte (both are
    little-endian COMP-5, so only widths and offsets move), and back again.
    """
    from engine.vsam.platform import convert_record_between

    (tmp_path / "d").mkdir()
    (tmp_path / "i").mkdir()
    default_file = write_with_gnucobol(tmp_path / "d", "default")
    ibm_file = write_with_gnucobol(tmp_path / "i", "ibm")
    rep_d, lay_d = layout_for_platform("GNUCOBOL_X86_DEFAULT")
    rep_i, lay_i = layout_for_platform("GNUCOBOL_X86_IBM_DIALECT")
    assert lay_d.record_length != lay_i.record_length
    for index in range(2):
        record = default_file[index * lay_d.record_length:(index + 1) * lay_d.record_length]
        expected = ibm_file[index * lay_i.record_length:(index + 1) * lay_i.record_length]
        assert convert_record_between(record, lay_d, lay_i, rep_d, rep_i, "ASCII", "ASCII") == expected, index
        assert convert_record_between(expected, lay_i, lay_d, rep_i, rep_d, "ASCII", "ASCII") == record, index


def test_comp5_goes_big_endian_for_the_ibm_target_and_everything_else_is_unchanged(tmp_path):
    """No big-endian COMP-5 exists on x86 GnuCOBOL, so the expected bytes are computed independently."""
    from engine.vsam.platform import convert_record_between

    ibm_file = write_with_gnucobol(tmp_path, "ibm")
    rep_i, lay_i = layout_for_platform("GNUCOBOL_X86_IBM_DIALECT")
    rep_z, lay_z = layout_for_platform("IBM_ZOS")
    assert lay_i.record_length == lay_z.record_length                     # same width model: only the byte order differs
    for index in range(2):
        record = ibm_file[index * lay_i.record_length:(index + 1) * lay_i.record_length]
        out = convert_record_between(record, lay_i, lay_z, rep_i, rep_z, "ASCII", "ASCII")
        for f in lay_i.fields:
            before, after = record[f.offset:f.offset + f.length], out[f.offset:f.offset + f.length]
            if f.usage == "COMP-5":
                value = int.from_bytes(before, "little", signed=f.signed)
                assert after == value.to_bytes(f.length, "big", signed=f.signed), f.path
            else:
                assert after == before, f.path


@pytest.mark.parametrize("std", ["default", "ibm"])
def test_the_records_gnucobol_wrote_migrate_and_reconcile(tmp_path, std):
    written = write_with_gnucobol(tmp_path, std)
    rep, layout = layout_for_platform(_PLATFORM_OF[std])
    source = DatasetDefinition("LAY", Organization.SEQUENTIAL, record_length=layout.record_length)
    # same platform on both sides: text is re-encoded, every binary and packed field is unchanged
    destination, report = migrate_dataset(source, written, layout, Encoding.EBCDIC_CP037,
                                          target_layout=layout, source_platform=rep, target_platform=rep)
    assert report.state == "RECONCILED" and report.success, report.failures
    assert report.to_dict()["source_record_count"] == 2 and report.to_dict()["rejected_record_count"] == 0

    # text fields are EBCDIC now; every packed and binary field is byte-identical to what COBOL wrote
    for index in range(2):
        old = written[index * layout.record_length:(index + 1) * layout.record_length]
        new = destination[index * layout.record_length:(index + 1) * layout.record_length]
        for f in layout.fields:
            before, after = old[f.offset:f.offset + f.length], new[f.offset:f.offset + f.length]
            if f.kind.value == "DISPLAY":
                assert after == before.decode("ascii").encode("cp037"), f.path
            else:
                assert after == before, f.path

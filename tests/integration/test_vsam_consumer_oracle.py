"""An independent consumer reads the migrated data: GnuCOBOL must see exactly the values the mainframe wrote.

Until now only our own reconciliation had read migrated output.  Here a dataset in the mainframe form (EBCDIC
cp037 text, big-endian binary at IBM widths, packed decimal) is migrated to the GnuCOBOL x86 form with the
real pipeline, and an independent COBOL program compiled by GnuCOBOL 3.1.2 reads the migrated file as an ordinary
sequential file and displays every field.  The expected values are the ones the test constructed the records
from, never anything the migration produced.

Evidence class: GNUCOBOL_DIFFERENTIAL (consumer = GnuCOBOL on x86-64).  Not an IBM runtime and not Java: the generated
Java consumer is a separate test.  Docker lane: RUN_DOCKER_TESTS=1 with the ``gnucobol-ocesql:latest`` image.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import derive_file_layout
from engine.vsam.migrate import migrate_dataset
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization
from engine.vsam.platform import platform

IMAGE = os.environ.get("VSAM_ORACLE_IMAGE", "gnucobol-ocesql:latest")  # override: same differential on another compiler image
IBM_Z, X86 = platform("IBM_ZOS"), platform("GNUCOBOL_X86_DEFAULT")

RECORD = """\
       01 REC.
          05 ID-X  PIC X(4).
          05 N     PIC S9(4) COMP.
          05 C5    PIC S9(4) COMP-5.
          05 B     PIC S9(9) COMP-5.
          05 A     PIC S9(5) COMP-3.
          05 Z     PIC S9(3).
          05 ZL    PIC S9(3) SIGN IS LEADING.
          05 MEMO  PIC X(6).
"""

ROWS = [  # id, N, C5, B, packed A as digits, Z (zoned trailing sign), ZL (zoned leading sign), note
    ("a001", 258, 300, 123456789, 12345, 123, -123, "alpha "),
    ("A001", -2, -300, -1, -999, -123, 123, "Bravo "),
    ("1001", 9999, 0, 999999999, 0, -90, -9, "xray 9"),
    ("Z999", 1, 1, 1, 1, 0, 0, "zero  "),
]


def source_text(select: str = 'SELECT F ASSIGN TO "F.DAT" ORGANIZATION IS SEQUENTIAL') -> str:
    return ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. RDR.\n       ENVIRONMENT DIVISION.\n"
            f"       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           {select}.\n"
            "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n" + RECORD)


def reader_program() -> str:
    show = ["MOVE N TO E-N", "MOVE C5 TO E-C5", "MOVE B TO E-B", "MOVE A TO E-A", "MOVE Z TO E-Z", "MOVE ZL TO E-ZL",
            'DISPLAY ID-X "|" E-N "|" E-C5 "|" NO ADVANCING', 'DISPLAY E-B "|" E-A "|" NO ADVANCING', 'DISPLAY E-Z "|" E-ZL "|" MEMO']
    return (source_text() +
            "       WORKING-STORAGE SECTION.\n       01 EOF-FLAG PIC X VALUE \"N\".\n"
            "       01 E-Z  PIC +9(9).\n       01 E-ZL PIC +9(9).\n       01 E-N  PIC +9(9).\n       01 E-C5 PIC +9(9).\n       01 E-B PIC +9(9).\n       01 E-A PIC +9(9).\n"
            "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           OPEN INPUT F.\n"
            "           PERFORM UNTIL EOF-FLAG = \"Y\"\n"
            "               READ F AT END MOVE \"Y\" TO EOF-FLAG\n"
            "               NOT AT END\n"
            + "".join(f"                   {line}\n" for line in show) +
            "               END-READ\n           END-PERFORM.\n           CLOSE F.\n           STOP RUN.\n")


def packed(value: int, digits: int = 5) -> bytes:
    sign = 0xD if value < 0 else 0xC
    text = f"{abs(value):0{digits}d}"
    nibbles = [int(c) for c in text] + [sign]
    if len(nibbles) % 2:
        nibbles.insert(0, 0)
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def zoned_trailing(value: int) -> bytes:
    """IBM zoned decimal, sign in the last byte's zone (C positive, D negative, F for digits)."""
    digits = f"{abs(value):03d}"
    return bytes([0xF0 + int(digits[0]), 0xF0 + int(digits[1]), (0xD0 if value < 0 else 0xC0) + int(digits[2])])


def zoned_leading(value: int) -> bytes:
    digits = f"{abs(value):03d}"
    return bytes([(0xD0 if value < 0 else 0xC0) + int(digits[0]), 0xF0 + int(digits[1]), 0xF0 + int(digits[2])])


def mainframe_dataset(layout) -> bytes:
    """Records as z/OS wrote them: EBCDIC text, big-endian binary at IBM widths, packed decimal."""
    out = b""
    for ident, n, c5, b, a, z, zl, note in ROWS:
        out += (ident.encode("cp037") + n.to_bytes(2, "big", signed=True) + c5.to_bytes(2, "big", signed=True)
                + b.to_bytes(4, "big", signed=True) + packed(a) + zoned_trailing(z) + zoned_leading(zl)
                + note.encode("cp037"))
    assert len(out) == len(ROWS) * layout.record_length
    return out


def read_with_gnucobol(tmp_path: Path, data: bytes) -> list[str]:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 with the gnucobol-ocesql image present")
    (tmp_path / "RDR.cob").write_text(reader_program(), encoding="utf-8")
    (tmp_path / "F.DAT").write_bytes(data)
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src", IMAGE, "sh", "-c",
         "cd /tmp && cp /src/F.DAT . && cobc -x -std=default /src/RDR.cob -o p && ./p"],
        capture_output=True, timeout=300)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return run.stdout.decode("latin-1").splitlines()


def test_gnucobol_reads_the_migrated_dataset_as_the_mainframe_values(tmp_path):
    fd = CobolParser().parse(source_text() + "       PROCEDURE DIVISION.\n       M.\n           STOP RUN.\n").file_definitions[0]
    src = derive_file_layout(fd, binary_width_model=IBM_Z.width_model)
    dst = derive_file_layout(fd, binary_width_model=X86.width_model)
    definition = DatasetDefinition("MF", Organization.SEQUENTIAL, record_length=src.record_length,
                                   encoding=Encoding.EBCDIC_CP037)
    migrated, report = migrate_dataset(definition, mainframe_dataset(src), src, Encoding.ASCII, target_layout=dst,
                                       source_platform=IBM_Z, target_platform=X86)
    assert report.state == "RECONCILED" and report.success, report.failures
    assert src.record_length == dst.record_length == 27                  # same widths here; COMP-5 byte order differs
    assert migrated != mainframe_dataset(src)

    shown = read_with_gnucobol(tmp_path, migrated)
    expected = [f"{ident}|{n:+010d}|{c5:+010d}|{b:+010d}|{a:+010d}|{z:+010d}|{zl:+010d}|{note}"
                for ident, n, c5, b, a, z, zl, note in ROWS]
    assert shown == expected


def test_the_unmigrated_mainframe_bytes_are_not_readable_as_the_same_values(tmp_path):
    """The control: reading the raw mainframe bytes with the same program shows different data, so the test above
    cannot pass by accident."""
    fd = CobolParser().parse(source_text() + "       PROCEDURE DIVISION.\n       M.\n           STOP RUN.\n").file_definitions[0]
    src = derive_file_layout(fd, binary_width_model=IBM_Z.width_model)
    raw = mainframe_dataset(src)
    shown = read_with_gnucobol(tmp_path, raw)                             # a compile or run failure fails the test
    expected = [f"{ident}|{n:+010d}|{c5:+010d}|{b:+010d}|{a:+010d}|{z:+010d}|{zl:+010d}|{note}"
                for ident, n, c5, b, a, z, zl, note in ROWS]
    assert shown and shown != expected          # the program ran and printed something different

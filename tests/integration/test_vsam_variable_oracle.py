"""Differential: variable-length records written by GnuCOBOL, migrated through the RDW pipeline.

GnuCOBOL's variable record header is a 2-byte big-endian length that EXCLUDES the 4-byte header plus two
zero bytes; IBM's RDW length INCLUDES it.  They are different formats, so a GnuCOBOL file is never fed to the
RDW migration as it is: this test reads GnuCOBOL's file with its own convention, re-frames the payloads as IBM
RDW records with independent code, migrates them, and compares every migrated payload with an independent
translation of what COBOL wrote.  Evidence class: GNUCOBOL_DIFFERENTIAL for payload content and boundaries
of two record layouts, in the default and -std=ibm dialects.  It says nothing about IBM RDW semantics beyond
the documented framing.  Docker lane: RUN_DOCKER_TESTS=1 with the gnucobol-ocesql image.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import BinaryWidthModel, derive_file_layout
from engine.vsam.migrate_variable import migrate_variable_dataset
from engine.vsam.model import DatasetDefinition, Encoding, Organization, RecordFormat

ORACLE_IMAGE = "gnucobol-ocesql:latest"

RECORDS = """\
       01 HDR.
          05 H-TAG   PIC X(2).
          05 H-DATE  PIC 9(8).
       01 DET.
          05 D-ID    PIC X(4).
          05 D-AMT   PIC S9(5) COMP-3.
          05 D-NOTE  PIC X(13).
"""


def program_source() -> str:
    return (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. VAR.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        '           SELECT F ASSIGN TO "VOUT.DAT" ORGANIZATION IS SEQUENTIAL.\n'
        "       DATA DIVISION.\n       FILE SECTION.\n"
        "       FD F RECORD VARYING FROM 10 TO 20 DEPENDING ON LEN.\n" + RECORDS +
        "       WORKING-STORAGE SECTION.\n       01 LEN PIC 9(4) COMP.\n"
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           OPEN OUTPUT F.\n"
        + "".join(f"           {statement}\n" for statement in (
            'MOVE "HD" TO H-TAG.', "MOVE 20261113 TO H-DATE.", "MOVE 10 TO LEN.", "WRITE HDR.",
            'MOVE "D001" TO D-ID.', "MOVE 12345 TO D-AMT.", 'MOVE "first note" TO D-NOTE.', "MOVE 20 TO LEN.", "WRITE DET.",
            'MOVE "D002" TO D-ID.', "MOVE -999 TO D-AMT.", 'MOVE "second" TO D-NOTE.', "MOVE 20 TO LEN.", "WRITE DET.",
            'MOVE "TL" TO H-TAG.', "MOVE 3 TO H-DATE.", "MOVE 10 TO LEN.", "WRITE HDR.",
            "CLOSE F.", "STOP RUN."))
    )


def write_with_gnucobol(tmp_path: Path, std: str) -> bytes:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 with the gnucobol-ocesql image present")
    (tmp_path / "VAR.cob").write_text(program_source(), encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp_path}:/src", ORACLE_IMAGE, "sh", "-c",
         f"cd /tmp && cobc -x -std={std} /src/VAR.cob -o p && ./p && cp VOUT.DAT /src/ && chmod a+r /src/VOUT.DAT"],
        capture_output=True, timeout=300)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return (tmp_path / "VOUT.DAT").read_bytes()


def gnucobol_payloads(blob: bytes) -> list[bytes]:
    """GnuCOBOL's own framing: 2-byte big-endian PAYLOAD length (excluding the header), two zero bytes."""
    out, i = [], 0
    while i < len(blob):
        n = int.from_bytes(blob[i:i + 2], "big")
        assert blob[i + 2:i + 4] == b"\x00\x00"
        out.append(blob[i + 4:i + 4 + n])
        i += 4 + n
    return out


def ibm_rdw(payloads: list[bytes]) -> bytes:
    return b"".join((len(p) + 4).to_bytes(2, "big") + b"\x00\x00" + p for p in payloads)


def ibm_payloads(blob: bytes) -> list[bytes]:
    out, i = [], 0
    while i < len(blob):
        n = int.from_bytes(blob[i:i + 2], "big")
        out.append(blob[i + 4:i + n])
        i += n
    return out


@pytest.mark.parametrize("std,model", [("default", BinaryWidthModel.GNUCOBOL_1_2_4_8), ("ibm", BinaryWidthModel.IBM_2_4_8)])
def test_the_variable_records_gnucobol_wrote_migrate_and_reconcile(tmp_path, std, model):
    written = write_with_gnucobol(tmp_path, std)
    payloads = gnucobol_payloads(written)
    assert [len(p) for p in payloads] == [10, 20, 20, 10]                       # boundaries as COBOL wrote them
    assert written[:4] == (10).to_bytes(2, "big") + b"\x00\x00"                  # GnuCOBOL header EXCLUDES itself ...
    assert ibm_rdw(payloads)[:4] == (14).to_bytes(2, "big") + b"\x00\x00"        # ... the IBM RDW INCLUDES it

    fdef = CobolParser().parse(program_source()).file_definitions[0]
    layouts = tuple(derive_file_layout(fdef, binary_width_model=model, record_name=name) for name in ("HDR", "DET"))
    assert [l.record_length for l in layouts] == [10, 20] and all(l.supported for l in layouts)

    source = DatasetDefinition("VAR", Organization.SEQUENTIAL, record_format=RecordFormat.VARIABLE, record_length=20)
    destination, report = migrate_variable_dataset(source, ibm_rdw(payloads), layouts, Encoding.EBCDIC_CP037)
    assert report.state == "RECONCILED" and report.success, report.failures
    assert report.to_dict()["source_record_count"] == 4 and report.to_dict()["rejected_record_count"] == 0

    migrated = ibm_payloads(destination)
    assert len(migrated) == 4
    for old, new in zip(payloads, migrated):
        assert len(old) == len(new)
        if len(old) == 10:                                                        # HDR: all DISPLAY
            assert new == old.decode("ascii").encode("cp037")
        else:                                                                     # DET: text translated, packed untouched
            assert new[0:4] == old[0:4].decode("ascii").encode("cp037")
            assert new[4:7] == old[4:7]
            assert new[7:20] == old[7:20].decode("ascii").encode("cp037")
    # the packed amounts really are what COBOL stored
    assert payloads[1][4:7] == bytes([0x12, 0x34, 0x5C]) and payloads[2][4:7] == bytes([0x00, 0x99, 0x9D])

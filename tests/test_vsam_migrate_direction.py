"""The product direction: mainframe data (EBCDIC cp037, IBM platform) to an ASCII target.

Earlier slices migrated ASCII to EBCDIC because the oracle writes ASCII.  A real migration reads data a
mainframe wrote: EBCDIC text, big-endian binary at IBM widths.  This file pins that direction end to end:
text is translated to ASCII (a byte with no ASCII counterpart rejects the record), binary fields are
converted between the two platforms, a KSDS is loaded in ASCII key order, and the independent
reconciliation agrees.  Only ASCII<->EBCDIC cp037 is supported; anything else is refused by name.
Dependency-free (pytest only).
"""
from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import derive_file_layout
from engine.vsam.migrate import migrate_dataset
from engine.vsam.migrate_variable import migrate_variable_dataset
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization, RecordFormat
from engine.vsam.platform import platform

IBM_Z = platform("IBM_ZOS")
X86 = platform("GNUCOBOL_X86_DEFAULT")

FD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO \"F.DAT\".\n"
    "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n"
    "       01 REC.\n"
    "          05 ID-X  PIC X(4).\n"
    "          05 N     PIC S9(2) COMP.\n"
    "          05 AMT   PIC S9(5) COMP-3.\n"
    "          05 C5    PIC S9(4) COMP-5.\n"
    "          05 NOTE  PIC X(3).\n"
    "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n"
)


def layout_for(plat):
    return derive_file_layout(CobolParser().parse(FD).file_definitions[0], binary_width_model=plat.width_model)


SRC, DST = layout_for(IBM_Z), layout_for(X86)        # 4+2+3+2+3 = 14 and 4+1+3+2+3 = 13


def mainframe_record(ident: str, n: int, amount: bytes, c5: int, note: str) -> bytes:
    """A record as z/OS wrote it: EBCDIC text, big-endian binary (COMP-5 too), IBM widths."""
    return (ident.encode("cp037") + n.to_bytes(2, "big", signed=True) + amount + c5.to_bytes(2, "big", signed=True)
            + note.encode("cp037"))


def source_def(**kw) -> DatasetDefinition:
    return DatasetDefinition("MF", Organization.KSDS, record_length=SRC.record_length, encoding=Encoding.EBCDIC_CP037,
                             primary_key=KeyDefinition(0, 4), **kw)


def migrate(data: bytes, defn=None, **kw):
    options = dict(target_layout=DST, source_platform=IBM_Z, target_platform=X86)
    options.update(kw)
    return migrate_dataset(defn or source_def(), data, SRC, Encoding.ASCII, **options)


def test_a_mainframe_ksds_becomes_an_ascii_x86_dataset_in_ascii_key_order():
    src = (mainframe_record("a001", 7, bytes([0x12, 0x34, 0x5C]), 300, "abc")
           + mainframe_record("A001", -5, bytes([0x99, 0x99, 0x9D]), -300, "def")
           + mainframe_record("1001", 99, bytes([0x00, 0x00, 0x0C]), 0, "xyz"))      # EBCDIC order: a001, A001, 1001
    out, report = migrate(src)
    assert report.state == "RECONCILED" and report.success, report.failures
    assert (DST.record_length, len(out)) == (13, 3 * 13)
    keys = [out[i:i + 4].decode("ascii") for i in range(0, len(out), 13)]
    assert keys == ["1001", "A001", "a001"]                                       # ASCII order: digits, upper, lower
    first = out[:13]                                                              # key 1001
    assert first[4:5] == (99).to_bytes(1, "big", signed=True)                      # COMP narrowed 2 -> 1 byte
    assert first[5:8] == bytes([0x00, 0x00, 0x0C])                                 # packed untouched
    assert first[8:10] == (0).to_bytes(2, "little", signed=True)                   # COMP-5 big -> little
    assert first[10:13] == b"xyz"
    last = out[26:]                                                               # key a001
    assert int.from_bytes(last[8:10], "little", signed=True) == 300 and last[10:13] == b"abc"


def test_the_report_states_the_direction_and_every_conversion_decision():
    _, report = migrate(mainframe_record("K001", 7, bytes([0x12, 0x34, 0x5C]), 5, "abc"))
    data = report.to_dict()
    assert data["source_encoding"] == "EBCDIC_CP037" and data["destination_encoding"] == "ASCII"
    assert data["source_platform"]["name"] == "IBM_ZOS" and data["target_platform"]["name"] == "GNUCOBOL_X86_DEFAULT"
    conversions = {c["path"]: c for c in data["binary_conversions"]}
    assert conversions["REC.N"]["source"] == {"byte_order": "big", "bytes": 2}
    assert conversions["REC.N"]["target"] == {"byte_order": "big", "bytes": 1}
    assert conversions["REC.C5"]["source"]["byte_order"] == "big" and conversions["REC.C5"]["target"]["byte_order"] == "little"


def test_an_ebcdic_character_with_no_ascii_counterpart_rejects_the_record_with_the_field_named():
    bad = mainframe_record("K002", 1, bytes([0x00, 0x00, 0x0C]), 1, "abc")[:-1] + bytes([0xB1])   # 0xB1 is a non-ASCII character
    out, report = migrate(mainframe_record("K001", 1, bytes([0x00, 0x00, 0x0C]), 1, "abc") + bad)
    data = report.to_dict()
    assert report.state == "RECONCILED" and data["rejected_record_count"] == 1
    assert "REC.NOTE" in data["rejected"][0]["reason"] and "no counterpart in ASCII" in data["rejected"][0]["reason"]
    assert len(out) == 13


def test_a_duplicate_key_and_a_corrupt_packed_field_are_rejected_in_this_direction_too():
    src = (mainframe_record("K001", 1, bytes([0x00, 0x00, 0x0C]), 1, "one")
           + mainframe_record("K001", 2, bytes([0x00, 0x00, 0x0C]), 2, "two")
           + mainframe_record("K003", 3, bytes([0x1A, 0x00, 0x0C]), 3, "bad"))
    out, report = migrate(src)
    data = report.to_dict()
    assert report.state == "RECONCILED" and [r["record_number"] for r in data["rejected"]] == [2, 3]
    assert data["duplicate_key_count"] == 1 and len(out) == 13


def test_a_comp_value_that_does_not_fit_the_picture_is_rejected():
    out, report = migrate(mainframe_record("K001", 100, bytes([0x00, 0x00, 0x0C]), 1, "abc"))   # S9(2) cannot hold 100
    assert report.state == "RECONCILED" and "exceeds the 2 digits" in report.to_dict()["rejected"][0]["reason"]


def test_a_tampered_destination_is_failed_by_the_independent_check():
    from engine.vsam.migrate import reconcile_destination

    src = mainframe_record("K001", 7, bytes([0x12, 0x34, 0x5C]), 5, "abc")
    out, _ = migrate(src)
    bad = out[:10] + b"X" + out[11:]
    again = reconcile_destination(source_def(), src, SRC, Encoding.ASCII, bad, target_layout=DST,
                                  source_platform=IBM_Z, target_platform=X86)
    assert again.state == "FAILED"


def test_interrupt_and_resume_work_in_this_direction():
    src = b"".join(mainframe_record(f"K{i:03d}", i, bytes([0x00, 0x00, 0x0C]), i, "abc") for i in range(1, 8))
    full, _ = migrate(src)
    part, part_report = migrate(src, stop_after=3)
    assert part_report.state == "INTERRUPTED"
    resumed, report = migrate(src, partial_output=part, resume_after=3)
    assert resumed == full and report.state == "RECONCILED"


def test_the_same_encoding_on_both_sides_is_still_refused():
    out, report = migrate_dataset(source_def(), b"", SRC, Encoding.EBCDIC_CP037, target_layout=DST,
                                  source_platform=IBM_Z, target_platform=X86)
    assert out == b"" and report.state == "REFUSED" and any("ASCII<->EBCDIC_CP037" in f for f in report.failures)


# --- variable-length records, same direction ------------------------------------------------------------------------------------

def test_a_variable_length_mainframe_dataset_migrates_to_ascii():
    program = CobolParser().parse(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO \"F.DAT\".\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n"
        "       01 HDR.\n          05 H-TAG PIC X(2).\n          05 H-DATE PIC 9(8).\n"
        "       01 DET.\n          05 D-ID PIC X(4).\n          05 D-AMT PIC S9(5) COMP-3.\n          05 D-NOTE PIC X(13).\n"
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n")
    fdef = program.file_definitions[0]
    layouts = tuple(derive_file_layout(fdef, binary_width_model=IBM_Z.width_model, record_name=n) for n in ("HDR", "DET"))

    def rdw(payload: bytes) -> bytes:
        return (len(payload) + 4).to_bytes(2, "big") + b"\x00\x00" + payload

    src = rdw("HD20261113".encode("cp037")) + rdw("D001".encode("cp037") + bytes([0x12, 0x34, 0x5C])
                                                  + "first note...".encode("cp037"))
    definition = DatasetDefinition("V", Organization.SEQUENTIAL, record_format=RecordFormat.VARIABLE, record_length=20,
                                   encoding=Encoding.EBCDIC_CP037)
    out, report = migrate_variable_dataset(definition, src, layouts, Encoding.ASCII)
    assert report.state == "RECONCILED", report.failures
    assert out[4:14] == b"HD20261113" and out[14 + 4:14 + 8] == b"D001" and out[14 + 8:14 + 11] == bytes([0x12, 0x34, 0x5C])
    assert out[14 + 11:] == b"first note..."


@pytest.mark.parametrize("source_encoding,destination", [(Encoding.ASCII, Encoding.ASCII), (Encoding.EBCDIC_CP037, Encoding.EBCDIC_CP037)])
def test_variable_length_with_the_same_encoding_is_refused(source_encoding, destination):
    layouts = (derive_file_layout(CobolParser().parse(FD).file_definitions[0], binary_width_model=IBM_Z.width_model),)
    definition = DatasetDefinition("V", Organization.SEQUENTIAL, record_format=RecordFormat.VARIABLE, record_length=20,
                                   encoding=source_encoding)
    out, report = migrate_variable_dataset(definition, b"", layouts, destination)
    assert out == b"" and report.state == "REFUSED" and any("ASCII<->EBCDIC_CP037" in f for f in report.failures)

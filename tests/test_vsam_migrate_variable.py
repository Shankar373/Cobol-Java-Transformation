"""G-28 (RDW): variable-length datasets are migrated in a bounded, deterministic way - or refused by name.

Supported: IBM RDW framing (4-byte descriptor, length *including* the descriptor, two reserved zero bytes);
sequential and entry-sequenced datasets; each record is converted with the record layout whose length
equals its payload length, so the layout lengths must be unique (no discriminator is guessed); a record
of any other length is rejected by name.  Not supported, refused by name: binary fields, KSDS (key
extraction across several layouts), RRDS.  Dependency-free (pytest only).
"""
from __future__ import annotations

import json

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import BinaryWidthModel, derive_file_layout
from engine.vsam.migrate_variable import migrate_variable_dataset, reconcile_variable_destination
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization, RecordFormat

IBM = BinaryWidthModel.IBM_2_4_8


def fd(*records: str) -> str:
    body = "\n".join("       " + r for r in records)
    return ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO \"F.DAT\".\n"
            "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n" + body + "\n"
            "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n")


HDR = ("01 HDR.", "   05 H-TAG PIC X(2).", "   05 H-DATE PIC 9(8).")                                    # 10 bytes
DET = ("01 DET.", "   05 D-ID PIC X(4).", "   05 D-AMT PIC S9(5) COMP-3.", "   05 D-NOTE PIC X(13).")  # 4 + 3 + 13 = 20


def layouts(*groups, model=IBM):
    program = CobolParser().parse(fd(*(line for group in groups for line in group)))
    fdef = program.file_definitions[0]
    return tuple(derive_file_layout(fdef, binary_width_model=model, record_name=g[0].split()[1].rstrip("."))
                 for g in groups)


HDR_L, DET_L = layouts(HDR, DET)


def rdw(payload: bytes) -> bytes:
    return (len(payload) + 4).to_bytes(2, "big") + b"\x00\x00" + payload


def hdr(tag="HD", date="20261113") -> bytes:
    return rdw((tag + date).encode())


def det(ident="D001", amount=bytes([0x12, 0x34, 0x5C]), note="ABCDEFGHIJKLM") -> bytes:
    return rdw(ident.encode() + amount + note.encode())


def dataset(organization=Organization.SEQUENTIAL, **kw) -> DatasetDefinition:
    return DatasetDefinition("VAR", organization, record_format=RecordFormat.VARIABLE, record_length=20, **kw)


def migrate(data, defn=None, ls=(HDR_L, DET_L), **kw):
    return migrate_variable_dataset(defn or dataset(), data, ls, Encoding.EBCDIC_CP037, **kw)


def payloads(blob: bytes) -> list[bytes]:
    out, i = [], 0
    while i < len(blob):
        n = int.from_bytes(blob[i:i + 2], "big")
        assert blob[i + 2:i + 4] == b"\x00\x00"
        out.append(blob[i + 4:i + n])
        i += n
    return out


def test_the_layouts_have_distinct_lengths():
    assert (HDR_L.record_length, DET_L.record_length) == (10, 20)


# --- the good path -------------------------------------------------------------------------------------------

def test_a_mixed_variable_file_is_migrated_record_by_record_in_arrival_order():
    src = hdr() + det("D001") + det("D002", note="nnnnnnnnnnnnn") + hdr("TL", "00000002")
    out, report = migrate(src)
    assert report.state == "RECONCILED" and report.success, report.failures
    got = payloads(out)
    assert len(got) == 4
    assert got[0] == "HD20261113".encode("cp037") and got[3] == "TL00000002".encode("cp037")
    assert got[1][0:4] == "D001".encode("cp037") and got[1][4:7] == bytes([0x12, 0x34, 0x5C])   # packed untouched
    assert got[1][7:20] == "ABCDEFGHIJKLM".encode("cp037")
    # the RDW is rewritten for the (unchanged) payload length: length including the descriptor, reserved zeros
    assert out[:4] == (14).to_bytes(2, "big") + b"\x00\x00"


def test_the_report_names_every_layout_and_the_selection_rule():
    _, report = migrate(hdr() + det())
    data = report.to_dict()
    assert data["record_format"] == "VARIABLE" and data["source"]["organization"] == "SEQUENTIAL"
    assert [b["record_name"] for b in data["layout"]["record_layouts"]] == ["HDR", "DET"]
    assert "exact payload length" in data["layout"]["selection_rule"]
    assert (data["source_record_count"], data["destination_record_count"], data["rejected_record_count"]) == (2, 2, 0)
    json.dumps(data)


def test_an_entry_sequenced_variable_dataset_keeps_entry_order_and_says_rba_is_not_modelled():
    out, report = migrate(det("ZZZZ") + det("AAAA"), dataset(Organization.ESDS))
    assert report.state == "RECONCILED" and payloads(out)[0][:4] == "ZZZZ".encode("cp037")
    assert any("RBA" in w for w in report.warnings)


def test_the_migration_is_deterministic():
    src = hdr() + det() + det("D002")
    assert json.dumps(migrate(src)[1].to_dict(), sort_keys=True) == json.dumps(migrate(src)[1].to_dict(), sort_keys=True)


# --- rejection ------------------------------------------------------------------------------------------------------

def test_a_record_whose_length_matches_no_layout_is_rejected_by_name_and_confirmed():
    odd = rdw(b"X" * 15)
    out, report = migrate(hdr() + odd + det())
    data = report.to_dict()
    assert report.state == "RECONCILED"
    assert data["rejected_record_count"] == 1 and data["rejected"][0]["record_number"] == 2
    assert "no record layout has length 15" in data["rejected"][0]["reason"]
    assert len(payloads(out)) == 2


def test_a_corrupt_packed_field_is_rejected_with_the_field_named():
    bad = det("D002", amount=bytes([0x1A, 0x34, 0x5C]))
    out, report = migrate(det("D001") + bad)
    data = report.to_dict()
    assert report.state == "RECONCILED" and data["rejected_record_count"] == 1
    assert "non-decimal digit" in data["rejected"][0]["reason"] and len(payloads(out)) == 1


# --- refusals before anything is converted -----------------------------------------------------------------------------

@pytest.mark.parametrize("blob,phrase", [
    (hdr() + b"\x00\x0e\x00", "truncated record descriptor"),
    (hdr() + b"\x00\x08\x00\x01abcd", "non-zero RDW reserved field"),
    (hdr() + b"\x00\x02\x00\x00", "invalid length"),
    (hdr() + (60).to_bytes(2, "big") + b"\x00\x00ab", "invalid length"),
])
def test_a_malformed_rdw_refuses_the_whole_dataset(blob, phrase):
    out, report = migrate(blob)
    assert out == b"" and report.state == "REFUSED" and any(phrase in f for f in report.failures)


def test_two_layouts_of_the_same_length_are_refused_because_nothing_tells_them_apart():
    same = layouts(("01 A.", "   05 A1 PIC X(10)."), ("01 B.", "   05 B1 PIC 9(10)."))
    out, report = migrate(hdr(), ls=same)
    assert out == b"" and report.state == "REFUSED" and any("same length" in f and "discriminator" in f for f in report.failures)


def test_a_binary_field_in_a_layout_is_refused_by_name():
    binary = layouts(("01 A.", "   05 N PIC S9(4) COMP.", "   05 T PIC X(4)."))
    out, report = migrate(hdr(), ls=binary)
    assert out == b"" and report.state == "REFUSED" and any("binary" in f and "variable-length" in f for f in report.failures)


@pytest.mark.parametrize("defn,phrase", [
    (dataset(Organization.KSDS, primary_key=KeyDefinition(0, 4)), "KSDS"),
    (DatasetDefinition("R", Organization.RRDS, record_format=RecordFormat.VARIABLE, record_length=20), "RRDS"),
    (DatasetDefinition("S", Organization.SEQUENTIAL, record_length=20), "variable-length"),
    (DatasetDefinition("S", Organization.SEQUENTIAL, record_format=RecordFormat.VARIABLE, record_length=20,
                       encoding=Encoding.EBCDIC_CP037), "ASCII source"),
])
def test_unsupported_dataset_kinds_are_refused_by_name(defn, phrase):
    out, report = migrate(hdr(), defn)
    assert out == b"" and report.state == "REFUSED" and any(phrase in f for f in report.failures)


def test_a_layout_longer_than_the_dataset_maximum_is_refused():
    out, report = migrate(hdr(), DatasetDefinition("S", Organization.SEQUENTIAL, record_format=RecordFormat.VARIABLE,
                                                   record_length=12))
    assert out == b"" and report.state == "REFUSED" and any("longer than" in f for f in report.failures)


def test_no_layouts_at_all_is_refused():
    out, report = migrate(hdr(), ls=())
    assert out == b"" and report.state == "REFUSED"


# --- restart --------------------------------------------------------------------------------------------------------------

def test_an_interrupted_variable_migration_resumes_to_the_same_result():
    src = b"".join(det(f"D{i:03d}") if i % 2 else hdr("HD", f"{i:08d}") for i in range(8))
    full, _ = migrate(src)
    part, part_report = migrate(src, stop_after=3)
    assert part_report.state == "INTERRUPTED" and part_report.to_dict()["checkpoint"]["resume_point"] == 3
    assert len(payloads(part)) == 3
    resumed, report = migrate(src, partial_output=part, resume_after=3)
    assert resumed == full and report.state == "RECONCILED"


def test_a_torn_partial_output_is_refused_on_resume():
    src = det("D001") + det("D002") + det("D003")
    part, _ = migrate(src, stop_after=2)
    out, report = migrate(src, partial_output=part[:-1], resume_after=2)
    assert out == b"" and report.state == "REFUSED" and any("partial output" in f for f in report.failures)


def test_resume_accounts_for_a_record_rejected_before_the_interruption():
    src = rdw(b"X" * 15) + det("D002") + det("D003") + det("D004")
    full, _ = migrate(src)
    part, _ = migrate(src, stop_after=2)
    resumed, report = migrate(src, partial_output=part, resume_after=2)
    assert resumed == full and report.to_dict()["rejected"][0]["record_number"] == 1


# --- independent reconciliation --------------------------------------------------------------------------------------------

def test_a_tampered_destination_is_reported_failed_by_the_independent_check():
    src = hdr() + det("D001")
    out, report = migrate(src)
    assert report.success
    tampered = bytearray(out)
    tampered[-3] ^= 0xFF
    again = reconcile_variable_destination(dataset(), src, (HDR_L, DET_L), Encoding.EBCDIC_CP037, bytes(tampered))
    assert again.state == "FAILED" and not again.success


def test_a_dropped_record_is_reported_failed():
    src = hdr() + det("D001")
    out, _ = migrate(src)
    again = reconcile_variable_destination(dataset(), src, (HDR_L, DET_L), Encoding.EBCDIC_CP037, out[:14])
    assert again.state == "FAILED" and any("destination holds 1" in f for f in again.failures)

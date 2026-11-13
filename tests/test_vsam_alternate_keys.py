"""G-28: alternate keys are validated, ESDS RBA identity is refused on request, RRDS is blocked by name.

What is claimed: for each declared alternate key the migration checks the key-to-record relationship that
can be checked from the data (a *unique* alternate key must not repeat; a non-unique one is counted) and
reports it; the independent reconciliation re-checks the destination.  What is not claimed: that an
alternate-index structure (or a path) is built - the report still lists that under unsupported semantics.
Dependency-free (pytest only).
"""
from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import BinaryWidthModel, derive_file_layout
from engine.vsam.migrate import migrate_dataset, reconcile_destination
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization
from engine.vsam.platform import platform

IBM_Z = platform("IBM_ZOS")

FD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO \"F.DAT\".\n"
    "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n"
    "       01 REC.\n"
    "          05 ID-X   PIC X(4).\n"
    "          05 DEPT   PIC X(3).\n"
    "          05 EMAIL  PIC X(6).\n"
    "          05 AMT    PIC S9(3) COMP-3.\n"
    "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n"
)
LAYOUT = derive_file_layout(CobolParser().parse(FD).file_definitions[0], binary_width_model=BinaryWidthModel.IBM_2_4_8)
LENGTH = LAYOUT.record_length                       # 4 + 3 + 6 + 2 = 15


def record(ident: str, dept: str, email: str, amount: bytes = bytes([0x01, 0x2C])) -> bytes:
    return ident.encode() + dept.encode() + email.encode() + amount


def definition(organization=Organization.KSDS, **kw) -> DatasetDefinition:
    key = KeyDefinition(0, 4) if organization is Organization.KSDS else None
    return DatasetDefinition("SRC", organization, record_length=LENGTH, primary_key=key, **kw)


DEPT = KeyDefinition(4, 3, unique=False)            # non-unique alternate key
EMAIL = KeyDefinition(7, 6, unique=True)            # unique alternate key


def migrate(data, defn=None, **kw):
    return migrate_dataset(defn or definition(), data, LAYOUT, Encoding.EBCDIC_CP037, **kw)


def test_a_non_unique_alternate_key_is_counted_and_its_duplicates_are_kept():
    src = record("K001", "ENG", "a@x.co") + record("K002", "ENG", "b@x.co") + record("K003", "OPS", "c@x.co")
    out, report = migrate(src, definition(alternate_keys=(DEPT,)))
    assert report.state == "RECONCILED" and len(out) == 3 * LENGTH
    index = report.to_dict()["alternate_indexes"][0]
    assert index == {"index": 1, "offset": 4, "length": 3, "unique": False, "distinct_keys": 2,
                     "duplicate_records": 1, "records": 3}


def test_a_unique_alternate_key_that_repeats_rejects_the_later_record_first_occurrence_wins():
    src = record("K001", "ENG", "same@x") + record("K002", "ENG", "other@") + record("K003", "OPS", "same@x")
    out, report = migrate(src, definition(alternate_keys=(EMAIL,)))
    data = report.to_dict()
    assert report.state == "RECONCILED"
    assert data["rejected_record_count"] == 1 and data["rejected"][0]["record_number"] == 3
    assert "unique alternate key 1" in data["rejected"][0]["reason"]
    assert data["alternate_indexes"][0]["distinct_keys"] == 2 and data["alternate_indexes"][0]["duplicate_records"] == 0
    assert len(out) == 2 * LENGTH


def test_a_primary_duplicate_does_not_hold_its_alternate_key():
    # record 2 repeats K001 (primary) and is rejected for that; its e-mail must stay available to record 3
    src = record("K001", "ENG", "a@x.co") + record("K001", "ENG", "dup@x0") + record("K003", "OPS", "dup@x0")
    out, report = migrate(src, definition(alternate_keys=(EMAIL,)))
    data = report.to_dict()
    assert report.state == "RECONCILED"
    assert [r["record_number"] for r in data["rejected"]] == [2] and data["destination_record_count"] == 2


def test_the_report_still_says_the_index_structure_is_not_built():
    _, report = migrate(record("K001", "ENG", "a@x.co"), definition(alternate_keys=(DEPT, EMAIL)))
    assert any("not built" in s and "2 alternate index" in s for s in report.unsupported_semantics)


def test_alternate_keys_work_for_entry_sequenced_datasets_too():
    src = record("K001", "ENG", "same@x") + record("K002", "ENG", "same@x")
    out, report = migrate(src, definition(Organization.ESDS, alternate_keys=(EMAIL,)))
    assert report.state == "RECONCILED" and report.to_dict()["rejected_record_count"] == 1
    assert len(out) == LENGTH


def test_the_independent_reconciliation_rejects_a_destination_that_repeats_a_unique_alternate_key():
    src = record("K001", "ENG", "a@x.co") + record("K002", "ENG", "b@x.co")
    out, report = migrate(src, definition(alternate_keys=(EMAIL,)))
    assert report.success
    pieces = [bytearray(out[i:i + LENGTH]) for i in range(0, len(out), LENGTH)]
    pieces[1][7:13] = pieces[0][7:13]                                  # force the same (EBCDIC) e-mail twice
    tampered = b"".join(bytes(p) for p in pieces)
    again = reconcile_destination(definition(alternate_keys=(EMAIL,)), src, LAYOUT, Encoding.EBCDIC_CP037, tampered)
    assert again.state == "FAILED" and any("unique alternate key 1" in f for f in again.failures)


def test_an_unjustified_rejection_for_an_alternate_key_is_not_a_full_reconciliation():
    from engine.vsam.reconcile import RejectedRecord

    src = record("K001", "ENG", "a@x.co") + record("K002", "ENG", "b@x.co")
    out, _ = migrate(src[:LENGTH], definition(alternate_keys=(EMAIL,)))           # destination lacks record 2
    again = reconcile_destination(definition(alternate_keys=(EMAIL,)), src, LAYOUT, Encoding.EBCDIC_CP037, out,
                                  rejected=(RejectedRecord(2, "dropped"),))
    assert again.state == "RECONCILED_PARTIAL"                                      # b@x.co is not a repeat: unverifiable


def test_alternate_keys_follow_a_platform_shift():
    fd = FD.replace("          05 ID-X   PIC X(4).\n", "          05 N      PIC S9(2) COMP.\n          05 ID-X   PIC X(4).\n")
    src_l = derive_file_layout(CobolParser().parse(fd).file_definitions[0], binary_width_model=platform("GNUCOBOL_X86_DEFAULT").width_model)
    dst_l = derive_file_layout(CobolParser().parse(fd).file_definitions[0], binary_width_model=IBM_Z.width_model)
    n = src_l.record_length
    shifted = DatasetDefinition("S", Organization.KSDS, record_length=n, primary_key=KeyDefinition(1, 4),
                                alternate_keys=(KeyDefinition(5, 3, unique=False),))
    data = bytes([5]) + b"K001ENGa@x.co" + bytes([0x01, 0x2C])
    out, report = migrate_dataset(shifted, data, src_l, Encoding.EBCDIC_CP037, target_layout=dst_l,
                                  source_platform=platform("GNUCOBOL_X86_DEFAULT"), target_platform=IBM_Z)
    assert report.state == "RECONCILED", report.failures
    assert report.to_dict()["alternate_indexes"][0]["offset"] == 6      # moved from 5 to 6 with the widened COMP


def test_esds_rba_identity_is_refused_when_the_caller_depends_on_it():
    out, report = migrate(record("K001", "ENG", "a@x.co"), definition(Organization.ESDS), require_rba_preserved=True)
    assert out == b"" and report.state == "REFUSED"
    assert any("RBA" in f and "cannot be preserved" in f for f in report.failures)


def test_esds_without_an_rba_dependency_migrates_in_entry_order_and_says_so():
    src = record("ZZZZ", "ENG", "a@x.co") + record("AAAA", "OPS", "b@x.co")
    out, report = migrate(src, definition(Organization.ESDS))
    assert report.state == "RECONCILED" and out[:4] == "ZZZZ".encode("cp037")
    assert any("RBA" in w for w in report.warnings)


def test_rrds_is_blocked_by_name_with_the_reason():
    out, report = migrate(record("K001", "ENG", "a@x.co"), DatasetDefinition("R", Organization.RRDS, record_length=LENGTH))
    assert out == b"" and report.state == "REFUSED"
    assert any("BLOCKED" in f and "RRDS" in f and "IBM" in f for f in report.failures)


@pytest.mark.parametrize("flag", [True, False])
def test_the_rba_flag_does_not_affect_other_organizations(flag):
    out, report = migrate(record("K001", "ENG", "a@x.co"), require_rba_preserved=flag)
    assert report.state == "RECONCILED"

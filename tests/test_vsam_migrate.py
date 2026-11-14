"""Stage 1 vertical slice: COBOL record description + data file -> layout -> migration -> reconciliation -> report.

``engine.vsam.migrate.migrate_dataset`` drives the existing pieces (layout derivation, field-aware
conversion, KSDS load order, independent reconciliation) and returns the converted bytes with a
machine-readable report.  Only a fully checked reconciliation is a success; ``RECONCILED_PARTIAL``
and ``FAILED`` never read as one, and anything the pipeline cannot do is REFUSED by name before a
byte is converted.  Dependency-free (pytest only).
"""
from __future__ import annotations

import json

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.collation import to_stored_bytes
from engine.vsam.layout import BinaryWidthModel, derive_file_layout
from engine.vsam.migrate import MigrationReport, migrate_dataset
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization, RecordFormat
from engine.vsam.platform import platform

IBM = BinaryWidthModel.IBM_2_4_8

FD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
    '           SELECT F ASSIGN TO "F.DAT".\n'
    "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n"
    "       01 REC.\n"
    "          05 ID-X PIC X(4).\n"
    "          05 AMT PIC S9(5) COMP-3.\n"
    "          05 CNT PIC S9(4) COMP.\n"
    "          05 NOTE PIC X(3).\n"
    "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n"
)
LENGTH = 4 + 3 + 2 + 3


def layout():
    return derive_file_layout(CobolParser().parse(FD).file_definitions[0], binary_width_model=IBM)


def record(ident: str, amount: bytes = bytes([0x12, 0x34, 0x5C]), count: int = 7, note: str = "ok ") -> bytes:
    return ident.encode("ascii") + amount + count.to_bytes(2, "big") + note.encode("ascii")


def source_def(organization=Organization.KSDS, **kw) -> DatasetDefinition:
    key = KeyDefinition(0, 4) if organization is Organization.KSDS else None
    return DatasetDefinition("SRC", organization, record_length=LENGTH, primary_key=key, **kw)


IBM_Z = platform("IBM_ZOS")


def migrate(data: bytes, definition: DatasetDefinition | None = None, **kw):
    # this layout has a COMP field, so the platforms are explicit (here: the same IBM platform on both sides)
    options = dict(target_layout=layout(), source_platform=IBM_Z, target_platform=IBM_Z)
    options.update(kw)
    return migrate_dataset(definition or source_def(), data, layout(), Encoding.EBCDIC_CP037, **options)


# --- the good path --------------------------------------------------------------------------------

def test_a_clean_ksds_migration_is_reconciled_in_ebcdic_key_order_with_a_complete_report():
    src = record("1001") + record("A001") + record("a001")          # ASCII order
    destination, report = migrate(src)
    assert report.state == "RECONCILED" and report.success is True
    keys = [destination[i:i + 4] for i in range(0, len(destination), LENGTH)]
    assert keys == [s.encode("cp037") for s in ("a001", "A001", "1001")]   # EBCDIC order
    data = report.to_dict()
    assert data["schema"] == "systemaops.migration_report" and data["schema_version"] == 1
    assert (data["source_record_count"], data["destination_record_count"], data["converted_record_count"],
            data["rejected_record_count"], data["duplicate_key_count"]) == (3, 3, 3, 0, 0)
    assert data["source_encoding"] == "ASCII" and data["destination_encoding"] == "EBCDIC_CP037"
    assert data["record_format"] == "FIXED" and data["source"]["organization"] == "KSDS"
    assert data["layout"]["identity"] == layout().identity and data["layout"]["binary_width_model"] == "IBM_2_4_8"
    assert len(data["source_sha256"]) == 64 and len(data["destination_sha256"]) == 64
    assert data["source_sha256"] != data["destination_sha256"]
    assert data["checkpoint"]["resume_point"] == 3 and len(data["checkpoint"]["identity"]) == 64
    assert data["rejected"] == [] and data["failures"] == [] and data["unsupported_semantics"] == []


def test_packed_and_binary_bytes_survive_and_text_is_translated():
    src = record("K001", amount=bytes([0x99, 0x99, 0x9D]), count=65000, note="abc")
    destination, report = migrate(src)
    assert report.success
    assert destination[0:4] == "K001".encode("cp037") and destination[4:9] == src[4:9]
    assert destination[9:12] == "abc".encode("cp037")


def test_the_report_is_deterministic():
    src = record("K001") + record("K002")
    a = migrate(src)[1].to_dict()
    b = migrate(src)[1].to_dict()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_an_entry_sequenced_migration_keeps_arrival_order_and_says_what_it_does_not_model():
    src = record("ZZZZ") + record("AAAA")
    destination, report = migrate(src, source_def(Organization.ESDS))
    assert report.success and destination[0:4] == "ZZZZ".encode("cp037")
    assert any("RBA" in w for w in report.warnings)


def test_an_alternate_character_key_over_a_packed_or_binary_field_is_refused():
    from engine.vsam.model import KeyKind

    for offset, length in ((4, 3), (7, 2)):                                   # AMT (COMP-3), CNT (COMP)
        definition = source_def(alternate_keys=(KeyDefinition(offset, length, unique=False),))   # CHARACTER by default
        destination, report = migrate(record("K001"), definition)
        assert not report.success and destination == b""
        assert any("alternate key 1" in f and "CHARACTER" in f.upper() for f in report.failures), report.failures
    ok = source_def(alternate_keys=(KeyDefinition(7, 2, kind=KeyKind.BINARY, unique=False),))
    assert migrate(record("K001"), ok)[1].success


def test_alternate_indexes_are_named_as_not_migrated():
    definition = source_def(alternate_keys=(KeyDefinition(7, 2, kind=__import__("engine.vsam.model", fromlist=["KeyKind"]).KeyKind.BINARY, unique=False),))
    _, report = migrate(record("K001"), definition)
    assert any("alternate" in s for s in report.to_dict()["unsupported_semantics"])
    assert report.state == "RECONCILED"          # the data is reconciled; the missing semantics are stated, not hidden


# --- rejections, duplicates ---------------------------------------------------------------------------

def test_an_unconvertible_record_is_rejected_with_a_reason_and_confirmed_independently():
    bad = record("B002", amount=bytes([0x12, 0x34, 0x45]))                 # invalid sign nibble
    destination, report = migrate(record("A001") + bad + record("C003"))
    assert report.state == "RECONCILED" and report.success
    data = report.to_dict()
    assert data["rejected_record_count"] == 1 and data["converted_record_count"] == 2
    assert data["rejected"] == [{"record_number": 2, "reason": data["rejected"][0]["reason"]}]
    assert "invalid sign nibble" in data["rejected"][0]["reason"]
    assert len(destination) == 2 * LENGTH


def test_a_duplicate_primary_key_is_rejected_first_occurrence_wins():
    destination, report = migrate(record("K001", note="1st") + record("K002") + record("K001", note="2nd"))
    data = report.to_dict()
    assert report.state == "RECONCILED"
    assert (data["duplicate_key_count"], data["rejected_record_count"], data["destination_record_count"]) == (1, 1, 2)
    assert data["rejected"][0]["record_number"] == 3 and "duplicate" in data["rejected"][0]["reason"]
    assert "1st".encode("cp037") in destination and "2nd".encode("cp037") not in destination


# --- refusals happen before any conversion -----------------------------------------------------------------

def test_an_unsupported_layout_is_refused_with_its_diagnostics_and_converts_nothing():
    bad_fd = FD.replace("05 CNT PIC S9(4) COMP.", "05 CNT PIC S9(4) COMP SYNC.")
    bad_layout = derive_file_layout(CobolParser().parse(bad_fd).file_definitions[0], binary_width_model=IBM)
    destination, report = migrate_dataset(source_def(), record("K001"), bad_layout, Encoding.EBCDIC_CP037)
    assert destination == b"" and report.state == "REFUSED" and not report.success
    assert any(d["code"] == "SYNCHRONIZED" for d in report.to_dict()["layout"]["diagnostics"])


def test_a_dataset_whose_record_length_differs_from_the_layout_is_refused():
    definition = DatasetDefinition("SRC", Organization.KSDS, record_length=LENGTH + 1, primary_key=KeyDefinition(0, 4))
    destination, report = migrate(record("K001") + b" ", definition)
    assert destination == b"" and report.state == "REFUSED"
    assert any("record length" in f for f in report.failures)


def test_a_key_outside_the_character_fields_of_the_layout_is_refused():
    definition = DatasetDefinition("SRC", Organization.KSDS, record_length=LENGTH, primary_key=KeyDefinition(5, 2))
    _, report = migrate(record("K001"), definition)
    assert report.state == "REFUSED" and any("key" in f for f in report.failures)


@pytest.mark.parametrize("definition,phrase", [
    (DatasetDefinition("S", Organization.KSDS, record_format=RecordFormat.VARIABLE, record_length=LENGTH,
                       primary_key=KeyDefinition(0, 4)), "variable-length"),
    (DatasetDefinition("S", Organization.RRDS, record_length=LENGTH), "RRDS"),
    (DatasetDefinition("S", Organization.KSDS, record_length=LENGTH, primary_key=KeyDefinition(0, 4),
                       encoding=Encoding.EBCDIC_CP037), "ASCII<->EBCDIC_CP037"),
])
def test_unmodelled_dataset_kinds_are_refused_by_name(definition, phrase):
    destination, report = migrate(record("K001"), definition)
    assert destination == b"" and report.state == "REFUSED" and any(phrase in f for f in report.failures)


def test_truncated_input_is_refused_not_converted():
    destination, report = migrate(record("K001") + b"xx")
    assert destination == b"" and report.state == "REFUSED" and any("trailing byte" in f for f in report.failures)


# --- restart ----------------------------------------------------------------------------------------------------

def test_an_interrupted_migration_reports_where_to_resume_and_resumes_to_the_same_result():
    src = b"".join(record(f"K{i:03d}") for i in range(8))
    full_bytes, full = migrate(src)
    part_bytes, part = migrate(src, stop_after=3)
    assert part.state == "INTERRUPTED" and not part.success and part.to_dict()["checkpoint"]["resume_point"] == 3
    assert part_bytes == b"" or len(part_bytes) == 3 * LENGTH
    resumed_bytes, resumed = migrate(src, partial_output=part_bytes, resume_after=3)
    assert resumed_bytes == full_bytes and resumed.state == "RECONCILED"
    assert resumed.to_dict()["destination_sha256"] == full.to_dict()["destination_sha256"]
    assert resumed.to_dict()["checkpoint"]["resumed_from"] == 3


def test_a_torn_partial_output_is_refused_on_resume():
    src = b"".join(record(f"K{i:03d}") for i in range(6))
    part_bytes, _ = migrate(src, stop_after=3)
    destination, report = migrate(src, partial_output=part_bytes[:-1], resume_after=3)
    assert destination == b"" and report.state == "REFUSED" and any("partial output" in f for f in report.failures)


# --- only a fully checked result is a success -----------------------------------------------------------------------

def test_reconciled_partial_and_failed_are_never_successes():
    for state in ("RECONCILED_PARTIAL", "FAILED", "REFUSED", "INTERRUPTED"):
        assert MigrationReport(state=state).success is False
    assert MigrationReport(state="RECONCILED").success is True


def test_a_destination_that_does_not_reconcile_is_reported_failed():
    src = record("K001") + record("K002")
    destination, report = migrate(src)
    assert report.success
    from engine.vsam.migrate import reconcile_destination

    tampered = destination[:5] + bytes([destination[5] ^ 0xFF]) + destination[6:]
    again = reconcile_destination(source_def(), src, layout(), Encoding.EBCDIC_CP037, tampered,
                                  target_layout=layout(), source_platform=IBM_Z, target_platform=IBM_Z)
    assert again.state == "FAILED" and not again.success and again.failures

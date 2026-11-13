"""G-27 in the migration pipeline: explicit platforms, a target layout, and a report that records the conversion.

A layout with binary (COMP / COMP-5) fields cannot be migrated by copying bytes.  ``migrate_dataset``
refuses unless the source and target platforms and the target layout are given; with them it converts
every binary field (width and byte order), keeps keys and offsets consistent, reconciles the result
independently, and records what it decided.  Dependency-free (pytest only).
"""
from __future__ import annotations

import json

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import derive_file_layout
from engine.vsam.migrate import migrate_dataset
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization
from engine.vsam.platform import platform

GNU = platform("GNUCOBOL_X86_DEFAULT")
IBM_Z = platform("IBM_ZOS")

FD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO \"F.DAT\".\n"
    "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n"
    "       01 REC.\n"
    "          05 N     PIC S9(2) COMP.\n"
    "          05 ID-X  PIC X(4).\n"
    "          05 C5    PIC S9(4) COMP-5.\n"
    "          05 NOTE  PIC X(2).\n"
    "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n"
)


def layout_for(plat):
    return derive_file_layout(CobolParser().parse(FD).file_definitions[0], binary_width_model=plat.width_model)


SRC, DST = layout_for(GNU), layout_for(IBM_Z)          # 9 and 10 bytes


def record(n: int, ident: str, c5: int, note: str = "ab") -> bytes:
    """A source record as written on the little-endian GnuCOBOL default platform."""
    return (n.to_bytes(1, "big", signed=True) + ident.encode() + c5.to_bytes(2, "little", signed=True) + note.encode())


def dataset(organization=Organization.KSDS, key_offset=1, **kw) -> DatasetDefinition:
    key = KeyDefinition(key_offset, 4) if organization is Organization.KSDS else None
    return DatasetDefinition("SRC", organization, record_length=SRC.record_length, primary_key=key, **kw)


def migrate(data: bytes, definition=None, **kw):
    options = dict(target_layout=DST, source_platform=GNU, target_platform=IBM_Z)
    options.update(kw)
    return migrate_dataset(definition or dataset(), data, SRC, Encoding.EBCDIC_CP037, **options)


def test_the_layouts_really_differ_in_length_and_offsets():
    assert (SRC.record_length, DST.record_length) == (9, 10)
    assert [f.offset for f in SRC.fields] == [0, 1, 5, 7] and [f.offset for f in DST.fields] == [0, 2, 6, 8]


# --- refusals ---------------------------------------------------------------------------------------------------------

def test_binary_fields_without_explicit_platforms_are_refused_not_copied():
    out, report = migrate_dataset(dataset(), record(1, "K001", 5), SRC, Encoding.EBCDIC_CP037)
    assert out == b"" and report.state == "REFUSED"
    assert any("source_platform" in f and "target_platform" in f and "target_layout" in f for f in report.failures)


@pytest.mark.parametrize("missing", ["target_layout", "source_platform", "target_platform"])
def test_every_one_of_the_three_is_required(missing):
    out, report = migrate(record(1, "K001", 5), **{missing: None})
    assert out == b"" and report.state == "REFUSED" and any(missing in f for f in report.failures)


def test_a_layout_derived_for_another_width_model_is_refused_by_name():
    out, report = migrate(record(1, "K001", 5), source_platform=IBM_Z)       # SRC has 1-byte COMP: not the IBM model
    assert out == b"" and report.state == "REFUSED" and any("width model" in f for f in report.failures)


def test_layouts_for_different_records_are_refused():
    other = derive_file_layout(CobolParser().parse(FD.replace("NOTE  PIC X(2)", "OTHER PIC X(2)")).file_definitions[0],
                               binary_width_model=IBM_Z.width_model)
    out, report = migrate(record(1, "K001", 5), target_layout=other)
    assert out == b"" and report.state == "REFUSED" and any("same fields" in f for f in report.failures)


def test_a_key_that_spans_a_binary_field_is_still_refused():
    out, report = migrate(record(1, "K001", 5), dataset(key_offset=0))     # offset 0 length 4 covers COMP N and part of ID-X
    assert out == b"" and report.state == "REFUSED" and any("key" in f for f in report.failures)


# --- the good path -------------------------------------------------------------------------------------------------------------

def test_a_migration_between_platforms_converts_widths_orders_and_offsets_and_reconciles():
    src = record(7, "K002", -300) + record(-5, "K001", 12345)
    out, report = migrate(src)
    assert report.state == "RECONCILED" and report.success, report.failures
    assert len(out) == 2 * DST.record_length
    first = out[:10]                                                          # K001 sorts first in EBCDIC too
    assert int.from_bytes(first[0:2], "big", signed=True) == -5                # N widened 1 -> 2 bytes
    assert first[2:6] == "K001".encode("cp037")                                # key moved from offset 1 to 2
    assert int.from_bytes(first[6:8], "big", signed=True) == 12345             # COMP-5 little -> big
    assert first[8:10] == "ab".encode("cp037")


def test_the_report_records_both_platforms_both_layouts_and_every_binary_decision():
    _, report = migrate(record(7, "K002", -300))
    data = report.to_dict()
    assert data["source_platform"]["name"] == "GNUCOBOL_X86_DEFAULT" and data["target_platform"]["name"] == "IBM_ZOS"
    assert data["source_platform"]["comp5_byte_order"] == "little" and data["target_platform"]["comp5_byte_order"] == "big"
    assert "no IBM" in data["target_platform"]["evidence"]
    assert data["layout"]["identity"] == SRC.identity and data["target_layout"]["identity"] == DST.identity
    assert data["target_layout"]["record_length"] == 10 and data["destination"]["record_length"] == 10
    conversions = {c["path"]: c for c in data["binary_conversions"]}
    assert conversions["REC.N"] == {"path": "REC.N", "usage": "COMP", "source": {"byte_order": "big", "bytes": 1},
                                    "target": {"byte_order": "big", "bytes": 2}}
    assert conversions["REC.C5"]["source"] == {"byte_order": "little", "bytes": 2}
    assert conversions["REC.C5"]["target"] == {"byte_order": "big", "bytes": 2}
    json.dumps(data)                                                           # serialisable


def test_a_layout_without_binary_fields_needs_no_platforms():
    plain = FD.replace("          05 N     PIC S9(2) COMP.\n", "").replace("          05 C5    PIC S9(4) COMP-5.\n", "")
    lay = derive_file_layout(CobolParser().parse(plain).file_definitions[0], binary_width_model=GNU.width_model)
    definition = DatasetDefinition("S", Organization.KSDS, record_length=lay.record_length, primary_key=KeyDefinition(0, 4))
    out, report = migrate_dataset(definition, b"K001ab", lay, Encoding.EBCDIC_CP037)
    assert report.state == "RECONCILED" and report.to_dict()["binary_conversions"] == []


# --- rejections ------------------------------------------------------------------------------------------------------------------------

def test_a_comp_value_beyond_its_picture_is_rejected_with_a_reason_and_confirmed_independently():
    bad = record(100, "K002", 1)                                               # S9(2) COMP cannot hold 100
    out, report = migrate(record(5, "K001", 1) + bad + record(6, "K003", 2))
    assert report.state == "RECONCILED"
    data = report.to_dict()
    assert data["rejected_record_count"] == 1 and "exceeds the 2 digits" in data["rejected"][0]["reason"]
    assert len(out) == 2 * DST.record_length


def test_the_extreme_values_survive_the_migration():
    src = record(99, "K001", 32767) + record(-99, "K002", -32768) + record(0, "K003", 0)
    out, report = migrate(src)
    assert report.state == "RECONCILED"
    values = [(int.from_bytes(out[i:i + 2], "big", signed=True), int.from_bytes(out[i + 6:i + 8], "big", signed=True))
              for i in range(0, len(out), 10)]
    assert values == [(99, 32767), (-99, -32768), (0, 0)]


# --- restart ---------------------------------------------------------------------------------------------------------------------------

def test_an_interrupted_platform_migration_resumes_to_the_same_result():
    src = b"".join(record(i, f"K{i:03d}", i * 100) for i in range(1, 9))
    full, full_report = migrate(src)
    part, part_report = migrate(src, stop_after=3)
    assert part_report.state == "INTERRUPTED" and len(part) == 3 * DST.record_length
    resumed, report = migrate(src, partial_output=part, resume_after=3)
    assert resumed == full and report.state == "RECONCILED"
    assert report.to_dict()["destination_sha256"] == full_report.to_dict()["destination_sha256"]


def test_a_torn_partial_output_is_refused_on_resume():
    src = b"".join(record(i, f"K{i:03d}", i) for i in range(1, 6))
    part, _ = migrate(src, stop_after=2)
    out, report = migrate(src, partial_output=part[:-1], resume_after=2)
    assert out == b"" and report.state == "REFUSED" and any("partial output" in f for f in report.failures)


def test_a_tampered_destination_is_reported_failed():
    from engine.vsam.migrate import reconcile_destination

    src = record(5, "K001", 77)
    out, report = migrate(src)
    assert report.success
    bad = out[:6] + bytes([out[6] ^ 0xFF]) + out[7:]
    again = reconcile_destination(dataset(), src, SRC, Encoding.EBCDIC_CP037, bad, target_layout=DST,
                                  source_platform=GNU, target_platform=IBM_Z)
    assert again.state == "FAILED" and not again.success


def test_the_migration_is_deterministic():
    src = record(7, "K002", -300) + record(-5, "K001", 12345)
    assert json.dumps(migrate(src)[1].to_dict(), sort_keys=True) == json.dumps(migrate(src)[1].to_dict(), sort_keys=True)

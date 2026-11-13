"""Stage 1: field-aware conversion, rejection with reasons, and resumable migration.

Deterministic offline tests.  The point of the converter is that a migration between
encodings becomes *fully* reconcilable (RECONCILED, not RECONCILED_PARTIAL) because the
record content can be translated and compared, while packed and binary fields are never
translated and unconvertible records are rejected with a reason, never dropped.
"""
from __future__ import annotations

import pytest

from engine.vsam.collation import to_stored_bytes
from engine.vsam.convert import (
    FieldKind, FieldSpec, check_record, convert_dataset, convert_record, sort_for_ksds, validate_layout,
)
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization, RecordFormat
from engine.vsam.reconcile import RejectedRecord, reconcile_migration

# 4-byte character key, 3-byte packed amount (+12345), 2-byte binary count, 3-byte filler
LAYOUT = (
    FieldSpec("ID", 0, 4),
    FieldSpec("AMOUNT", 4, 3, FieldKind.PACKED),
    FieldSpec("COUNT", 7, 2, FieldKind.BINARY),
    FieldSpec("PAD", 9, 3),
)
LENGTH = 12
KEY = KeyDefinition(0, 4)


def packed(digits: str, sign: int = 0xC) -> bytes:
    nibbles = [int(d) for d in digits] + [sign]
    if len(nibbles) % 2:
        nibbles.insert(0, 0)
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def record(ident: str, amount: bytes = None, count: int = 7, pad: str = "   ",
           encoding: Encoding = Encoding.ASCII) -> bytes:
    amount = packed("12345") if amount is None else amount
    return (to_stored_bytes(ident, encoding) + amount + count.to_bytes(2, "big")
            + to_stored_bytes(pad, encoding))


def dataset(name="SRC", encoding=Encoding.ASCII) -> DatasetDefinition:
    return DatasetDefinition(name, Organization.KSDS, record_length=LENGTH, encoding=encoding, primary_key=KEY)


# --- layout -----------------------------------------------------------------------------

def test_a_full_layout_has_no_problems():
    assert validate_layout(LAYOUT, LENGTH) == ()


@pytest.mark.parametrize("fields,phrase", [
    ((FieldSpec("A", 0, 4), FieldSpec("B", 6, 6)), "not covered by any field"),
    ((FieldSpec("A", 0, 8), FieldSpec("B", 4, 8)), "overlaps"),
    ((FieldSpec("A", 0, 4),), "not covered"),
    ((FieldSpec("A", 0, 20),), "past the 12-byte record"),
    ((FieldSpec("A", 0, 0), FieldSpec("B", 0, 12)), "non-positive"),
])
def test_layouts_that_do_not_cover_the_record_exactly_are_refused(fields, phrase):
    assert any(phrase in p for p in validate_layout(fields, LENGTH))


# --- converting one record ------------------------------------------------------------------

def test_display_is_translated_and_packed_and_binary_are_copied_untouched():
    src = record("AB12", pad="x  ")
    out = convert_record(src, LAYOUT, Encoding.ASCII, Encoding.EBCDIC_CP037)
    assert out[0:4] == "AB12".encode("cp037") and out[9:12] == "x  ".encode("cp037")
    assert out[4:9] == src[4:9]          # packed amount and binary count: byte for byte
    assert convert_record(out, LAYOUT, Encoding.EBCDIC_CP037, Encoding.ASCII) == src


def test_same_encoding_is_an_identity():
    src = record("AB12")
    assert convert_record(src, LAYOUT, Encoding.ASCII, Encoding.ASCII) == src


@pytest.mark.parametrize("amount,phrase", [
    (bytes([0x1A, 0x23, 0x4C]), "non-decimal digit"),
    (bytes([0x01, 0x23, 0x45]), "invalid sign nibble"),
    (bytes([0x01, 0x23, 0x40]), "invalid sign nibble"),
])
def test_a_corrupt_packed_field_is_refused_with_a_reason(amount, phrase):
    src = record("AB12", amount=amount)
    assert phrase in (check_record(src, LAYOUT) or "")
    with pytest.raises(ValueError, match=phrase):
        convert_record(src, LAYOUT, Encoding.ASCII, Encoding.EBCDIC_CP037)


def test_a_display_byte_with_no_counterpart_names_the_field():
    src = b"\xe9" + record("B123")[1:]
    with pytest.raises(ValueError, match="field ID: byte has no counterpart in EBCDIC_CP037"):
        convert_record(src, LAYOUT, Encoding.ASCII, Encoding.EBCDIC_CP037)


@pytest.mark.parametrize("sign", [0xA, 0xB, 0xC, 0xD, 0xE, 0xF])
def test_every_valid_packed_sign_nibble_is_accepted(sign):
    assert check_record(record("AB12", amount=packed("12345", sign)), LAYOUT) is None


# --- converting and reconciling a dataset ------------------------------------------------------

def _source():
    ids = ["1001", "A001", "a001"]  # ascending in ASCII: digits, upper case, lower case
    return b"".join(record(i) for i in ids)


def test_a_converted_ksds_reconciles_fully_once_sorted_into_ebcdic_order():
    src = _source()
    result = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037)
    assert result.rejected == () and result.records_read == 3
    destination = dataset("DST", Encoding.EBCDIC_CP037)
    translate = lambda r: convert_record(r, LAYOUT, Encoding.ASCII, Encoding.EBCDIC_CP037)  # noqa: E731

    unsorted_report = reconcile_migration(dataset(), src, destination, result.output, translate=translate)
    assert unsorted_report.status == "FAILED"  # converted in ASCII order: not a valid EBCDIC KSDS

    loaded = sort_for_ksds(result.output, LENGTH, 0, 4)
    report = reconcile_migration(dataset(), src, destination, loaded, translate=translate)
    assert report.status == "RECONCILED" and report.content_compared and report.failures == ()
    # EBCDIC order: lower case, upper case, digits
    assert [loaded[i:i + 4] for i in range(0, len(loaded), LENGTH)] == [
        s.encode("cp037") for s in ("a001", "A001", "1001")]


def test_without_a_translator_the_same_migration_is_only_partially_reconciled():
    src = _source()
    out = sort_for_ksds(convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037).output, LENGTH, 0, 4)
    report = reconcile_migration(dataset(), src, dataset("DST", Encoding.EBCDIC_CP037), out)
    assert report.status == "RECONCILED_PARTIAL" and not report.content_compared


def test_a_wrongly_translated_destination_fails_the_content_comparison():
    src = _source()
    good = sort_for_ksds(convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037).output,
                         LENGTH, 0, 4)
    corrupted = good[:5] + bytes([good[5] ^ 0xFF]) + good[6:]  # flip a packed byte
    translate = lambda r: convert_record(r, LAYOUT, Encoding.ASCII, Encoding.EBCDIC_CP037)  # noqa: E731
    report = reconcile_migration(dataset(), src, dataset("DST", Encoding.EBCDIC_CP037), corrupted, translate=translate)
    assert report.status == "FAILED" and any("content differs" in f for f in report.failures)


def test_unconvertible_records_are_rejected_with_reasons_and_the_rejection_is_independently_justified():
    bad = record("B002", amount=bytes([0x01, 0x23, 0x45]))  # invalid sign nibble
    src = record("A001") + bad + record("C003")
    result = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037)
    assert [r.record_number for r in result.rejected] == [2]
    assert "invalid sign nibble" in result.rejected[0].reason
    loaded = sort_for_ksds(result.output, LENGTH, 0, 4)
    translate = lambda r: convert_record(r, LAYOUT, Encoding.ASCII, Encoding.EBCDIC_CP037)  # noqa: E731
    destination = dataset("DST", Encoding.EBCDIC_CP037)

    justified = reconcile_migration(dataset(), src, destination, loaded, rejected=result.rejected,
                                    translate=translate, validate_record=lambda r: check_record(r, LAYOUT))
    assert justified.status == "RECONCILED" and justified.rejected_record_count == 1

    # the same rejection without a validator cannot be confirmed
    unverified = reconcile_migration(dataset(), src, destination, loaded, rejected=result.rejected, translate=translate)
    assert unverified.status == "RECONCILED_PARTIAL"
    assert any("not independently justified" in w for w in unverified.warnings)

    # a valid record listed as rejected is not justified by the validator either
    fake = (RejectedRecord(1, "claimed bad"),)
    all_valid = record("A001") + record("B002") + record("C003")
    converted = convert_dataset(dataset(), all_valid, LAYOUT, Encoding.EBCDIC_CP037).output
    dropped = reconcile_migration(dataset(), all_valid, destination,
                                  sort_for_ksds(converted[LENGTH:], LENGTH, 0, 4),
                                  rejected=fake, translate=translate,
                                  validate_record=lambda r: check_record(r, LAYOUT))
    assert dropped.status == "RECONCILED_PARTIAL"  # record 1 is valid, so its rejection stays unverified
    assert any("not independently justified" in w for w in dropped.warnings)


# --- interrupted migration and restart ----------------------------------------------------------------

def test_an_interrupted_conversion_resumes_to_exactly_the_uninterrupted_result():
    src = b"".join(record(f"K{i:03d}") for i in range(10))
    full = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037)
    first = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037, stop_after=4)
    assert first.records_read == 4 and len(first.output) == 4 * LENGTH
    resumed = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037,
                              partial_output=first.output, resume_after=4)
    assert resumed.output == full.output and resumed.resumed_from == 4
    assert resumed.checkpoint_sha256 == full.checkpoint_sha256


def test_a_torn_or_altered_partial_output_is_refused_not_continued():
    src = b"".join(record(f"K{i:03d}") for i in range(6))
    first = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037, stop_after=3)
    for tampered in (first.output[:-1], first.output[:-1] + b"\x00", first.output + first.output[:LENGTH], b""):
        with pytest.raises(ValueError, match="partial output does not match"):
            convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037, partial_output=tampered, resume_after=3)


def test_resume_points_are_validated():
    src = b"".join(record(f"K{i:03d}") for i in range(3))
    with pytest.raises(ValueError, match="cannot resume after record 9 of 3"):
        convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037, resume_after=9)
    with pytest.raises(ValueError, match="without a resume point"):
        convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037, partial_output=b"x")


def test_resume_accounts_for_records_rejected_before_the_interruption():
    bad = record("K001", amount=bytes([0x01, 0x23, 0x45]))
    src = record("K000") + bad + record("K002") + record("K003")
    full = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037)
    first = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037, stop_after=2)
    assert len(first.output) == LENGTH and [r.record_number for r in first.rejected] == [2]
    resumed = convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037, partial_output=first.output, resume_after=2)
    assert resumed.output == full.output
    assert [r.record_number for r in resumed.rejected] == [2]


# --- guards -----------------------------------------------------------------------------------------------

def test_bad_layout_or_variable_format_or_truncated_input_is_refused():
    with pytest.raises(ValueError, match="not covered"):
        convert_dataset(dataset(), record("K000"), (FieldSpec("A", 0, 4),), Encoding.EBCDIC_CP037)
    variable = DatasetDefinition("V", Organization.ESDS, record_format=RecordFormat.VARIABLE, record_length=LENGTH)
    with pytest.raises(ValueError, match="fixed-length"):
        convert_dataset(variable, b"", LAYOUT, Encoding.EBCDIC_CP037)
    with pytest.raises(ValueError, match="trailing byte"):
        convert_dataset(dataset(), record("K000") + b"xx", LAYOUT, Encoding.EBCDIC_CP037)


def test_sort_for_ksds_is_stable_and_refuses_a_ragged_output():
    a, b = record("K001", count=1), record("K001", count=2)
    assert sort_for_ksds(b + a, LENGTH, 0, 4) == b + a  # equal keys keep arrival order
    with pytest.raises(ValueError, match="whole number"):
        sort_for_ksds(b"abc", LENGTH, 0, 4)


def test_conversion_is_deterministic():
    src = _source()
    assert convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037) == \
        convert_dataset(dataset(), src, LAYOUT, Encoding.EBCDIC_CP037)

"""Stage 1: VSAM-style dataset model, EBCDIC key collation, migration reconciliation.

Deterministic tests only - no GnuCOBOL and no IBM runtime is involved, and the
capability table says so.  A migration is accepted only when an independent
recomputation agrees; every failure mode is named.
"""
from __future__ import annotations

import pytest

from engine.vsam.collation import collation_key, is_ascending, key_bytes, to_stored_bytes
from engine.vsam.model import (
    CAPABILITIES, Capability, DatasetDefinition, Encoding, KeyDefinition, KeyKind,
    Organization, RecordFormat, capability,
)
from engine.vsam.reconcile import RejectedRecord, reconcile_migration, split_records

KEY = KeyDefinition(offset=0, length=4)


def ksds(name="MASTER", encoding=Encoding.ASCII, length=10, key=KEY, **kw):
    return DatasetDefinition(name=name, organization=Organization.KSDS, record_length=length,
                             encoding=encoding, primary_key=key, **kw)


def rec(key: str, rest: str = "payload", enc=Encoding.ASCII, length=10) -> bytes:
    return to_stored_bytes((key + rest).ljust(length)[:length], enc)


# --- model -------------------------------------------------------------------

def test_valid_ksds_has_no_problems():
    assert ksds().validate() == ()


@pytest.mark.parametrize("definition,phrase", [
    (DatasetDefinition("X", Organization.KSDS, record_length=10), "requires a primary key"),
    (ksds(key=KeyDefinition(0, 4, unique=False)), "must be unique"),
    (ksds(key=KeyDefinition(8, 4)), "outside the 10-byte record"),
    (ksds(length=0), "record length must be positive"),
    (DatasetDefinition("E", Organization.ESDS, record_length=10, primary_key=KEY), "only a KSDS has a primary key"),
    (DatasetDefinition("R", Organization.RRDS, record_length=10, alternate_keys=(KEY,)), "RRDS cannot have an alternate"),
    (DatasetDefinition("R", Organization.RRDS, record_length=10, record_format=RecordFormat.VARIABLE),
     "variable-length RRDS is not modelled"),
    (DatasetDefinition("S", Organization.SEQUENTIAL, record_length=10, alternate_keys=(KEY,)), "sequential dataset"),
])
def test_impossible_definitions_are_refused_with_a_reason(definition, phrase):
    assert any(phrase in p for p in definition.validate())


def test_esds_and_rrds_are_valid_without_keys():
    assert DatasetDefinition("E", Organization.ESDS, record_length=80).validate() == ()
    assert DatasetDefinition("R", Organization.RRDS, record_length=80).validate() == ()


def test_alternate_keys_are_allowed_on_ksds_and_esds_only():
    alt = (KeyDefinition(4, 2, unique=False),)
    assert ksds(alternate_keys=alt).validate() == ()
    assert DatasetDefinition("E", Organization.ESDS, record_length=10, alternate_keys=alt).validate() == ()


# --- capability table: no blanket flag, no promoted evidence ----------------------

def test_every_capability_has_its_own_status_and_evidence_class():
    ids = [c.id for c in CAPABILITIES]
    assert len(ids) == len(set(ids)) and len(ids) >= 10
    assert not any("supported" == c.id.lower() for c in CAPABILITIES)
    allowed = {"IMPLEMENTED_AND_VERIFIED", "IMPLEMENTED_NOT_RUNTIME_VERIFIED", "PARTIAL", "UNSUPPORTED", "NOT_IMPLEMENTED"}
    assert {c.status for c in CAPABILITIES} <= allowed
    assert {c.evidence_class for c in CAPABILITIES} <= {
        "GNUCOBOL_DIFFERENTIAL", "DETERMINISTIC_TEST", "DOCUMENTED_SEMANTICS", "NONE"}


def test_nothing_claims_ibm_runtime_evidence():
    assert not any("IBM_RUNTIME" in c.evidence_class for c in CAPABILITIES)
    assert capability("vsam.ibm_runtime_equivalence").status == "NOT_IMPLEMENTED"


def test_esds_is_not_modelled_as_ksds_and_has_no_local_proof():
    esds = capability("esds.entry_sequence_rba")
    assert esds.organization is Organization.ESDS and esds.status == "NOT_IMPLEMENTED" and esds.evidence_class == "NONE"


def test_gnucobol_evidence_is_only_claimed_where_a_differential_exists():
    for c in CAPABILITIES:
        if c.evidence_class == "GNUCOBOL_DIFFERENTIAL":
            assert c.status in ("IMPLEMENTED_AND_VERIFIED", "PARTIAL")
    with pytest.raises(KeyError):
        capability("does.not.exist")
    assert isinstance(capability("ksds.alternate_key.bounded_browse"), Capability)


# --- collation ---------------------------------------------------------------

def test_ebcdic_and_ascii_order_the_same_keys_differently():
    names = ["a1", "A1", "11"]
    ascii_order = sorted(names, key=lambda s: to_stored_bytes(s, Encoding.ASCII))
    ebcdic_order = sorted(names, key=lambda s: to_stored_bytes(s, Encoding.EBCDIC_CP037))
    assert ascii_order == ["11", "A1", "a1"]       # digits < upper < lower
    assert ebcdic_order == ["a1", "A1", "11"]      # lower < upper < digits
    assert ascii_order != ebcdic_order


def test_collation_key_translates_character_keys_and_never_binary_keys():
    k = KeyDefinition(0, 2)
    ebcdic_bytes = to_stored_bytes("A1", Encoding.EBCDIC_CP037)
    assert collation_key(ebcdic_bytes, k, Encoding.EBCDIC_CP037, Encoding.ASCII) == b"A1"
    assert collation_key(b"A1", k, Encoding.ASCII, Encoding.EBCDIC_CP037) == ebcdic_bytes
    packed = KeyDefinition(0, 2, kind=KeyKind.BINARY)
    assert collation_key(b"\x12\x3c", packed, Encoding.EBCDIC_CP037, Encoding.ASCII) == b"\x12\x3c"


def test_is_ascending_allows_duplicates_and_rejects_disorder():
    assert is_ascending([b"a", b"a", b"b"]) and not is_ascending([b"b", b"a"]) and is_ascending([])


def test_key_bytes_slices_without_translation():
    assert key_bytes(b"ABCDEFG", KeyDefinition(2, 3)) == b"CDE"


# --- reconciliation: the good path -------------------------------------------------

def _data(*keys, enc=Encoding.ASCII):
    return b"".join(rec(k, enc=enc) for k in keys)


def test_identical_migration_reconciles_and_reports_every_fact():
    src = _data("0001", "0002", "0003")
    report = reconcile_migration(ksds("SRC"), src, ksds("DST"), src)
    assert report.reconciled and report.status == "RECONCILED"
    assert (report.source_record_count, report.destination_record_count,
            report.rejected_record_count, report.duplicate_key_count) == (3, 3, 0, 0)
    assert report.source_sha256 == report.destination_sha256 and report.content_compared
    d = report.to_dict()
    assert d["source"]["name"] == "SRC" and d["destination"]["name"] == "DST" and d["failures"] == []


def test_destination_may_be_reordered_only_if_still_in_key_order():
    src = _data("0002", "0001")  # source not in key order (a load file)
    dst = _data("0001", "0002")
    sequential_source = DatasetDefinition("SRC", Organization.SEQUENTIAL, record_length=10)
    report = reconcile_migration(sequential_source, src, ksds("DST"), dst)
    # sequential source has no primary key -> keys unchecked, content still compared as a multiset
    assert report.status == "RECONCILED" and any("no primary key" in w for w in report.warnings)


# --- reconciliation: every failure is named ----------------------------------------------

def test_target_file_that_merely_exists_is_not_success():
    report = reconcile_migration(ksds(), _data("0001", "0002"), ksds("DST"), b"")
    assert report.status == "FAILED"
    assert any("destination holds 0" in f for f in report.failures)
    assert any("missing from the destination" in f for f in report.failures)


def test_lost_record_and_substituted_record_are_detected():
    src = _data("0001", "0002", "0003")
    lost = reconcile_migration(ksds(), src, ksds("D"), _data("0001", "0002"))
    assert lost.status == "FAILED" and any("1 source key(s) are missing" in f for f in lost.failures)
    swapped = reconcile_migration(ksds(), src, ksds("D"), _data("0001", "0002", "0009"))
    assert any("no source record" in f for f in swapped.failures)


def test_changed_record_content_is_detected_even_when_keys_match():
    src = _data("0001", "0002")
    dst = rec("0001") + rec("0002", "CHANGED")
    report = reconcile_migration(ksds(), src, ksds("D"), dst)
    assert report.status == "FAILED" and any("content differs" in f for f in report.failures)
    assert report.source_sha256 != report.destination_sha256


def test_duplicate_source_key_must_be_rejected_on_purpose():
    src = _data("0001", "0001", "0002")
    unrejected = reconcile_migration(ksds(), src, ksds("D"), _data("0001", "0001", "0002"))
    assert unrejected.status == "FAILED" and unrejected.duplicate_key_count == 1
    assert any("repeats the primary key" in f for f in unrejected.failures)
    accepted = reconcile_migration(ksds(), src, ksds("D"), _data("0001", "0002"),
                                   rejected=(RejectedRecord(2, "duplicate key"),))
    assert accepted.status == "RECONCILED" and accepted.rejected_record_count == 1
    assert accepted.duplicate_key_count == 1 and any("rejected on purpose" in w for w in accepted.warnings)


def test_destination_duplicate_keys_and_disorder_are_detected():
    src = _data("0001", "0002")
    dup = reconcile_migration(ksds(), src, ksds("D"), _data("0001", "0001"))
    assert any("duplicate" in f for f in dup.failures)
    disorder = reconcile_migration(ksds(), src, ksds("D"), _data("0002", "0001"))
    assert any("not in ASCII key order" in f for f in disorder.failures)


def test_rejecting_a_record_that_does_not_exist_or_twice_fails():
    src = _data("0001")
    report = reconcile_migration(ksds(), src, ksds("D"), src, rejected=(RejectedRecord(5, "x"),))
    assert any("does not exist" in f for f in report.failures)
    twice = reconcile_migration(ksds(), src, ksds("D"), b"", rejected=(RejectedRecord(1, "x"), RejectedRecord(1, "y")))
    assert any("listed as rejected 2 times" in f for f in twice.failures)


def test_truncated_final_record_and_invalid_definitions_fail():
    report = reconcile_migration(ksds(), _data("0001") + b"xx", ksds("D"), _data("0001"))
    assert report.status == "FAILED" and any("trailing byte" in f for f in report.failures)
    bad = reconcile_migration(DatasetDefinition("S", Organization.KSDS, record_length=10), b"", ksds("D"), b"")
    assert any("invalid source definition" in f and "requires a primary key" in f for f in bad.failures)


# --- encodings: counts and keys checked, content honestly not -----------------------------

def test_ascii_to_ebcdic_migration_is_only_partially_reconciled_and_must_be_in_ebcdic_order():
    ascii_ds = ksds("SRC")
    ebcdic_ds = ksds("DST", encoding=Encoding.EBCDIC_CP037)
    src = _data("a001", "A001", "1001")                     # ASCII order: 1001 < A001 < a001
    ordered = b"".join(rec(k, enc=Encoding.EBCDIC_CP037) for k in ("a001", "A001", "1001"))
    report = reconcile_migration(ascii_ds, src, ebcdic_ds, ordered)
    assert report.status == "RECONCILED_PARTIAL" and not report.reconciled
    assert report.content_compared is False and any("not compared" in w for w in report.warnings)
    kept_ascii_order = b"".join(rec(k, enc=Encoding.EBCDIC_CP037) for k in ("1001", "A001", "a001"))
    wrong = reconcile_migration(ascii_ds, src, ebcdic_ds, kept_ascii_order)
    assert wrong.status == "FAILED" and any("not in EBCDIC_CP037 key order" in f for f in wrong.failures)


def test_translated_keys_must_match_the_source_keys():
    src = _data("0001", "0002")
    dst = b"".join(rec(k, enc=Encoding.EBCDIC_CP037) for k in ("0001", "0003"))
    report = reconcile_migration(ksds("S"), src, ksds("D", encoding=Encoding.EBCDIC_CP037), dst)
    assert report.status == "FAILED" and any("missing from the destination" in f for f in report.failures)


# --- variable-length records ----------------------------------------------------------------

def _rdw(payload: bytes) -> bytes:
    return (len(payload) + 4).to_bytes(2, "big") + b"\x00\x00" + payload


def test_variable_records_are_split_by_their_descriptor_words():
    ds = DatasetDefinition("V", Organization.KSDS, record_format=RecordFormat.VARIABLE, record_length=20,
                           primary_key=KEY)
    records, problems = split_records(_rdw(b"0001abc") + _rdw(b"0002"), ds)
    assert records == [b"0001abc", b"0002"] and problems == []


@pytest.mark.parametrize("blob,phrase", [
    (b"\x00\x08\x00", "truncated record descriptor"),
    (b"\x00\x08\x00\x01abcd", "non-zero RDW reserved field"),
    (b"\x00\x02\x00\x00", "invalid length"),
    (b"\x00\xff\x00\x00ab", "invalid length"),
])
def test_corrupt_variable_data_is_reported(blob, phrase):
    ds = DatasetDefinition("V", Organization.ESDS, record_format=RecordFormat.VARIABLE, record_length=20)
    _, problems = split_records(blob, ds)
    assert any(phrase in p for p in problems)


def test_variable_length_migration_reconciles():
    ds = DatasetDefinition("V", Organization.KSDS, record_format=RecordFormat.VARIABLE, record_length=20,
                           primary_key=KEY)
    data = _rdw(b"0001abc") + _rdw(b"0002")
    assert reconcile_migration(ds, data, ds, data).status == "RECONCILED"


def test_report_is_deterministic():
    src = _data("0001", "0002")
    a = reconcile_migration(ksds(), src, ksds("D"), src).to_dict()
    b = reconcile_migration(ksds(), src, ksds("D"), src).to_dict()
    assert a == b

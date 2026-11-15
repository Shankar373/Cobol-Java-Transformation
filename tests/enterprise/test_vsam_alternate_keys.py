"""Alternate keys in the streaming KSDS migration: write-sequence prefix, unique-key checks, resume, COBOL cross-check."""

import pytest

from enterprise.quotas import VsamQuotas
from enterprise.vsam import VsamRefusal, migrate_export
from enterprise.vsam.layout_check import check_manifest_against_cobol
from tests.enterprise.test_vsam_layout_check import KSDS_FD, KSDS_SELECT, program
from tests.enterprise.vsam_support import fixed_export, make_manifest, write_export

SMALL = VsamQuotas(stream_buffer_bytes=4096, checkpoint_interval_records=7)
SEP = "\u0001"


def records(n: int) -> list[bytes]:
    # key(4) + AKD(2, repeats every 3 records) + AKU(2, unique) + 2 filler = 10 bytes
    return [f"{i:04d}{'ABC'[i % 3] * 2}{i % 100:02d}xx".encode("ascii") for i in range(1, n + 1)]


def migrate(tmp_path, recs, alternates, quotas=SMALL, **kw):
    blob = fixed_export(recs)
    manifest = make_manifest(blob, len(recs), alternate_keys=alternates)
    out = tmp_path / "out.idx"
    return migrate_export(write_export(tmp_path, blob), manifest, out, quotas=quotas, **kw), out


def test_alternate_keys_prefix_each_record_with_its_write_sequence(tmp_path):
    _, out = migrate(tmp_path, records(3), ((4, 2, True), (6, 2, False)))
    lines = out.read_text(encoding="utf-8").split("\n")
    assert lines[0] == "K4"
    one, two = "0000000000000001", "0000000000000002"
    assert lines[1] == f"0001{SEP}{one}{one}BB01xx"
    assert lines[2] == f"0002{SEP}{two}{two}CC02xx"


def test_a_repeated_value_of_a_unique_alternate_key_is_refused(tmp_path):
    with pytest.raises(VsamRefusal) as exc:
        migrate(tmp_path, records(5), ((4, 2, False),))  # AKD repeats, declared unique
    assert exc.value.code == "ALTERNATE_KEY_DUPLICATE"
    assert not (tmp_path / "out.idx").exists()


def test_duplicates_are_allowed_when_the_key_is_declared_with_duplicates(tmp_path):
    result, _ = migrate(tmp_path, records(30), ((4, 2, True),))
    assert result.records == 30


@pytest.mark.parametrize(
    "alternates,code",
    [
        (((0, 4, True),), "INVALID_LAYOUT"),  # the primary key itself
        (((9, 3, True),), "INVALID_LAYOUT"),  # runs past the record
        (((4, 1, True), (5, 1, True), (6, 1, True), (7, 1, True)), "ALTERNATE_KEY_UNSUPPORTED"),
    ],
)
def test_bad_alternate_key_shapes_are_refused(tmp_path, alternates, code):
    with pytest.raises(VsamRefusal) as exc:
        migrate(tmp_path, records(3), alternates)
    assert exc.value.code == code


def test_unique_check_that_would_exceed_bounded_memory_is_refused(tmp_path):
    tight = VsamQuotas(stream_buffer_bytes=4096, alternate_unique_check_records=10)
    with pytest.raises(VsamRefusal) as exc:
        migrate(tmp_path, records(40), ((6, 2, False),), quotas=tight)
    assert exc.value.code == "ALTERNATE_CHECK_TOO_LARGE"


def test_resume_reproduces_the_uninterrupted_output_and_still_checks_uniqueness(tmp_path):
    recs, alternates = records(60), ((4, 2, True), (6, 2, False))
    whole_dir = tmp_path / "whole"
    whole_dir.mkdir()
    whole, whole_out = migrate(whole_dir, recs, alternates)

    blob = fixed_export(recs)
    manifest = make_manifest(blob, len(recs), alternate_keys=alternates)
    src, out = write_export(tmp_path, blob), tmp_path / "out.idx"
    with pytest.raises(KeyboardInterrupt):
        migrate_export(src, manifest, out, quotas=SMALL, stop_after_records=30)
    resumed = migrate_export(src, manifest, out, quotas=SMALL)
    assert resumed.resumed_from_records > 0
    assert resumed.output_sha256 == whole.output_sha256
    assert out.read_bytes() == whole_out.read_bytes()


def test_resume_refuses_a_unique_value_that_repeats_one_before_the_checkpoint(tmp_path):
    recs = records(30)
    recs[20] = recs[20][:6] + recs[2][6:8] + recs[20][8:]  # AKU of record 21 equals AKU of record 3
    alternates = ((6, 2, False),)
    blob = fixed_export(recs)
    manifest = make_manifest(blob, len(recs), alternate_keys=alternates)
    src, out = write_export(tmp_path, blob), tmp_path / "out.idx"
    with pytest.raises(KeyboardInterrupt):
        migrate_export(src, manifest, out, quotas=SMALL, stop_after_records=14)
    with pytest.raises(VsamRefusal) as exc:
        migrate_export(src, manifest, out, quotas=SMALL)
    assert exc.value.code == "ALTERNATE_KEY_DUPLICATE"


ALT_SELECT = KSDS_SELECT.replace(
    "RECORD KEY IS KS-KEY",
    "RECORD KEY IS KS-KEY\n               ALTERNATE RECORD KEY IS KS-AKD WITH DUPLICATES"
    "\n               ALTERNATE RECORD KEY IS KS-AKU")
ALT_FD = (
    "       FD KS.\n       01 KS-REC.\n"
    "           05 KS-KEY  PIC X(4).\n           05 KS-AKD  PIC X(2).\n"
    "           05 KS-AKU  PIC X(2).\n           05 KS-PAD  PIC X(2).\n"
)


def cobol_check(manifest, select=ALT_SELECT, fd=ALT_FD):
    return check_manifest_against_cobol(program(select, fd), manifest, "ks.dat")


def test_manifest_alternate_keys_matching_the_cobol_file_are_accepted():
    blob = fixed_export(records(3))
    layout = cobol_check(make_manifest(blob, 3, alternate_keys=((4, 2, True), (6, 2, False))))
    assert layout.key_length == 4


@pytest.mark.parametrize(
    "alternates",
    [
        ((4, 2, False), (6, 2, False)),  # duplicates flag differs
        ((6, 2, False), (4, 2, True)),   # order differs (ordinals are what the runtime registers)
        ((4, 2, True),),                 # one missing
        (),                              # none declared
    ],
)
def test_manifest_alternate_keys_that_differ_from_the_cobol_file_are_refused(alternates):
    blob = fixed_export(records(3))
    with pytest.raises(VsamRefusal) as exc:
        cobol_check(make_manifest(blob, 3, alternate_keys=alternates))
    assert exc.value.code == "ALTERNATE_KEY_MISMATCH"


def test_a_group_item_as_alternate_key_is_refused():
    fd = (
        "       FD KS.\n       01 KS-REC.\n           05 KS-KEY PIC X(4).\n"
        "           05 KS-AKD.\n               10 A PIC X(1).\n               10 B PIC X(1).\n"
        "           05 KS-AKU PIC X(2).\n           05 KS-PAD PIC X(2).\n"
    )
    blob = fixed_export(records(3))
    with pytest.raises(VsamRefusal) as exc:
        cobol_check(make_manifest(blob, 3, alternate_keys=((4, 2, True), (6, 2, False))), fd=fd)
    assert exc.value.code == "ALTERNATE_KEY_UNSUPPORTED"

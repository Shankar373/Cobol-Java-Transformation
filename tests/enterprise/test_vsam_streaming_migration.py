import hashlib
import tracemalloc

import pytest

from enterprise.quotas import VsamQuotas
from enterprise.vsam import VsamRefusal, migrate_export
from tests.enterprise.vsam_support import (
    fixed_export,
    ksds_records,
    make_manifest,
    rdw_export,
    rrds_export,
    write_export,
)

SMALL_BUFFER = VsamQuotas(stream_buffer_bytes=4096)


def run(tmp_path, blob, count, **kw):
    manifest_kw = {k: kw.pop(k) for k in list(kw) if k in {
        "organization", "record_format", "min_len", "max_len", "key_length",
        "code_page", "duplicate_keys", "alternate_keys"}}
    manifest = make_manifest(blob, count, **manifest_kw)
    src = write_export(tmp_path, blob)
    out = tmp_path / "out.idx"
    return migrate_export(src, manifest, out, quotas=SMALL_BUFFER, **kw), out


def test_ksds_fixed_produces_idx_image(tmp_path):
    recs = ksds_records(3)
    result, out = run(tmp_path, fixed_export(recs), 3)
    lines = out.read_bytes().decode().split("\n")
    assert lines[0] == "K4"
    assert lines[1] == "0001\u0001REC001"
    assert result.records == 3 and result.output_bytes == out.stat().st_size
    assert result.output_sha256 == hashlib.sha256(out.read_bytes()).hexdigest()
    assert not (tmp_path / "out.idx.part").exists()


def test_ksds_variable_rdw(tmp_path):
    recs = [b"0001AB", b"0002ABCDEF", b"0003A"]
    result, out = run(
        tmp_path, rdw_export(recs), 3, record_format="VARIABLE_RDW", min_len=5, max_len=10
    )
    assert out.read_text(encoding="utf-8").split("\n")[1:4] == [
        "0001\u0001AB", "0002\u0001ABCDEF", "0003\u0001A"]
    assert result.records == 3


def test_esds_is_line_sequential(tmp_path):
    result, out = run(tmp_path, fixed_export([b"HELLO     ", b"WORLD     "]), 2, organization="ESDS")
    assert out.read_text() == "HELLO     \nWORLD     \n"
    assert result.records == 2


def test_rrds_produces_rel_image_and_keeps_gaps(tmp_path):
    blob = rrds_export([(1, b"AAAAAAAAAA"), (4, b"BBBBBBBBBB")])
    _, out = run(tmp_path, blob, 2, organization="RRDS")
    assert out.read_text() == "R\n1\u0001AAAAAAAAAA\n4\u0001BBBBBBBBBB\n"


def test_ebcdic_cp037_is_decoded(tmp_path):
    recs = [r.decode("ascii").encode("cp037") for r in ksds_records(2)]
    _, out = run(tmp_path, fixed_export(recs), 2, code_page="cp037")
    assert out.read_text().split("\n")[1] == "0001\u0001REC001"


@pytest.mark.parametrize(
    "recs,code",
    [
        ([b"0001AAAAAA", b"0001BBBBBB"], "DUPLICATE_KEY"),
        ([b"0002AAAAAA", b"0001BBBBBB"], "KEYS_OUT_OF_ORDER"),
    ],
)
def test_ksds_key_violations_refuse_and_publish_nothing(tmp_path, recs, code):
    with pytest.raises(VsamRefusal) as exc:
        run(tmp_path, fixed_export(recs), 2)
    assert exc.value.code == code
    assert not (tmp_path / "out.idx").exists()
    assert not (tmp_path / "out.idx.part").exists()


def test_ebcdic_collation_difference_is_refused(tmp_path):
    # In EBCDIC digits sort after letters; decoded text order disagrees.
    recs = ["A".encode("cp037") + b"\xf1" * 3 + b"X" * 6, "1".encode("cp037") + b"\xf1" * 3 + b"X" * 6]
    recs = [r[:10].ljust(10, b"\x40") for r in recs]
    recs.sort()
    with pytest.raises(VsamRefusal) as exc:
        run(tmp_path, fixed_export(recs), 2, code_page="cp037")
    assert exc.value.code == "COLLATION_MISMATCH"


def test_truncated_fixed_record_refused(tmp_path):
    blob = fixed_export(ksds_records(2)) + b"0003"
    with pytest.raises(VsamRefusal) as exc:
        run(tmp_path, blob, 3)
    assert exc.value.code == "TRUNCATED_RECORD"


def test_rdw_length_out_of_range_refused(tmp_path):
    blob = rdw_export([b"0001ABCDEFGHIJKLMNOP"])
    with pytest.raises(VsamRefusal) as exc:
        run(tmp_path, blob, 1, record_format="VARIABLE_RDW", min_len=5, max_len=10)
    assert exc.value.code == "RECORD_LENGTH_OUT_OF_RANGE"


def test_binary_packed_data_is_refused_not_corrupted(tmp_path):
    blob = fixed_export([b"0001\x00\x00\x00\x0c\x00\x00"])
    with pytest.raises(VsamRefusal) as exc:
        run(tmp_path, blob, 1)
    assert exc.value.code == "UNREPRESENTABLE_RECORD"


def test_checksum_and_count_and_size_mismatches(tmp_path):
    blob = fixed_export(ksds_records(2))
    src = write_export(tmp_path, blob)
    base = make_manifest(blob, 2)
    for patch, code in (
        ({"sha256": "0" * 64}, "CHECKSUM_MISMATCH"),
        ({"record_count": 5}, "RECORD_COUNT_MISMATCH"),
    ):
        bad = base.model_copy(update=patch)
        with pytest.raises(VsamRefusal) as exc:
            migrate_export(src, bad, tmp_path / "o.idx", quotas=SMALL_BUFFER)
        assert exc.value.code == code
    wrong_size = base.model_copy(update={"dataset_bytes": 1})
    with pytest.raises(VsamRefusal) as exc:
        migrate_export(src, wrong_size, tmp_path / "o.idx", quotas=SMALL_BUFFER)
    assert exc.value.code == "SIZE_MISMATCH"
    assert not (tmp_path / "o.idx").exists()


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"alternate_keys": ((4, 2),)}, "ALTERNATE_KEY_UNSUPPORTED"),
        ({"duplicate_keys": "ALLOW"}, "DUPLICATE_KEYS_UNSUPPORTED"),
        ({"code_page": "utf-8"}, "CODE_PAGE_UNSUPPORTED"),
    ],
)
def test_unsupported_manifest_options_are_refused(tmp_path, kwargs, code):
    with pytest.raises(VsamRefusal) as exc:
        run(tmp_path, fixed_export(ksds_records(1)), 1, **kwargs)
    assert exc.value.code == code


def test_nonzero_key_offset_is_refused(tmp_path):
    blob = fixed_export(ksds_records(1))
    manifest = make_manifest(blob, 1)
    shifted = manifest.model_copy(
        update={"layout": manifest.layout.model_copy(update={"key_offset": 2})}
    )
    with pytest.raises(VsamRefusal) as exc:
        migrate_export(write_export(tmp_path, blob), shifted, tmp_path / "o.idx")
    assert exc.value.code == "KEY_OFFSET_UNSUPPORTED"


def test_dataset_quota_is_enforced(tmp_path):
    blob = fixed_export(ksds_records(5))
    manifest = make_manifest(blob, 5)
    with pytest.raises(VsamRefusal) as exc:
        migrate_export(
            write_export(tmp_path, blob), manifest, tmp_path / "o.idx",
            quotas=VsamQuotas(dataset_bytes=10),
        )
    assert exc.value.code == "DATASET_TOO_LARGE"


def test_interrupted_run_resumes_to_identical_output(tmp_path):
    blob = fixed_export(ksds_records(500))
    manifest = make_manifest(blob, 500)
    src = write_export(tmp_path, blob)
    reference = tmp_path / "ref.idx"
    ref = migrate_export(src, manifest, reference, quotas=SMALL_BUFFER)

    out = tmp_path / "resumed.idx"
    with pytest.raises(KeyboardInterrupt):
        migrate_export(src, manifest, out, quotas=SMALL_BUFFER,
                       checkpoint_every=100, stop_after_records=250)
    assert not out.exists()
    result = migrate_export(src, manifest, out, quotas=SMALL_BUFFER, checkpoint_every=100)
    assert result.resumed_from_records == 200
    assert out.read_bytes() == reference.read_bytes()
    assert result.output_sha256 == ref.output_sha256
    assert not (tmp_path / "resumed.idx.ckpt").exists()


def test_resume_refused_when_source_content_changed(tmp_path):
    blob = fixed_export(ksds_records(300))
    manifest = make_manifest(blob, 300)
    src = write_export(tmp_path, blob)
    out = tmp_path / "o.idx"
    with pytest.raises(KeyboardInterrupt):
        migrate_export(src, manifest, out, quotas=SMALL_BUFFER,
                       checkpoint_every=50, stop_after_records=120)
    tampered = bytearray(blob)
    tampered[5] ^= 0x01  # same size, different content inside the checkpointed prefix
    src.write_bytes(bytes(tampered))
    with pytest.raises(VsamRefusal) as exc:
        migrate_export(src, manifest, out, quotas=SMALL_BUFFER, checkpoint_every=50)
    assert exc.value.code == "RESUME_REJECTED"
    assert not out.exists()


def test_repeated_conversion_is_deterministic(tmp_path):
    blob = fixed_export(ksds_records(200))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first, a = run(tmp_path / "a", blob, 200)
    second, b = run(tmp_path / "b", blob, 200)
    assert first.output_sha256 == second.output_sha256
    assert a.read_bytes() == b.read_bytes()


def test_memory_does_not_grow_with_dataset_size(tmp_path):
    def peak(count, sub):
        folder = tmp_path / sub
        folder.mkdir()
        blob = fixed_export(ksds_records(count))
        manifest = make_manifest(blob, count)
        src = write_export(folder, blob)
        del blob
        tracemalloc.start()
        migrate_export(src, manifest, folder / "o.idx", quotas=SMALL_BUFFER)
        _, high = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return high

    small = peak(500, "s")
    large = peak(9000, "l")  # 18x the data
    assert large < small + 128 * 1024

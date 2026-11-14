"""Behavior every ObjectStore adapter must satisfy (local now; S3-compatible next)."""

import hashlib
import io

import pytest

from enterprise.quotas import IngestionQuotas, QuotaExceeded
from enterprise.storage import (
    IntegrityError,
    InvalidKey,
    LocalObjectStore,
    ObjectNotFound,
    validate_key,
)

QUOTAS = IngestionQuotas(multipart_part_min_bytes=4, multipart_part_max_bytes=64, multipart_max_parts=50)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(params=["local"])
def store(request, tmp_path):
    if request.param == "local":
        return LocalObjectStore(tmp_path / "store", QUOTAS)
    raise AssertionError(request.param)


def test_put_stat_open_roundtrip(store):
    ref = store.put("src/app1/snap.zip", io.BytesIO(b"hello world"))
    assert (ref.size, ref.sha256, ref.version) == (11, sha(b"hello world"), sha(b"hello world"))
    assert store.stat("src/app1/snap.zip") == ref
    with store.open("src/app1/snap.zip") as handle:
        assert handle.read() == b"hello world"
    assert store.verify("src/app1/snap.zip") is True


def test_expected_checksum_mismatch_leaves_nothing(store):
    with pytest.raises(IntegrityError):
        store.put("a/b.bin", io.BytesIO(b"data"), expected_sha256="0" * 64)
    with pytest.raises(ObjectNotFound):
        store.stat("a/b.bin")
    assert list(store.list()) == []


def test_max_bytes_is_enforced_while_streaming(store):
    with pytest.raises(QuotaExceeded):
        store.put("a/big.bin", io.BytesIO(b"x" * 100), max_bytes=10)
    assert list(store.list()) == []


@pytest.mark.parametrize(
    "key", ["", "/abs", "a/../b", "a/./b", "a//b", "../x", "a/b/", "a\\b", "a/b c", "a/.hidden", "x" * 600],
)
def test_invalid_keys_are_rejected(store, key):
    with pytest.raises(InvalidKey):
        store.put(key, io.BytesIO(b"x"))
    with pytest.raises(InvalidKey):
        validate_key(key)


def test_overwrite_changes_version_and_missing_object_errors(store):
    first = store.put("k/v", io.BytesIO(b"one"))
    second = store.put("k/v", io.BytesIO(b"two"))
    assert first.version != second.version
    assert store.stat("k/v").version == second.version
    store.delete("k/v")
    store.delete("k/v")  # idempotent
    for call in (store.stat, store.open, store.verify):
        with pytest.raises(ObjectNotFound):
            call("k/v")


def test_list_filters_by_prefix(store):
    for key in ("x/1", "x/2", "y/1"):
        store.put(key, io.BytesIO(b"."))
    assert list(store.list("x/")) == ["x/1", "x/2"]
    assert list(store.list()) == ["x/1", "x/2", "y/1"]


def _upload(store, key, chunks):
    upload = store.create_multipart(key)
    return upload, [(i, store.upload_part(key, upload, i, c)) for i, c in enumerate(chunks, start=1)]


def test_multipart_roundtrip(store):
    chunks = [b"aaaa", b"bbbbbb", b"cc"]
    whole = b"".join(chunks)
    upload, parts = _upload(store, "big/obj", chunks)
    ref = store.complete_multipart("big/obj", upload, parts, expected_sha256=sha(whole), expected_size=len(whole))
    assert ref.sha256 == sha(whole) and ref.size == len(whole)
    with store.open("big/obj") as handle:
        assert handle.read() == whole


def test_multipart_wrong_whole_checksum_publishes_nothing(store):
    upload, parts = _upload(store, "big/bad", [b"aaaa", b"bb"])
    with pytest.raises(IntegrityError):
        store.complete_multipart("big/bad", upload, parts, expected_sha256="0" * 64, expected_size=6)
    with pytest.raises(ObjectNotFound):
        store.stat("big/bad")


def test_multipart_tampered_part_and_missing_part_are_rejected(store):
    upload, parts = _upload(store, "big/t", [b"aaaa", b"bbbb"])
    forged = [(1, "0" * 64), parts[1]]
    with pytest.raises(IntegrityError):
        store.complete_multipart("big/t", upload, forged, expected_sha256=sha(b"aaaabbbb"), expected_size=8)
    with pytest.raises(IntegrityError):
        store.complete_multipart("big/t", upload, [*parts, (3, "1" * 64)],
                                 expected_sha256=sha(b"aaaabbbb"), expected_size=8)


def test_multipart_small_non_final_part_and_bad_numbers(store):
    upload, parts = _upload(store, "big/s", [b"aa", b"bbbb"])
    with pytest.raises(IntegrityError):
        store.complete_multipart("big/s", upload, parts, expected_sha256=sha(b"aabbbb"), expected_size=6)
    with pytest.raises(InvalidKey):
        store.upload_part("big/s", upload, 0, b"x")
    with pytest.raises(InvalidKey):
        store.upload_part("big/s", upload, 51, b"x")
    with pytest.raises(QuotaExceeded):
        store.upload_part("big/s", upload, 1, b"x" * 65)
    with pytest.raises(IntegrityError):
        store.complete_multipart("big/s", upload, [parts[1], parts[0]],
                                 expected_sha256=sha(b"aabbbb"), expected_size=6)


def test_multipart_abort_and_wrong_key(store):
    upload, parts = _upload(store, "big/a", [b"aaaa"])
    with pytest.raises(ObjectNotFound):
        store.upload_part("big/other", upload, 2, b"zzzz")
    store.abort_multipart("big/a", upload)
    with pytest.raises(ObjectNotFound):
        store.complete_multipart("big/a", upload, parts, expected_sha256=sha(b"aaaa"), expected_size=4)


def test_local_verify_detects_on_disk_corruption(tmp_path):
    local = LocalObjectStore(tmp_path / "s", QUOTAS)
    local.put("c/o", io.BytesIO(b"original"))
    (tmp_path / "s" / "objects" / "c" / "o").write_bytes(b"tampered")
    assert local.verify("c/o") is False

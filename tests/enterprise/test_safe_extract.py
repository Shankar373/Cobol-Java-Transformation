"""Safe ZIP extraction: every refusal has a stable code and leaves nothing behind."""

import hashlib
import os
import stat
import zipfile
from pathlib import Path

import pytest

from enterprise.ingest.safe_extract import ArchiveRefusal, ExtractLimits, extract_zip


def make_zip(path: Path, entries, compression=zipfile.ZIP_DEFLATED) -> Path:
    """entries: (name, data) or (name, data, unix_mode); names are written exactly as given."""
    with zipfile.ZipFile(path, "w", compression) as zf:
        for entry in entries:
            name, data = entry[0], entry[1]
            info = zipfile.ZipInfo("placeholder")
            info.filename = name  # assigned after construction: ZipInfo would rewrite a backslash on Windows
            info.compress_type = compression
            if len(entry) > 2:
                info.external_attr = entry[2] << 16
            zf.writestr(info, data)
    return path


def refusal(tmp_path, entries, limits=None, compression=zipfile.ZIP_DEFLATED) -> str:
    archive = make_zip(tmp_path / "a.zip", entries, compression)
    dest = tmp_path / "out"
    with pytest.raises(ArchiveRefusal) as exc:
        extract_zip(archive, dest, limits)
    assert not dest.exists(), "a refused archive must leave nothing extracted"
    return exc.value.code


def test_extracts_files_with_sizes_and_hashes_in_sorted_order(tmp_path):
    archive = make_zip(tmp_path / "a.zip", [("src/b.cbl", b"BBB"), ("a.txt", b"hello"), ("src/", b""), ("src/c/d.cpy", b"")])
    result = extract_zip(archive, tmp_path / "out")
    assert [f.path for f in result.files] == ["a.txt", "src/b.cbl", "src/c/d.cpy"]
    assert result.files[0].sha256 == hashlib.sha256(b"hello").hexdigest() and result.files[0].size == 5
    assert (tmp_path / "out" / "src" / "b.cbl").read_bytes() == b"BBB"
    assert result.expanded_bytes == 8 and result.skipped == ()


@pytest.mark.parametrize(
    "name",
    ["../evil.txt", "a/../../evil.txt", "/abs.txt", "C:/win.txt", "a/./b.txt", "a//b.txt", "x/..",
     "dir/CON.txt", "trailing./x", "space /x", "a" * 2000],
)
def test_path_traversal_and_non_portable_names_are_refused(tmp_path, name):
    assert refusal(tmp_path, [("fine.txt", b"x"), (name, b"evil")]) == "ARCHIVE_BAD_PATH"
    assert not (tmp_path / "evil.txt").exists()


def test_symlinks_are_refused_by_default_and_skipped_when_asked(tmp_path):
    link = ("lib/link", b"/etc/passwd", stat.S_IFLNK | 0o777)
    assert refusal(tmp_path, [("a.txt", b"x"), link]) == "ARCHIVE_SYMLINK"
    archive = make_zip(tmp_path / "b.zip", [("a.txt", b"x"), link])
    result = extract_zip(archive, tmp_path / "out2", ExtractLimits(symlinks="skip"))
    assert [f.path for f in result.files] == ["a.txt"] and result.skipped == (("lib/link", "symlink"),)
    assert not (tmp_path / "out2" / "lib" / "link").exists()


def test_special_files_are_always_refused(tmp_path):
    fifo = ("pipe", b"", stat.S_IFIFO | 0o644)
    assert refusal(tmp_path, [fifo]) == "ARCHIVE_SPECIAL"
    assert refusal(tmp_path, [fifo], ExtractLimits(symlinks="skip")) == "ARCHIVE_SPECIAL"


@pytest.mark.filterwarnings("ignore:Duplicate name")  # zipfile warns about the repeated name we write on purpose
def test_paths_that_differ_only_by_case_collide(tmp_path):
    assert refusal(tmp_path, [("Readme.md", b"1"), ("README.MD", b"2")]) == "ARCHIVE_DUPLICATE_PATH"
    assert refusal(tmp_path, [("same.txt", b"1"), ("same.txt", b"2")]) == "ARCHIVE_DUPLICATE_PATH"


@pytest.mark.skipif(os.sep != "/", reason="zipfile rewrites a backslash to a slash while reading on Windows")
def test_a_backslash_in_an_entry_name_is_refused(tmp_path):
    assert refusal(tmp_path, [("a\\b.txt", b"x")]) == "ARCHIVE_BAD_PATH"


def test_encrypted_entries_are_refused(tmp_path):
    archive = make_zip(tmp_path / "enc.zip", [("secret.txt", b"x" * 64)])
    raw = bytearray(archive.read_bytes())
    raw[raw.index(b"PK\x01\x02") + 8] |= 0x1  # general purpose flag bit 0 in the central directory: encrypted
    archive.write_bytes(bytes(raw))
    with pytest.raises(ArchiveRefusal) as exc:
        extract_zip(archive, tmp_path / "out")
    assert exc.value.code == "ARCHIVE_ENCRYPTED"


def test_count_depth_and_size_limits(tmp_path):
    many = [(f"f{i}.txt", b"x") for i in range(6)]
    assert refusal(tmp_path, many, ExtractLimits(max_files=5)) == "ARCHIVE_TOO_MANY_FILES"
    assert refusal(tmp_path, [("a/b/c/d.txt", b"x")], ExtractLimits(max_depth=3)) == "ARCHIVE_TOO_DEEP"
    assert refusal(tmp_path, [("big.bin", b"x" * 100)], ExtractLimits(max_file_bytes=50)) == "ARCHIVE_FILE_TOO_LARGE"


def test_decompression_bomb_is_refused_by_ratio(tmp_path):
    zeros = b"\0" * (20 * 1024 * 1024)  # 20 MiB of zeros deflates to about 20 KiB
    assert refusal(tmp_path, [("bomb.bin", zeros)]) == "ARCHIVE_BOMB"


def test_actual_expanded_bytes_are_counted_not_just_declared_sizes(tmp_path):
    # ratio check disabled so only the running total of bytes really written can stop it
    limits = ExtractLimits(max_compression_ratio=10**9, max_expanded_bytes=1024 * 1024)
    entries = [(f"z{i}.bin", b"\0" * 400_000) for i in range(4)]
    assert refusal(tmp_path, entries, limits) == "ARCHIVE_BOMB"


def test_not_a_zip_truncated_and_corrupt_archives_are_refused(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"this is not a zip file at all")
    with pytest.raises(ArchiveRefusal) as exc:
        extract_zip(bad, tmp_path / "o1")
    assert exc.value.code == "ARCHIVE_INVALID"

    good = make_zip(tmp_path / "good.zip", [("a.txt", b"hello world" * 100)])
    bad.write_bytes(good.read_bytes()[:-30])  # the central directory is cut off
    with pytest.raises(ArchiveRefusal) as exc:
        extract_zip(bad, tmp_path / "o2")
    assert exc.value.code == "ARCHIVE_INVALID"

    stored = make_zip(tmp_path / "stored.zip", [("a.txt", b"A" * 64)], zipfile.ZIP_STORED)
    raw = bytearray(stored.read_bytes())
    raw[raw.index(b"A" * 64) + 10] ^= 0xFF  # flip a data byte: the CRC no longer matches
    bad.write_bytes(bytes(raw))
    with pytest.raises(ArchiveRefusal) as exc:
        extract_zip(bad, tmp_path / "o3")
    assert exc.value.code == "ARCHIVE_CORRUPT"
    assert not (tmp_path / "o3").exists()


def test_a_non_empty_target_is_refused_and_left_untouched(tmp_path):
    archive = make_zip(tmp_path / "a.zip", [("a.txt", b"x")])
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("mine")
    with pytest.raises(ArchiveRefusal) as exc:
        extract_zip(archive, out)
    assert exc.value.code == "ARCHIVE_DEST_NOT_EMPTY" and (out / "keep.txt").read_text() == "mine"


def test_extraction_is_deterministic(tmp_path):
    entries = [("b.txt", b"2"), ("a.txt", b"1"), ("c/d.txt", b"3")]
    archive = make_zip(tmp_path / "a.zip", entries)
    first = extract_zip(archive, tmp_path / "o1")
    second = extract_zip(archive, tmp_path / "o2")
    assert first == second

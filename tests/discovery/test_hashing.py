"""Unit tests for hashing and encoding detection (plan §5.2).

Two invariants:

* **Bytes are never modified.**  Detection is metadata; the digest is taken
  over exactly what was ingested.
* **Confidence is honest.**  A BOM is proof, a strict UTF-8 decode is strong
  evidence, a cp1252 fallback is a guess — and the three are labelled
  differently rather than presented as equal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.discovery.hashing import (
    EncodingGuess,
    detect_encoding,
    sha256_bytes,
    sha256_file,
)

EMPTY_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
HELLO_SHA256 = (
    "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
)


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def test_sha256_of_empty_input() -> None:
    assert sha256_bytes(b"") == EMPTY_SHA256


def test_sha256_known_vector() -> None:
    assert sha256_bytes(b"hello") == HELLO_SHA256


def test_sha256_file_matches_bytes(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    path.write_bytes(b"hello")
    assert sha256_file(path) == sha256_bytes(b"hello")


def test_sha256_file_is_streamed_and_stable(tmp_path: Path) -> None:
    """A file larger than one chunk hashes the same as its bytes."""

    payload = b"x" * (1024 * 1024 + 7)
    path = tmp_path / "big.bin"
    path.write_bytes(payload)
    assert sha256_file(path) == sha256_bytes(payload)


def test_sha256_file_does_not_modify_the_file(tmp_path: Path) -> None:
    path = tmp_path / "keep.bin"
    path.write_bytes(b"hello")
    before = path.read_bytes()
    sha256_file(path)
    assert path.read_bytes() == before


def test_digests_differ_for_different_bytes() -> None:
    assert sha256_bytes(b"a") != sha256_bytes(b"b")


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "name", "confidence", "bom"),
    [
        (b"", "ascii", "high", False),
        (b"unit u;\n", "ascii", "high", False),
        (b"unit u;\r\nend.\r\n", "ascii", "high", False),
        (b"caf\xc3\xa9", "utf-8", "high", False),
        ("unit \u00fcnicode;\n".encode("utf-8"), "utf-8", "high", False),
        (b"caf\xe9", "cp1252", "low", False),
        (b"\x81", "latin-1", "low", False),
        (b"\xef\xbb\xbfunit u;\n", "utf-8", "high", True),
        (b"\xff\xfe" + "unit u;\n".encode("utf-16-le"),
         "utf-16-le", "high", True),
        (b"\xfe\xff" + "unit u;\n".encode("utf-16-be"),
         "utf-16-be", "high", True),
        (b"\x00\x00\xfe\xff" + "u".encode("utf-32-be"),
         "utf-32-be", "high", True),
        (b"\xff\xfe\x00\x00" + "u".encode("utf-32-le"),
         "utf-32-le", "high", True),
        (b"\x00\x01\x02\x03BINARYBLOB\xff\xfe", "binary", "high", False),
    ],
)
def test_detect_encoding(
    data: bytes, name: str, confidence: str, bom: bool
) -> None:
    guess = detect_encoding(data)
    assert guess.name == name
    assert guess.confidence == confidence
    assert guess.bom is bom


def test_bom_length_is_reported() -> None:
    assert detect_encoding(b"\xef\xbb\xbf").bom_length == 3
    assert detect_encoding(b"\xff\xfe").bom_length == 2
    assert detect_encoding(b"\xfe\xff").bom_length == 2
    assert detect_encoding(b"\xff\xfe\x00\x00").bom_length == 4
    assert detect_encoding(b"unit u;\n").bom_length == 0


def test_ascii_is_labelled_ascii_not_utf8() -> None:
    """A subset of every candidate is unambiguous, so it is named exactly."""

    guess = detect_encoding(b"unit u;\n")
    assert guess.name == "ascii"
    assert guess.confidence == "high"


def test_strict_utf8_is_high_confidence() -> None:
    guess = detect_encoding("na\u00efve".encode("utf-8"))
    assert guess.name == "utf-8"
    assert guess.confidence == "high"


def test_cp1252_fallback_is_explicitly_a_guess() -> None:
    guess = detect_encoding(b"caf\xe9")
    assert guess.name == "cp1252"
    assert guess.confidence == "low"


def test_byte_undefined_in_cp1252_falls_back_to_latin_1() -> None:
    # 0x81, 0x8d, 0x8f, 0x90 and 0x9d are undefined in cp1252.
    for byte in (b"\x81", b"\x8d", b"\x8f", b"\x90", b"\x9d"):
        guess = detect_encoding(byte)
        assert guess.name == "latin-1"
        assert guess.confidence == "low"


def test_interior_nuls_are_a_utf16_heuristic_at_medium_confidence() -> None:
    guess = detect_encoding("unit u; interface end.".encode("utf-16-le"))
    assert guess.name == "utf-16-le"
    assert guess.confidence == "medium"


def test_utf16_be_without_a_bom_is_not_claimed() -> None:
    """The NUL-offset heuristic only recognises little-endian layout.

    Guessing ``utf-16-be`` from a big-endian buffer would be a coin flip
    dressed up as a detection, so the honest answer is ``binary``.
    """

    guess = detect_encoding("unit u; interface end.".encode("utf-16-be"))
    assert guess.name == "binary"
    assert guess.confidence == "high"


def test_detection_never_mutates_the_input() -> None:
    data = b"\xef\xbb\xbfunit u;\n"
    before = bytes(data)
    detect_encoding(data)
    assert data == before


def test_as_dict_has_the_stable_key_set() -> None:
    keys = set(detect_encoding(b"unit u;\n").as_dict())
    assert keys == {"bom", "bom_length", "confidence", "encoding"}


def test_encoding_guess_is_comparable_and_hashable() -> None:
    """Frozen dataclass: equal guesses are interchangeable in sets/dicts."""

    a = detect_encoding(b"unit u;\n")
    b = detect_encoding(b"other ascii")
    assert a == b
    assert len({a, b}) == 1
    assert isinstance(a, EncodingGuess)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x00",
        b"\xff",
        b"\xfe\xff",
        b"\xef\xbb\xbf",
        bytes(range(256)),
        b"unit u;\r\n",
    ],
)
def test_detection_is_deterministic(data: bytes) -> None:
    assert detect_encoding(data) == detect_encoding(bytes(data))

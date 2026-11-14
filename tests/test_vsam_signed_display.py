"""Signed zoned DISPLAY numerics (PIC S9(n), sign overpunched in a digit) are converted as numbers, not as text.

Review finding: the sign of ``PIC S9(3)`` lives in the zone of its last (or, with SIGN LEADING, first) byte, so
translating the bytes as characters turned EBCDIC ``F1 F2 D3`` (-123) into the ASCII text ``12L``.  GnuCOBOL's ASCII form
(identical in 3.1.2 and 3.2.0, default and -std=ibm; see tests/integration/test_vsam_consumer_oracle.py) is: positive =
plain digits, negative = the sign digit shifted into ``p``..``y`` (0x70 + digit).  EBCDIC: positive zone C (or F), negative
zone D.  Anything else is rejected with the field named, never guessed.  Dependency-free (pytest only).
"""
from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.convert import convert_record
from engine.vsam.layout import BinaryWidthModel, derive_file_layout
from engine.vsam.model import Encoding

FD = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
      "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO \"F.DAT\".\n"
      "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n"
      "       01 REC.\n          05 T PIC S9(3).\n          05 L PIC S9(3) SIGN IS LEADING.\n"
      "          05 U PIC 9(3).\n          05 S PIC S9(3) SIGN IS TRAILING SEPARATE.\n"
      "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n")
LAYOUT = derive_file_layout(CobolParser().parse(FD).file_definitions[0], binary_width_model=BinaryWidthModel.IBM_2_4_8)
SPECS = LAYOUT.field_specs()


def convert(record: bytes, source: Encoding, destination: Encoding) -> bytes:
    return convert_record(record, SPECS, source, destination)


def ascii_record(t: str, l: str, u: str, s: str = "+123") -> bytes:
    return (t + l + u + s).encode("ascii")


def ebcdic_record(t: bytes, l: bytes, u: bytes, s: str = "+123") -> bytes:
    return t + l + u + s.encode("cp037")


def test_the_layout_records_where_each_sign_lives():
    by_name = {f.source: f.sign_overpunch for f in LAYOUT.fields}
    assert by_name == {"T": "TRAILING", "L": "LEADING", "U": "", "S": ""}      # unsigned and SIGN SEPARATE have none


@pytest.mark.parametrize("ascii_t,ebcdic_t", [
    ("12s", bytes([0xF1, 0xF2, 0xD3])),     # -123
    ("123", bytes([0xF1, 0xF2, 0xC3])),     # +123
    ("09p", bytes([0xF0, 0xF9, 0xD0])),     # -90
    ("000", bytes([0xF0, 0xF0, 0xC0])),     # 0
])
def test_a_trailing_overpunch_is_translated_as_a_number_in_both_directions(ascii_t, ebcdic_t):
    ascii_rec = ascii_record(ascii_t, "123", "123")
    ebcdic_rec = ebcdic_record(ebcdic_t, bytes([0xC1, 0xF2, 0xF3]), bytes([0xF1, 0xF2, 0xF3]))   # L: +123 SIGN LEADING
    assert convert(ascii_rec, Encoding.ASCII, Encoding.EBCDIC_CP037) == ebcdic_rec
    assert convert(ebcdic_rec, Encoding.EBCDIC_CP037, Encoding.ASCII) == ascii_rec


@pytest.mark.parametrize("ascii_l,ebcdic_l", [
    ("q23", bytes([0xD1, 0xF2, 0xF3])),     # -123 SIGN LEADING
    ("p09", bytes([0xD0, 0xF0, 0xF9])),     # -9
    ("123", bytes([0xC1, 0xF2, 0xF3])),     # +123
])
def test_a_leading_overpunch_is_translated_from_the_first_byte(ascii_l, ebcdic_l):
    ascii_rec = ascii_record("123", ascii_l, "123")
    ebcdic_rec = ebcdic_record(bytes([0xF1, 0xF2, 0xC3]), ebcdic_l, bytes([0xF1, 0xF2, 0xF3]))
    assert convert(ascii_rec, Encoding.ASCII, Encoding.EBCDIC_CP037) == ebcdic_rec
    assert convert(ebcdic_rec, Encoding.EBCDIC_CP037, Encoding.ASCII) == ascii_rec


def test_an_ebcdic_unsigned_looking_positive_zone_f_is_a_positive_number():
    rec = ebcdic_record(bytes([0xF1, 0xF2, 0xF3]), bytes([0xF1, 0xF2, 0xF3]), bytes([0xF1, 0xF2, 0xF3]))
    assert convert(rec, Encoding.EBCDIC_CP037, Encoding.ASCII)[:3] == b"123"


@pytest.mark.parametrize("bad_t", [bytes([0xF1, 0xF2, 0xA3]), bytes([0xF1, 0xF2, 0xE3]), bytes([0xF1, 0xF2, 0x40]),
                                   bytes([0xC1, 0xF2, 0xC3]), bytes([0xF1, 0xFA, 0xC3])])
def test_an_invalid_ebcdic_zoned_field_is_rejected_with_the_field_named(bad_t):
    rec = ebcdic_record(bad_t, bytes([0xF1, 0xF2, 0xC3]), bytes([0xF1, 0xF2, 0xF3]))
    with pytest.raises(ValueError, match="field REC.T"):
        convert(rec, Encoding.EBCDIC_CP037, Encoding.ASCII)


@pytest.mark.parametrize("bad", ["12z", "1 3", "12L", "-23", "12\x00"])
def test_an_invalid_ascii_zoned_field_is_rejected_with_the_field_named(bad):
    with pytest.raises(ValueError, match="field REC.T"):
        convert(ascii_record(bad, "123", "123"), Encoding.ASCII, Encoding.EBCDIC_CP037)


def test_the_value_survives_a_round_trip_for_every_three_digit_signed_number():
    for value in range(-999, 1000):
        digits = f"{abs(value):03d}"
        ascii_t = digits[:2] + (chr(0x70 + int(digits[2])) if value < 0 else digits[2])
        rec = ascii_record(ascii_t, "123", "123")
        assert convert(convert(rec, Encoding.ASCII, Encoding.EBCDIC_CP037), Encoding.EBCDIC_CP037, Encoding.ASCII) == rec

"""G-27: binary fields are converted between explicit source and target representations, or refused.

COMP is big-endian on both IBM and GnuCOBOL; COMP-5 is native byte order (big-endian on z/OS,
little-endian on the x86 oracle); the byte width of a binary item depends on the width model (IBM
2/4/8 bytes, GnuCOBOL default 1/2/4/8).  A binary field is therefore decoded to an integer, checked
and re-encoded for the target - never copied as if it were portable.  COMP-3 and DISPLAY semantics are
untouched by the platform.  Nothing is inferred: the representations are named by the caller.
Dependency-free (pytest only).
"""
from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import BinaryWidthModel, RecordLayout, derive_file_layout
from engine.vsam.platform import (
    PLATFORMS, BinaryRepresentation, ByteOrder, check_binary_fields, convert_record_between, platform,
)

IBM_Z = platform("IBM_ZOS")
GNU = platform("GNUCOBOL_X86_DEFAULT")
GNU_IBM = platform("GNUCOBOL_X86_IBM_DIALECT")


def fd(*record_lines: str) -> str:
    body = "\n".join("       " + line for line in record_lines)
    return ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO \"F.DAT\".\n"
            "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n" + body + "\n"
            "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n")


def layout(plat: BinaryRepresentation, *record_lines: str) -> RecordLayout:
    program = CobolParser().parse(fd(*record_lines))
    return derive_file_layout(program.file_definitions[0], binary_width_model=plat.width_model)


def both(source: BinaryRepresentation, target: BinaryRepresentation, *record_lines: str):
    return layout(source, *record_lines), layout(target, *record_lines)


# --- the representations -----------------------------------------------------------------------------------------------

def test_the_documented_platforms_are_explicit_about_order_width_and_evidence():
    assert IBM_Z.comp_byte_order is ByteOrder.BIG and IBM_Z.comp5_byte_order is ByteOrder.BIG
    assert IBM_Z.width_model is BinaryWidthModel.IBM_2_4_8
    assert GNU.comp_byte_order is ByteOrder.BIG and GNU.comp5_byte_order is ByteOrder.LITTLE
    assert GNU.width_model is BinaryWidthModel.GNUCOBOL_1_2_4_8
    assert GNU_IBM.width_model is BinaryWidthModel.IBM_2_4_8 and GNU_IBM.comp5_byte_order is ByteOrder.LITTLE
    assert "DOCUMENTED" in IBM_Z.evidence and "no IBM" in IBM_Z.evidence
    assert "GNUCOBOL_DIFFERENTIAL" in GNU.evidence and "GNUCOBOL_DIFFERENTIAL" in GNU_IBM.evidence
    assert set(PLATFORMS) == {"IBM_ZOS", "GNUCOBOL_X86_DEFAULT", "GNUCOBOL_X86_IBM_DIALECT"}


def test_an_unknown_platform_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown platform 'AS400'"):
        platform("AS400")


# --- COMP-5 byte order -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [0, 1, -1, 12345, -12345, 32767, -32768])
def test_comp5_is_reordered_between_a_little_and_a_big_endian_platform(value):
    src, dst = both(GNU_IBM, IBM_Z, "01 REC.", "   05 N PIC S9(4) COMP-5.")
    record = value.to_bytes(2, "little", signed=True)
    out = convert_record_between(record, src, dst, GNU_IBM, IBM_Z, "ASCII", "ASCII")
    assert out == value.to_bytes(2, "big", signed=True)


def test_comp_is_big_endian_on_every_platform_so_its_bytes_do_not_move():
    src, dst = both(GNU_IBM, IBM_Z, "01 REC.", "   05 N PIC S9(4) COMP.")
    record = (-1234).to_bytes(2, "big", signed=True)
    assert convert_record_between(record, src, dst, GNU_IBM, IBM_Z, "ASCII", "ASCII") == record


def test_round_trip_between_platforms_restores_the_original_bytes():
    lines = ("01 REC.", "   05 A PIC S9(4) COMP-5.", "   05 B PIC S9(9) COMP.", "   05 C PIC 9(18) COMP-5.")
    there_src, there_dst = both(GNU_IBM, IBM_Z, *lines)
    record = ((-777).to_bytes(2, "little", signed=True) + (123456789).to_bytes(4, "big", signed=True)
              + (10**17).to_bytes(8, "little", signed=False))
    converted = convert_record_between(record, there_src, there_dst, GNU_IBM, IBM_Z, "ASCII", "ASCII")
    back = convert_record_between(converted, there_dst, there_src, IBM_Z, GNU_IBM, "ASCII", "ASCII")
    assert back == record and converted != record


# --- widths: IBM 2/4/8 versus GnuCOBOL default 1/2/4/8 -------------------------------------------------------------------------

@pytest.mark.parametrize("digits,value", [(2, 42), (2, -99), (2, 0), (2, 99), (4, 9999), (4, -9999), (9, 999999999),
                                          (10, 9999999999), (18, 10**18 - 1), (18, -(10**18 - 1))])
def test_comp_widens_from_the_gnucobol_default_to_the_ibm_width(digits, value):
    src, dst = both(GNU, IBM_Z, "01 REC.", f"   05 N PIC S9({digits}) COMP.")
    width_src = src.fields[0].length
    out = convert_record_between(value.to_bytes(width_src, "big", signed=True), src, dst, GNU, IBM_Z, "ASCII", "ASCII")
    assert len(out) == dst.record_length and dst.record_length >= src.record_length
    assert int.from_bytes(out, "big", signed=True) == value


def test_comp_narrows_from_ibm_to_the_gnucobol_default_only_when_the_value_fits_the_picture():
    src, dst = both(IBM_Z, GNU, "01 REC.", "   05 N PIC S9(2) COMP.")
    assert (src.record_length, dst.record_length) == (2, 1)
    ok = convert_record_between((42).to_bytes(2, "big", signed=True), src, dst, IBM_Z, GNU, "ASCII", "ASCII")
    assert ok == (42).to_bytes(1, "big", signed=True)


def test_an_unsigned_comp_field_is_decoded_unsigned():
    src, dst = both(GNU, IBM_Z, "01 REC.", "   05 N PIC 9(2) COMP.")
    out = convert_record_between(bytes([99]), src, dst, GNU, IBM_Z, "ASCII", "ASCII")
    assert int.from_bytes(out, "big", signed=False) == 99


def test_scaled_binary_converts_the_stored_integer_not_a_decimal():
    src, dst = both(GNU, IBM_Z, "01 REC.", "   05 PRICE PIC S9(5)V99 COMP.")
    stored = -1234567                                          # -12345.67 scaled by 100
    out = convert_record_between(stored.to_bytes(4, "big", signed=True), src, dst, GNU, IBM_Z, "ASCII", "ASCII")
    assert int.from_bytes(out, "big", signed=True) == stored


# --- overflow, truncation and corruption are rejected with a reason -----------------------------------------------------------------

def test_a_comp_value_larger_than_its_picture_is_rejected_not_silently_truncated():
    src, dst = both(IBM_Z, GNU, "01 REC.", "   05 N PIC S9(2) COMP.")
    bad = (100).to_bytes(2, "big", signed=True)                # fits the 2-byte field, exceeds PIC S9(2)
    assert "exceeds" in (check_binary_fields(bad, src, IBM_Z) or "")
    with pytest.raises(ValueError, match="N: .*exceeds the 2 digits"):
        convert_record_between(bad, src, dst, IBM_Z, GNU, "ASCII", "ASCII")


def test_comp5_is_not_limited_by_the_picture_but_by_the_target_width():
    src, dst = both(IBM_Z, GNU, "01 REC.", "   05 N PIC S9(2) COMP-5.")
    big = (1000).to_bytes(2, "big", signed=True)               # beyond PIC S9(2), legal in COMP-5; target is 1 byte wide
    assert check_binary_fields(big, src, IBM_Z) is None
    with pytest.raises(ValueError, match="does not fit the 1-byte target"):
        convert_record_between(big, src, dst, IBM_Z, GNU, "ASCII", "ASCII")
    assert convert_record_between((100).to_bytes(2, "big", signed=True), src, dst, IBM_Z, GNU, "ASCII", "ASCII") == bytes([100])


def test_the_extreme_values_of_each_width_round_trip():
    for digits, width in ((4, 2), (9, 4), (18, 8)):
        src, dst = both(IBM_Z, IBM_Z, "01 REC.", f"   05 N PIC S9({digits}) COMP-5.")
        for value in (-(2 ** (8 * width - 1)), 2 ** (8 * width - 1) - 1):
            record = value.to_bytes(width, "big", signed=True)
            assert convert_record_between(record, src, dst, IBM_Z, IBM_Z, "ASCII", "ASCII") == record


def test_a_record_shorter_than_the_layout_is_rejected():
    src, dst = both(GNU, IBM_Z, "01 REC.", "   05 N PIC S9(4) COMP.", "   05 T PIC X(3).")
    with pytest.raises(ValueError, match="record length"):
        convert_record_between(b"\x00\x01", src, dst, GNU, IBM_Z, "ASCII", "ASCII")


# --- the rest of the record keeps its own semantics ---------------------------------------------------------------------------------

def test_display_is_translated_packed_is_validated_and_copied_and_offsets_follow_the_target_layout():
    lines = ("01 REC.", "   05 ID PIC X(4).", "   05 N PIC S9(2) COMP.", "   05 P PIC S9(5) COMP-3.", "   05 T PIC X(2).")
    src, dst = both(GNU, IBM_Z, *lines)
    assert (src.record_length, dst.record_length) == (4 + 1 + 3 + 2, 4 + 2 + 3 + 2)
    record = b"AB12" + bytes([7]) + bytes([0x12, 0x34, 0x5C]) + b"zz"
    out = convert_record_between(record, src, dst, GNU, IBM_Z, "ASCII", "EBCDIC_CP037")
    assert out[0:4] == "AB12".encode("cp037")
    assert int.from_bytes(out[4:6], "big", signed=True) == 7          # moved and widened
    assert out[6:9] == bytes([0x12, 0x34, 0x5C])                       # packed: untouched
    assert out[9:11] == "zz".encode("cp037")


def test_a_corrupt_packed_field_is_still_rejected_by_the_shared_validation():
    src, dst = both(GNU, IBM_Z, "01 REC.", "   05 P PIC S9(3) COMP-3.", "   05 N PIC S9(2) COMP.")
    with pytest.raises(ValueError, match="packed field has a non-decimal digit"):
        convert_record_between(bytes([0x1A, 0x3C, 0x01]), src, dst, GNU, IBM_Z, "ASCII", "ASCII")


def test_layouts_that_do_not_describe_the_same_record_are_refused():
    src = layout(GNU, "01 REC.", "   05 N PIC S9(4) COMP.")
    other = layout(IBM_Z, "01 REC.", "   05 M PIC S9(4) COMP.")
    with pytest.raises(ValueError, match="do not describe the same fields"):
        convert_record_between(b"\x00\x01", src, other, GNU, IBM_Z, "ASCII", "ASCII")
    comp5 = layout(IBM_Z, "01 REC.", "   05 N PIC S9(4) COMP-5.")
    with pytest.raises(ValueError, match="do not describe the same fields"):
        convert_record_between(b"\x00\x01", src, comp5, GNU, IBM_Z, "ASCII", "ASCII")


def test_a_layout_derived_for_another_width_model_than_the_declared_platform_is_refused():
    wrong = layout(GNU, "01 REC.", "   05 N PIC S9(2) COMP.")           # 1 byte: the GnuCOBOL default model
    right = layout(IBM_Z, "01 REC.", "   05 N PIC S9(2) COMP.")
    with pytest.raises(ValueError, match="width model"):
        convert_record_between(b"\x01", wrong, right, IBM_Z, IBM_Z, "ASCII", "ASCII")   # source claims the IBM platform


def test_conversion_is_deterministic():
    src, dst = both(GNU_IBM, IBM_Z, "01 REC.", "   05 N PIC S9(4) COMP-5.")
    record = (-1234).to_bytes(2, "little", signed=True)
    assert convert_record_between(record, src, dst, GNU_IBM, IBM_Z, "ASCII", "ASCII") == \
        convert_record_between(record, src, dst, GNU_IBM, IBM_Z, "ASCII", "ASCII")

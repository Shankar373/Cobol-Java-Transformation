"""Explicit binary representations and record conversion between two of them (G-27).

A binary (COMP / COMP-5) field is not a portable byte string: its width follows the width model
(IBM 2/4/8 bytes, GnuCOBOL default 1/2/4/8) and its byte order follows the usage and the platform
(COMP is big-endian on both; COMP-5 is native order - big-endian on z/OS, little-endian on the x86
GnuCOBOL oracle).  ``convert_record_between`` therefore decodes each binary field to an integer,
checks it and re-encodes it for the target; DISPLAY text is translated between encodings; COMP-3 is
validated and copied (packed decimal does not depend on the platform).

Nothing is guessed: the source and target representations are named by the caller, the layouts must
have been derived for those representations' width models, and an unknown platform is refused.  A
value that does not fit is *rejected with a reason* - never truncated.  The IBM entry is documented
semantics only: no IBM runtime has produced or read data in this repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.vsam.convert import FieldKind, check_record, translate_display
from engine.vsam.layout import BinaryWidthModel, LayoutField, RecordLayout
from engine.vsam.model import Encoding


class ByteOrder(str, Enum):
    BIG = "big"
    LITTLE = "little"


@dataclass(frozen=True)
class BinaryRepresentation:
    name: str
    comp_byte_order: ByteOrder
    comp5_byte_order: ByteOrder
    width_model: BinaryWidthModel
    evidence: str

    def to_dict(self) -> dict:
        return {"name": self.name, "comp_byte_order": self.comp_byte_order.value,
                "comp5_byte_order": self.comp5_byte_order.value, "width_model": self.width_model.value,
                "evidence": self.evidence}


PLATFORMS: dict[str, BinaryRepresentation] = {
    "IBM_ZOS": BinaryRepresentation(
        "IBM_ZOS", ByteOrder.BIG, ByteOrder.BIG, BinaryWidthModel.IBM_2_4_8,
        "DOCUMENTED semantics (z/Architecture is big-endian; IBM COMP widths 2/4/8); no IBM runtime evidence"),
    "GNUCOBOL_X86_DEFAULT": BinaryRepresentation(
        "GNUCOBOL_X86_DEFAULT", ByteOrder.BIG, ByteOrder.LITTLE, BinaryWidthModel.GNUCOBOL_1_2_4_8,
        "GNUCOBOL_DIFFERENTIAL: records written by GnuCOBOL 3.1.2 -std=default on x86-64"),
    "GNUCOBOL_X86_IBM_DIALECT": BinaryRepresentation(
        "GNUCOBOL_X86_IBM_DIALECT", ByteOrder.BIG, ByteOrder.LITTLE, BinaryWidthModel.IBM_2_4_8,
        "GNUCOBOL_DIFFERENTIAL: records written by GnuCOBOL 3.1.2 -std=ibm on x86-64; not IBM Enterprise COBOL"),
    "GNUCOBOL_S390X_DEFAULT": BinaryRepresentation(
        "GNUCOBOL_S390X_DEFAULT", ByteOrder.BIG, ByteOrder.BIG, BinaryWidthModel.GNUCOBOL_1_2_4_8,
        "GNUCOBOL_DIFFERENTIAL: records written by GnuCOBOL 3.1.2 -std=default on linux/s390x (big-endian CPU, "
        "QEMU); Linux on s390x, not z/OS"),
    "GNUCOBOL_S390X_IBM_DIALECT": BinaryRepresentation(
        "GNUCOBOL_S390X_IBM_DIALECT", ByteOrder.BIG, ByteOrder.BIG, BinaryWidthModel.IBM_2_4_8,
        "GNUCOBOL_DIFFERENTIAL: records written by GnuCOBOL 3.1.2 -std=ibm on linux/s390x (big-endian CPU, QEMU); "
        "Linux on s390x, not z/OS or IBM Enterprise COBOL"),
}


def platform(name: str) -> BinaryRepresentation:
    try:
        return PLATFORMS[name]
    except KeyError:
        raise ValueError(f"unknown platform {name!r}; supported: {', '.join(sorted(PLATFORMS))}") from None


def _order(field: LayoutField, representation: BinaryRepresentation) -> str:
    return (representation.comp5_byte_order if field.usage == "COMP-5" else representation.comp_byte_order).value


def _decode(chunk: bytes, field: LayoutField, representation: BinaryRepresentation) -> int:
    return int.from_bytes(chunk, _order(field, representation), signed=field.signed)  # type: ignore[arg-type]


def check_binary_fields(record: bytes, layout: RecordLayout, representation: BinaryRepresentation) -> str | None:
    """A reason a binary field of ``record`` is invalid for its picture, or ``None``.

    A COMP field is bound by its picture (binary-truncate semantics): its magnitude may not exceed
    ``digits`` decimal digits.  COMP-5 is bound only by its width.
    """
    for field in layout.fields:
        if field.kind is not FieldKind.BINARY:
            continue
        chunk = record[field.offset:field.offset + field.length]
        if len(chunk) != field.length:
            return f"field {field.path}: record is too short"
        value = _decode(chunk, field, representation)
        if field.usage == "COMP" and abs(value) > 10 ** field.digits - 1:
            return (f"field {field.path}: COMP value {value} exceeds the {field.digits} digits of its picture")
    return None


def _same_fields(source: RecordLayout, target: RecordLayout) -> bool:
    shape = lambda layout: [(f.path, f.kind, f.usage, f.signed, f.digits, f.decimals) for f in layout.fields]  # noqa: E731
    return shape(source) == shape(target)


def check_layout_pair(source_layout: RecordLayout, target_layout: RecordLayout,
                      source_platform: BinaryRepresentation, target_platform: BinaryRepresentation) -> list[str]:
    """Every reason these two layouts cannot be converted into one another (empty when they can)."""
    problems: list[str] = []
    for label, layout, representation in (("source", source_layout, source_platform),
                                          ("target", target_layout, target_platform)):
        if not layout.supported:
            problems.append(f"the {label} layout is not supported: {[d.code for d in layout.diagnostics]}")
        elif layout.binary_width_model != representation.width_model.value:
            problems.append(f"the {label} layout was derived for the {layout.binary_width_model} width model but "
                            f"platform {representation.name} uses {representation.width_model.value}")
    if not problems and not _same_fields(source_layout, target_layout):
        problems.append("the source and target layouts do not describe the same fields")
    return problems


def convert_record_between(record: bytes, source_layout: RecordLayout, target_layout: RecordLayout,
                           source_platform: BinaryRepresentation, target_platform: BinaryRepresentation,
                           source_encoding: Encoding | str, destination_encoding: Encoding | str) -> bytes:
    """Convert one record from the source representation to the target one.

    Raises ``ValueError`` naming the field when the record cannot be converted exactly.
    """
    source_encoding, destination_encoding = Encoding(source_encoding), Encoding(destination_encoding)
    problems = check_layout_pair(source_layout, target_layout, source_platform, target_platform)
    if problems:
        raise ValueError("; ".join(problems))
    if len(record) != source_layout.record_length:
        raise ValueError(f"record length {len(record)} bytes, layout needs {source_layout.record_length}")

    reason = check_record(record, source_layout.field_specs())  # packed-decimal validity
    if reason:
        raise ValueError(reason)
    reason = check_binary_fields(record, source_layout, source_platform)
    if reason:
        raise ValueError(reason)

    out = bytearray(target_layout.record_length)
    for src, dst in zip(source_layout.fields, target_layout.fields):
        chunk = record[src.offset:src.offset + src.length]
        if src.kind is FieldKind.DISPLAY and source_encoding is not destination_encoding:
            chunk = translate_display(chunk, src.path, src.sign_overpunch, source_encoding, destination_encoding)
        elif src.kind is FieldKind.BINARY:
            value = _decode(chunk, src, source_platform)
            try:
                chunk = value.to_bytes(dst.length, _order(dst, target_platform), signed=dst.signed)  # type: ignore[arg-type]
            except OverflowError:
                raise ValueError(f"field {src.path}: value {value} does not fit the {dst.length}-byte target "
                                 f"field ({'signed' if dst.signed else 'unsigned'})") from None
        out[dst.offset:dst.offset + dst.length] = chunk
    return bytes(out)

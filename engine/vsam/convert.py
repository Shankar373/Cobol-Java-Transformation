"""Field-aware record conversion for a migration between encodings.

A record is converted field by field from its COBOL layout: DISPLAY text is
translated between ASCII and EBCDIC (cp037), PACKED (COMP-3) and BINARY (COMP)
fields are copied byte for byte, because translating them would corrupt the
number.  The layout must cover the whole record (use an explicit ``FILLER``
DISPLAY field for padding) - uncovered bytes are never guessed.

A record that cannot be converted is *rejected with a reason*, never dropped or
repaired: a DISPLAY byte with no counterpart in the other encoding, or a packed
field with a non-decimal digit or an invalid sign nibble.  ``validate_record``
exposes the same checks to ``reconcile_migration`` so a rejection can be
confirmed independently.

``convert_dataset`` can resume an interrupted run: given the output written so
far and the number of records it claims to hold, it re-converts those records and
refuses to continue if they differ (a torn or altered partial output).

Pure and deterministic; fixed-length datasets only.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from engine.vsam.model import DatasetDefinition, Encoding, RecordFormat
from engine.vsam.reconcile import RejectedRecord, split_records

_PACKED_SIGNS = frozenset({0xA, 0xB, 0xC, 0xD, 0xE, 0xF})


class FieldKind(str, Enum):
    DISPLAY = "DISPLAY"  # character data, translated
    PACKED = "PACKED"  # COMP-3, copied; validated
    BINARY = "BINARY"  # COMP / COMP-5, copied


@dataclass(frozen=True)
class FieldSpec:
    name: str
    offset: int
    length: int
    kind: FieldKind = FieldKind.DISPLAY
    sign: str = ""  # "TRAILING" / "LEADING": a sign overpunched in a zoned DISPLAY digit


def validate_layout(fields: tuple[FieldSpec, ...], record_length: int) -> tuple[str, ...]:
    """Reasons the layout cannot convert a ``record_length``-byte record."""
    problems: list[str] = []
    covered = 0
    for spec in sorted(fields, key=lambda f: f.offset):
        if spec.length <= 0 or spec.offset < 0:
            problems.append(f"field {spec.name}: non-positive length or negative offset")
        elif spec.offset < covered:
            problems.append(f"field {spec.name} overlaps the field before it")
        elif spec.offset > covered:
            problems.append(f"bytes {covered}..{spec.offset - 1} are not covered by any field "
                            "(declare a FILLER DISPLAY field)")
        covered = max(covered, spec.offset + spec.length)
    if covered < record_length:
        problems.append(f"bytes {covered}..{record_length - 1} are not covered by any field")
    elif covered > record_length:
        problems.append(f"fields extend to byte {covered}, past the {record_length}-byte record")
    return tuple(problems)


def check_record(record: bytes, fields: tuple[FieldSpec, ...]) -> str | None:
    """A reason this record cannot be converted, or ``None`` when it can."""
    for spec in fields:
        chunk = record[spec.offset:spec.offset + spec.length]
        if len(chunk) != spec.length:
            return f"field {spec.name}: record is too short"
        if spec.kind is FieldKind.PACKED:
            nibbles = [n for byte in chunk for n in (byte >> 4, byte & 0xF)]
            if any(n > 9 for n in nibbles[:-1]):
                return f"field {spec.name}: packed field has a non-decimal digit"
            if nibbles[-1] not in _PACKED_SIGNS:
                return f"field {spec.name}: packed field has an invalid sign nibble"
    return None


def translate_display(chunk: bytes, name: str, sign: str, source: Encoding, destination: Encoding) -> bytes:
    """Translate one DISPLAY field between ASCII and EBCDIC cp037; a field with an overpunched sign is converted as a number.

    GnuCOBOL's ASCII form: positive = plain digits, negative = the sign digit shifted to ``p``..``y`` (0x70 + digit).
    EBCDIC: digits are zone F, the sign byte is zone C (or F) for positive and D for negative.  Anything else is rejected.
    """
    if not sign:
        try:
            return (chunk.decode("cp037").encode("ascii") if source is Encoding.EBCDIC_CP037
                    else chunk.decode("ascii").encode("cp037"))
        except (UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise ValueError(f"field {name}: byte has no counterpart in {destination.value}: {exc.reason}") from exc
    sign_index = 0 if sign == "LEADING" else len(chunk) - 1
    digits: list[int] = []
    negative = False
    for index, byte in enumerate(chunk):
        if source is Encoding.EBCDIC_CP037:
            zone, digit = byte >> 4, byte & 0xF
            valid = digit <= 9 and (zone == 0xF or (index == sign_index and zone in (0xC, 0xD)))
            if index == sign_index:
                negative = zone == 0xD
        else:
            digit = byte - 0x30
            if index == sign_index and 0x70 <= byte <= 0x79:
                digit, negative = byte - 0x70, True
            valid = 0 <= digit <= 9
        if not valid:
            raise ValueError(f"field {name}: byte 0x{byte:02X} is not a valid {sign.lower()} signed zoned digit in "
                             f"{source.value}")
        digits.append(digit)
    out = bytearray()
    for index, digit in enumerate(digits):
        marked = index == sign_index
        if destination is Encoding.ASCII:
            out.append(0x70 + digit if marked and negative else 0x30 + digit)
        else:
            out.append(((0xD0 if negative else 0xC0) if marked else 0xF0) + digit)
    return bytes(out)


def convert_record(record: bytes, fields: tuple[FieldSpec, ...], source: Encoding, destination: Encoding) -> bytes:
    """Convert one record; raises ``ValueError`` naming the field that cannot be converted."""
    reason = check_record(record, fields)
    if reason:
        raise ValueError(reason)
    out = bytearray(len(record))
    for spec in fields:
        chunk = record[spec.offset:spec.offset + spec.length]
        if spec.kind is FieldKind.DISPLAY and source is not destination:
            chunk = translate_display(chunk, spec.name, spec.sign, source, destination)
        out[spec.offset:spec.offset + spec.length] = chunk
    return bytes(out)


@dataclass(frozen=True)
class ConversionResult:
    output: bytes
    rejected: tuple[RejectedRecord, ...]
    records_read: int
    resumed_from: int
    checkpoint_sha256: str  # SHA-256 of the output, to verify before a later resume


def convert_dataset(source: DatasetDefinition, data: bytes, fields: tuple[FieldSpec, ...],
                    destination_encoding: Encoding, *, partial_output: bytes = b"",
                    resume_after: int = 0, stop_after: int | None = None,
                    convert: Callable[[bytes], bytes] | None = None) -> ConversionResult:
    """Convert ``data``; resume after ``resume_after`` source records already written.

    ``partial_output`` must hold exactly the converted form of the first
    ``resume_after`` records (rejected ones are absent); otherwise a ``ValueError`` is
    raised and nothing is continued.  ``stop_after`` ends the run early (an
    interruption, in tests and for batching) after that many source records.

    ``convert`` replaces the field-wise conversion with a caller-supplied record converter (used for
    conversions that change the record length, such as a binary width change); it must raise
    ``ValueError`` with a reason for a record it cannot convert, and that record is rejected.
    """
    if source.record_format is not RecordFormat.FIXED:
        raise ValueError("convert_dataset supports fixed-length datasets only")
    if convert is None:
        problems = list(source.validate()) + list(validate_layout(fields, source.record_length))
        check = lambda record: check_record(record, fields)  # noqa: E731
        convert = lambda record: convert_record(record, fields, source.encoding, destination_encoding)  # noqa: E731
    else:
        problems = list(source.validate())

        def check(record: bytes) -> str | None:
            try:
                convert(record)  # type: ignore[misc]
            except ValueError as exc:
                return str(exc)
            return None
    if problems:
        raise ValueError("; ".join(problems))
    records, structural = split_records(data, source)
    if structural:
        raise ValueError("; ".join(structural))
    if resume_after < 0 or resume_after > len(records):
        raise ValueError(f"cannot resume after record {resume_after} of {len(records)}")

    expected_prefix = bytearray()
    rejected: list[RejectedRecord] = []
    for number, record in enumerate(records[:resume_after], start=1):
        reason = check(record)
        if reason:
            rejected.append(RejectedRecord(number, reason))
        else:
            expected_prefix += convert(record)
    if resume_after and bytes(expected_prefix) != partial_output:
        raise ValueError("the partial output does not match the first "
                         f"{resume_after} source record(s); refusing to continue a torn or altered output")
    if not resume_after and partial_output:
        raise ValueError("partial output supplied without a resume point")

    output = bytearray(partial_output)
    end = len(records) if stop_after is None else min(stop_after, len(records))
    for number in range(resume_after + 1, end + 1):
        record = records[number - 1]
        reason = check(record)
        if reason:
            rejected.append(RejectedRecord(number, reason))
            continue
        output += convert(record)
    return ConversionResult(bytes(output), tuple(rejected), max(end, resume_after), resume_after,
                            hashlib.sha256(bytes(output)).hexdigest())


def sort_for_ksds(output: bytes, record_length: int, key_offset: int, key_length: int) -> bytes:
    """Stable sort of fixed-length records by the raw key bytes of the destination.

    A KSDS is loaded in ascending key order of its own encoding, which is not the
    order of the source file (ASCII and EBCDIC collate differently), so the converted
    records are sorted explicitly after conversion.  Records are compared by their
    stored key bytes, which are already in the destination encoding.
    """
    if record_length <= 0 or len(output) % record_length:
        raise ValueError("output is not a whole number of fixed-length records")
    records = [output[i:i + record_length] for i in range(0, len(output), record_length)]
    records.sort(key=lambda r: r[key_offset:key_offset + key_length])
    return b"".join(records)

"""Validate a VSAM export manifest against the COBOL SELECT / FD it will feed.

The manifest is client-supplied metadata, so it is never trusted on its own:
organization, record length and primary key must agree with the program that
reads the file. Layouts that cannot be computed without guessing (REDEFINES,
OCCURS DEPENDING ON, non-DISPLAY usage, several 01 records) are refused.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.transformation.cobol_parser import CobolParseError, CobolParser
from engine.transformation.ir import DataItem, FileDefinition, FileOrganization
from enterprise.contracts import VsamExportManifest
from enterprise.vsam.errors import VsamRefusal

_EXPECTED_ORGANIZATION = {
    "KSDS": FileOrganization.INDEXED,
    "RRDS": FileOrganization.RELATIVE,
    "ESDS": FileOrganization.SEQUENTIAL,
}


@dataclass(frozen=True)
class CobolFileLayout:
    file_name: str
    record_length: int
    key_offset: int | None
    key_length: int | None


def _unverifiable(item: DataItem, reason: str) -> VsamRefusal:
    return VsamRefusal("LAYOUT_UNVERIFIABLE", f"{item.name}: {reason}")


def _size(item: DataItem) -> int:
    if item.redefines:
        raise _unverifiable(item, "REDEFINES")
    if item.occurs_depending_on:
        raise _unverifiable(item, "OCCURS DEPENDING ON")
    if item.usage:
        raise _unverifiable(item, f"USAGE {item.usage} has no certified byte layout")
    count = item.occurs or 1
    children = [c for c in item.children if c.level != 88]
    if children:
        return count * sum(_size(c) for c in children)
    if item.pic_length <= 0:
        raise _unverifiable(item, "no PIC size")
    return count * item.pic_length


def _offset_of(root: DataItem, field: str) -> tuple[int, int]:
    """Return ``(offset, length)`` of ``field`` inside ``root``."""
    position = 0

    def walk(item: DataItem, in_table: bool) -> tuple[int, int] | None:
        nonlocal position
        in_table = in_table or bool(item.occurs)
        if item.name.upper() == field.upper():
            if in_table:
                raise _unverifiable(item, "key inside an OCCURS table")
            return position, _size(item)
        children = [c for c in item.children if c.level != 88]
        if children:
            for child in children:
                found = walk(child, in_table)
                if found:
                    return found
            return None
        position += _size(item)
        return None

    found = walk(root, False)
    if found is None:
        raise VsamRefusal("KEY_FIELD_NOT_FOUND", f"{field} is not in the FD record")
    return found


def _select(fd_list: tuple[FileDefinition, ...], runtime_path: str, file_name: str | None) -> FileDefinition:
    for fd in fd_list:
        if file_name and fd.name.upper() == file_name.upper():
            return fd
        if not file_name and fd.container_path == runtime_path:
            return fd
    raise VsamRefusal("FD_NOT_FOUND", f"no SELECT matches {file_name or runtime_path!r}")


def check_manifest_against_cobol(
    source: str,
    manifest: VsamExportManifest,
    runtime_path: str,
    file_name: str | None = None,
) -> CobolFileLayout:
    try:
        program = CobolParser().parse(source)
    except CobolParseError as exc:
        raise VsamRefusal("COBOL_PARSE_ERROR", str(exc)[:200]) from None
    fd = _select(program.file_definitions, runtime_path, file_name)

    expected = _EXPECTED_ORGANIZATION[manifest.organization]
    if fd.organization is not expected or (
        manifest.organization == "ESDS" and not fd.record_sequential
    ):
        raise VsamRefusal(
            "ORGANIZATION_MISMATCH",
            f"manifest says {manifest.organization}, SELECT {fd.name} is {fd.organization.value}",
        )
    if fd.alternate_keys:
        raise VsamRefusal("ALTERNATE_KEY_UNSUPPORTED", f"SELECT {fd.name} declares ALTERNATE RECORD KEY")
    if len(fd.record_groups) != 1:
        raise VsamRefusal("LAYOUT_UNVERIFIABLE", f"FD {fd.name} has {len(fd.record_groups)} record layouts")

    root = fd.record_groups[0]
    record_length = _size(root)
    if fd.record_contains is not None and fd.record_contains != record_length:
        raise VsamRefusal("RECORD_LENGTH_MISMATCH", "RECORD CONTAINS disagrees with the FD items")
    layout = manifest.layout
    if layout.record_format == "FIXED" and layout.max_record_length != record_length:
        raise VsamRefusal(
            "RECORD_LENGTH_MISMATCH",
            f"manifest record length {layout.max_record_length}, FD {fd.name} is {record_length}",
        )
    if layout.record_format == "VARIABLE_RDW" and layout.max_record_length > record_length:
        raise VsamRefusal(
            "RECORD_LENGTH_MISMATCH",
            f"manifest maximum {layout.max_record_length} exceeds FD {fd.name} record of {record_length}",
        )

    key_offset = key_length = None
    if manifest.organization == "KSDS":
        if fd.record_key is None:
            raise VsamRefusal("KEY_FIELD_NOT_FOUND", f"SELECT {fd.name} has no RECORD KEY")
        key_offset, key_length = _offset_of(root, fd.record_key.field_name)
        if (key_offset, key_length) != (layout.key_offset, layout.key_length):
            raise VsamRefusal(
                "KEY_MISMATCH",
                f"manifest key {layout.key_offset}+{layout.key_length}, "
                f"RECORD KEY {fd.record_key.field_name} is {key_offset}+{key_length}",
            )
    return CobolFileLayout(fd.name, record_length, key_offset, key_length)

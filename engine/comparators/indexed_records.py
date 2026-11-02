"""Logical records of INDEXED and RELATIVE files, read from each side's image.

GnuCOBOL 3.1.2 (the oracle image's ``cobc --info``: "indexed file handler:
BDB") stores an INDEXED file as a Berkeley DB B-tree; the generated Java
runtime stores its own emulation (``<file>.idx``).  The two images can never
be byte-identical, but both hold the same logical content — the records a
COBOL program reading the file sees, in primary-key order — and that is
what is compared.

The oracle side is read here directly from the Berkeley DB pages, with no
use of the COBOL parser or the generated runtime, so the reference content
does not depend on the system under test.  Only the layout this reader
certifies is accepted; anything else (encryption, overflow or duplicate
items, an unknown page type, a malformed page) raises
:class:`UnreadableImage` and the caller keeps the image INCONCLUSIVE.

Berkeley DB B-tree layout used (little-endian, database format 9):

* page 0, metadata: magic ``0x00053162`` at 12, version at 16, page size
  at 20, encryption algorithm at 24, page type 9 at 25, root page at 88;
* every other page: 26-byte header (``pgno`` at 8, ``entries`` at 20,
  ``level`` at 24, type at 25) followed by ``entries`` 2-byte item offsets;
* internal page (type 3) items: length (2), type (1), pad (1), child page
  (4), record count (4), key bytes;
* leaf page (type 5) items alternate key, data: length (2), type (1),
  bytes.  Item type 1 is plain data; bit 0x80 marks a deleted item.

RELATIVE files (GnuCOBOL 3.1.2 on x86-64, measured): one slot per RRN, RRN
``n`` at offset ``(n - 1) * (8 + record length)``; a slot is an 8-byte
little-endian record size followed by the whole record area.  Size 0 marks
an empty slot (never written, or DELETEd — the old bytes stay), a live
fixed-length record has size = record length.  The image does not state
the record length, so it is inferred: exactly one length must make every
slot's size 0 or that length, with at least one live slot; anything else
is refused.  An empty image is a file with no records.
"""

from __future__ import annotations

import struct

_BTREE_MAGIC = 0x00053162
_BTREE_VERSION = 9
_META_TYPE = 9
_INTERNAL = 3
_LEAF = 5
_KEYDATA = 1
_DELETED = 0x80
_HEADER = 26


class UnreadableImage(ValueError):
    """The image is not a layout this reader certifies."""


def _u16(buf: bytes, at: int) -> int:
    return struct.unpack_from("<H", buf, at)[0]


def _u32(buf: bytes, at: int) -> int:
    return struct.unpack_from("<I", buf, at)[0]


def bdb_btree_records(image: bytes) -> list[bytes]:
    """Data items of a GnuCOBOL (Berkeley DB B-tree) INDEXED file, in key
    order — each one a full COBOL record."""
    if len(image) < 512 or _u32(image, 12) != _BTREE_MAGIC:
        raise UnreadableImage("not a little-endian Berkeley DB B-tree")
    if _u32(image, 16) != _BTREE_VERSION:
        raise UnreadableImage(f"B-tree version {_u32(image, 16)} not certified")
    page_size = _u32(image, 20)
    if page_size < 512 or page_size & (page_size - 1) or len(image) % page_size:
        raise UnreadableImage(f"bad page size {page_size}")
    if image[24] != 0:
        raise UnreadableImage("encrypted database")
    if image[25] != _META_TYPE:
        raise UnreadableImage(f"page 0 has type {image[25]}, not B-tree metadata")
    pages = len(image) // page_size

    def page(number: int) -> bytes:
        if not 0 < number < pages:
            raise UnreadableImage(f"page {number} outside the file")
        data = image[number * page_size:(number + 1) * page_size]
        if _u32(data, 8) != number:
            raise UnreadableImage(f"page {number} header names page {_u32(data, 8)}")
        return data

    def items(data: bytes) -> list[int]:
        entries = _u16(data, 20)
        offsets = [_u16(data, _HEADER + 2 * i) for i in range(entries)]
        if any(not _HEADER + 2 * entries <= o < page_size - 3 for o in offsets):
            raise UnreadableImage("item offset outside the page")
        return offsets

    records: list[bytes] = []
    seen: set[int] = set()

    def walk(number: int) -> None:
        if number in seen:
            raise UnreadableImage(f"page {number} reached twice")
        seen.add(number)
        data = page(number)
        kind = data[25]
        if kind == _INTERNAL:
            for offset in items(data):
                walk(_u32(data, offset + 4))
            return
        if kind != _LEAF:
            raise UnreadableImage(f"page {number} has type {kind}")
        offsets = items(data)
        if len(offsets) % 2:
            raise UnreadableImage(f"leaf page {number} has an unpaired key")
        for key_at, data_at in zip(offsets[::2], offsets[1::2]):
            key_type, data_type = data[key_at + 2], data[data_at + 2]
            if (key_type | data_type) & _DELETED:
                continue
            if key_type != _KEYDATA or data_type != _KEYDATA:
                raise UnreadableImage(
                    f"item types {key_type}/{data_type} (overflow or duplicates) not certified"
                )
            length = _u16(data, data_at)
            if data_at + 3 + length > page_size:
                raise UnreadableImage("data item runs past the page")
            records.append(bytes(data[data_at + 3:data_at + 3 + length]))

    walk(_u32(image, 88))
    return records


def emulated_index_records(image: bytes) -> list[bytes]:
    """Records of the generated Java runtime's INDEXED emulation
    (``CobolFileIo.persistIndex``): a ``K<key length>`` line, then one
    ``key \\x01 data`` line per record in key order; the record is
    ``key + data``."""
    lines = image.decode("utf-8").split("\n")
    if not lines or not lines[0].startswith("K") or not lines[0][1:].isdigit():
        raise UnreadableImage("not a generated INDEXED emulation file")
    key_length = int(lines[0][1:])
    if lines[-1] != "":
        raise UnreadableImage("emulation file does not end with a newline")
    records: list[bytes] = []
    for line in lines[1:-1]:
        key, sep, rest = line.partition("\x01")
        if not sep or len(key) != key_length:
            raise UnreadableImage("malformed emulation record line")
        records.append((key + rest).encode("utf-8"))
    return records


def canonical_records(records: list[bytes]) -> bytes:
    """One line per record, in file order: hex bytes, a tab, and the bytes
    with non-printable characters shown as ``.`` (for readable differences).
    Byte-exact and unambiguous: equal text means equal records."""
    lines = []
    for record in records:
        shown = "".join(chr(b) if 32 <= b < 127 else "." for b in record)
        lines.append(f"{record.hex()}\t{shown}\n")
    return "".join(lines).encode("ascii")


def gnucobol_relative_records(image: bytes) -> list[tuple[int, bytes]]:
    """(RRN, record) of every live slot of a GnuCOBOL RELATIVE file."""
    if not image:
        return []
    layouts = []
    for length in range(1, len(image) - 7):
        slot = 8 + length
        if len(image) % slot:
            continue
        sizes = [struct.unpack_from("<Q", image, at)[0] for at in range(0, len(image), slot)]
        if all(size in (0, length) for size in sizes) and length in sizes:
            layouts.append((slot, sizes))
    if len(layouts) != 1:
        raise UnreadableImage(
            "no RELATIVE slot layout fits the image" if not layouts
            else "several RELATIVE slot layouts fit the image"
        )
    slot, sizes = layouts[0]
    return [
        (index + 1, bytes(image[index * slot + 8:index * slot + 8 + size]))
        for index, size in enumerate(sizes)
        if size
    ]


def emulated_relative_records(image: bytes) -> list[tuple[int, bytes]]:
    """(RRN, record) of the generated Java runtime's RELATIVE emulation
    (``CobolFileIo.persistRelative``): an ``R`` line, then one
    ``rrn \\x01 record`` line per record in RRN order."""
    lines = image.decode("utf-8").split("\n")
    if lines[0] != "R" or lines[-1] != "":
        raise UnreadableImage("not a generated RELATIVE emulation file")
    records: list[tuple[int, bytes]] = []
    for line in lines[1:-1]:
        rrn, sep, record = line.partition("\x01")
        if not sep or not rrn.isdigit() or int(rrn) < 1:
            raise UnreadableImage("malformed emulation record line")
        if records and int(rrn) <= records[-1][0]:
            raise UnreadableImage("emulation records out of RRN order")
        records.append((int(rrn), record.encode("utf-8")))
    return records


def canonical_relative_records(records: list[tuple[int, bytes]]) -> bytes:
    """``canonical_records`` with each line prefixed by its RRN and a tab:
    a record in the wrong slot differs as much as a different record."""
    lines = canonical_records([record for _, record in records]).decode("ascii").splitlines(True)
    return "".join(f"{rrn}\t{line}" for (rrn, _), line in zip(records, lines)).encode("ascii")

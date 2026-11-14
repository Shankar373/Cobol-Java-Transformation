"""Incremental record framing over a binary stream.

Memory is O(chunk size + maximum record size): records are cut from a bounded
buffer and yielded one at a time.

Logical export framing (docs/vsam/VSAM_EXPORT_FORMAT.md):
  FIXED         record bytes back to back, each ``max_record_length`` long
  VARIABLE_RDW  4-byte RDW (big-endian length including the RDW, 2 zero bytes)
                followed by the record
  RRDS          each record is preceded by a 4-byte big-endian relative record
                number that is not part of the record length
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO, NamedTuple

from enterprise.contracts import VsamRecordLayout
from enterprise.vsam.errors import VsamRefusal

RDW_BYTES = 4
RRN_BYTES = 4


class Frame(NamedTuple):
    offset: int  # offset of the first framing byte of this record
    end: int  # offset just past the record
    rrn: int  # relative record number, 0 when not RRDS
    data: bytes
    raw: bytes  # framing bytes plus data, for exact hashing


class _Buffered:
    """Exact-length reads over a stream with a bounded refill chunk."""

    def __init__(self, stream: BinaryIO, chunk: int) -> None:
        self._stream = stream
        self._chunk = max(chunk, 1)
        self._buf = bytearray()
        self._pos = 0

    def read(self, n: int) -> bytes:
        while len(self._buf) - self._pos < n:
            more = self._stream.read(self._chunk)
            if not more:
                break
            if self._pos:
                del self._buf[: self._pos]
                self._pos = 0
            self._buf += more
        out = bytes(self._buf[self._pos : self._pos + n])
        self._pos += len(out)
        return out


def iter_frames(
    stream: BinaryIO,
    layout: VsamRecordLayout,
    *,
    relative: bool = False,
    chunk: int = 1 << 20,
    start_offset: int = 0,
) -> Iterator[Frame]:
    """Yield framed records; raise VsamRefusal on any framing violation."""
    reader = _Buffered(stream, chunk)
    offset = start_offset
    while True:
        begin = offset
        rrn = 0
        framing = b""
        if relative:
            head = reader.read(RRN_BYTES)
            if not head:
                return
            if len(head) < RRN_BYTES:
                raise VsamRefusal("TRUNCATED_RECORD", f"partial RRN at offset {begin}")
            framing = head
            rrn = int.from_bytes(head, "big")
            if rrn < 1:
                raise VsamRefusal("INVALID_RRN", f"RRN {rrn} at offset {begin}")
            offset += RRN_BYTES
        if layout.record_format == "FIXED":
            length = layout.max_record_length
            data = reader.read(length)
            if not data and not relative and offset == begin:
                return
            if len(data) < length:
                raise VsamRefusal(
                    "TRUNCATED_RECORD",
                    f"record at offset {begin} has {len(data)} of {length} bytes",
                )
        else:
            rdw = reader.read(RDW_BYTES)
            if not rdw:
                if relative:
                    raise VsamRefusal("TRUNCATED_RECORD", f"missing RDW at offset {offset}")
                return
            if len(rdw) < RDW_BYTES:
                raise VsamRefusal("TRUNCATED_RECORD", f"partial RDW at offset {offset}")
            total = int.from_bytes(rdw[:2], "big")
            if rdw[2:] != b"\x00\x00":
                raise VsamRefusal("INVALID_RDW", f"reserved RDW bytes set at offset {offset}")
            length = total - RDW_BYTES
            if length < layout.min_record_length or length > layout.max_record_length:
                raise VsamRefusal(
                    "RECORD_LENGTH_OUT_OF_RANGE",
                    f"record length {length} at offset {offset} outside "
                    f"{layout.min_record_length}..{layout.max_record_length}",
                )
            framing += rdw
            offset += RDW_BYTES
            data = reader.read(length)
            if len(data) < length:
                raise VsamRefusal(
                    "TRUNCATED_RECORD",
                    f"record at offset {begin} has {len(data)} of {length} bytes",
                )
        offset += len(data)
        yield Frame(begin, offset, rrn, data, framing + data)

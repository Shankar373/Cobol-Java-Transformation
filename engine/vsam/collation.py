"""Key collation for VSAM-style datasets: EBCDIC and ASCII order differ.

A KSDS returns records in ascending key order, and "ascending" means the byte
order of the data as stored.  On z/OS character keys are EBCDIC (code page 037
here), where lower case sorts before upper case and both before digits; in
ASCII digits sort first, then upper case, then lower case.  A migration that
moves a KSDS between encodings therefore changes the record order unless the
keys are re-sorted - reconciliation checks the destination against the order
its own encoding implies.

Deterministic and table driven (Python's ``cp037`` codec); no locale.
"""
from __future__ import annotations

from engine.vsam.model import Encoding, KeyDefinition, KeyKind


def to_stored_bytes(text: str, encoding: Encoding) -> bytes:
    """Bytes of ``text`` as they would be stored in ``encoding``."""
    return text.encode("ascii") if encoding is Encoding.ASCII else text.encode("cp037")


def key_bytes(record: bytes, key: KeyDefinition) -> bytes:
    """The key field of ``record`` exactly as stored (no translation)."""
    return record[key.offset:key.offset + key.length]


def collation_key(stored_key: bytes, key: KeyDefinition, stored_in: Encoding, order_by: Encoding) -> bytes:
    """Sort key giving ``order_by`` collation for a key stored in ``stored_in``.

    BINARY keys (packed, binary) are never translated.  A CHARACTER key stored
    in another encoding is translated through cp037 <-> ASCII before ordering;
    a byte with no counterpart is an error, never a silent substitution.
    """
    if key.kind is KeyKind.BINARY or stored_in is order_by:
        return stored_key
    if stored_in is Encoding.EBCDIC_CP037 and order_by is Encoding.ASCII:
        return stored_key.decode("cp037").encode("ascii")
    return stored_key.decode("ascii").encode("cp037")


def is_ascending(keys: list[bytes]) -> bool:
    """True when ``keys`` are in non-decreasing order (duplicates allowed)."""
    return all(a <= b for a, b in zip(keys, keys[1:]))

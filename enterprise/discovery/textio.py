"""Decoding of customer source bytes for analysis (never modifies the stored bytes).

Besides the BOM/UTF-8/cp1252 ladder of :func:`hashing.detect_encoding`, mainframe exports are often EBCDIC (cp037),
sometimes as fixed 80-byte records with no line breaks.  EBCDIC is accepted only when decoding it produces text that
looks like COBOL/JCL source, and is always reported with ``medium`` confidence and an explicit encoding name.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hashing import detect_encoding

__all__ = ["Decoded", "decode_source"]

RECORD_LENGTH = 80
_EBCDIC_MARKERS = ("DIVISION", "PROGRAM-ID", "//", "PIC ", "DFHMSD", "EXEC ", "COPY ", "CREATE TABLE")


@dataclass(frozen=True)
class Decoded:
    text: str
    encoding: str
    confidence: str
    binary: bool = False
    note: str = ""


def _looks_like_source(text: str) -> bool:
    upper = text.upper()
    return sum(marker in upper for marker in _EBCDIC_MARKERS) >= 1 and text.count("\x00") == 0 \
        and sum(ch.isprintable() or ch in "\r\n\t" for ch in text) >= 0.97 * max(len(text), 1)


def _ebcdic(data: bytes) -> Decoded | None:
    window = data[:8192]
    if not window or window.count(0x40) < len(window) * 0.1:
        return None
    try:
        text = data.decode("cp037")
    except UnicodeDecodeError:  # pragma: no cover - cp037 maps every byte
        return None
    if not _looks_like_source(text[:8192]):
        return None
    note = ""
    if "\n" not in text and "\x25" not in text and len(data) % RECORD_LENGTH == 0:
        text = "\n".join(text[i:i + RECORD_LENGTH].rstrip() for i in range(0, len(text), RECORD_LENGTH)) + "\n"
        note = "fixed 80-byte records without line breaks"
    else:
        text = text.replace("\x25", "\n").replace("\x15", "\n")
    return Decoded(text, "ebcdic-cp037", "medium", False, note)


def decode_source(data: bytes) -> Decoded:
    """Decode ``data`` for scanning; ``binary=True`` means it is not text and must not be scanned."""
    guess = detect_encoding(data)
    if guess.name == "binary":
        decoded = _ebcdic(data) if b"\x00" not in data[:8192] else None
        return decoded or Decoded("", "binary", "high", True)
    if guess.confidence == "low":
        ebcdic = _ebcdic(data)
        if ebcdic:
            return ebcdic
    payload = data[guess.bom_length:]
    try:
        text = payload.decode(guess.name)
    except (UnicodeDecodeError, LookupError):
        text = payload.decode("latin-1")
        return Decoded(text, "latin-1", "low")
    return Decoded(text, guess.name, guess.confidence)

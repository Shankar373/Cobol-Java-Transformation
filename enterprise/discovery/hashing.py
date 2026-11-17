"""SHA-256 hashing and encoding detection (plan §5.2).

Two rules govern this module:

* **Bytes are never modified.**  Encoding detection is read-only metadata; the
  file on disk is hashed exactly as ingested.  Re-encoding would destroy the
  evidence that P0 established for byte-faithful inputs.
* **Detection is reported with confidence.**  A BOM is proof, a strict UTF-8
  decode is strong evidence, a cp1252 fallback is a guess — and the manifest
  says which is which rather than presenting all three as equal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

__all__ = ["sha256_file", "sha256_bytes", "EncodingGuess", "detect_encoding"]

_CHUNK = 1024 * 1024

#: BOM → encoding name.  Ordered longest-first so UTF-32 beats UTF-16.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


@dataclass(frozen=True)
class EncodingGuess:
    """Result of :func:`detect_encoding`."""

    name: str
    #: ``high`` = proven by a BOM or pure ASCII; ``medium`` = strict decode or
    #: NUL-driven UTF-16 heuristic; ``low`` = byte-range fallback.
    confidence: str
    bom: bool
    bom_length: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "bom": self.bom,
            "bom_length": self.bom_length,
            "confidence": self.confidence,
            "encoding": self.name,
        }


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of an in-memory buffer."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Streaming SHA-256; never loads the whole file (bounded memory)."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_encoding(data: bytes) -> EncodingGuess:
    """Classify the encoding of *data* without altering it.

    Order of proof, strongest first:

    1. BOM ⇒ named exactly, ``high``.
    2. Pure ASCII ⇒ ``ascii``/``us-ascii``, ``high`` (a subset of every
       candidate, so the label is unambiguous).
    3. Strict UTF-8 decode ⇒ ``utf-8``, ``high`` (UTF-8 is self-synchronising,
       so a successful strict decode of non-ASCII bytes is conclusive).
    4. Interior NULs at even/odd offsets ⇒ UTF-16 heuristic, ``medium``.
    5. Otherwise cp1252 (superset of the legacy Windows code page that
       mainframe-era ASCII exports overwhelmingly use), ``low`` — explicitly a guess.
    """

    if not data:
        return EncodingGuess("ascii", "high", False, 0)

    for bom, name in _BOMS:
        if data.startswith(bom):
            return EncodingGuess(name, "high", True, len(bom))

    if b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            # Non-ASCII, invalid UTF-8: a legacy single-byte code page.
            try:
                data.decode("cp1252")
                return EncodingGuess("cp1252", "low", False, 0)
            except UnicodeDecodeError:
                # Bytes undefined in cp1252 (0x81, 0x8d, 0x8f, 0x90, 0x9d).
                return EncodingGuess("latin-1", "low", False, 0)
        if any(b >= 0x80 for b in data):
            return EncodingGuess("utf-8", "high", False, 0)
        return EncodingGuess("ascii", "high", False, 0)

    # Interior NULs: try UTF-16 on a bounded window.
    window = data[:4096]
    even_nuls = window[0::2].count(0)
    odd_nuls = window[1::2].count(0)
    pairs = max(1, len(window) // 2)
    if odd_nuls > pairs * 0.6 and even_nuls < pairs * 0.2:
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                window.decode(enc)
                return EncodingGuess(enc, "medium", False, 0)
            except UnicodeDecodeError:
                continue
    # Binary content with NULs (an executable or data file).
    return EncodingGuess("binary", "high", False, 0)

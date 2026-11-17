"""Deterministic ingestion limits — single source of truth (plan §4.1).

Every bound the security model depends on lives here so that the adversarial
tests and the implementation cannot drift apart: the tests import these
constants rather than repeating literals.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Limits", "DEFAULT_LIMITS"]


@dataclass(frozen=True)
class Limits:
    """Immutable bound set for one ingestion run.

    Frozen and hashable so it can be embedded in a manifest for audit.
    """

    #: Maximum number of entries (files + directories) accepted from an archive.
    max_entries: int = 10_000
    #: Maximum total uncompressed bytes written for one run.
    max_total_bytes: int = 512 * 1024 * 1024
    #: Maximum uncompressed bytes for a single entry.
    max_entry_bytes: int = 128 * 1024 * 1024
    #: Maximum uncompressed:compressed ratio for a single entry (zip bomb).
    max_compression_ratio: float = 200.0
    #: Minimum compressed size before the ratio is enforced (tiny files have
    #: meaningless ratios; a 20-byte deflate stream of zeros is not an attack).
    min_bytes_for_ratio: int = 1024
    #: Maximum path depth (separator-delimited components).
    max_path_depth: int = 32
    #: Maximum total length of an entry path.
    max_path_length: int = 4096
    #: Maximum length of a single path component.
    max_name_length: int = 255
    #: Bytes read for content sniffing (hashing is never truncated).
    max_sniff_bytes: int = 1024 * 1024
    #: Hard cap on diagnostics retained, so a hostile input cannot grow output.
    max_diagnostics: int = 500
    #: Maximum bytes read from a single source file for discovery analysis.
    #: Files larger than this are inventoried and hashed but not tokenised.
    max_source_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:  # pragma: no cover - trivial validation
        if self.max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if self.max_compression_ratio <= 1.0:
            raise ValueError("max_compression_ratio must exceed 1.0")
        if self.max_path_depth <= 0:
            raise ValueError("max_path_depth must be positive")

    def as_dict(self) -> dict[str, object]:
        """Deterministic mapping for inclusion in a manifest."""

        return {
            "max_compression_ratio": self.max_compression_ratio,
            "max_diagnostics": self.max_diagnostics,
            "max_entries": self.max_entries,
            "max_entry_bytes": self.max_entry_bytes,
            "max_name_length": self.max_name_length,
            "max_path_depth": self.max_path_depth,
            "max_path_length": self.max_path_length,
            "max_sniff_bytes": self.max_sniff_bytes,
            "max_source_bytes": self.max_source_bytes,
            "max_total_bytes": self.max_total_bytes,
        }


DEFAULT_LIMITS = Limits()

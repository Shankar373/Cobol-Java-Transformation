"""Normalization attack tests.

Tests that only explicitly authorized normalizations are applied.
All other normalizations must NOT cause MATCH when content differs.

The V1 normalization policy FORBIDS:
- case_folding
- whitespace_normalization
- encoding_conversion
- trailing_whitespace_removal
- trailing_newline_removal
- substring_containment

The only ALLOWED normalization is: crlf_to_lf
"""

from __future__ import annotations

import pytest

from engine.comparators.framework import (
    FixedRecordComparator,
    StdoutComparator,
    TextFileComparator,
)
from engine.contracts.models import NormalizationPolicy
from engine.domain.identities import ArtifactIdentity

from .conftest import _hash


def _art(aid: str, atype: str, role: str, content: bytes) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=aid, artifact_type=atype, logical_name=atype.lower(),
        producer_role=role, content_hash=_hash(content.decode("utf-8", errors="replace")),
        size_bytes=len(content),
    )


class TestForbiddenNormalizations:
    """NormalizationPolicy forbids 6 normalizations. Verify enforcement."""

    def test_case_folding_forbidden(self):
        with pytest.raises(ValueError, match="permanently forbidden"):
            NormalizationPolicy(allowed_normalizations=("case_folding",))

    def test_whitespace_normalization_forbidden(self):
        with pytest.raises(ValueError, match="permanently forbidden"):
            NormalizationPolicy(allowed_normalizations=("whitespace_normalization",))

    def test_encoding_conversion_forbidden(self):
        with pytest.raises(ValueError, match="permanently forbidden"):
            NormalizationPolicy(allowed_normalizations=("encoding_conversion",))

    def test_trailing_whitespace_removal_forbidden(self):
        with pytest.raises(ValueError, match="permanently forbidden"):
            NormalizationPolicy(allowed_normalizations=("trailing_whitespace_removal",))

    def test_trailing_newline_removal_forbidden(self):
        with pytest.raises(ValueError, match="permanently forbidden"):
            NormalizationPolicy(allowed_normalizations=("trailing_newline_removal",))

    def test_substring_containment_forbidden(self):
        with pytest.raises(ValueError, match="permanently forbidden"):
            NormalizationPolicy(allowed_normalizations=("substring_containment",))


class TestCaseFolding:
    """Case is NOT folded. 'Hello' ≠ 'hello'."""

    def setup_method(self):
        self.comp = StdoutComparator()
        self.ora = _art("ora", "STDOUT", "ORACLE", b"")
        self.cand = _art("cand", "STDOUT", "CANDIDATE", b"")

    def test_upper_vs_lower(self):
        r = self.comp.compare(self.ora, b"Hello World", self.cand, b"hello world")
        assert r.result.value == "MISMATCH"

    def test_mixed_case(self):
        r = self.comp.compare(self.ora, b"ABC", self.cand, b"Abc")
        assert r.result.value == "MISMATCH"


class TestTrailingWhitespace:
    """Trailing whitespace is NOT removed."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "TEXT_FILE", "ORACLE", b"")
        self.cand = _art("cand", "TEXT_FILE", "CANDIDATE", b"")

    def test_trailing_space(self):
        r = self.comp.compare(self.ora, b"line  ", self.cand, b"line")
        assert r.result.value == "MISMATCH"

    def test_trailing_tab(self):
        r = self.comp.compare(self.ora, b"line\t", self.cand, b"line")
        assert r.result.value == "MISMATCH"

    def test_trailing_newline_not_removed(self):
        r = self.comp.compare(self.ora, b"line\n", self.cand, b"line")
        assert r.result.value == "MISMATCH"


class TestLeadingWhitespace:
    """Leading whitespace is NOT removed."""

    def setup_method(self):
        self.comp = StdoutComparator()
        self.ora = _art("ora", "STDOUT", "ORACLE", b"")
        self.cand = _art("cand", "STDOUT", "CANDIDATE", b"")

    def test_leading_space(self):
        r = self.comp.compare(self.ora, b" hello", self.cand, b"hello")
        assert r.result.value == "MISMATCH"

    def test_leading_newline(self):
        r = self.comp.compare(self.ora, b"\nhello", self.cand, b"hello")
        assert r.result.value == "MISMATCH"


class TestEncodingDifferences:
    """Encoding differences are NOT normalized."""

    def setup_method(self):
        self.comp = StdoutComparator()
        self.ora = _art("ora", "STDOUT", "ORACLE", b"")
        self.cand = _art("cand", "STDOUT", "CANDIDATE", b"")

    def test_utf8_vs_latin1(self):
        """Same character, different byte encoding."""
        r = self.comp.compare(
            self.ora, "café".encode(),
            self.cand, "café".encode("latin-1"),
        )
        assert r.result.value == "MISMATCH"

    def test_bom_not_stripped(self):
        """UTF-8 BOM is NOT removed."""
        r = self.comp.compare(
            self.ora, b"\xef\xbb\xbfhello",
            self.cand, b"hello",
        )
        assert r.result.value == "MISMATCH"


class TestInternalWhitespace:
    """Internal whitespace differences are NOT normalized."""

    def setup_method(self):
        self.comp = StdoutComparator()
        self.ora = _art("ora", "STDOUT", "ORACLE", b"")
        self.cand = _art("cand", "STDOUT", "CANDIDATE", b"")

    def test_tab_vs_spaces(self):
        r = self.comp.compare(self.ora, b"a\tb", self.cand, b"a    b")
        assert r.result.value == "MISMATCH"

    def test_multiple_spaces(self):
        r = self.comp.compare(self.ora, b"a  b", self.cand, b"a b")
        assert r.result.value == "MISMATCH"


class TestNewlineVariations:
    """Only \\r\\n → \\n is normalized. Other newline variations are not."""

    def setup_method(self):
        self.comp = StdoutComparator()
        self.ora = _art("ora", "STDOUT", "ORACLE", b"")
        self.cand = _art("cand", "STDOUT", "CANDIDATE", b"")

    def test_crlf_to_lf(self):
        r = self.comp.compare(self.ora, b"A\r\nB", self.cand, b"A\nB")
        assert r.result.value == "MATCH"

    def test_lone_cr_not_normalized(self):
        r = self.comp.compare(self.ora, b"A\rB", self.cand, b"AB")
        assert r.result.value == "MISMATCH"

    def test_lf_to_crlf_direction(self):
        """CRLF→LF normalization is one-directional. Oracle has LF, candidate has CRLF.
        After normalization: oracle='A\\nB', candidate='A\\nB' → MATCH."""
        r = self.comp.compare(self.ora, b"A\nB", self.cand, b"A\r\nB")
        assert r.result.value == "MATCH"


class TestFixedRecordNoNormalization:
    """FixedRecordComparator applies NO normalization at all."""

    def setup_method(self):
        self.comp = FixedRecordComparator()
        self.ora = _art("ora", "FIXED_RECORD", "ORACLE", b"")
        self.cand = _art("cand", "FIXED_RECORD", "CANDIDATE", b"")

    def test_crlf_not_normalized_in_fixed_record(self):
        """Fixed records compare raw bytes, no CRLF normalization."""
        # Create equal-length records with CRLF vs LF
        r = self.comp.compare(
            self.ora, b"A\r\nBB",
            self.cand, b"A\nBBB",
        )
        assert r.result.value == "MISMATCH"

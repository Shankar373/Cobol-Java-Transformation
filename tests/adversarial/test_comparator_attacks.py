"""Comparator attack surface tests.

Tests that each V1 comparator does NOT accept:
- Substring containment
- Partial matching
- Prefix/suffix acceptance
- Subset acceptance
- Count-only validation
- Empty-output acceptance
- Accidental normalization beyond CRLF→LF

Every comparator must use byte-exact comparison (after explicit normalizations).
"""

from __future__ import annotations

from engine.comparators.framework import (
    ExitStatusComparator,
    FixedRecordComparator,
    StderrComparator,
    StdoutComparator,
    TextFileComparator,
    create_default_registry,
)
from engine.domain.identities import ArtifactIdentity

from .conftest import _hash


def _make_artifact(
    artifact_id: str,
    artifact_type: str,
    producer_role: str,
    content: bytes,
    record_count: int | None = None,
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        logical_name=f"{artifact_type.lower()}",
        producer_role=producer_role,
        content_hash=_hash(content.decode("utf-8", errors="replace")),
        size_bytes=len(content),
        record_count=record_count,
    )


class TestStdoutComparatorAttacks:
    """StdoutComparator must reject all partial/substring attacks."""

    def setup_method(self):
        self.comp = StdoutComparator()
        self.oracle = _make_artifact("ora-stdout", "STDOUT", "ORACLE", b"")
        self.cand = _make_artifact("cand-stdout", "STDOUT", "CANDIDATE", b"")

    def test_substring_not_accepted(self):
        """Oracle: 'HELLO WORLD' vs Candidate: 'HELLO' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"HELLO WORLD",
            self.cand, b"HELLO",
        )
        assert result.result.value == "MISMATCH"

    def test_superset_not_accepted(self):
        """Oracle: 'AB' vs Candidate: 'ABC' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"AB",
            self.cand, b"ABC",
        )
        assert result.result.value == "MISMATCH"

    def test_prefix_not_accepted(self):
        """Oracle: 'abcdef' vs Candidate: 'abc' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"abcdef",
            self.cand, b"abc",
        )
        assert result.result.value == "MISMATCH"

    def test_suffix_not_accepted(self):
        """Oracle: 'abcdef' vs Candidate: 'def' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"abcdef",
            self.cand, b"def",
        )
        assert result.result.value == "MISMATCH"

    def test_empty_vs_nonempty(self):
        """Oracle: '' vs Candidate: 'x' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"",
            self.cand, b"x",
        )
        assert result.result.value == "MISMATCH"

    def test_reversed_content(self):
        """Oracle: 'ABC' vs Candidate: 'CBA' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"ABC",
            self.cand, b"CBA",
        )
        assert result.result.value == "MISMATCH"

    def test_only_whitespace_diff(self):
        """Oracle: 'A B' vs Candidate: 'A  B' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"A B",
            self.cand, b"A  B",
        )
        assert result.result.value == "MISMATCH"

    def test_newline_only_diff(self):
        """Oracle: 'A\nB' vs Candidate: 'AB' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"A\nB",
            self.cand, b"AB",
        )
        assert result.result.value == "MISMATCH"

    def test_case_not_folded(self):
        """Oracle: 'Hello' vs Candidate: 'hello' → MISMATCH."""
        result = self.comp.compare(
            self.oracle, b"Hello",
            self.cand, b"hello",
        )
        assert result.result.value == "MISMATCH"

    def test_crlf_normalization_only(self):
        """CRLF → LF normalization is the ONLY allowed normalization."""
        result = self.comp.compare(
            self.oracle, b"A\r\nB",
            self.cand, b"A\nB",
        )
        assert result.result.value == "MATCH"
        assert "crlf_to_lf" in result.normalization_applied

    def test_only_trailing_cr_not_normalized(self):
        """Trailing CR without LF is NOT normalized."""
        result = self.comp.compare(
            self.oracle, b"A\r",
            self.cand, b"A",
        )
        assert result.result.value == "MISMATCH"


class TestStderrComparatorAttacks:
    """StderrComparator must reject all partial/substring attacks."""

    def setup_method(self):
        self.comp = StderrComparator()
        self.oracle = _make_artifact("ora-stderr", "STDERR", "ORACLE", b"")
        self.cand = _make_artifact("cand-stderr", "STDERR", "CANDIDATE", b"")

    def test_substring_not_accepted(self):
        result = self.comp.compare(self.oracle, b"FULL TEXT", self.cand, b"FULL")
        assert result.result.value == "MISMATCH"

    def test_empty_vs_content(self):
        result = self.comp.compare(self.oracle, b"", self.cand, b"anything")
        assert result.result.value == "MISMATCH"

    def test_crlf_normalization(self):
        result = self.comp.compare(self.oracle, b"X\r\nY", self.cand, b"X\nY")
        assert result.result.value == "MATCH"


class TestExitStatusComparatorAttacks:
    """ExitStatusComparator must reject invalid formats and mismatched codes."""

    def setup_method(self):
        self.comp = ExitStatusComparator()
        self.oracle = _make_artifact("ora-exit", "EXIT_STATUS", "ORACLE", b"")
        self.cand = _make_artifact("cand-exit", "EXIT_STATUS", "CANDIDATE", b"")

    def test_identical_exits_match(self):
        result = self.comp.compare(self.oracle, b"0", self.cand, b"0")
        assert result.result.value == "MATCH"

    def test_different_exits_mismatch(self):
        result = self.comp.compare(self.oracle, b"0", self.cand, b"1")
        assert result.result.value == "MISMATCH"

    def test_non_numeric_oracle_inconclusive(self):
        result = self.comp.compare(self.oracle, b"abc", self.cand, b"0")
        assert result.result.value == "INCONCLUSIVE"

    def test_non_numeric_candidate_inconclusive(self):
        result = self.comp.compare(self.oracle, b"0", self.cand, b"xyz")
        assert result.result.value == "INCONCLUSIVE"

    def test_both_non_numeric_inconclusive(self):
        result = self.comp.compare(self.oracle, b"abc", self.cand, b"xyz")
        assert result.result.value == "INCONCLUSIVE"

    def test_whitespace_handling(self):
        """Exit codes are stripped before comparison."""
        result = self.comp.compare(self.oracle, b"  0  ", self.cand, b"0")
        assert result.result.value == "MATCH"

    def test_negative_exit_code(self):
        """Negative exit codes are valid integers."""
        result = self.comp.compare(self.oracle, b"-1", self.cand, b"-1")
        assert result.result.value == "MATCH"

    def test_large_exit_code(self):
        result = self.comp.compare(self.oracle, b"255", self.cand, b"255")
        assert result.result.value == "MATCH"


class TestTextFileComparatorAttacks:
    """TextFileComparator must reject all partial/substring attacks."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.oracle = _make_artifact("ora-tf", "TEXT_FILE", "ORACLE", b"")
        self.cand = _make_artifact("cand-tf", "TEXT_FILE", "CANDIDATE", b"")

    def test_subset_not_accepted(self):
        result = self.comp.compare(self.oracle, b"LINE1\nLINE2\nLINE3", self.cand, b"LINE1\nLINE2")
        assert result.result.value == "MISMATCH"

    def test_reordered_lines_not_accepted(self):
        result = self.comp.compare(self.oracle, b"A\nB\nC", self.cand, b"C\nB\nA")
        assert result.result.value == "MISMATCH"

    def test_extra_line_not_accepted(self):
        result = self.comp.compare(self.oracle, b"A\nB", self.cand, b"A\nB\nC")
        assert result.result.value == "MISMATCH"

    def test_trailing_newline_diff(self):
        result = self.comp.compare(self.oracle, b"A\nB\n", self.cand, b"A\nB")
        assert result.result.value == "MISMATCH"

    def test_crlf_normalization(self):
        result = self.comp.compare(self.oracle, b"A\r\nB", self.cand, b"A\nB")
        assert result.result.value == "MATCH"


class TestFixedRecordComparatorAttacks:
    """FixedRecordComparator must reject subset, reordered, and partial records."""

    def setup_method(self):
        self.comp = FixedRecordComparator()

    def _artifact(self, aid: str, role: str, content: bytes, rc: int | None = None):
        return _make_artifact(aid, "FIXED_RECORD", role, content, record_count=rc)

    def test_identical_records_match(self):
        oracle = self._artifact("ora", "ORACLE", b"AAAABBBBCCCC", rc=3)
        cand = self._artifact("cand", "CANDIDATE", b"AAAABBBBCCCC", rc=3)
        result = self.comp.compare(oracle, b"AAAABBBBCCCC", cand, b"AAAABBBBCCCC")
        assert result.result.value == "MATCH"

    def test_record_count_mismatch(self):
        oracle = self._artifact("ora", "ORACLE", b"AAAABBBB", rc=2)
        cand = self._artifact("cand", "CANDIDATE", b"AAAABBBBCCCC", rc=3)
        result = self.comp.compare(oracle, b"AAAABBBB", cand, b"AAAABBBBCCCC")
        assert result.result.value == "MISMATCH"

    def test_missing_record(self):
        oracle = self._artifact("ora", "ORACLE", b"AAAABBBBCCCC", rc=3)
        cand = self._artifact("cand", "CANDIDATE", b"AAAABBBB", rc=2)
        result = self.comp.compare(oracle, b"AAAABBBBCCCC", cand, b"AAAABBBB")
        assert result.result.value == "MISMATCH"

    def test_extra_record(self):
        oracle = self._artifact("ora", "ORACLE", b"AAAABBBB", rc=2)
        cand = self._artifact("cand", "CANDIDATE", b"AAAABBBBCCCC", rc=3)
        result = self.comp.compare(oracle, b"AAAABBBB", cand, b"AAAABBBBCCCC")
        assert result.result.value == "MISMATCH"

    def test_reordered_records(self):
        """Records in different order → MISMATCH (not accepted as equivalent)."""
        oracle = self._artifact("ora", "ORACLE", b"AAAABBBBCCCC", rc=3)
        cand = self._artifact("cand", "CANDIDATE", b"CCCCAAAABBBB", rc=3)
        result = self.comp.compare(oracle, b"AAAABBBBCCCC", cand, b"CCCCAAAABBBB")
        assert result.result.value == "MISMATCH"

    def test_single_byte_diff_in_record(self):
        oracle = self._artifact("ora", "ORACLE", b"AAAABBBB", rc=2)
        cand = self._artifact("cand", "CANDIDATE", b"AAAABBBC", rc=2)
        result = self.comp.compare(oracle, b"AAAABBBB", cand, b"AAAABBBC")
        assert result.result.value == "MISMATCH"

    def test_empty_records(self):
        oracle = self._artifact("ora", "ORACLE", b"", rc=0)
        cand = self._artifact("cand", "CANDIDATE", b"", rc=0)
        result = self.comp.compare(oracle, b"", cand, b"")
        assert result.result.value == "MATCH"


class TestRegistryCompleteness:
    """All five V1 comparators are registered."""

    def test_all_five_registered(self):
        registry = create_default_registry()
        all_comps = registry.get_all()
        assert len(all_comps) == 5
        assert "STDOUT" in all_comps
        assert "STDERR" in all_comps
        assert "EXIT_STATUS" in all_comps
        assert "TEXT_FILE" in all_comps
        assert "FIXED_RECORD" in all_comps

    def test_no_unregistered_types(self):
        """Comparators exist only for the 5 V1 types."""
        registry = create_default_registry()
        for art_type in ["STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE", "FIXED_RECORD"]:
            assert registry.is_registered(art_type)
        # Random types not registered
        assert not registry.is_registered("INDEXED")
        assert not registry.is_registered("JSON")
        assert not registry.is_registered("BINARY")

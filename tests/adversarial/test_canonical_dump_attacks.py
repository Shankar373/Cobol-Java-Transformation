"""Canonical dump attack tests.

Tests that malformed or manipulated canonical dumps (used for
INDEXED/RELATIVE validation) cannot produce VERIFIED.

Canonical dump format:
  INDEXED: KEY|DATA\n
  RELATIVE: RRNN|DATA\n
  Terminal: FILESTATUS=NN\nEND\n

These tests verify the TextFileComparator (which compares dumps byte-exact)
rejects all manipulation.
"""

from __future__ import annotations

from engine.comparators.framework import TextFileComparator
from engine.domain.identities import ArtifactIdentity

from .conftest import _hash


def _art(aid: str, role: str, content: bytes) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=aid, artifact_type="STDOUT", logical_name="stdout",
        producer_role=role, content_hash=_hash(content.decode("utf-8", errors="replace")),
        size_bytes=len(content),
    )


class TestRecordReordering:
    """Reordered records in canonical dump → MISMATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_indexed_reorder(self):
        oracle = b"K001|RECORD-ONE\nK002|RECORD-TWO\nK003|RECORD-THREE\nFILESTATUS=00\nEND\n"
        candidate = b"K003|RECORD-THREE\nK001|RECORD-ONE\nK002|RECORD-TWO\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"

    def test_relative_reorder(self):
        oracle = b"0001|DATA-A\n0002|DATA-B\n0003|DATA-C\nFILESTATUS=00\nEND\n"
        candidate = b"0002|DATA-B\n0001|DATA-A\n0003|DATA-C\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"


class TestDuplicateRecords:
    """Duplicate records in canonical dump → MISMATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_duplicate_key(self):
        oracle = b"K001|RECORD-ONE\nK002|RECORD-TWO\nFILESTATUS=00\nEND\n"
        candidate = b"K001|RECORD-ONE\nK001|RECORD-ONE\nK002|RECORD-TWO\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"


class TestMissingTerminalLine:
    """Missing terminal lines → MISMATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_missing_end(self):
        oracle = b"K001|RECORD-ONE\nFILESTATUS=00\nEND\n"
        candidate = b"K001|RECORD-ONE\nFILESTATUS=00\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"

    def test_missing_filestatus(self):
        oracle = b"K001|RECORD-ONE\nFILESTATUS=00\nEND\n"
        candidate = b"K001|RECORD-ONE\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"


class TestInvalidFileStatus:
    """Invalid file status in canonical dump → MISMATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_wrong_filestatus(self):
        oracle = b"K001|RECORD-ONE\nFILESTATUS=00\nEND\n"
        candidate = b"K001|RECORD-ONE\nFILESTATUS=23\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"

    def test_non_numeric_filestatus(self):
        oracle = b"K001|RECORD-ONE\nFILESTATUS=00\nEND\n"
        candidate = b"K001|RECORD-ONE\nFILESTATUS=XX\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"


class TestContentManipulation:
    """Manipulated record content → MISMATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_changed_data(self):
        oracle = b"K001|ORIGINAL-DATA\nFILESTATUS=00\nEND\n"
        candidate = b"K001|TAMPERD-DATA\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"

    def test_changed_key(self):
        oracle = b"K001|DATA\nFILESTATUS=00\nEND\n"
        candidate = b"K999|DATA\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"


class TestExtraRecords:
    """Extra records in candidate dump → MISMATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_extra_record(self):
        oracle = b"K001|DATA\nFILESTATUS=00\nEND\n"
        candidate = b"K001|DATA\nK002|EXTRA\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"


class TestMissingRecords:
    """Missing records in candidate dump → MISMATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_missing_record(self):
        oracle = b"K001|DATA-A\nK002|DATA-B\nFILESTATUS=00\nEND\n"
        candidate = b"K001|DATA-A\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"


class TestSubsetAcceptance:
    """Subset of oracle dump must NOT be accepted as equivalent."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_partial_dump(self):
        oracle = (
            b"K001|RECORD-ONE\nK002|RECORD-TWO\nK003|RECORD-THREE\n"
            b"FILESTATUS=00\nEND\n"
        )
        candidate = b"K001|RECORD-ONE\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"

    def test_empty_dump(self):
        oracle = b"K001|DATA\nFILESTATUS=00\nEND\n"
        candidate = b""
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"


class TestMalformedDump:
    """Malformed canonical dumps → MISMATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    def test_no_pipe_delimiter(self):
        oracle = b"K001|DATA\nFILESTATUS=00\nEND\n"
        candidate = b"K001 DATA\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"

    def test_binary_garbage(self):
        oracle = b"K001|DATA\nFILESTATUS=00\nEND\n"
        candidate = b"\x00\x01\x02\x03\nFILESTATUS=00\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"

    def test_empty_filestatus_value(self):
        oracle = b"K001|DATA\nFILESTATUS=00\nEND\n"
        candidate = b"K001|DATA\nFILESTATUS=\nEND\n"
        r = self.comp.compare(self.ora, oracle, self.cand, candidate)
        assert r.result.value == "MISMATCH"

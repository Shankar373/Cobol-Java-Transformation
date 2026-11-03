"""BL-052: FIXED_RECORD comparator must not ignore trailing partial-record bytes.

The record-by-record path counts records with floor division
(``len(content) // record_length``), so bytes after the last whole record are
never compared.  When artifact metadata disagrees with captured content (or
the comparator is used directly), a truncated/extended tail could hide behind
record counting and produce a false MATCH.

These tests pin the expected behavior: any byte not covered by a compared
whole record is compared explicitly, so differing trailing bytes always
produce a MISMATCH that reports them.

Metadata precondition (documented defect scope): the declared identity says
``record_count`` whole records while the captured content carries bytes
beyond (or short of) that whole-record area — the metadata-mismatch case the
backlog entry calls out as reachable outside the V1 capture path.
"""

from __future__ import annotations

from engine.comparators.framework import FixedRecordComparator
from engine.domain.identities import ArtifactIdentity
from tests.common import make_hash

#: Ten whole records of 10 bytes = 100 bytes of record area.
RECORD_LENGTH = 10
RECORDS = b"".join(f"{i:010d}".encode() for i in range(10))
assert len(RECORDS) == 100

#: Five bytes beyond the last whole record.
TAIL = b"TAIL!"


def _artifact(
    artifact_id: str,
    producer_role: str,
    content: bytes,
    *,
    record_count: int | None = 10,
    size_bytes: int | None = None,
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=artifact_id,
        artifact_type="FIXED_RECORD",
        logical_name="fixed-records",
        producer_role=producer_role,
        content_hash=make_hash(f"{artifact_id}-hash"),
        size_bytes=len(content) if size_bytes is None else size_bytes,
        record_count=record_count,
    )


class TestTrailingPartialRecordNeverHidesADifference:
    """Floor division must not drop bytes after the last whole record."""

    def setup_method(self) -> None:
        self.comparator = FixedRecordComparator()

    def test_oracle_trailing_partial_record_produces_mismatch(self) -> None:
        """Oracle carries 5 bytes beyond 10 whole records; candidate does not."""
        oracle_content = RECORDS + TAIL  # 105 bytes, 10 declared records
        candidate_content = RECORDS  # 100 bytes
        oracle = _artifact("ora-tail-oracle", "ORACLE", oracle_content)
        candidate = _artifact("cand-tail-oracle", "CANDIDATE", candidate_content)

        result = self.comparator.compare(
            oracle, oracle_content, candidate, candidate_content
        )

        assert result.result.value == "MISMATCH"
        assert any(
            "partial" in difference.description.lower()
            or "trailing" in difference.description.lower()
            for difference in result.differences
        ), [d.description for d in result.differences]

    def test_candidate_trailing_partial_record_produces_mismatch(self) -> None:
        """Candidate carries 5 bytes beyond 10 whole records; oracle does not."""
        oracle_content = RECORDS  # 100 bytes
        candidate_content = RECORDS + TAIL  # 105 bytes
        oracle = _artifact("ora-tail-cand", "ORACLE", oracle_content)
        candidate = _artifact("cand-tail-cand", "CANDIDATE", candidate_content)

        result = self.comparator.compare(
            oracle, oracle_content, candidate, candidate_content
        )

        assert result.result.value == "MISMATCH"

    def test_differing_trailing_bytes_produce_mismatch(self) -> None:
        """Both sides carry a tail of equal length but different bytes."""
        oracle_content = RECORDS + b"AAAAA"
        candidate_content = RECORDS + b"BBBBB"
        oracle = _artifact("ora-tail-diff", "ORACLE", oracle_content)
        candidate = _artifact("cand-tail-diff", "CANDIDATE", candidate_content)

        result = self.comparator.compare(
            oracle, oracle_content, candidate, candidate_content
        )

        assert result.result.value == "MISMATCH"

    def test_reported_difference_contains_the_trailing_bytes(self) -> None:
        """The mismatch evidence must report the unexamined trailing bytes."""
        oracle_content = RECORDS + TAIL
        candidate_content = RECORDS
        oracle = _artifact("ora-tail-report", "ORACLE", oracle_content)
        candidate = _artifact("cand-tail-report", "CANDIDATE", candidate_content)

        result = self.comparator.compare(
            oracle, oracle_content, candidate, candidate_content
        )

        tail_differences = [
            d for d in result.differences if d.location == "trailing_partial_record"
        ]
        assert tail_differences, [d.location for d in result.differences]
        assert repr(TAIL) in tail_differences[0].expected
        assert result.differences and tail_differences[0].actual in ("b''", "")

    def test_content_shorter_than_declared_record_length_produces_mismatch(self) -> None:
        """Metadata declares one 10-byte record; both sides captured only 5 bytes.

        Floor division yields zero whole records on both sides, so the record
        loop compares nothing — the differing bytes must still mismatch.
        """
        oracle_content = b"AAAAA"
        candidate_content = b"BBBBB"
        oracle = _artifact(
            "ora-short", "ORACLE", oracle_content, record_count=1, size_bytes=RECORD_LENGTH
        )
        candidate = _artifact(
            "cand-short", "CANDIDATE", candidate_content, record_count=1, size_bytes=RECORD_LENGTH
        )

        result = self.comparator.compare(
            oracle, oracle_content, candidate, candidate_content
        )

        assert result.result.value == "MISMATCH"


class TestWholeRecordComparisonStillBehaves:
    """The remainder check must not disturb established record semantics."""

    def setup_method(self) -> None:
        self.comparator = FixedRecordComparator()

    def test_identical_content_matches(self) -> None:
        oracle = _artifact("ora-same", "ORACLE", RECORDS)
        candidate = _artifact("cand-same", "CANDIDATE", RECORDS)

        result = self.comparator.compare(oracle, RECORDS, candidate, RECORDS)

        assert result.result.value == "MATCH"
        assert result.differences == ()

    def test_differing_whole_record_still_mismatches(self) -> None:
        mutated = b"X" + RECORDS[1:]
        oracle = _artifact("ora-rec", "ORACLE", RECORDS)
        candidate = _artifact("cand-rec", "CANDIDATE", mutated)

        result = self.comparator.compare(oracle, RECORDS, candidate, mutated)

        assert result.result.value == "MISMATCH"

    def test_missing_whole_record_still_mismatches(self) -> None:
        truncated_records = RECORDS[:90]
        oracle = _artifact("ora-miss", "ORACLE", RECORDS)
        candidate = _artifact("cand-miss", "CANDIDATE", truncated_records)

        result = self.comparator.compare(
            oracle, RECORDS, candidate, truncated_records
        )

        assert result.result.value == "MISMATCH"

    def test_equal_tails_with_differing_record_still_mismatches(self) -> None:
        """Tails equal, records differ: the record difference decides."""
        oracle_content = RECORDS + TAIL
        candidate_content = (b"X" + RECORDS[1:]) + TAIL
        oracle = _artifact("ora-both", "ORACLE", oracle_content)
        candidate = _artifact("cand-both", "CANDIDATE", candidate_content)

        result = self.comparator.compare(
            oracle, oracle_content, candidate, candidate_content
        )

        assert result.result.value == "MISMATCH"

"""Typed comparator framework for the validation engine.

Implements the comparator FRAMEWORK, not broad semantic coverage.
V1 registered artifact types ONLY:
STDOUT, STDERR, EXIT_STATUS, TEXT_FILE, FIXED_RECORD

ABSOLUTE RULE:
Never implement a generic "compare anything" comparator.
ABSOLUTE RULE:
Never use substring containment as semantic equivalence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from engine.domain.identities import (
    ArtifactIdentity,
    ComparatorId,
    ContentHash,
    RunId,
)
from engine.evidence.models import ComparisonEvidence


class ComparisonResult(Enum):
    """Comparison result states."""
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class ComparisonDifference:
    """A single difference found during comparison."""
    location: str
    expected: str
    actual: str
    description: str


@dataclass(frozen=True)
class ComparatorResult:
    """Result of a comparison operation."""
    comparator_id: ComparatorId
    oracle_artifact: ArtifactIdentity
    candidate_artifact: ArtifactIdentity
    result: ComparisonResult
    differences: tuple[ComparisonDifference, ...]
    normalization_applied: tuple[str, ...]
    field_level_results: tuple[dict[str, Any], ...] = ()
    evidence_hash: ContentHash | None = None

    def to_comparison_evidence(self, run_id: RunId) -> ComparisonEvidence:
        """Convert to comparison evidence."""
        import json
        
        evidence_dict = {
            "comparator_id": self.comparator_id.comparator_id,
            "comparator_version": self.comparator_id.version,
            "oracle_artifact_id": self.oracle_artifact.artifact_id,
            "candidate_artifact_id": self.candidate_artifact.artifact_id,
            "result": self.result.value,
            "differences": [
                {"location": d.location, "expected": d.expected, "actual": d.actual}
                for d in self.differences
            ],
        }
        evidence_bytes = json.dumps(evidence_dict, sort_keys=True).encode("utf-8")
        evidence_hash = ContentHash.from_bytes(evidence_bytes)

        return ComparisonEvidence(
            comparison_id=f"comp-{self.oracle_artifact.artifact_id}-{self.candidate_artifact.artifact_id}",
            run_id=run_id,
            comparator_id=self.comparator_id.comparator_id,
            comparator_version=self.comparator_id.version,
            oracle_artifact_id=self.oracle_artifact.artifact_id,
            candidate_artifact_id=self.candidate_artifact.artifact_id,
            artifact_type=self.oracle_artifact.artifact_type,
            result=self.result.value,
            normalization_applied=self.normalization_applied,
            differences=tuple(d.description for d in self.differences),
            field_level_results=self.field_level_results,
            content_hash=evidence_hash,
        )


class TypedComparator(ABC):
    """Abstract base class for typed comparators."""

    def __init__(self, comparator_id: str, version: str, artifact_type: str) -> None:
        self._comparator_id = ComparatorId(comparator_id=comparator_id, version=version)
        self._artifact_type = artifact_type

    @property
    def comparator_id(self) -> ComparatorId:
        return self._comparator_id

    @property
    def artifact_type(self) -> str:
        return self._artifact_type

    @abstractmethod
    def compare(
        self,
        oracle_artifact: ArtifactIdentity,
        oracle_content: bytes,
        candidate_artifact: ArtifactIdentity,
        candidate_content: bytes,
    ) -> ComparatorResult:
        """Compare two artifacts. Must be deterministic and reproducible."""
        ...

    def _normalize(self, content: bytes, normalizations: tuple[str, ...]) -> bytes:
        """Apply normalizations to content."""
        normalized = content
        for norm in normalizations:
            if norm == "crlf_to_lf":
                normalized = normalized.replace(b"\r\n", b"\n")
            # No other normalizations allowed in V1
        return normalized


class ComparatorRegistry:
    """Registry of typed comparators."""

    def __init__(self) -> None:
        self._comparators: dict[str, TypedComparator] = {}

    def register(self, comparator: TypedComparator) -> None:
        """Register a comparator."""
        artifact_type = comparator.artifact_type
        if artifact_type in self._comparators:
            raise ValueError(f"Comparator already registered for {artifact_type}")
        self._comparators[artifact_type] = comparator

    def get(self, artifact_type: str) -> TypedComparator | None:
        """Get comparator for artifact type."""
        return self._comparators.get(artifact_type)

    def is_registered(self, artifact_type: str) -> bool:
        """Check if comparator is registered for artifact type."""
        return artifact_type in self._comparators

    def get_all(self) -> dict[str, TypedComparator]:
        """Get all registered comparators."""
        return dict(self._comparators)


# ---------------------------------------------------------------------------
# V1 Comparator implementations
# ---------------------------------------------------------------------------

class StdoutComparator(TypedComparator):
    """STDOUT comparator implementation."""

    def __init__(self) -> None:
        super().__init__("STDOUT_COMPARATOR", "1.0.0", "STDOUT")

    def compare(
        self,
        oracle_artifact: ArtifactIdentity,
        oracle_content: bytes,
        candidate_artifact: ArtifactIdentity,
        candidate_content: bytes,
    ) -> ComparatorResult:
        """Compare STDOUT artifacts."""
        normalizations = ("crlf_to_lf",)
        oracle_normalized = self._normalize(oracle_content, normalizations)
        candidate_normalized = self._normalize(candidate_content, normalizations)

        if oracle_normalized == candidate_normalized:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MATCH,
                differences=(),
                normalization_applied=normalizations,
            )
        else:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MISMATCH,
                differences=(
                    ComparisonDifference(
                        location="stdout",
                        expected=str(oracle_normalized),
                        actual=str(candidate_normalized),
                        description="STDOUT output differs",
                    ),
                ),
                normalization_applied=normalizations,
            )


class StderrComparator(TypedComparator):
    """STDERR comparator implementation."""

    def __init__(self) -> None:
        super().__init__("STDERR_COMPARATOR", "1.0.0", "STDERR")

    def compare(
        self,
        oracle_artifact: ArtifactIdentity,
        oracle_content: bytes,
        candidate_artifact: ArtifactIdentity,
        candidate_content: bytes,
    ) -> ComparatorResult:
        """Compare STDERR artifacts."""
        normalizations = ("crlf_to_lf",)
        oracle_normalized = self._normalize(oracle_content, normalizations)
        candidate_normalized = self._normalize(candidate_content, normalizations)

        if oracle_normalized == candidate_normalized:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MATCH,
                differences=(),
                normalization_applied=normalizations,
            )
        else:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MISMATCH,
                differences=(
                    ComparisonDifference(
                        location="stderr",
                        expected=str(oracle_normalized),
                        actual=str(candidate_normalized),
                        description="STDERR output differs",
                    ),
                ),
                normalization_applied=normalizations,
            )


class ExitStatusComparator(TypedComparator):
    """EXIT_STATUS comparator implementation."""

    def __init__(self) -> None:
        super().__init__("EXIT_STATUS_COMPARATOR", "1.0.0", "EXIT_STATUS")

    def compare(
        self,
        oracle_artifact: ArtifactIdentity,
        oracle_content: bytes,
        candidate_artifact: ArtifactIdentity,
        candidate_content: bytes,
    ) -> ComparatorResult:
        """Compare EXIT_STATUS artifacts."""
        try:
            oracle_exit = int(oracle_content.strip())
            candidate_exit = int(candidate_content.strip())
        except ValueError:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.INCONCLUSIVE,
                differences=(
                    ComparisonDifference(
                        location="exit_code",
                        expected=str(oracle_content),
                        actual=str(candidate_content),
                        description="Invalid exit code format",
                    ),
                ),
                normalization_applied=(),
            )

        if oracle_exit == candidate_exit:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MATCH,
                differences=(),
                normalization_applied=(),
            )
        else:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MISMATCH,
                differences=(
                    ComparisonDifference(
                        location="exit_code",
                        expected=str(oracle_exit),
                        actual=str(candidate_exit),
                        description=f"Exit code differs: {oracle_exit} vs {candidate_exit}",
                    ),
                ),
                normalization_applied=(),
            )


class TextFileComparator(TypedComparator):
    """TEXT_FILE comparator implementation."""

    def __init__(self) -> None:
        super().__init__("TEXT_FILE_COMPARATOR", "1.0.0", "TEXT_FILE")

    def compare(
        self,
        oracle_artifact: ArtifactIdentity,
        oracle_content: bytes,
        candidate_artifact: ArtifactIdentity,
        candidate_content: bytes,
    ) -> ComparatorResult:
        """Compare TEXT_FILE artifacts."""
        normalizations = ("crlf_to_lf",)
        oracle_normalized = self._normalize(oracle_content, normalizations)
        candidate_normalized = self._normalize(candidate_content, normalizations)

        if oracle_normalized == candidate_normalized:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MATCH,
                differences=(),
                normalization_applied=normalizations,
            )
        else:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MISMATCH,
                differences=(
                    ComparisonDifference(
                        location="file_content",
                        expected=str(oracle_normalized),
                        actual=str(candidate_normalized),
                        description="TEXT_FILE content differs",
                    ),
                ),
                normalization_applied=normalizations,
            )


class FixedRecordComparator(TypedComparator):
    """FIXED_RECORD comparator implementation.

    V1: record-aware comparison using declared record length.
    If record_length is available on the artifact identity, comparison
    is performed record-by-record. Otherwise falls back to byte-level.
    """

    def __init__(self) -> None:
        super().__init__("FIXED_RECORD_COMPARATOR", "1.0.0", "FIXED_RECORD")

    def compare(
        self,
        oracle_artifact: ArtifactIdentity,
        oracle_content: bytes,
        candidate_artifact: ArtifactIdentity,
        candidate_content: bytes,
    ) -> ComparatorResult:
        """Compare FIXED_RECORD artifacts record-by-record."""
        oracle_rl = oracle_artifact.record_count
        candidate_rl = candidate_artifact.record_count

        if oracle_rl is not None and candidate_rl is not None and oracle_rl != candidate_rl:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MISMATCH,
                differences=(
                    ComparisonDifference(
                        location="record_count",
                        expected=str(oracle_rl),
                        actual=str(candidate_rl),
                        description=f"Record count differs: oracle={oracle_rl} candidate={candidate_rl}",
                    ),
                ),
                normalization_applied=(),
            )

        if oracle_content == candidate_content:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MATCH,
                differences=(),
                normalization_applied=(),
            )

        record_length = self._infer_record_length(oracle_artifact, candidate_artifact)
        if record_length is not None and record_length > 0:
            return self._compare_record_by_record(
                oracle_artifact, oracle_content,
                candidate_artifact, candidate_content,
                record_length,
            )

        return ComparatorResult(
            comparator_id=self._comparator_id,
            oracle_artifact=oracle_artifact,
            candidate_artifact=candidate_artifact,
            result=ComparisonResult.MISMATCH,
            differences=(
                ComparisonDifference(
                    location="records",
                    expected=str(len(oracle_content)),
                    actual=str(len(candidate_content)),
                    description="FIXED_RECORD content differs (byte-level fallback)",
                ),
            ),
            normalization_applied=(),
        )

    def _infer_record_length(
        self, oracle_artifact: ArtifactIdentity, candidate_artifact: ArtifactIdentity,
    ) -> int | None:
        """Infer record length from artifact size and record count."""
        if oracle_artifact.record_count is not None and oracle_artifact.record_count > 0:
            return oracle_artifact.size_bytes // oracle_artifact.record_count
        if candidate_artifact.record_count is not None and candidate_artifact.record_count > 0:
            return candidate_artifact.size_bytes // candidate_artifact.record_count
        return None

    def _compare_record_by_record(
        self,
        oracle_artifact: ArtifactIdentity,
        oracle_content: bytes,
        candidate_artifact: ArtifactIdentity,
        candidate_content: bytes,
        record_length: int,
    ) -> ComparatorResult:
        """Compare two fixed-record artifacts record by record."""
        oracle_count = len(oracle_content) // record_length
        candidate_count = len(candidate_content) // record_length
        max_count = max(oracle_count, candidate_count)

        differences: list[ComparisonDifference] = []

        for i in range(max_count):
            oracle_start = i * record_length
            oracle_end = oracle_start + record_length
            candidate_start = i * record_length
            candidate_end = candidate_start + record_length

            oracle_rec = oracle_content[oracle_start:oracle_end] if oracle_start < len(oracle_content) else b""
            candidate_rec = candidate_content[candidate_start:candidate_end] if candidate_start < len(candidate_content) else b""

            if i >= oracle_count:
                differences.append(ComparisonDifference(
                    location=f"record[{i}]",
                    expected="<missing>",
                    actual=str(candidate_rec),
                    description=f"Extra candidate record at index {i}",
                ))
            elif i >= candidate_count:
                differences.append(ComparisonDifference(
                    location=f"record[{i}]",
                    expected=str(oracle_rec),
                    actual="<missing>",
                    description=f"Missing candidate record at index {i}",
                ))
            elif oracle_rec != candidate_rec:
                differences.append(ComparisonDifference(
                    location=f"record[{i}]",
                    expected=str(oracle_rec),
                    actual=str(candidate_rec),
                    description=f"Record {i} differs",
                ))

        if differences:
            return ComparatorResult(
                comparator_id=self._comparator_id,
                oracle_artifact=oracle_artifact,
                candidate_artifact=candidate_artifact,
                result=ComparisonResult.MISMATCH,
                differences=tuple(differences),
                normalization_applied=(),
            )

        return ComparatorResult(
            comparator_id=self._comparator_id,
            oracle_artifact=oracle_artifact,
            candidate_artifact=candidate_artifact,
            result=ComparisonResult.MATCH,
            differences=(),
            normalization_applied=(),
        )


def create_default_registry() -> ComparatorRegistry:
    """Create a registry with all V1 comparators."""
    registry = ComparatorRegistry()
    registry.register(StdoutComparator())
    registry.register(StderrComparator())
    registry.register(ExitStatusComparator())
    registry.register(TextFileComparator())
    registry.register(FixedRecordComparator())
    return registry

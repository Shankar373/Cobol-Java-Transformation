"""Transformation producer contracts and result types.

Defines the interface that ALL transformation producers must implement.
The producer is UNTRUSTED by the validation engine. It generates candidates;
it does not validate, compare, or certify.

Architecture:

    TransformationProducer (interface)
        ↓
    InternalNativeJavaProducer (primary)
    OpenSourceCOBOL4JProducerAdapter (alternative)
    Future producers (LLM, commercial, etc.)
        ↓
    TransformationResult
        ↓
    Validation Engine (independent)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TransformationStatus(Enum):
    """Status of a transformation attempt."""
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ProducerCapability(Enum):
    """Capabilities a producer may advertise."""
    NATIVE_JAVA = "NATIVE_JAVA"
    SEQUENTIAL_FILES = "SEQUENTIAL_FILES"
    INDEXED_FILES = "INDEXED_FILES"
    RELATIVE_FILES = "RELATIVE_FILES"
    SORT_STATEMENTS = "SORT_STATEMENTS"
    CALL_STATEMENTS = "CALL_STATEMENTS"
    EMBEDDED_SQL = "EMBEDDED_SQL"
    SOURCE_DRIVEN = "SOURCE_DRIVEN"


@dataclass(frozen=True)
class Diagnostic:
    """A diagnostic message from transformation."""
    level: str  # "INFO", "WARNING", "ERROR"
    code: str  # e.g., "PARSE_ERROR", "UNSUPPORTED_CONSTRUCT"
    message: str
    location: str = ""  # e.g., "line 42, column 5"


@dataclass(frozen=True)
class GeneratedFile:
    """A generated source file."""
    filename: str
    source_code: str
    language: str = "java"


@dataclass(frozen=True)
class TransformationResult:
    """Result of a COBOL-to-Java transformation.

    This contains ONLY transformation results. It does NOT contain
    authoritative certification. The validation engine determines equivalence.
    """
    status: TransformationStatus
    generated_files: tuple[GeneratedFile, ...] = ()
    entrypoint: str = ""
    producer_identity: str = ""
    producer_version: str = ""
    diagnostics: tuple[Diagnostic, ...] = ()
    supported_constructs: tuple[str, ...] = ()
    unsupported_constructs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == TransformationStatus.SUCCESS

    @property
    def java_source_tree(self) -> dict[str, str]:
        """Map of filename → source code."""
        return {f.filename: f.source_code for f in self.generated_files}

    @property
    def has_warnings(self) -> bool:
        return any(d.level == "WARNING" for d in self.diagnostics)

    @property
    def has_errors(self) -> bool:
        return any(d.level == "ERROR" for d in self.diagnostics)


class TransformationProducer(ABC):
    """Interface for all transformation producers.

    A producer transforms COBOL source into a candidate implementation.
    The producer is UNTRUSTED — it does NOT validate, compare, or certify.

    The validation engine consumes the producer's output independently.
    """

    @abstractmethod
    def transform(
        self,
        cobol_source: str,
        program_id: str = "UNKNOWN",
    ) -> TransformationResult:
        """Transform COBOL source to a candidate implementation.

        Args:
            cobol_source: The COBOL source code as a string.
            program_id: The COBOL program ID (used for class name).

        Returns:
            TransformationResult with generated files or errors.
        """

    @abstractmethod
    def get_capabilities(self) -> tuple[ProducerCapability, ...]:
        """Return the capabilities this producer supports."""

    @abstractmethod
    def get_identity(self) -> tuple[str, str]:
        """Return (producer_name, producer_version)."""

    def get_runtime_requirements(self) -> tuple[str, ...]:
        """Return runtime dependencies required by generated code.

        For standalone native Java, this should be empty.
        For OpenSourceCOBOL4J, this would include 'libcobj.jar'.
        """
        return ()

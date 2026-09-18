"""Transformation diagnostics.

Provides structured diagnostic messages for transformation results.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DiagnosticLevel(Enum):
    """Severity level for diagnostics."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class DiagnosticCode(Enum):
    """Structured diagnostic codes."""
    # Success
    TRANSFORMATION_COMPLETE = "TRANSFORMATION_COMPLETE"

    # Parse errors
    PARSE_ERROR = "PARSE_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    UNSUPPORTED_DIVISION = "UNSUPPORTED_DIVISION"

    # Semantic errors
    SEMANTIC_ERROR = "SEMANTIC_ERROR"
    UNKNOWN_VARIABLE = "UNKNOWN_VARIABLE"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    UNDEFINED_FILE = "UNDEFINED_FILE"

    # Generation errors
    GENERATION_ERROR = "GENERATION_ERROR"
    UNSUPPORTED_CONSTRUCT = "UNSUPPORTED_CONSTRUCT"

    # Warnings
    IMPLICIT_TYPE = "IMPLICIT_TYPE"
    TRUNCATION_WARNING = "TRUNCATION_WARNING"
    DEPRECATED_SYNTAX = "DEPRECATED_SYNTAX"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"


@dataclass(frozen=True)
class Diagnostic:
    """A structured diagnostic message."""
    level: DiagnosticLevel
    code: DiagnosticCode
    message: str
    location: str = ""

    @classmethod
    def info(cls, code: DiagnosticCode, message: str, location: str = "") -> Diagnostic:
        return cls(level=DiagnosticLevel.INFO, code=code, message=message, location=location)

    @classmethod
    def warning(cls, code: DiagnosticCode, message: str, location: str = "") -> Diagnostic:
        return cls(level=DiagnosticLevel.WARNING, code=code, message=message, location=location)

    @classmethod
    def error(cls, code: DiagnosticCode, message: str, location: str = "") -> Diagnostic:
        return cls(level=DiagnosticLevel.ERROR, code=code, message=message, location=location)


class DiagnosticCollector:
    """Collects diagnostics during transformation."""

    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []

    def add(self, diagnostic: Diagnostic) -> None:
        self._diagnostics.append(diagnostic)

    def info(self, code: DiagnosticCode, message: str, location: str = "") -> None:
        self.add(Diagnostic.info(code, message, location))

    def warning(self, code: DiagnosticCode, message: str, location: str = "") -> None:
        self.add(Diagnostic.warning(code, message, location))

    def error(self, code: DiagnosticCode, message: str, location: str = "") -> None:
        self.add(Diagnostic.error(code, message, location))

    @property
    def has_errors(self) -> bool:
        return any(d.level == DiagnosticLevel.ERROR for d in self._diagnostics)

    @property
    def has_warnings(self) -> bool:
        return any(d.level == DiagnosticLevel.WARNING for d in self._diagnostics)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self._diagnostics if d.level == DiagnosticLevel.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self._diagnostics if d.level == DiagnosticLevel.WARNING]

    @property
    def all(self) -> tuple[Diagnostic, ...]:
        return tuple(self._diagnostics)

    def clear(self) -> None:
        self._diagnostics.clear()

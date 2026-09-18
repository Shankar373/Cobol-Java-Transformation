"""Comparator subsystem for the validation engine."""

from engine.comparators.framework import (
    ComparatorRegistry,
    ComparatorResult,
    ComparisonDifference,
    ComparisonResult,
    ExitStatusComparator,
    FixedRecordComparator,
    StderrComparator,
    StdoutComparator,
    TextFileComparator,
    TypedComparator,
    create_default_registry,
)

__all__ = [
    "ComparatorRegistry",
    "ComparatorResult",
    "ComparisonDifference",
    "ComparisonResult",
    "ExitStatusComparator",
    "FixedRecordComparator",
    "StderrComparator",
    "StdoutComparator",
    "TextFileComparator",
    "TypedComparator",
    "create_default_registry",
]

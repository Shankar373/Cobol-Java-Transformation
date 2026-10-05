"""Authoritative semantic capability registry for deterministic COBOL transformation.

The registry is consumed by the modernization capability analyzer. A source-only
finding for a construct that normally requires parsed IR is fail-closed as
UNKNOWN; unsupported constructs remain explicitly unsupported.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from engine.transformation.ir import (
    AddStatement,
    CallStatement,
    CloseStatement,
    ComputeStatement,
    DeleteStatement,
    DisplayStatement,
    DivideStatement,
    GoToStatement,
    IfStatement,
    MoveStatement,
    MultiplyStatement,
    OpenStatement,
    PerformStatement,
    PerformTimesStatement,
    ReadStatement,
    RewriteStatement,
    StartStatement,
    StopRunStatement,
    StringStatement,
    SubtractStatement,
    UnstringStatement,
    WriteStatement,
)


class CapabilityLevel(Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ConstructCapability:
    level: CapabilityLevel
    evidence: str
    effective_source_level: CapabilityLevel


def _supported(evidence: str) -> ConstructCapability:
    return ConstructCapability(
        CapabilityLevel.SUPPORTED,
        evidence,
        CapabilityLevel.UNKNOWN,
    )


def _partial(evidence: str) -> ConstructCapability:
    return ConstructCapability(
        CapabilityLevel.PARTIAL,
        evidence,
        CapabilityLevel.PARTIAL,
    )


def _unsupported(evidence: str) -> ConstructCapability:
    return ConstructCapability(
        CapabilityLevel.UNSUPPORTED,
        evidence,
        CapabilityLevel.UNSUPPORTED,
    )


CONSTRUCT_REGISTRY: dict[str, ConstructCapability] = {
    "MOVE": _supported("MOVE is mapped to Java assignment semantics"),
    "ADD": _supported("ADD is mapped to Java arithmetic semantics"),
    "SUBTRACT": _supported("SUBTRACT is mapped to Java arithmetic semantics"),
    "MULTIPLY": _supported("MULTIPLY is mapped to Java arithmetic semantics"),
    "COMPUTE": _supported("COMPUTE is mapped to Java expression semantics"),
    "DIVIDE": _supported("DIVIDE is mapped to Java arithmetic semantics"),
    "IF/ELSE": _supported("IF/ELSE is mapped to Java conditional semantics"),
    "PERFORM": _supported("PERFORM is mapped to Java method/control-flow semantics"),
    "READ": _supported("READ is mapped to deterministic file-input semantics"),
    "WRITE": _supported("WRITE is mapped to deterministic file-output semantics"),
    "OPEN": _supported("OPEN is mapped to file-resource semantics"),
    "CLOSE": _supported("CLOSE is mapped to file-resource semantics"),
    "START": _supported("START has an explicit IR mapping"),
    "REWRITE": _supported("REWRITE has an explicit IR mapping"),
    "DELETE": _supported("DELETE has an explicit IR mapping"),
    "STRING": _supported("STRING is mapped to Java string construction"),
    "UNSTRING": _partial("UNSTRING is supported only for the certified delimited subset"),
    "DISPLAY": _supported("DISPLAY is mapped to deterministic output semantics"),
    "STOP RUN": _supported("STOP RUN terminates generated execution"),
    "CALL": _supported("Static CALL has an explicit application dependency mapping"),
    "GO TO": _unsupported("GO TO has no semantic Java control-flow mapping"),
    "PERFORM TIMES": _unsupported("PERFORM TIMES/VARYING has no certified direct mapping"),
    "EVALUATE": _partial("EVALUATE is recognized but remains outside the certified transformation subset"),
    "EXEC CICS": _unsupported("EXEC CICS is outside the certified deterministic Java lane"),
    "EXEC SQL": _unsupported("EXEC SQL requires the separate DB2/SQL semantic lane"),
    "SORT": _unsupported("SORT is not implemented in the deterministic mapper"),
    "MERGE": _unsupported("MERGE is not implemented in the deterministic mapper"),
    "ACCEPT": _unsupported("ACCEPT is not implemented in the deterministic mapper"),
    "INITIALIZE": _unsupported("INITIALIZE is not implemented in the deterministic mapper"),
    "INSPECT": _unsupported("INSPECT is not implemented in the deterministic mapper"),
    "SEARCH": _unsupported("SEARCH is not implemented in the deterministic mapper"),
    "SET": _unsupported("SET semantics are not implemented in the deterministic mapper"),
    "ALTER": _unsupported("ALTER is outside the certified deterministic subset"),
    "NEXT SENTENCE": _unsupported("NEXT SENTENCE is not represented by the procedure IR"),
    "GOBACK": _unsupported("GOBACK is not represented by the procedure IR"),
    "SIZE ERROR": _unsupported("SIZE ERROR handling is not yet represented in the arithmetic IR"),
}


IR_TYPE_TO_CONSTRUCT: dict[str, str] = {
    AddStatement.__name__: "ADD",
    CallStatement.__name__: "CALL",
    CloseStatement.__name__: "CLOSE",
    ComputeStatement.__name__: "COMPUTE",
    DeleteStatement.__name__: "DELETE",
    DisplayStatement.__name__: "DISPLAY",
    DivideStatement.__name__: "DIVIDE",
    GoToStatement.__name__: "GO TO",
    IfStatement.__name__: "IF/ELSE",
    MoveStatement.__name__: "MOVE",
    MultiplyStatement.__name__: "MULTIPLY",
    OpenStatement.__name__: "OPEN",
    PerformStatement.__name__: "PERFORM",
    PerformTimesStatement.__name__: "PERFORM TIMES",
    ReadStatement.__name__: "READ",
    RewriteStatement.__name__: "REWRITE",
    StartStatement.__name__: "START",
    StopRunStatement.__name__: "STOP RUN",
    StringStatement.__name__: "STRING",
    SubtractStatement.__name__: "SUBTRACT",
    UnstringStatement.__name__: "UNSTRING",
    WriteStatement.__name__: "WRITE",
}


SUPPORTED_CONSTRUCTS = frozenset(
    key for key, entry in CONSTRUCT_REGISTRY.items()
    if entry.level is CapabilityLevel.SUPPORTED
)
PARTIAL_CONSTRUCTS = frozenset(
    key for key, entry in CONSTRUCT_REGISTRY.items()
    if entry.level is CapabilityLevel.PARTIAL
)
UNSUPPORTED_CONSTRUCTS = frozenset(
    key for key, entry in CONSTRUCT_REGISTRY.items()
    if entry.level is CapabilityLevel.UNSUPPORTED
)


_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EXEC CICS", re.compile(r"\bEXEC\s+CICS\b", re.IGNORECASE)),
    ("EXEC SQL", re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)),
    ("EVALUATE", re.compile(r"\bEVALUATE\b", re.IGNORECASE)),
    ("GO TO", re.compile(r"\bGO\s+TO\b|\bGOTO\b", re.IGNORECASE)),
    ("SORT", re.compile(r"\bSORT\b", re.IGNORECASE)),
    ("MERGE", re.compile(r"\bMERGE\b", re.IGNORECASE)),
    ("ACCEPT", re.compile(r"\bACCEPT\b", re.IGNORECASE)),
    ("INITIALIZE", re.compile(r"\bINITIALIZE\b", re.IGNORECASE)),
    ("INSPECT", re.compile(r"\bINSPECT\b", re.IGNORECASE)),
    ("SEARCH", re.compile(r"\bSEARCH(?:\s+ALL)?\b", re.IGNORECASE)),
    ("SET", re.compile(r"\bSET\b", re.IGNORECASE)),
    ("ALTER", re.compile(r"\bALTER\b", re.IGNORECASE)),
    ("NEXT SENTENCE", re.compile(r"\bNEXT\s+SENTENCE\b", re.IGNORECASE)),
    ("GOBACK", re.compile(r"\bGOBACK\b", re.IGNORECASE)),
    ("SIZE ERROR", re.compile(r"\b(?:ON\s+)?SIZE\s+ERROR\b", re.IGNORECASE)),
    ("PERFORM TIMES", re.compile(r"\bPERFORM\b[^.\n]*(?:\bTIMES\b|\bVARYING\b)", re.IGNORECASE)),
)


def _strip_literals_and_comments(source: str) -> str:
    """Remove comments and quoted literals before keyword scanning."""
    kept: list[str] = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("*") or stripped.startswith("/"):
            continue
        without_literals = re.sub(
            r"""'(?:''|[^'])*'|"(?:\\\"\\\"|[^"])*" """.strip(),
            " ",
            line,
        )
        kept.append(without_literals)
    return "\n".join(kept)


def scan_constructs(source: str, *, restrict_to_procedure: bool = True) -> set[str]:
    """Detect source-level constructs that need capability classification."""
    text = _strip_literals_and_comments(source)
    if restrict_to_procedure:
        match = re.search(r"\bPROCEDURE\s+DIVISION\b", text, re.IGNORECASE)
        if match:
            text = text[match.end():]

    found: set[str] = set()
    for key, pattern in _SOURCE_PATTERNS:
        if pattern.search(text):
            found.add(key)
    return found


_LEVEL_RANK = {
    CapabilityLevel.SUPPORTED: 0,
    CapabilityLevel.UNAVAILABLE: 1,
    CapabilityLevel.PARTIAL: 2,
    CapabilityLevel.UNKNOWN: 3,
    CapabilityLevel.UNSUPPORTED: 4,
}


def worst_level(
    levels: list[CapabilityLevel] | tuple[CapabilityLevel, ...],
) -> CapabilityLevel | None:
    """Return the most severe capability level, or None for no findings."""
    if not levels:
        return None
    return max(levels, key=lambda level: _LEVEL_RANK[level])


__all__ = [
    "CapabilityLevel",
    "ConstructCapability",
    "CONSTRUCT_REGISTRY",
    "IR_TYPE_TO_CONSTRUCT",
    "PARTIAL_CONSTRUCTS",
    "SUPPORTED_CONSTRUCTS",
    "UNSUPPORTED_CONSTRUCTS",
    "scan_constructs",
    "worst_level",
]

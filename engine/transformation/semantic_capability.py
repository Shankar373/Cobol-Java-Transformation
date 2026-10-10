"""Authoritative semantic capability registry for deterministic COBOL transformation.

The registry is consumed by the modernization capability analyzer.  Each entry
carries two levels:

* ``level`` — the verdict for an instance the parser actually produced (IR).
* ``effective_source_level`` — the verdict for an instance found only in COBOL
  source with no corresponding IR (the parser silently dropped it).  For a
  construct the chain can implement (``_supported``) this defaults to UNKNOWN
  so a dropped instance can never be reported as supported; helpers may lower
  it to UNSUPPORTED when absence of IR proves the mapper will never see it.

Some source constructs are legitimately *realised* by a different IR node
(EVALUATE is lowered to IfStatement; PERFORM ... TIMES/VARYING is parsed into
PerformStatement).  ``CONSTRUCT_IR_COVERAGE`` records those relations so the
analyzer skips a source finding when the realising IR is present instead of
mis-reporting the construct as unrepresented.
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
    ExitProgramStatement,
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


def _supported(
    evidence: str,
    *,
    source_only: CapabilityLevel = CapabilityLevel.UNKNOWN,
) -> ConstructCapability:
    return ConstructCapability(
        CapabilityLevel.SUPPORTED,
        evidence,
        source_only,
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
    "CLOSE": _supported(
        "CLOSE is mapped to file-resource semantics",
        # CobolParser constructs CloseStatement for the single-file subset.
        # A CLOSE in source with no CloseStatement IR was dropped (multi-file
        # CLOSE or unparsed form) and the mapper will never see it.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "START": _supported(
        "START has an explicit IR mapping",
        # CobolParser constructs StartStatement for the symbolic-operator
        # subset (=, >, >=, <, <=).  A source START with no IR was dropped.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "REWRITE": _supported(
        "REWRITE has an explicit IR mapping",
        # CobolParser constructs RewriteStatement for the deterministic
        # subset.  A source REWRITE with no IR was dropped.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "DELETE": _supported(
        "DELETE has an explicit IR mapping",
        # CobolParser constructs DeleteStatement for the deterministic
        # subset.  A source DELETE with no IR was dropped.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "INVALID KEY": _supported(
        "IR file nodes carry invalid_key_body and the mapper emits the "
        "branch",
        # CobolParser populates invalid_key_body for the deterministic file
        # subset (READ/WRITE/START/REWRITE/DELETE).  An INVALID KEY in source
        # with no InvalidKeyScope IR was dropped and behaves as unhandled.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "STRING": _supported("STRING is mapped to Java string construction"),
    "UNSTRING": _partial("UNSTRING is supported only for the certified delimited subset"),
    "DISPLAY": _supported("DISPLAY is mapped to deterministic output semantics"),
    "STOP RUN": _supported("STOP RUN terminates generated execution"),
    "EXIT PROGRAM": _supported(
        "EXIT PROGRAM is mapped to a Java return from the generated "
        "program body",
        # A source instance with no ExitProgramStatement means the parser
        # dropped it and no Java return is emitted for that exit.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "CALL": _supported("Static CALL has an explicit application dependency mapping"),
    "GO TO": _unsupported("GO TO has no semantic Java control-flow mapping"),
    "PERFORM TIMES": _supported(
        "PERFORM ... TIMES/VARYING parses into PerformStatement and is mapped "
        "to bounded Java loop semantics",
        # An instance present in source with no PerformStatement anywhere in
        # the program was dropped by the parser, so the mapper will never see
        # it — absence of IR proves this instance is not transformable.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "PERFORM TIMES IR": _unsupported(
        "PerformTimesStatement legacy IR node is not implemented by the "
        "deterministic mapper"
    ),
    "EVALUATE": _supported(
        "EVALUATE is lowered to IfStatement by CobolParser and mapped "
        "through IF/ELSE semantics",
        # An EVALUATE in source with no IfStatement in the program means the
        # lowering never ran for it; the mapper will never see it.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
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
    # USAGE clauses.  The numeric *value* path (arithmetic, DISPLAY text,
    # VALUE normalization) is certified, but the record-area *byte encoding*
    # of these usages (binary layout, packed sign overpunch) is not, so each
    # is honestly PARTIAL rather than silently treated as DISPLAY.  The
    # parser records the usage on ``DataItem.usage`` and emits a
    # PARTIAL_SUPPORT diagnostic so the narrowing is never silent.
    "COMP": _partial(
        "COMP (binary) value semantics are mapped; record-area byte encoding "
        "is not certified"
    ),
    "COMP-1": _partial(
        "COMP-1 (single float) value semantics are mapped; byte encoding is "
        "not certified"
    ),
    "COMP-2": _partial(
        "COMP-2 (double float) value semantics are mapped; byte encoding is "
        "not certified"
    ),
    "COMP-3": _partial(
        "COMP-3 (packed decimal) value semantics are mapped; packed sign/byte "
        "encoding is not certified"
    ),
    "COMP-5": _partial(
        "COMP-5 (native binary) value semantics are mapped; byte encoding is "
        "not certified"
    ),
}


# Declared USAGE synonym -> canonical registry token.  Collapsing synonyms
# here keeps ``DataItem.usage`` canonical so capability classification cannot
# drift between ``COMP``/``COMPUTATIONAL``/``BINARY`` spellings.
_USAGE_SYNONYMS: dict[str, str] = {
    "COMP": "COMP",
    "COMPUTATIONAL": "COMP",
    "BINARY": "COMP",
    "COMP-4": "COMP",
    "COMPUTATIONAL-4": "COMP",
    "COMP-1": "COMP-1",
    "COMPUTATIONAL-1": "COMP-1",
    "COMP-2": "COMP-2",
    "COMPUTATIONAL-2": "COMP-2",
    "COMP-3": "COMP-3",
    "COMPUTATIONAL-3": "COMP-3",
    "PACKED-DECIMAL": "COMP-3",
    "COMP-5": "COMP-5",
    "COMPUTATIONAL-5": "COMP-5",
}


def canonical_usage(token: str | None) -> str | None:
    """Return the canonical USAGE token, or None for DISPLAY/unrecognised.

    ``DISPLAY`` is the COBOL default and carries no encoding narrowing, so it
    canonicalises to ``None`` exactly like an absent clause.  An unrecognised
    non-default token is returned upper-cased so the caller can surface it
    explicitly instead of silently dropping it.
    """
    if token is None:
        return None
    normalised = token.strip().upper()
    if not normalised or normalised in ("DISPLAY", "DISPLAY-1"):
        return None
    return _USAGE_SYNONYMS.get(normalised, normalised)


# Canonical usage token -> registry key.  Consumers classify a data item by
# looking its ``usage`` up here; a token with no entry is not silently
# ignored (the analyzer reports it as PARTIAL).
USAGE_TO_CONSTRUCT: dict[str, str] = {
    "COMP": "COMP",
    "COMP-1": "COMP-1",
    "COMP-2": "COMP-2",
    "COMP-3": "COMP-3",
    "COMP-5": "COMP-5",
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
    PerformTimesStatement.__name__: "PERFORM TIMES IR",
    ReadStatement.__name__: "READ",
    RewriteStatement.__name__: "REWRITE",
    StartStatement.__name__: "START",
    StopRunStatement.__name__: "STOP RUN",
    ExitProgramStatement.__name__: "EXIT PROGRAM",
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


# COBOL words are hyphen-delimited: every pattern anchors on word boundaries
# that also refuse adjacent hyphens so that paragraph/file names such as
# SET-PARA, END-EVALUATE or SORT-AREA are never mistaken for the verb.
_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EXEC CICS", re.compile(r"(?<![\w-])EXEC\s+CICS(?![\w-])", re.IGNORECASE)),
    ("EXEC SQL", re.compile(r"(?<![\w-])EXEC\s+SQL(?![\w-])", re.IGNORECASE)),
    ("EVALUATE", re.compile(r"(?<![\w-])EVALUATE(?![\w-])", re.IGNORECASE)),
    ("GO TO", re.compile(r"(?<![\w-])GO\s+TO(?![\w-])|(?<![\w-])GOTO(?![\w-])", re.IGNORECASE)),
    ("SORT", re.compile(r"(?<![\w-])SORT(?![\w-])", re.IGNORECASE)),
    ("MERGE", re.compile(r"(?<![\w-])MERGE(?![\w-])", re.IGNORECASE)),
    ("ACCEPT", re.compile(r"(?<![\w-])ACCEPT(?![\w-])", re.IGNORECASE)),
    ("INITIALIZE", re.compile(r"(?<![\w-])INITIALIZE(?![\w-])", re.IGNORECASE)),
    ("INSPECT", re.compile(r"(?<![\w-])INSPECT(?![\w-])", re.IGNORECASE)),
    ("SEARCH", re.compile(r"(?<![\w-])SEARCH(?:\s+ALL)?(?![\w-])", re.IGNORECASE)),
    ("SET", re.compile(r"(?<![\w-])SET(?![\w-])", re.IGNORECASE)),
    ("ALTER", re.compile(r"(?<![\w-])ALTER(?![\w-])", re.IGNORECASE)),
    ("NEXT SENTENCE", re.compile(r"(?<![\w-])NEXT\s+SENTENCE(?![\w-])", re.IGNORECASE)),
    ("GOBACK", re.compile(r"(?<![\w-])GOBACK(?![\w-])", re.IGNORECASE)),
    ("SIZE ERROR", re.compile(r"(?<![\w-])(?:ON\s+)?SIZE\s+ERROR(?![\w-])", re.IGNORECASE)),
    ("PERFORM TIMES", re.compile(r"(?<![\w-])PERFORM\b[^.\n]*(?:\bTIMES\b|\bVARYING\b)(?![\w-])", re.IGNORECASE)),
    ("CLOSE", re.compile(r"(?<![\w-])CLOSE(?![\w-])", re.IGNORECASE)),
    ("START", re.compile(r"(?<![\w-])START(?![\w-])", re.IGNORECASE)),
    ("EXIT PROGRAM", re.compile(r"(?<![\w-])EXIT\s+PROGRAM(?![\w-])", re.IGNORECASE)),
    ("REWRITE", re.compile(r"(?<![\w-])REWRITE(?![\w-])", re.IGNORECASE)),
    ("DELETE", re.compile(r"(?<![\w-])DELETE(?![\w-])", re.IGNORECASE)),
    ("INVALID KEY", re.compile(r"(?<![\w-])INVALID\s+KEY(?![\w-])", re.IGNORECASE)),
    # USAGE clauses (data-division only; only reached when callers scan with
    # restrict_to_procedure=False, e.g. the copybook classifier).  Longest
    # alternatives first so COMP-3/COMP-5 are not shadowed by plain COMP.
    ("COMP-1", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-1|COMP-1)(?![\w-])", re.IGNORECASE)),
    ("COMP-2", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-2|COMP-2)(?![\w-])", re.IGNORECASE)),
    ("COMP-5", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-5|COMP-5)(?![\w-])", re.IGNORECASE)),
    ("COMP-3", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-3|PACKED-DECIMAL|COMP-3)(?![\w-])", re.IGNORECASE)),
    ("COMP", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-4|COMPUTATIONAL|COMP-4|BINARY|COMP)(?![\w-])", re.IGNORECASE)),
)


# Source constructs that the parser legitimately realises through a different
# IR node.  When the realising IR key is present in the program the source
# finding is redundant — the construct IS represented.  Granularity is
# program-level: coverage is claimed when the realising node exists anywhere
# in the parsed program.
CONSTRUCT_IR_COVERAGE: dict[str, tuple[str, ...]] = {
    "EVALUATE": ("IF/ELSE",),
    "PERFORM TIMES": ("PERFORM",),
    # Only the sentinel added by the capability walker when a statement
    # actually carries a non-empty invalid_key_body proves the clause was
    # represented; a bare ReadStatement/WriteStatement does not.
    "INVALID KEY": ("InvalidKeyScope",),
}


def ir_covers(source_key: str, ir_keys: set[str]) -> bool:
    """True when parsed IR contains a node that realises this source construct."""
    return any(key in ir_keys for key in CONSTRUCT_IR_COVERAGE.get(source_key, ()))


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
    "CONSTRUCT_IR_COVERAGE",
    "CONSTRUCT_REGISTRY",
    "IR_TYPE_TO_CONSTRUCT",
    "PARTIAL_CONSTRUCTS",
    "SUPPORTED_CONSTRUCTS",
    "UNSUPPORTED_CONSTRUCTS",
    "USAGE_TO_CONSTRUCT",
    "canonical_usage",
    "ir_covers",
    "scan_constructs",
    "worst_level",
]

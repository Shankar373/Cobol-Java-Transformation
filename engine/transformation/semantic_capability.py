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
    AcceptStatement,
    ExitProgramStatement,
    GobackStatement,
    InitializeStatement,
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
    SetConditionStatement,
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


def _partial(
    evidence: str,
    *,
    source_only: CapabilityLevel = CapabilityLevel.PARTIAL,
) -> ConstructCapability:
    return ConstructCapability(
        CapabilityLevel.PARTIAL,
        evidence,
        source_only,
    )


def _unsupported(evidence: str) -> ConstructCapability:
    return ConstructCapability(
        CapabilityLevel.UNSUPPORTED,
        evidence,
        CapabilityLevel.UNSUPPORTED,
    )


def _unknown(evidence: str) -> ConstructCapability:
    return ConstructCapability(
        CapabilityLevel.UNKNOWN,
        evidence,
        CapabilityLevel.UNKNOWN,
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
    "STRING": _supported(
        "STRING is mapped to Java string construction with COBOL write "
        "semantics: per-phrase DELIMITED BY truncation (SIZE, literal, "
        "SPACE), the delimiter excluded from the result, tail-preserving "
        "writes and WITH POINTER insert/advance. Identifier delimiters, "
        "ON OVERFLOW and VARYING IN fail closed with UNSUPPORTED_CONSTRUCT "
        "(BL-027, BL-029); the fixed-width receiver is truncated to its "
        "declared PIC width and the pointer follows the oracle-pinned "
        "boundary rule (writes and advances capped at W+1 inside 1..W+1, "
        "no-op outside) — byte-verified against GnuCOBOL 3.1.2 (BL-028)"
    ),
    "UNSTRING": _supported(
        "UNSTRING DELIMITED BY <literal> INTO targets is mapped to a Java "
        "String.split with per-receiver PIC-width padding/truncation; byte-"
        "identical to GnuCOBOL 3.1.2 for the certified subset "
        "(tests/integration/test_unstring_oracle_proof.py). WITH POINTER and "
        "TALLYING IN are now also implemented and oracle-proven. ON OVERFLOW, "
        "VARYING IN, DELIMITER IN, COUNT IN, ALL and multiple delimiters "
        "still fail closed with an UNSUPPORTED_CONSTRUCT diagnostic naming "
        "the clause (test_unstring_clause_diagnostics.py)",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
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
    # CALL parameter-passing modes are classified from the caller's USING
    # clause (CallStatement.passing_modes), not from the callee's PROCEDURE
    # DIVISION declaration.  BY REFERENCE keeps the CALL verdict and writes
    # back; BY CONTENT and BY VALUE are sync-in only.
    "BY CONTENT": _supported(
        "CALL ... USING BY CONTENT lowers to a positional sync-in with no "
        "write-back, so callee mutations never reach the caller. The shipped "
        "workload-by-content fixture and a mixed BY REFERENCE/BY CONTENT "
        "program are byte-identical to GnuCOBOL 3.1.2 "
        "(tests/integration/test_call_passing_mode_oracle_proof.py). Only "
        "plain data-item arguments are certified",
        # A BY CONTENT phrase in source with no parsed CallStatement means the
        # parser dropped the call; the mapper never sees the mode.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "BY VALUE": _partial(
        "CALL ... USING BY VALUE lowers to a positional sync-in with no "
        "write-back, but the mapping is NOT runtime-certified: GnuCOBOL 3.1.2 "
        "is the only available COBOL runtime and its BY VALUE implementation "
        "is unfinished (-Wunfinished); it passes garbage to the callee or "
        "aborts with SIGSEGV, so no oracle equivalence can be established "
        "(see tests/integration/test_call_passing_mode_oracle_proof.py)",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
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
    # IMS and IBM MQ support was added detection-first: no IR, no mapper, no
    # runtime integration, so absence of IR proves the mapper can never see
    # them.  The evidence text names the subsystem so capability verdicts say
    # *why* a program is blocked instead of only listing generic skipped
    # statements.  No equivalence claim: classification only.
    "EXEC DLI": _unsupported(
        "EXEC DLI (IMS) has no deterministic Java lane: no IR, no mapper "
        "and no IMS runtime; the block is classified UNSUPPORTED by "
        "detection, never transformed"
    ),
    "EXEC MQI": _unsupported(
        "EXEC MQI (IBM MQ) has no deterministic Java lane: no IR, no mapper "
        "and no MQ runtime; the block is classified UNSUPPORTED by "
        "detection, never transformed"
    ),
    "SORT": _unsupported("SORT is not implemented in the deterministic mapper"),
    "MERGE": _unsupported("MERGE is not implemented in the deterministic mapper"),
    "ACCEPT": _supported(
        "ACCEPT target reads a line from standard input into the field",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "INITIALIZE": _supported(
        "INITIALIZE sets each target field to its type default (spaces for "
        "alphanumeric, zero for numeric)",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "INSPECT": _unsupported("INSPECT is not implemented in the deterministic mapper"),
    "SEARCH": _unsupported("SEARCH is not implemented in the deterministic mapper"),
    "SET": _unsupported("SET semantics are not implemented in the deterministic mapper"),
    # ``SET <condition-name> TO TRUE`` is a separate, certified statement class:
    # the parser lowers it to SetConditionStatement and the mapper assigns the
    # conditional variable the first VALUE term.  All other SET forms (TO
    # FALSE, index arithmetic, pointer adjustment) stay under the generic
    # UNSUPPORTED ``SET`` key and fail closed.
    "SET CONDITION TO TRUE": _supported(
        "SET <condition-name> TO TRUE assigns the 88-level parent's first "
        "VALUE term; generated Java output is byte-identical to GnuCOBOL "
        "3.1.2 (tests/integration/test_structural_oracle_proof.py)",
        # A certified SET clause in source with no SetConditionStatement was
        # dropped by the parser, so the mapper can never see it.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "ALTER": _unsupported("ALTER is outside the certified deterministic subset"),
    "NEXT SENTENCE": _unsupported("NEXT SENTENCE is not represented by the procedure IR"),
    "GOBACK": _supported(
        "GOBACK terminates the generated program and returns to the caller, "
        "lowered to a Java return from the current method",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "SIZE ERROR": _unsupported("SIZE ERROR handling is not yet represented in the arithmetic IR"),
    # External utilities and system services are detection-first classified —
    # the first step of the verification ladder (Detected -> Classified) only.
    # No IR, no mapper, no utility runner, no equivalence claim: the evidence
    # text names the construct so capability verdicts say *why* a program is
    # blocked.  The four VSAM SELECT keys below are NOT in this group: the
    # parser records them on FileDefinition and the mapper lowers them into the
    # certified indexed/relative subset (SUPPORTED for that subset, not
    # detection-only).
    "RELEASE": _unsupported(
        "RELEASE (SORT output step) has no deterministic Java lane: no IR, "
        "no mapper and no SORT utility runtime; classified UNSUPPORTED by "
        "detection, never transformed"
    ),
    "IDCAMS": _unsupported(
        "IDCAMS is an external system utility with no deterministic Java "
        "lane: no IR, no mapper and no utility runner; classified "
        "UNSUPPORTED by detection, never transformed"
    ),
    "ORGANIZATION INDEXED": _supported(
        "SELECT ... ORGANIZATION IS INDEXED parses to "
        "FileDefinition.organization and the mapper lowers keyed OPEN/WRITE/"
        "READ/REWRITE/DELETE/START to CobolFileIo indexed access. The shipped "
        "workload-indexed-file fixture produces byte-identical stdout and FILE "
        "STATUS values to GnuCOBOL 3.1.2 "
        "(tests/integration/test_indexed_relative_oracle_proof.py). Certified "
        "subset: primary RECORD KEY starting at offset 0, ACCESS MODE DYNAMIC. "
        "The on-disk index is an emulated side file, not VSAM; file-image "
        "equivalence is not claimed. Behavioral equivalence (stdout, FILE "
        "STATUS, exit code) is PROVEN for the certified subset.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "ORGANIZATION RELATIVE": _supported(
        "SELECT ... ORGANIZATION IS RELATIVE parses to "
        "FileDefinition.organization and the mapper lowers RRN-addressed "
        "OPEN/WRITE/READ/REWRITE/DELETE/START to CobolFileIo relative access. "
        "The shipped workload-relative-file fixture produces byte-identical "
        "stdout and FILE STATUS values to GnuCOBOL 3.1.2 "
        "(tests/integration/test_indexed_relative_oracle_proof.py). The record "
        "store is emulated, not a VSAM ESDS; file-image equivalence is not "
        "claimed. Behavioral equivalence (stdout, FILE STATUS, exit code) is "
        "PROVEN for the certified subset.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "ACCESS DYNAMIC": _supported(
        "ACCESS MODE IS DYNAMIC parses to FileAccessMode.DYNAMIC and is "
        "lowered for the certified indexed/relative fixtures (keyed and "
        "sequential access in one run unit, byte-identical to GnuCOBOL 3.1.2). "
        "ACCESS MODE RANDOM has no registry key and no dedicated oracle proof. "
        "Behavioral equivalence is PROVEN for the certified subset.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "RECORD KEY": _supported(
        "RECORD KEY IS parses to FileDefinition.record_key and supplies the "
        "key length for keyed OPEN/WRITE/READ/REWRITE/DELETE/START. Certified "
        "subset: a primary key beginning at offset 0 in the record area "
        "(byte-identical to GnuCOBOL 3.1.2 in both shipped fixtures). "
        "ALTERNATE RECORD KEY is parsed but never lowered to an alternate "
        "index and is reported UNSUPPORTED per instance. Behavioral "
        "equivalence is PROVEN for the certified subset.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "ROUNDED": _supported(
        "ROUNDED reaches the generated Java as a HALF_UP rounding mode on the "
        "receiving item (default stays DOWN truncation)"
    ),
    # LOCAL-STORAGE SECTION and the REPLACE compiler directive are recognised
    # by the universality requirements but are not implemented by this lane:
    # there is no IR node, no mapper, and no runtime semantics for either.  A
    # program that uses them would otherwise be reported as fully transformable
    # while its per-invocation storage or its text-substitution never happens.
    # Classified UNSUPPORTED by detection so the capability verdict names the
    # construct and the plan stays blocked instead of silently dropping it.
    "LOCAL-STORAGE": _unsupported(
        "LOCAL-STORAGE SECTION (per-invocation storage) has no deterministic "
        "Java lane: no IR node, no mapper and no re-entrant runtime semantics; "
        "classified UNSUPPORTED by detection, never transformed"
    ),
    "REPLACE": _supported(
        "REPLACE ==old== BY ==new== is applied as a source preprocessor before "
        "parsing; only pseudo-text operands are supported",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    # Figurative constants (ZERO / SPACES / QUOTES / LOW-VALUE / HIGH-VALUE /
    # ALL "x").  These are reserved *words* with a fixed value.  They used to
    # parse into a FieldReference named after the word, which mapped to an
    # undeclared Java identifier (`A = ZERO;`) — non-compiling output, no
    # diagnostic, and a false SUPPORTED verdict.  The parser now emits
    # ir.FigurativeConstant and the mapper expands it to the correct fill
    # across the receiving item's declared width.
    "FIGURATIVE CONSTANT": _supported(
        "Figurative constants are parsed into FigurativeConstant and mapped to "
        "the receiving item's width (whole-field fill for MOVE, whole-field "
        "equality for comparison).  BL-030: the fill is materialized at the "
        "declared PIC width for both MOVE and VALUE — ``ALL <pattern>`` is "
        "replicated across the receiver and truncated at the final copy, "
        "``ALL <figurative word>`` collapses onto the word, and a numeric "
        "figurative on an alphanumeric receiver stores its character form "
        "('00000' for ZEROS) — byte-verified against the GnuCOBOL 3.1.2 "
        "oracle, so no COBOL spelling ever leaks into generated Java"
    ),
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
    # REDEFINES / OCCURS / 88-level: the parser produces IR (DataItem.redefines /
    # occurs / level 88).  All three now have deterministic lowering for a
    # certified subset, proven against GnuCOBOL 3.1.2; everything outside that
    # subset fails closed with UNSUPPORTED_CONSTRUCT.
    "REDEFINES": _partial(
        "Elementary alphanumeric DISPLAY views over an elementary alphanumeric "
        "base are lowered as a shared byte string with synchronised views and "
        "are byte-identical to GnuCOBOL 3.1.2 "
        "(tests/integration/test_structural_oracle_proof.py). Numeric views, "
        "groups, OCCURS, chained REDEFINES, aliases wider than the base and "
        "non-MOVE writers are reported UNSUPPORTED because GnuCOBOL's numeric "
        "reinterpretation of overwritten bytes is compiler-specific undefined "
        "data, not a COBOL semantic"
    ),
    "OCCURS": _partial(
        "Fixed-size OCCURS n TIMES lowers to Java arrays with 1-based to "
        "0-based subscripts; the shipped table fixture is byte-identical to "
        "GnuCOBOL 3.1.2 (tests/integration/test_structural_oracle_proof.py). "
        "OCCURS DEPENDING ON fails closed with UNSUPPORTED_CONSTRUCT, and "
        "whole-record references to an occurring group are outside the "
        "certified subset"
    ),
    "88-LEVEL": _supported(
        "88-level condition names lower to comparisons on their parent "
        "(numeric value, THRU range, content equality) in IF, EVALUATE and "
        "PERFORM UNTIL; the shipped condition-name fixture is byte-identical "
        "to GnuCOBOL 3.1.2 (tests/integration/test_structural_oracle_proof.py). "
        "VALUE forms with no certified lowering (bare identifiers, missing "
        "VALUE) are reported UNSUPPORTED by the analyzer",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
}

# NOTE — CALL passing modes are certified asymmetrically on purpose.
#
# BY CONTENT is SUPPORTED because the shipped fixture and a mixed-mode program
# reproduce GnuCOBOL 3.1.2 stdout byte for byte (caller unchanged, callee copy
# mutated locally).  BY VALUE stays PARTIAL: the mapper implements the required
# sync-in / no-write-back behaviour, but the only available COBOL runtime
# (GnuCOBOL 3.1.2) declares its BY VALUE handling unfinished (-Wunfinished) and
# either passes garbage or aborts with SIGSEGV, so no oracle proof is possible.
# A PARTIAL verdict is a bounded claim, never a SUPPORTED one; the analyzer also
# classifies an unparsed source phrase as UNSUPPORTED through source_only.


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
    SetConditionStatement.__name__: "SET CONDITION TO TRUE",
    StartStatement.__name__: "START",
    StopRunStatement.__name__: "STOP RUN",
    ExitProgramStatement.__name__: "EXIT PROGRAM",
    AcceptStatement.__name__: "ACCEPT",
    GobackStatement.__name__: "GOBACK",
    InitializeStatement.__name__: "INITIALIZE",
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
    # IMS and IBM MQ detection — classified by detection only, never
    # transformed.  Same word-boundary discipline as EXEC CICS/EXEC SQL so
    # identifiers such as ``WS-EXEC-MQI`` or verbs like ``EXECUTE`` can
    # never match.
    ("EXEC DLI", re.compile(r"(?<![\w-])EXEC\s+DLI(?![\w-])", re.IGNORECASE)),
    ("EXEC MQI", re.compile(r"(?<![\w-])EXEC\s+MQI(?![\w-])", re.IGNORECASE)),
    ("EVALUATE", re.compile(r"(?<![\w-])EVALUATE(?![\w-])", re.IGNORECASE)),
    ("GO TO", re.compile(r"(?<![\w-])GO\s+TO(?![\w-])|(?<![\w-])GOTO(?![\w-])", re.IGNORECASE)),
    ("SORT", re.compile(r"(?<![\w-])SORT(?![\w-])", re.IGNORECASE)),
    ("MERGE", re.compile(r"(?<![\w-])MERGE(?![\w-])", re.IGNORECASE)),
    # External utilities / system services — detection-first, same
    # word-boundary discipline so identifiers such as
    # WS-RELEASE-CODE or WS-IDCAMS-COUNT can never match.
    ("RELEASE", re.compile(r"(?<![\w-])RELEASE(?![\w-])", re.IGNORECASE)),
    ("IDCAMS", re.compile(r"(?<![\w-])IDCAMS(?![\w-])", re.IGNORECASE)),
    ("ACCEPT", re.compile(r"(?<![\w-])ACCEPT(?![\w-])", re.IGNORECASE)),
    ("INITIALIZE", re.compile(r"(?<![\w-])INITIALIZE(?![\w-])", re.IGNORECASE)),
    ("INSPECT", re.compile(r"(?<![\w-])INSPECT(?![\w-])", re.IGNORECASE)),
    ("SEARCH", re.compile(r"(?<![\w-])SEARCH(?:\s+ALL)?(?![\w-])", re.IGNORECASE)),
    # ``SET <condition-name> TO TRUE`` has its own certified key; the generic
    # SET pattern must not shadow it, or every certified level-88 assignment
    # would also be reported UNSUPPORTED.
    ("SET CONDITION TO TRUE", re.compile(
        r"(?<![\w-])SET\s+[A-Z0-9][\w-]*\s+TO\s+TRUE(?![\w-])", re.IGNORECASE,
    )),
    ("SET", re.compile(
        r"(?<![\w-])SET(?!\s+[A-Z0-9][\w-]*\s+TO\s+TRUE(?![\w-]))(?![\w-])",
        re.IGNORECASE,
    )),
    ("ALTER", re.compile(r"(?<![\w-])ALTER(?![\w-])", re.IGNORECASE)),
    ("NEXT SENTENCE", re.compile(r"(?<![\w-])NEXT\s+SENTENCE(?![\w-])", re.IGNORECASE)),
    ("GOBACK", re.compile(r"(?<![\w-])GOBACK(?![\w-])", re.IGNORECASE)),
    ("SIZE ERROR", re.compile(r"(?<![\w-])(?:ON\s+)?SIZE\s+ERROR(?![\w-])", re.IGNORECASE)),
    # CALL parameter-passing modes.  Only the USING-clause spelling matches:
    # data names such as WS-BY-VALUE are protected by the hyphen lookarounds.
    ("BY CONTENT", re.compile(r"(?<![\w-])BY\s+CONTENT(?![\w-])", re.IGNORECASE)),
    ("BY VALUE", re.compile(r"(?<![\w-])BY\s+VALUE(?![\w-])", re.IGNORECASE)),
    ("PERFORM TIMES", re.compile(r"(?<![\w-])PERFORM\b[^.\n]*(?:\bTIMES\b|\bVARYING\b)(?![\w-])", re.IGNORECASE)),
    ("CLOSE", re.compile(r"(?<![\w-])CLOSE(?![\w-])", re.IGNORECASE)),
    ("START", re.compile(r"(?<![\w-])START(?![\w-])", re.IGNORECASE)),
    ("EXIT PROGRAM", re.compile(r"(?<![\w-])EXIT\s+PROGRAM(?![\w-])", re.IGNORECASE)),
    ("REWRITE", re.compile(r"(?<![\w-])REWRITE(?![\w-])", re.IGNORECASE)),
    ("DELETE", re.compile(r"(?<![\w-])DELETE(?![\w-])", re.IGNORECASE)),
    ("INVALID KEY", re.compile(r"(?<![\w-])INVALID\s+KEY(?![\w-])", re.IGNORECASE)),
    # VSAM specifics in FILE-CONTROL.  These sit in
    # the ENVIRONMENT DIVISION, so the analyzer's pre-procedure data door
    # (restrict_to_procedure=False on the source-before-PROCEDURE slice)
    # reaches them; the word-boundary and optional-IS forms mirror COBOL
    # phrase flexibility.
    ("ORGANIZATION INDEXED", re.compile(
        r"(?<![\w-])ORGANIZATION\s+(?:IS\s+)?INDEXED(?![\w-])", re.IGNORECASE,
    )),
    ("ORGANIZATION RELATIVE", re.compile(
        r"(?<![\w-])ORGANIZATION\s+(?:IS\s+)?RELATIVE(?![\w-])", re.IGNORECASE,
    )),
    ("ACCESS DYNAMIC", re.compile(
        r"(?<![\w-])ACCESS\s+(?:MODE\s+(?:IS\s+)?)?DYNAMIC(?![\w-])", re.IGNORECASE,
    )),
    ("RECORD KEY", re.compile(
        r"(?<![\w-])(?:ALTERNATE\s+)?RECORD\s+KEY(?![\w-])", re.IGNORECASE,
    )),
    ("ROUNDED", re.compile(r"(?<![\w-])ROUNDED(?![\w-])", re.IGNORECASE)),
    # Figurative constants.  Word boundaries also refuse adjacent hyphens so a
    # field such as HIGH-VALUE-CODE or ZERO-COUNT is never read as the
    # reserved word.  Restricted to the procedure division by the caller's
    # default restrict_to_procedure=True, because `VALUE SPACES` in a data
    # description is an initializer the mapper already normalizes.
    ("FIGURATIVE CONSTANT", re.compile(
        r"(?<![\w-])(?:ALL\s+(?:\"[^\"]{1}\"|'[^']{1}')"
        r"|ZEROES|ZEROS|ZERO-ZERO-ZERO|ZERO|SPACES|SPACE|QUOTES|QUOTE"
        r"|LOW-VALUES|LOW-VALUE|HIGH-VALUES|HIGH-VALUE)(?![\w-])",
        re.IGNORECASE,
    )),
    # USAGE clauses (data-division only; only reached when callers scan with
    # restrict_to_procedure=False, e.g. the copybook classifier).  Longest
    # alternatives first so COMP-3/COMP-5 are not shadowed by plain COMP.
    ("COMP-1", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-1|COMP-1)(?![\w-])", re.IGNORECASE)),
    ("COMP-2", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-2|COMP-2)(?![\w-])", re.IGNORECASE)),
    ("COMP-5", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-5|COMP-5)(?![\w-])", re.IGNORECASE)),
    ("COMP-3", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-3|PACKED-DECIMAL|COMP-3)(?![\w-])", re.IGNORECASE)),
    ("COMP", re.compile(r"(?<![\w-])(?:COMPUTATIONAL-4|COMPUTATIONAL|COMP-4|BINARY|COMP)(?![\w-])", re.IGNORECASE)),
    # Data-division constructs (only reached when callers scan with
    # restrict_to_procedure=False, e.g. the copybook classifier).
    ("REDEFINES", re.compile(r"(?<![\w-])REDEFINES(?![\w-])", re.IGNORECASE)),
    ("OCCURS", re.compile(r"(?<![\w-])OCCURS(?![\w-])", re.IGNORECASE)),
    ("88-LEVEL", re.compile(r"(?<![\w-])88\s+[A-Z0-9][\w-]*\s+(?:VALUE|THRU|THROUGH)(?![\w-])", re.IGNORECASE)),
    # LOCAL-STORAGE SECTION and the REPLACE compiler directive are recognised
    # COBOL constructs the lane does not implement.  The lookarounds refuse
    # adjacent hyphens/word characters so data names such as
    # WS-LOCAL-STORAGE-FLAG or WS-REPLACE-COUNT are never mistaken for the
    # constructs, and the REPLACE pattern cannot match COPY ... REPLACING
    # (that is a different construct handled by the copybook lane).  Both sit
    # before the PROCEDURE DIVISION, so they surface via the
    # restrict_to_procedure=False pre-procedure scan.
    ("LOCAL-STORAGE", re.compile(r"(?<![\w-])LOCAL-STORAGE(?![\w-])", re.IGNORECASE)),
    ("REPLACE", re.compile(r"(?<![\w-])REPLACE(?![\w-])", re.IGNORECASE)),
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

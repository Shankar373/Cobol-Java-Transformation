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
    ExecSqlStatement,
    InspectStatement,
    SortStatement,
    SetIndexStatement,
    SearchStatement,
    ExitPerformStatement,
    ExitProgramStatement,
    GobackStatement,
    InitializeStatement,
    GoToStatement,
    IfStatement,
    MoveStatement,
    MultiplyStatement,
    OpenStatement,
    PerformStatement,
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
        "(tests/integration/test_unstring_oracle_proof.py). WITH POINTER, "
        "TALLYING IN, ON OVERFLOW, VARYING IN, DELIMITER IN, COUNT IN, ALL "
        "and multiple delimiters fail closed with an UNSUPPORTED_CONSTRUCT "
        "diagnostic naming the clause (test_unstring_clause_diagnostics.py; "
        "re-probed against GnuCOBOL 2026-11-02: POINTER/TALLYING generation "
        "is refused, never approximated)",
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
    "GO TO": _supported(
        "GO TO paragraph-name in a program without LINKAGE or EXIT PROGRAM: paragraphs run through the CobolFlow "
        "scheduler (fall-through, GO TO re-dispatch, STOP RUN / GOBACK end the run unit); GO TO inside a plain "
        "PERFORM first THRU last range must land inside that range. Output equals GnuCOBOL 3.1.2 "
        "(tests/integration/test_goto_oracle.py). GO TO DEPENDING ON, altered GO TO, a jump out of a PERFORM range, "
        "a paragraph with a GO TO under a simple/TIMES/UNTIL/VARYING PERFORM and called programs fail closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "PERFORM TIMES": _supported(
        "PERFORM ... TIMES/VARYING parses into PerformStatement and is mapped "
        "to bounded Java loop semantics",
        # An instance present in source with no PerformStatement anywhere in
        # the program was dropped by the parser, so the mapper will never see
        # it — absence of IR proves this instance is not transformable.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "EVALUATE": _supported(
        "EVALUATE is lowered to IfStatement by CobolParser and mapped "
        "through IF/ELSE semantics",
        # An EVALUATE in source with no IfStatement in the program means the
        # lowering never ran for it; the mapper will never see it.
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "EXEC CICS": _unsupported("EXEC CICS is outside the certified deterministic Java lane"),
    "EXEC SQL": _supported(
        "EXEC SQL on a PostgreSQL target through JDBC: CONNECT :user IDENTIFIED BY :password "
        "USING :database, DISCONNECT, singleton SELECT ... INTO, INSERT/UPDATE/DELETE, "
        "COMMIT/ROLLBACK and DECLARE/OPEN/FETCH/CLOSE cursors, with elementary DISPLAY host "
        "variables (PIC X, PIC 9, PIC S9(i)V9(s)) and SQLCODE/SQLSTATE; SQLCODE 0/100, row "
        "effects and database state equal the OCESQL v1.4 + PostgreSQL 14 reference "
        "(tests/integration/test_sql_jdbc_oracle.py). Not DB2: no DB2 subsystem is available, "
        "the reference reports its own error SQLCODEs and zero-row UPDATE/DELETE is SQLCODE 0. "
        "Indicators, WHENEVER, dynamic SQL, CALL, WITH HOLD, untranslatable DB2 syntax and "
        "other host variables fail closed with an unresolvable symbol.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
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
        "detection, never transformed. Note: EXEC MQI is not IBM-documented "
        "syntax - real MQ programs use CALL 'MQxxx' (see CALL MQI)"
    ),
    # The real IBM call forms (roadmap unit 2). Detection looks at the CALL
    # target literal, which the literal-stripping scan cannot see; see
    # engine/transformation/subsystem_calls.py.
    "CALL DLI": _unsupported(
        "CALL 'CBLTDLI'/'AIBTDLI'/'CEETDLI'/'PLITDLI' (IMS DL/I) has no "
        "deterministic Java lane: no IR, no mapper and no IMS runtime; the "
        "call is classified UNSUPPORTED by detection, never transformed"
    ),
    "CALL MQI": _unsupported(
        "CALL 'MQCONN'/'MQOPEN'/'MQGET'/'MQPUT'... (IBM MQ) has no "
        "deterministic Java lane: no IR, no mapper and no MQ runtime; the "
        "call is classified UNSUPPORTED by detection, never transformed"
    ),
    "SORT": _supported(
        "SORT or MERGE sd ON ASCENDING|DESCENDING KEY k... [WITH DUPLICATES IN ORDER] USING f... GIVING g "
        "between LINE SEQUENTIAL files of one fixed record length (several USING files are concatenated in order, "
        "MERGE needs two or more), keys elementary alphanumeric or unsigned numeric "
        "DISPLAY items of the SD record, lowered to CobolSort.run (stable sort, ASCII order, a missing USING "
        "file is an empty input). Output equals GnuCOBOL 3.1.2 (tests/integration/test_sort_oracle.py). "
        "INPUT/OUTPUT PROCEDURE, several USING/GIVING files, COLLATING SEQUENCE, record-sequential files, "
        "signed or binary keys fail closed with an unresolvable method name.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "MERGE": _supported(
        "MERGE sd ON ASCENDING|DESCENDING KEY k... USING f1 f2... GIVING g, the same certified subset as SORT "
        "(file_to_file): the USING files are concatenated in the order written and sorted stably, which is what "
        "GnuCOBOL 3.1.2 does even for inputs that are not in key order (tests/integration/test_sort_oracle.py). "
        "Procedures, several GIVING files, COLLATING SEQUENCE, record-sequential files and signed or binary keys "
        "fail closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "ACCEPT": _supported(
        "ACCEPT <field> [FROM CONSOLE|STDIN|SYSIN] consumes one whole "
        "standard-input line per statement through a shared reader: "
        "PIC X(n) receives the first n characters space-padded (EOF: n "
        "spaces); unsigned PIC 9(n) and 9(i)V9(s), i+s <= 18, receive "
        "GnuCOBOL's alphanumeric-to-numeric-display move of the first "
        "i+s bytes (leading spaces and one sign skipped, integer digits "
        "right-aligned, spaces and ',' ignored, one '.' starts the "
        "decimals, a bad character before the field is full zeroes it; "
        "EOF: zero). Byte-identical to GnuCOBOL 3.1.2, including a "
        "240-line seeded fuzz (tests/integration/test_accept_oracle_proof"
        ".py). Other FROM devices (DATE/TIME/DAY/COMMAND-LINE/...), "
        "signed, non-DISPLAY, table, group and unknown targets fail "
        "closed with an unresolvable symbol.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "INITIALIZE": _supported(
        "INITIALIZE sets each target field to its type default (spaces for "
        "alphanumeric, zero for numeric)",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "INSPECT": _supported(
        "INSPECT <alphanumeric field> TALLYING <counter> FOR CHARACTERS | ALL lit | "
        "LEADING lit, REPLACING CHARACTERS | ALL | LEADING | FIRST lit BY lit, and "
        "CONVERTING lit TO lit, each with optional BEFORE/AFTER INITIAL lit, on an "
        "elementary DISPLAY PIC X target (counter: unsigned integer DISPLAY, at most 9 "
        "digits). Literal operands only; phrases apply in source order with marked "
        "positions, as the oracle does (tests/integration/test_inspect_oracle.py). "
        "Data-name operands, TRAILING, hex/ALL/HIGH-VALUE/QUOTE operands, a combined "
        "TALLYING ... REPLACING, several counters, group/table/numeric targets fail closed "
        "with an unresolvable symbol.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "SEARCH": _supported(
        "Linear SEARCH table [VARYING item] [AT END ...] WHEN cond ... [END-SEARCH] over a one-dimensional "
        "DISPLAY elementary OCCURS table with INDEXED BY: starts at the first index as it stands, tests the WHEN "
        "conditions in order, leaves the index on the match or at n + 1 with AT END, goes straight to AT END when "
        "the index is already past n, and VARYING an integer item assigns it the index value after each advance. "
        "SEARCH ALL table [AT END ...] WHEN table(idx) = literal|item on a table declared ASCENDING|DESCENDING KEY IS "
        "itself is a binary search (mid = (lo + hi) / 2 over 1..n; the index is left on the match, or on the last "
        "element probed with AT END, also for a table out of key order). Output equals GnuCOBOL 3.1.2 "
        "(tests/integration/test_search_oracle.py). VARYING an index, VARYING with SEARCH ALL, other SEARCH ALL "
        "conditions (several WHENs, AND, ranges), group or non-DISPLAY tables, an index below 1 and a statement "
        "with no WHEN fail closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "EXPONENTIATION": _supported(
        "COMPUTE with ** over integer and decimal operands: right-associative, tighter than * and /, looser than a unary "
        "sign (-2 ** 2 is 4, 2 ** 3 ** 2 is 512), evaluated exactly in BigDecimal (pow) for a non-negative integer "
        "exponent (digit literal, unsigned integer item, + * ** of those) and then truncated, ROUNDED or size-checked by the "
        "receiver like any COMPUTE; equal to GnuCOBOL 3.1.2 (tests/integration/test_power_oracle.py). Negative exponents "
        "are refused because GnuCOBOL 3.1.2 returns unstable values for them (2 ** -1 gave 0.5 in one program and 4.00 in "
        "another), fractional exponents because it uses floating-point pow; ** outside an arithmetic receiver (a "
        "condition, MOVE) fails closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "INTRINSIC FUNCTIONS": _supported(
        "FUNCTION UPPER-CASE / LOWER-CASE / REVERSE / TRIM [LEADING | TRAILING] / LENGTH over a quoted literal, a plain "
        "alphanumeric DISPLAY item or a reference modification, as a DISPLAY operand or a MOVE sender (into an "
        "alphanumeric receiver; LENGTH also into a numeric one); equal to GnuCOBOL 3.1.2 "
        "(tests/integration/test_intrinsic_oracle.py): TRIM of all spaces is empty, LENGTH of a plain item or literal "
        "displays unpadded and of a reference modification as nine digits. Every other function, argument or context "
        "(IF, COMPUTE, EVALUATE, numeric arguments, group items) fails closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "QUALIFIED NAMES": _supported(
        "A data name declared under several groups (working storage, linkage, file records) with references qualified "
        "by OF / IN (A OF G, A IN S OF G, partial chains): each declaration gets a unique deterministic name "
        "(A-OF-S-OF-G) and each qualified reference is resolved against the declared ancestor chains; equal to GnuCOBOL "
        "3.1.2 (tests/integration/test_qualified_oracle.py). An unqualified reference to a duplicated name, a "
        "qualification that matches no item or several, and a duplicated name in a REDEFINES / DEPENDING ON clause "
        "fail closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "EVALUATE ALSO": _supported(
        "EVALUATE a ALSO b [ALSO c] with WHEN x ALSO y [ALSO z] (a value, a THRU range or ANY per subject; TRUE as a "
        "subject with a condition as its object), stacked WHEN clauses sharing one statement list, and WHEN OTHER; "
        "equal to GnuCOBOL 3.1.2 (tests/integration/test_evaluate_oracle.py). A WHEN with a different number of "
        "objects than subjects, EVALUATE FALSE and a NOT object fail closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "PERFORM VARYING AFTER": _supported(
        "PERFORM VARYING a FROM x BY y UNTIL c AFTER b FROM ... AFTER d FROM ... (up to any depth of integer PIC 9(1..9) "
        "control items, inline or PERFORM paragraph), TEST BEFORE and WITH TEST AFTER, also for a single VARYING item. "
        "Initialisation pinned against GnuCOBOL 3.1.2 (tests/integration/test_varying_oracle.py): the first two items are "
        "initialised at the start, every deeper item at the start of each iteration of the level above (also when the next "
        "level then runs zero times), a level's step initialises only the next item, so items leave the loop with their "
        "FROM values and a dependent start value is fresh in every iteration; TEST AFTER runs the body, tests, then steps. "
        "PERFORM p1 THRU p2 VARYING, decimal or subscripted control items and EXIT PERFORM inside an AFTER chain fail "
        "closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "REFERENCE MODIFICATION": _supported(
        "name(start:length) and name(start:) on a plain elementary alphanumeric item, or on the digits of an unsigned "
        "integer DISPLAY item, with start / length an integer literal, an unsigned integer item or item +/- literal: "
        "a MOVE sender (padded or truncated like any alphanumeric value), a MOVE receiver (only those characters change; "
        "literal, item, reference, SPACES, ZEROS or ALL literal as sender), a DISPLAY operand and an operand of an "
        "alphanumeric relation in IF / WHEN / UNTIL (the shorter operand is padded with spaces). Output equals GnuCOBOL "
        "3.1.2 (tests/integration/test_refmod_oracle.py). A reference outside the item has no defined COBOL meaning "
        "(GnuCOBOL reads the adjacent storage) and the generated Java throws IllegalStateException; ADD, COMPUTE, "
        "STRING, INSPECT and every other statement, numeric or signed or decimal receivers and bases, subscripted bases "
        "and other start / length expressions fail closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "EXIT PERFORM": _supported(
        "EXIT PERFORM directly inside an inline PERFORM (UNTIL, TIMES, VARYING or a plain inline body) leaves that "
        "loop (Java break), also from nested IF / EVALUATE; DISPLAY ... WITH NO ADVANCING and CONTINUE (as a "
        "statement or inside IF / EVALUATE arms) behave as in GnuCOBOL 3.1.2 "
        "(tests/integration/test_small_statements_oracle.py). EXIT PERFORM outside an inline PERFORM or inside a "
        "SEARCH, and EXIT PERFORM CYCLE, fail closed.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
    "SET INDEX": _supported(
        "SET idx... TO integer | idx | integer-item, SET idx UP BY / DOWN BY integer | integer-item, and SET "
        "integer-item TO idx on OCCURS ... INDEXED BY indexes (occurrence numbers kept as int, Java declared "
        "per index); equal to GnuCOBOL 3.1.2 (tests/integration/test_search_oracle.py). Expressions and the other "
        "SET forms stay refused.",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
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
    "SIZE ERROR": _supported(
        "[NOT] ON SIZE ERROR on ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE is parsed into "
        "the arithmetic IR bodies; a zero divisor or a result needing more "
        "integer digits than the receiver leaves it unchanged and runs the "
        "SIZE ERROR body (GnuCOBOL 3.1.2, tests/test_size_error.py).  A phrase "
        "the parser did not attach to a statement is source-only and refused",
        source_only=CapabilityLevel.UNSUPPORTED,
    ),
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
        "ACCESS MODE RANDOM is certified by the analyzer gate (no registry key) "
        "and oracle-proven in tests/integration/test_keyed_random_oracle.py; "
        "SEQUENTIAL stays refused. "
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
    # PARTIAL, not SUPPORTED (Phase 5 certification, 2026-11-02): no GnuCOBOL
    # proof exists, and a GnuCOBOL probe with two pseudo-text pairs
    # (tests/data/phase5/REPL.cob) failed generation - only the first pair
    # was applied. Generation fails closed; the claim must not exceed that.
    "REPLACE": _partial(
        "REPLACE ==old== BY ==new== is applied as a source preprocessor before "
        "parsing (pseudo-text operands only); no GnuCOBOL proof, and a "
        "two-pair REPLACE fails generation (only the first pair is applied)",
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
        "COMP (binary) value semantics are mapped; the record-area bytes (big-endian, 1/2/4/8 bytes for 1-2/3-4/5-9/"
        "10-18 digits) are certified only for the leaves of a RECORD SEQUENTIAL or INDEXED file record inside "
        "engine/transformation/binary_record.py (GnuCOBOL 3.1.2: tests/integration/test_binary_record_oracle.py); "
        "anywhere else the byte encoding is not certified"
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
        "COMP-3 (packed decimal) value semantics are mapped; the packed bytes (digits/2+1 bytes, sign nibble C/D/F) "
        "are certified only for the leaves of a RECORD SEQUENTIAL or INDEXED file record inside "
        "engine/transformation/binary_record.py (GnuCOBOL 3.1.2: tests/integration/test_binary_record_oracle.py); "
        "anywhere else the byte encoding is not certified"
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
        "PIC X / unsigned DISPLAY integer views (and groups of them, leaves at "
        "their offsets) over an elementary base are lowered as a shared byte "
        "string with synchronised views, byte-identical to GnuCOBOL 3.1.2 "
        "(tests/test_redefines_digit_views.py, "
        "tests/integration/test_structural_oracle_proof.py); a program whose "
        "overlays are all in that subset is classified SUPPORTED.  Signed, "
        "scaled or COMP members, nested groups, chained REDEFINES, aliases "
        "wider than the base, non-MOVE writers and non-digit bytes written "
        "under a numeric view are reported UNSUPPORTED: GnuCOBOL's numeric "
        "reinterpretation of such bytes is compiler-specific undefined data"
    ),
    "OCCURS": _partial(
        "Fixed-size OCCURS n TIMES lowers to Java arrays with 1-based to "
        "0-based subscripts, element receivers keeping their PIC semantics "
        "(tests/test_occurs_elements.py); a program whose tables are "
        "one-dimensional DISPLAY elementary WORKING-STORAGE items referenced "
        "only by subscript is classified SUPPORTED.  OCCURS DEPENDING ON fails "
        "closed with UNSUPPORTED_CONSTRUCT; whole-table references, group or "
        "multi-dimension tables, ASCENDING/DESCENDING KEY clauses and tables outside the SEARCH / SET INDEX "
        "subset stay PARTIAL (INDEXED BY with SEARCH and SET on indexes is certified)"
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
    ReadStatement.__name__: "READ",
    RewriteStatement.__name__: "REWRITE",
    SetConditionStatement.__name__: "SET CONDITION TO TRUE",
    StartStatement.__name__: "START",
    StopRunStatement.__name__: "STOP RUN",
    ExitProgramStatement.__name__: "EXIT PROGRAM",
    AcceptStatement.__name__: "ACCEPT",
    InspectStatement.__name__: "INSPECT",
    SortStatement.__name__: "SORT",
    ExitPerformStatement.__name__: "EXIT PERFORM",
    SetIndexStatement.__name__: "SET INDEX",
    SearchStatement.__name__: "SEARCH",
    ExecSqlStatement.__name__: "EXEC SQL",
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
    # GO TO is decided on the whole program by control_flow.goto_plan_reasons (capability analyzer), not by a pattern
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
        r"(?<![\w-])SET(?!\s+[A-Z0-9][\w-]*\s+TO\s+TRUE(?![\w-]))"
        # the certified index forms: SET name... TO|UP BY|DOWN BY <one word> (a TRUE/FALSE or ADDRESS form is not one)
        r"(?!\s+(?!ADDRESS(?![\w-]))[A-Z0-9][\w-]*(?:[\s,]+[A-Z0-9][\w-]*)*?\s+"
        r"(?:TO\s+(?!(?:TRUE|FALSE|ADDRESS)(?![\w-]))|(?:UP|DOWN)\s+BY\s+)[A-Z0-9][\w-]*(?!\s*[-+*/(])\s*\.?(?:\s|$))"
        r"(?![\w-])",
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


_QUOTED_LITERAL = re.compile("'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"")


def _strip_literals_and_comments(source: str) -> str:
    """Remove comments and quoted literals before keyword scanning.

    Reads the text the compiler reads (audit T13): fixed format keeps
    columns 1-72 and treats a column-7 ``*``, ``/`` or ``D`` as a comment
    line whatever columns 1-6 hold (``000100* SORT ...`` used to be scanned
    as code); ``*>`` starts a comment in both formats; literals use COBOL's
    doubled-quote escape (the old pattern looked for backslash escapes).
    """
    from engine.transformation.source_format import (
        compiler_visible_text,
        detect_source_format,
    )

    fixed = detect_source_format(source) == "fixed"
    kept: list[str] = []
    for line in compiler_visible_text(source).splitlines():
        if fixed and len(line) > 6 and line[6] in "*/Dd":
            continue
        if line.lstrip().startswith("*>") or (not fixed and line.lstrip()[:1] == "*"):
            continue
        without_literals = _QUOTED_LITERAL.sub(" ", line)
        marker = without_literals.find("*>")
        if marker >= 0:
            without_literals = without_literals[:marker]
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
    # Real MQ / IMS call forms name their target in a literal, which the
    # stripped text above no longer has (roadmap unit 2).
    from engine.transformation.subsystem_calls import find_subsystem_calls

    for call in find_subsystem_calls(source):
        found.add("CALL MQI" if call.subsystem == "MQ" else "CALL DLI")
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

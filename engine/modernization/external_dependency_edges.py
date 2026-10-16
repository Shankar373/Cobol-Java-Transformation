"""MQ queue-name, IMS PCB/segment, DB2 table and CICS resource dependency edges.

Phase 7 P3-4 (BL-084/BL-085) detects ``EXEC DLI`` / ``EXEC MQI`` as
*constructs*; P3-6 lifts the queue-name and PCB/segment references out of
those blocks and into the platform dependency ledger via
``build_dependency_ledger(extra_dependencies=...)`` — the mechanism
``integrated_proof`` already reserves for lanes the modernization report
does not model (JCL/DB2/CICS), now with its first real producer.

Phase 10 (BL-083 / P1-a and P1-b) adds the DB2 and CICS producers to the
same surface: ``extract_db2_dependency_entries`` drives the SQL lane's own
chain (extractor → parser → ``extract_table_dependencies``) and
``extract_cics_dependency_entries`` drives the CICS lane facade
(``extract_cics_blocks`` → ``CicsParser``), so ``DependencyKind.DB2`` and
``DependencyKind.CICS`` finally have product producers.

Every entry this module returns is fail-closed, exactly like the JCL
lane: ``visible=True`` (the dependency is on the record), classified
``UNSUPPORTED`` (no MQ, IMS, DB2 or CICS runtime lane exists in this
repository — see docs/CAPABILITY_MATRIX.md), proof state ``BLOCKED``, and
``required=True`` so the central status gate can never certify an
application that references an external queue, PCB/segment, table or CICS
resource.

Extraction is deterministic and bounded: only real ``EXEC MQI …
END-EXEC`` / ``EXEC DLI … END-EXEC`` / ``EXEC SQL … END-EXEC`` /
``EXEC CICS … END-EXEC`` blocks are scanned (comment lines and inline
``*>`` comments are masked first); text outside a block — including string
literals that merely *mention* ``QUEUE(...)`` — never extracts.  The
covered statement forms are the documented ones:
``QUEUE('name')`` / ``QUEUE("name")`` / ``QUEUE(name)`` and the short
``Q(...)`` form for MQ; ``PCB(...)`` / ``PCB NAME=…`` and ``SEGMENT(...)``
/ ``SEGMENT NAME=…`` for IMS DLI; table references after
SELECT/INSERT/UPDATE/DELETE for DB2; PROGRAM/FILE/QUEUE/MAP/TERMID/
TRANSID resource operands for CICS.

No equivalence claim, no message-semantics claim, no runtime, no IR and
no mapper touch these entries: classification and ledger visibility
only (§29 ladder, Rung 0 -> 1 -> 2 stays open).
"""

from __future__ import annotations

import re

from engine.modernization.integrated_proof import (
    CapabilityLevel,
    DependencyKind,
    DependencyLedgerEntry,
    ProofState,
)

# EXEC block boundaries.  DOTALL so a block may span the usual fixed-format
# continuation lines; word boundaries so identifiers such as EXECUTABLE or
# WS-EXEC-MQI can never open a block.
_EXEC_MQI_BLOCK = re.compile(
    r"(?<![\w-])EXEC\s+MQI\b(.*?)END-EXEC",
    re.IGNORECASE | re.DOTALL,
)
_EXEC_DLI_BLOCK = re.compile(
    r"(?<![\w-])EXEC\s+DLI\b(.*?)END-EXEC",
    re.IGNORECASE | re.DOTALL,
)

# Cheap precheck for the common case: most programs contain no MQ/IMS block
# at all, so the literal-preserving mask and the block scans can be skipped
# entirely.  A literal that merely *mentions* EXEC MQI/EXEC DLI can only
# cause a false precheck hit (safe: the real pass then finds no block and
# returns the empty tuple) — never a miss, because masking only removes
# text.
_EXEC_ANY = re.compile(r"(?<![\w-])EXEC\s+(?:MQI|DLI)\b", re.IGNORECASE)

# MQ queue-name forms inside an EXEC MQI block.  Alternation order matters:
# QUEUE is tried before the short Q form so QUEUE('X') cannot double-match.
_MQ_QUEUE = re.compile(
    r"(?<![\w-])(?:QUEUE|Q)\s*\(\s*"
    r"(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z0-9][A-Za-z0-9-]*))"
    r"\s*\)",
    re.IGNORECASE,
)

_IMS_PCB_PAREN = re.compile(
    r"(?<![\w-])PCB\s*\(\s*([A-Za-z0-9][A-Za-z0-9-]*)\s*\)",
    re.IGNORECASE,
)
_IMS_PCB_NAME = re.compile(
    r"(?<![\w-])PCB\s+NAME\s*=\s*([A-Za-z0-9][A-Za-z0-9-]*)",
    re.IGNORECASE,
)
_IMS_SEGMENT_PAREN = re.compile(
    r"(?<![\w-])SEGMENT\s*\(\s*([A-Za-z0-9][A-Za-z0-9-]*)\s*\)",
    re.IGNORECASE,
)
_IMS_SEGMENT_NAME = re.compile(
    r"(?<![\w-])SEGMENT\s+NAME\s*=\s*([A-Za-z0-9][A-Za-z0-9-]*)",
    re.IGNORECASE,
)

# Quoted literals, doubled-quote escapes included (same rule as
# ``semantic_capability._strip_literals_and_comments``).
_LITERAL = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"")


def _mask_comments(source: str) -> str:
    """Blank out COBOL comment lines and inline ``*>`` comments.

    Literals are deliberately *kept* — ``QUEUE('ORDERS')`` carries the
    queue name inside a literal — so this is not the full literal-and-
    comment mask ``semantic_capability`` uses for verb detection.
    """
    masked: list[str] = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("*"):
            masked.append("")
            continue
        idx = line.find("*>")
        masked.append(line[:idx] if idx != -1 else line)
    return "\n".join(masked)


def _mask_literals_same_length(text: str) -> str:
    """Replace every quoted literal with spaces of the same length.

    Same-length masking keeps character offsets aligned with the
    comment-masked text, so block spans found on this pass can be sliced
    back out of the literal-preserving text for name extraction.  A
    string literal that merely *mentions* ``EXEC DLI … END-EXEC`` can
    therefore never open or close a block.
    """
    return _LITERAL.sub(lambda m: " " * (m.end() - m.start()), text)


def _queue_names(block_text: str) -> list[str]:
    names: list[str] = []
    for match in _MQ_QUEUE.finditer(block_text):
        name = next(g for g in match.groups() if g)
        names.append(name.upper())
    return names


def _ims_refs(block_text: str) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for pattern in (_IMS_PCB_PAREN, _IMS_PCB_NAME):
        refs.extend(
            ("PCB", m.group(1).upper()) for m in pattern.finditer(block_text)
        )
    for pattern in (_IMS_SEGMENT_PAREN, _IMS_SEGMENT_NAME):
        refs.extend(
            ("SEGMENT", m.group(1).upper()) for m in pattern.finditer(block_text)
        )
    return refs


def _mq_entry(queue_name: str) -> DependencyLedgerEntry:
    return DependencyLedgerEntry(
        dependency_id=f"MQ:QUEUE={queue_name}",
        kind=DependencyKind.MQ,
        visible=True,
        capability_level=CapabilityLevel.UNSUPPORTED,
        proof_state=ProofState.BLOCKED,
        required=True,
        reason=(
            f"MQ queue {queue_name} is referenced via EXEC MQI; no MQ "
            "runtime lane exists, so the dependency is classified "
            "UNSUPPORTED and proof state BLOCKED (fail-closed)"
        ),
    )


def _ims_entry(role: str, name: str) -> DependencyLedgerEntry:
    return DependencyLedgerEntry(
        dependency_id=f"IMS:{role}={name}",
        kind=DependencyKind.IMS,
        visible=True,
        capability_level=CapabilityLevel.UNSUPPORTED,
        proof_state=ProofState.BLOCKED,
        required=True,
        reason=(
            f"IMS {role} {name} is referenced via EXEC DLI; no IMS "
            "runtime lane exists, so the dependency is classified "
            "UNSUPPORTED and proof state BLOCKED (fail-closed)"
        ),
    )


def extract_external_dependency_entries(
    source_text: str,
) -> tuple[DependencyLedgerEntry, ...]:
    """Extract MQ queue and IMS PCB/segment ledger entries from one source.

    Deterministic, deduplicated, sorted by ``dependency_id``.  Empty
    tuple when the source contains no real ``EXEC MQI`` / ``EXEC DLI``
    block with a queue-name / PCB / segment reference.
    """
    comment_masked = _mask_comments(source_text)
    if not _EXEC_ANY.search(comment_masked):
        # Fast path: no EXEC MQI/EXEC DLI anywhere — the common case.
        return ()
    block_view = _mask_literals_same_length(comment_masked)
    by_id: dict[str, DependencyLedgerEntry] = {}

    for block in _EXEC_MQI_BLOCK.finditer(block_view):
        span = comment_masked[block.start(1) : block.end(1)]
        for queue_name in _queue_names(span):
            entry = _mq_entry(queue_name)
            by_id.setdefault(entry.dependency_id, entry)

    for block in _EXEC_DLI_BLOCK.finditer(block_view):
        span = comment_masked[block.start(1) : block.end(1)]
        for role, name in _ims_refs(span):
            entry = _ims_entry(role, name)
            by_id.setdefault(entry.dependency_id, entry)

    return tuple(by_id[key] for key in sorted(by_id))


# Phase 10 (BL-083): DB2 / CICS prechecks, same fast-path contract as
# ``_EXEC_ANY`` above — a false hit only costs a real pass that then finds
# no block; a miss is impossible because masking only removes text.
_EXEC_SQL_ANY = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)
_EXEC_CICS_ANY = re.compile(r"\bEXEC\s+CICS\b", re.IGNORECASE)

# TRANSID operand inside an EXEC CICS block: TRANSID('TSK1') /
# TRANSID("TSK1") / TRANSID(TSK1).  The CICS parser never surfaces these as
# transaction resources, so the block text is scanned directly.
_CICS_TRANSID = re.compile(
    r"(?<![\w-])TRANSID\s*\(\s*"
    r"(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z0-9][A-Za-z0-9-]*))\s*\)",
    re.IGNORECASE,
)


def _unquote(value: str) -> str:
    """Strip one surrounding quote pair from a parser-produced name.

    The CICS parser keeps resource operands quoted (``LINK PROGRAM('SUBPROG')``
    yields ``'SUBPROG'``); ledger ids are unquoted and uppercased so
    ``CICS:PROGRAM=SUBPROG`` reads like every other dependency id.
    """
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def _db2_entry(
    table: str,
    operations: tuple[str, ...],
    program_id: str,
) -> DependencyLedgerEntry:
    scope = f" by {program_id}" if program_id else ""
    return DependencyLedgerEntry(
        dependency_id=f"DB2:TABLE={table}",
        kind=DependencyKind.DB2,
        visible=True,
        capability_level=CapabilityLevel.UNSUPPORTED,
        proof_state=ProofState.BLOCKED,
        required=True,
        reason=(
            f"DB2 table {table} is referenced via EXEC SQL{scope} "
            f"(operations: {', '.join(operations)}); no DB2 runtime lane "
            "exists in this repository, so the dependency is classified "
            "UNSUPPORTED and proof state BLOCKED (fail-closed)"
        ),
    )


def _db2_unparseable_entry(
    program_id: str,
    statements: tuple[str, ...],
) -> DependencyLedgerEntry:
    scope = program_id or "unknown program"
    preview = "; ".join(statements[:3])
    return DependencyLedgerEntry(
        dependency_id="DB2:UNPARSEABLE",
        kind=DependencyKind.DB2,
        visible=True,
        capability_level=CapabilityLevel.UNSUPPORTED,
        proof_state=ProofState.BLOCKED,
        required=True,
        reason=(
            f"Embedded SQL in {scope} could not be mapped to table "
            f"dependencies: {preview}; no DB2 runtime lane exists in this "
            "repository, so the unmodelled statements are classified "
            "UNSUPPORTED and proof state BLOCKED (fail-closed)"
        ),
    )


def extract_db2_dependency_entries(
    source_text: str,
    program_id: str = "",
) -> tuple[DependencyLedgerEntry, ...]:
    """Extract DB2 table ledger entries from embedded SQL in one source.

    Phase 10 (BL-083): drives the SQL lane's own chain —
    ``extract_embedded_sql_blocks`` → ``SqlParser.parse_embedded_sql`` →
    ``SqlParser.extract_table_dependencies`` — so declared tables finally
    reach ``build_dependency_ledger(extra_dependencies=...)``.  Statements
    the parser preserves as unsupported (BL-080) never yield a table
    dependency, so they surface as one fail-closed ``DB2:UNPARSEABLE``
    entry instead of silently vanishing from the inventory.

    Deterministic, deduplicated, sorted by ``dependency_id``.  Empty tuple
    when the source contains no ``EXEC SQL`` block.  The optional
    ``program_id`` is traceability in the reason only — the dependency id
    stays table-based so ledger ordering is stable across callers.
    """
    if not source_text or not _EXEC_SQL_ANY.search(source_text):
        return ()

    from engine.sql.extractor import extract_embedded_sql_blocks
    from engine.transformation.sql_parser import SqlParser

    # Blank comment lines and inline ``*>`` comments before the lane's own
    # block scan: a commented ``EXEC SQL`` line never opens a region, and a
    # trailing comment can never leak into a parsed statement.
    comment_masked = _mask_comments(source_text)
    parser = SqlParser()
    ops_by_table: dict[str, set[str]] = {}
    unmodelled: list[str] = []

    for sql_text in extract_embedded_sql_blocks(comment_masked):
        flattened = " ".join(sql_text.split())[:120]
        try:
            block = parser.parse_embedded_sql(sql_text)
            dependencies = parser.extract_table_dependencies(block, program_id)
        except Exception:
            # Fail closed: an unparseable block is reported below rather
            # than presenting the program as dependency-free.
            if flattened:
                unmodelled.append(flattened)
            continue
        for dependency in dependencies:
            table = _unquote(str(dependency.table_name)).upper()
            if table:
                ops_by_table.setdefault(table, set()).add(
                    str(dependency.operation).upper()
                )
        for statement_text in getattr(block, "unsupported_statements", ()):
            flattened = " ".join(str(statement_text).split())[:120]
            if flattened:
                unmodelled.append(flattened)

    by_id: dict[str, DependencyLedgerEntry] = {}
    for table, operations in ops_by_table.items():
        entry = _db2_entry(table, tuple(sorted(operations)), program_id)
        by_id[entry.dependency_id] = entry
    if unmodelled:
        entry = _db2_unparseable_entry(program_id, tuple(unmodelled))
        by_id[entry.dependency_id] = entry
    return tuple(by_id[key] for key in sorted(by_id))


def _cics_entry(role: str, name: str) -> DependencyLedgerEntry:
    return DependencyLedgerEntry(
        dependency_id=f"CICS:{role}={name}",
        kind=DependencyKind.CICS,
        visible=True,
        capability_level=CapabilityLevel.UNSUPPORTED,
        proof_state=ProofState.BLOCKED,
        required=True,
        reason=(
            f"CICS {role} {name} is referenced via EXEC CICS; no CICS "
            "runtime lane exists in this repository, so the dependency is "
            "classified UNSUPPORTED and proof state BLOCKED (fail-closed)"
        ),
    )


def extract_cics_dependency_entries(
    source_text: str,
) -> tuple[DependencyLedgerEntry, ...]:
    """Extract CICS resource ledger entries from one source.

    Phase 10 (BL-083): drives the CICS lane facade
    (``extract_cics_blocks`` → ``CicsParser``) over comment-masked source —
    a comment-only ``*> EXEC CICS … END-EXEC`` line parses as a live block
    if fed unmasked and would invent phantom resources.  Resource operands
    (PROGRAM/FILE/QUEUE/MAP/TERMID) come from the parser's resource tuples
    unquoted and uppercased; ``TRANSID('…')`` operands never reach the
    ``transactions`` tuple, so the masked block text is scanned for them
    as well.

    Deterministic, deduplicated, sorted by ``dependency_id``.  Empty tuple
    when the source contains no live ``EXEC CICS`` block.
    """
    if not source_text or not _EXEC_CICS_ANY.search(source_text):
        return ()

    from engine.transformation.cics_java_mapping import extract_cics_blocks

    comment_masked = _mask_comments(source_text)
    if not _EXEC_CICS_ANY.search(comment_masked):
        # The precheck hit only a comment line — no live block exists.
        return ()

    by_id: dict[str, DependencyLedgerEntry] = {}
    for application in extract_cics_blocks(comment_masked):
        for role, resources in (
            ("PROGRAM", application.program_resources),
            ("FILE", application.file_resources),
            ("QUEUE", application.queue_resources),
            ("MAP", application.map_resources),
            ("TERMID", application.terminal_resources),
        ):
            for resource in resources:
                name = _unquote(str(resource)).upper()
                if name:
                    entry = _cics_entry(role, name)
                    by_id.setdefault(entry.dependency_id, entry)
        for transaction in application.transactions:
            name = _unquote(
                str(getattr(transaction, "transaction_id", "") or "")
            ).upper()
            if name:
                entry = _cics_entry("TRANSID", name)
                by_id.setdefault(entry.dependency_id, entry)
        for match in _CICS_TRANSID.finditer(
            _mask_comments(application.raw_text or "")
        ):
            name = next(g for g in match.groups() if g).upper()
            if name:
                entry = _cics_entry("TRANSID", name)
                by_id.setdefault(entry.dependency_id, entry)

    return tuple(by_id[key] for key in sorted(by_id))

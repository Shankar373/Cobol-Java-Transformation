"""MQ queue-name and IMS PCB/segment dependency edges (roadmap P3-6, BL-087).

Phase 7 P3-4 (BL-084/BL-085) detects ``EXEC DLI`` / ``EXEC MQI`` as
*constructs*; P3-6 lifts the queue-name and PCB/segment references out of
those blocks and into the platform dependency ledger via
``build_dependency_ledger(extra_dependencies=...)`` — the mechanism
``integrated_proof`` already reserves for lanes the modernization report
does not model (JCL/DB2/CICS), now with its first real producer.

Every entry this module returns is fail-closed, exactly like the JCL
lane: ``visible=True`` (the dependency is on the record), classified
``UNSUPPORTED`` (no MQ or IMS runtime lane exists in this repository —
see docs/CAPABILITY_MATRIX.md), proof state ``BLOCKED``, and
``required=True`` so the central status gate can never certify an
application that references an external queue or PCB/segment.

Extraction is deterministic and bounded: only real ``EXEC MQI …
END-EXEC`` / ``EXEC DLI … END-EXEC`` blocks are scanned (comment lines
and inline ``*>`` comments are masked first); text outside a block —
including string literals that merely *mention* ``QUEUE(...)`` — never
extracts.  The covered statement forms are the documented ones:
``QUEUE('name')`` / ``QUEUE("name")`` / ``QUEUE(name)`` and the short
``Q(...)`` form for MQ; ``PCB(...)`` / ``PCB NAME=…`` and ``SEGMENT(...)``
/ ``SEGMENT NAME=…`` for IMS DLI.

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

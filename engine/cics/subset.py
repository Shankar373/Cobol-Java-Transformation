"""Supported CICS subset contract for the CICS modernization lane.

This module is the single source of truth for which CICS commands are:

- ``MAPPED``          → given an explicit Java/Spring service element.
- ``EXPLICIT_ONLY``   → carried verbatim (HANDLE CONDITION, HANDLE AID,
                        ASSIGN) but never auto-translated into runtime logic.
- ``UNSUPPORTED``     → kept explicit and emitted into the generated source
                        and mapping report.

The CICS parser (``engine.transformation.cics_parser``) intentionally
recognizes more command families than this subset maps.  Every recognized
command is therefore classified explicitly: nothing is silently dropped.

Supported subset categories:

1. **Terminal I/O request/response** — ``SEND`` / ``RECEIVE`` (maps, FROM/INTO
   data + LENGTH, TERMID/TRANSID).
2. **Program/service interaction** — ``LINK`` / ``XCTL`` / ``RETURN``
   (PROGRAM, COMMAREA + LENGTH, channel/container references).
3. **Transaction boundary** — ``SYNCPOINT`` (commit), ``ABEND`` (rollback),
   ``RETURN`` (pseudo-conversational boundary with optional next TRANSID).
4. **Resource access** — file commands (``READ``/``WRITE``/``REWRITE``/
   ``DELETE``/``STARTBR``/``READNEXT``/``READPREV``/``ENDBR``) and
   temporary-storage queue commands (``WRITEQ``/``READQ``/``DELETEQ``),
   including ``RESP``/``RESP2`` handling.

Explicitly unsupported today (kept explicit, never silently dropped):
``ALLOCATE``, ``FREE``, ``HOLD``, ``RELEASE``, ``SET``, ``IGNORE``, ``POP``,
``PUSH``.

This subset does NOT claim CICS Transaction Server runtime equivalence.  The
mapping preserves the *structure* (boundaries, request/response, program
interaction, resources); real CICS runtime behavior (RESP codes, commarea
copy semantics, transaction isolation, pseudo-conversational state) is
explicitly out of scope of this model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from engine.cics.model import CicsConstructStatus
from engine.transformation.ir import CicsCommandType

# Version of the supported-subset contract (semantic version).
SUPPORTED_SUBSET_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Command classification tables
# ---------------------------------------------------------------------------

TERMINAL_IO_COMMANDS: frozenset[CicsCommandType] = frozenset(
    {
        CicsCommandType.SEND,
        CicsCommandType.RECEIVE,
    }
)

PROGRAM_INTERACTION_COMMANDS: frozenset[CicsCommandType] = frozenset(
    {
        CicsCommandType.LINK,
        CicsCommandType.XCTL,
        CicsCommandType.RETURN,
    }
)

RESOURCE_ACCESS_COMMANDS: frozenset[CicsCommandType] = frozenset(
    {
        CicsCommandType.READ,
        CicsCommandType.WRITE,
        CicsCommandType.REWRITE,
        CicsCommandType.DELETE,
        CicsCommandType.STARTBR,
        CicsCommandType.READNEXT,
        CicsCommandType.READPREV,
        CicsCommandType.ENDBR,
        CicsCommandType.WRITEQ,
        CicsCommandType.READQ,
        CicsCommandType.DELETEQ,
    }
)

BOUNDARY_COMMANDS: frozenset[CicsCommandType] = frozenset(
    {
        # SYNCPOINT commits the current unit of work.
        CicsCommandType.SYNCPOINT,
        # ABEND rolls the current unit of work back and abends.
        CicsCommandType.ABEND,
        # RETURN completes the pseudo-conversational exchange.
        CicsCommandType.RETURN,
    }
)

EXPLICIT_ONLY_COMMANDS: frozenset[CicsCommandType] = frozenset(
    {
        CicsCommandType.HANDLE_CONDITION,
        CicsCommandType.HANDLE_AID,
        CicsCommandType.ASSIGN,
    }
)

UNSUPPORTED_COMMANDS: frozenset[CicsCommandType] = frozenset(
    {
        CicsCommandType.ALLOCATE,
        CicsCommandType.FREE,
        CicsCommandType.HOLD,
        CicsCommandType.RELEASE,
        CicsCommandType.SET,
        CicsCommandType.IGNORE,
        CicsCommandType.POP,
        CicsCommandType.PUSH,
    }
)

# Every command family the parser can emit must be classified somewhere.
_ALL_KNOWN_COMMANDS = (
    TERMINAL_IO_COMMANDS
    | PROGRAM_INTERACTION_COMMANDS
    | RESOURCE_ACCESS_COMMANDS
    | BOUNDARY_COMMANDS
    | EXPLICIT_ONLY_COMMANDS
    | UNSUPPORTED_COMMANDS
)


@dataclass(frozen=True)
class CicsSubsetClassification:
    """Classification of a single CICS command type."""

    status: str  # CicsConstructStatus
    category: str  # TERMINAL_IO / PROGRAM_INTERACTION / RESOURCE_ACCESS /
    #               BOUNDARY / EXPLICIT_ONLY / UNSUPPORTED

    @property
    def is_mapped(self) -> bool:
        return self.status == CicsConstructStatus.MAPPED


@cache
def classify_command(command: CicsCommandType) -> CicsSubsetClassification:
    """Classify a CICS command type against the supported subset.

    ``RETURN`` is classified as a program interaction (its primary category)
    and additionally as a transaction boundary by the mapper.
    """
    if command in TERMINAL_IO_COMMANDS:
        return CicsSubsetClassification(CicsConstructStatus.MAPPED, "TERMINAL_IO")
    if command in PROGRAM_INTERACTION_COMMANDS:
        return CicsSubsetClassification(CicsConstructStatus.MAPPED, "PROGRAM_INTERACTION")
    if command in RESOURCE_ACCESS_COMMANDS:
        return CicsSubsetClassification(CicsConstructStatus.MAPPED, "RESOURCE_ACCESS")
    if command in BOUNDARY_COMMANDS:
        return CicsSubsetClassification(CicsConstructStatus.MAPPED, "BOUNDARY")
    if command in EXPLICIT_ONLY_COMMANDS:
        return CicsSubsetClassification(CicsConstructStatus.EXPLICIT_ONLY, "EXPLICIT_ONLY")
    if command in UNSUPPORTED_COMMANDS:
        return CicsSubsetClassification(CicsConstructStatus.UNSUPPORTED, "UNSUPPORTED")
    # The parser may yet recognize commands not present in the tables above;
    # they are always UNSUPPORTED and explicit — never silently dropped.
    return CicsSubsetClassification(CicsConstructStatus.UNSUPPORTED, "UNSUPPORTED")


def is_supported(command: CicsCommandType) -> bool:
    """True when the command is part of the MAPPED supported subset."""
    return classify_command(command).is_mapped


def known_command_names() -> tuple[str, ...]:
    """Command type value names, sorted, for documentation/tests."""
    return tuple(sorted(command.value for command in CicsCommandType))


def supported_command_names() -> tuple[str, ...]:
    """Mapped command type value names, sorted."""
    names = {
        command.value
        for command in CicsCommandType
        if classify_command(command).status == CicsConstructStatus.MAPPED
    }
    return tuple(sorted(names))


def unsupported_command_names() -> tuple[str, ...]:
    """UNSUPPORTED command type value names, sorted."""
    names = {
        command.value
        for command in CicsCommandType
        if classify_command(command).status == CicsConstructStatus.UNSUPPORTED
    }
    return tuple(sorted(names))
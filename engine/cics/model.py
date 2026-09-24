"""Explicit Java/Spring service model for CICS transations.

This is the CICS modernization **output** model.  It is consumed from the
CICS semantic IR (``CicsApplication``) and produced as an explicit,
deterministic Java/Spring service representation covering:

- Transaction boundaries (pseudo-conversational ``RETURN``, ``SYNCPOINT``,
  ``ABEND``).
- Request/response semantics (``RECEIVE`` / ``SEND`` terminal I/O).
- Program/service interaction (``LINK``, ``XCTL``, ``RETURN``).
- Resource access (``READ``/``WRITE``/``REWRITE``/``DELETE``/browse commands,
  temporary-storage queue commands).
- Response-code handling (``RESP`` / ``RESP2``).

Design rules (mirrors ``engine.transformation.spring_boot_ir``):

- This model MUST NOT import ``engine.transformation.ir``.  The mapper at
  ``engine.cics.mapper`` is the only boundary that translates the shared IR
  into this model.  ``CicsRespPolicy`` duplicates the four ``RESP`` handling
  modes by value so the output model stays IR-free.
- **No CICS TS runtime equivalence is claimed anywhere in this model.**
  Every runtime seam and every generated source file states that IBM CICS
  Transaction Server runtime behavior is NOT reproduced.
- Unsupported CICS constructs remain **explicit** (never dropped).  Each one
  is carried with its raw text and the reason it is outside the supported
  subset, and is emitted verbatim into the generated service and report.
- Mapping is deterministic: same input always yields the same model.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# CICS output-model enums (IR-free)
# ---------------------------------------------------------------------------


class CicsRespPolicy:
    """CICS RESP/RESP2 handling mode (mirrors IR ``CicsRespHandling`` by value)."""

    NO_HANDLE = "NO_HANDLE"
    HANDLE_CONDITION = "HANDLE_CONDITION"
    RESP_VARIABLE = "RESP_VARIABLE"
    RESP2_VARIABLE = "RESP2_VARIABLE"


class CicsTerminalIoKind:
    """Terminal I/O direction for a CICS request/response exchange."""

    RECEIVE = "RECEIVE"
    SEND = "SEND"


class CicsInteractionKind:
    """Program/service interaction kind within the CICS program control API."""

    LINK = "LINK"
    XCTL = "XCTL"
    RETURN = "RETURN"


class CicsResourceKind:
    """Kind of CICS resource accessed by a resource-access command."""

    FILE = "FILE"
    QUEUE = "QUEUE"


class CicsBoundaryKind:
    """Transaction boundary kind surfaced by the CICS program."""

    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"
    PSEUDO_CONVERSATIONAL = "PSEUDO_CONVERSATIONAL"


class CicsExplicitKind:
    """CICS constructs that are carried EXPLICITLY but never auto-translated."""

    HANDLE_CONDITION = "HANDLE_CONDITION"
    HANDLE_AID = "HANDLE_AID"
    ASSIGN = "ASSIGN"


class CicsConstructStatus:
    """Classification of each CICS command with respect to the supported subset."""

    MAPPED = "MAPPED"
    EXPLICIT_ONLY = "EXPLICIT_ONLY"
    UNSUPPORTED = "UNSUPPORTED"


class CicsIssueSeverity:
    """Severity of a mapping issue."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Core model types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CicsHostValue:
    """A resolved operand value (host variable name or literal)."""

    name: str
    is_literal: bool = False
    literal_value: str = ""

    def display(self) -> str:
        """Render the value for traceability text (quoted literal or name)."""
        if self.is_literal:
            return repr(self.literal_value)
        return self.name


@dataclass(frozen=True)
class CicsTerminalIo:
    """One SEND or RECEIVE mapped to an explicit request/response element."""

    kind: str  # CicsTerminalIoKind
    map_name: str = ""
    mapset_name: str = ""
    terminal_id: str = ""
    data_field: str = ""
    length_field: str = ""
    transaction_id: str = ""
    raw_text: str = ""


@dataclass(frozen=True)
class CicsProgramInteraction:
    """One LINK/XCTL/RETURN mapped to an explicit program/service interaction."""

    kind: str  # CicsInteractionKind
    program: str = ""
    commarea: str = ""
    commarea_length: str = ""
    channel: str = ""
    containers: tuple[str, ...] = ()
    transaction_id: str = ""
    raw_text: str = ""


@dataclass(frozen=True)
class CicsResourceAccess:
    """One resource-access command (file or queue) with its operands."""

    operation: str  # READ, WRITE, REWRITE, DELETE, STARTBR, READNEXT, READPREV,
    #                 ENDBR, WRITEQ, READQ, DELETEQ
    resource_kind: str  # CicsResourceKind
    resource: str = ""
    key_field: str = ""
    data_field: str = ""
    length_field: str = ""
    resp_field: str = ""
    resp2_field: str = ""
    resp_policy: str = CicsRespPolicy.NO_HANDLE
    raw_text: str = ""


@dataclass(frozen=True)
class CicsTransactionBoundary:
    """A transaction boundary surfaced by the CICS program.

    ``RETURN TRANSID(...)`` is both a program interaction and a
    pseudo-conversational boundary; the mapper records it in both places.
    """

    kind: str  # CicsBoundaryKind
    program_id: str = ""
    transaction_id: str = ""  # next TRANSID for pseudo-conversational restart
    commarea: str = ""
    raw_text: str = ""


@dataclass(frozen=True)
class CicsExplicitConstruct:
    """A CICS construct carried EXPLICITLY but not auto-translated.

    These are preserved verbatim so no CICS semantics are silently dropped.
    They are never claimed to be equivalent to generated Java behavior.
    """

    kind: str  # CicsExplicitKind
    raw_text: str = ""
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class CicsUnsupportedConstruct:
    """A CICS construct outside the supported subset, kept explicit."""

    command: str
    raw_text: str
    reason: str


@dataclass(frozen=True)
class CicsMappingIssue:
    """A non-fatal issue recorded while mapping a CICS program."""

    severity: str  # CicsIssueSeverity
    message: str
    program_id: str = ""


@dataclass(frozen=True)
class CicsFlowStep:
    """One CICS command occurrence in source order.

    The flow preserves the exact order of CICS commands within the program so
    the generated service exposes the pseudo-conversational exchange sequence.
    """

    index: int
    status: str  # CicsConstructStatus
    step_kind: str  # further granularity, e.g. RECEIVE / READ / SYNCPOINT
    detail: str = ""  # primary operand detail (map, resource, program)
    raw_text: str = ""


@dataclass(frozen=True)
class CicsService:
    """A CICS program mapped to an explicit Spring service.

    Every attribute is source-derived (program-id, operands, host variables).
    No business logic is invented.
    """

    service_name: str  # Java class name of the generated service
    source_program: str  # CICS PROGRAM-ID
    package: str  # target package
    is_transactional: bool  # True when a SYNCPOINT/RETURN boundary exists
    flow: tuple[CicsFlowStep, ...] = ()
    terminal_ios: tuple[CicsTerminalIo, ...] = ()
    program_interactions: tuple[CicsProgramInteraction, ...] = ()
    resource_accesses: tuple[CicsResourceAccess, ...] = ()
    transaction_boundaries: tuple[CicsTransactionBoundary, ...] = ()
    explicit_constructs: tuple[CicsExplicitConstruct, ...] = ()
    unsupported_constructs: tuple[CicsUnsupportedConstruct, ...] = ()
    host_variables: tuple[str, ...] = ()
    issues: tuple[CicsMappingIssue, ...] = ()

    @property
    def has_unsupported(self) -> bool:
        return bool(self.unsupported_constructs)

    def get_resource_operations(self) -> set[str]:
        """Distinct resource operation names used by this service (lower-case)."""
        return {access.operation.lower() for access in self.resource_accesses}

    def get_interaction_targets(self) -> list[tuple[str, str]]:
        """Distinct (kind, program) interaction targets in stable order."""
        seen: list[tuple[str, str]] = []
        for interaction in self.program_interactions:
            if not interaction.program:
                continue
            key = (interaction.kind, interaction.program)
            if key not in seen:
                seen.append(key)
        return seen


@dataclass(frozen=True)
class CicsGeneratedFile:
    """A generated file with a project-relative path."""

    filename: str
    source_code: str
    class_name: str
    path: str  # project-relative path (e.g. "src/main/java/<pkg>/X.java")


@dataclass(frozen=True)
class CicsSpringApplication:
    """An explicit Java/Spring representation of one CICS application.

    Aggregates one service per CICS program plus cross-cutting runtime and
    client seams.  This is the top-level container consumed by the generator.
    """

    application_id: str
    base_package: str = "com.generated.cics"
    services: tuple[CicsService, ...] = ()
    source_program_ids: tuple[str, ...] = ()
    generator_version: str = "1.0.0"
    supported_subset_version: str = "1.0.0"

    def get_service(self, name: str) -> CicsService | None:
        """Find a service by generated class name."""
        for service in self.services:
            if service.service_name == name:
                return service
        return None

    def all_unsupported(self) -> list[CicsUnsupportedConstruct]:
        """All unsupported constructs across services, in service order."""
        result: list[CicsUnsupportedConstruct] = []
        for service in self.services:
            result.extend(service.unsupported_constructs)
        return result

    def all_issues(self) -> list[CicsMappingIssue]:
        """All mapping issues across services, in service order."""
        result: list[CicsMappingIssue] = []
        for service in self.services:
            result.extend(service.issues)
        return result

    def validate(self) -> list[str]:
        """Validate the CICS Spring application model.

        Returns a list of validation errors (empty when valid).
        """
        errors: list[str] = []
        seen_names: set[str] = set()
        for service in self.services:
            if service.service_name in seen_names:
                errors.append(f"Duplicate service name: {service.service_name}")
            seen_names.add(service.service_name)
            if service.is_transactional and not service.transaction_boundaries:
                errors.append(
                    f"Service {service.service_name} is transactional "
                    "but declares no transaction boundary"
                )
            for boundary in service.transaction_boundaries:
                if boundary.kind not in (
                    CicsBoundaryKind.COMMIT,
                    CicsBoundaryKind.ROLLBACK,
                    CicsBoundaryKind.PSEUDO_CONVERSATIONAL,
                ):
                    errors.append(
                        f"Service {service.service_name} has unknown boundary kind "
                        f"{boundary.kind!r}"
                    )
        return errors

    def summary(self) -> dict[str, int]:
        """High-level counts useful for reports and tests."""
        unsupported = len(self.all_unsupported())
        boundaries = sum(len(s.transaction_boundaries) for s in self.services)
        interactions = sum(len(s.program_interactions) for s in self.services)
        accesses = sum(len(s.resource_accesses) for s in self.services)
        return {
            "programs": len(self.services),
            "unsupported": unsupported,
            "boundaries": boundaries,
            "interactions": interactions,
            "resource_accesses": accesses,
        }
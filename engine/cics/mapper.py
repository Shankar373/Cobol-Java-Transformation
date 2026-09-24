"""Mapper: CICS semantic IR (``CicsApplication``) → CICS Java/Spring model.

This is the single boundary that translates the shared CICS IR types from
``engine.transformation.ir`` into the explicit, IR-free output model in
``engine.cics.model``.

Mapping rules are deterministic and source-derived:

- Every ``CicsCommand`` is classified against the supported subset
  (``engine.cics.subset``).
- Mapped commands become explicit terminal I/O, program interaction,
  resource-access, or transaction-boundary elements.
- ``EXPLICIT_ONLY`` constructs (HANDLE CONDITION / HANDLE AID / ASSIGN) are
  carried verbatim and never auto-translated into runtime logic.
- ``UNSUPPORTED`` constructs are recorded with raw text and reason; they are
  never dropped and always surface in the generated service and report.
- Host variables (``:WS-xxx``) are normalized to their name and deduplicated
  per service.

No CICS TS runtime equivalence is claimed.
"""

from __future__ import annotations

from engine.cics.model import (
    CicsBoundaryKind,
    CicsConstructStatus,
    CicsExplicitConstruct,
    CicsExplicitKind,
    CicsFlowStep,
    CicsIssueSeverity,
    CicsMappingIssue,
    CicsProgramInteraction,
    CicsResourceAccess,
    CicsResourceKind,
    CicsRespPolicy,
    CicsService,
    CicsSpringApplication,
    CicsTerminalIo,
    CicsTerminalIoKind,
    CicsTransactionBoundary,
    CicsUnsupportedConstruct,
)
from engine.cics.naming import pascal
from engine.cics.subset import SUPPORTED_SUBSET_VERSION, classify_command
from engine.transformation.ir import (
    CicsApplication,
    CicsCommandType,
    CicsRespHandling,
)

# Commands whose mapped transaction-boundary counterpart is COMMIT / ROLLBACK
# / PSEUDO_CONVERSATIONAL.
_COMMIT_BOUNDARY_COMMANDS = frozenset({CicsCommandType.SYNCPOINT})
_ROLLBACK_BOUNDARY_COMMANDS = frozenset({CicsCommandType.ABEND})
_PSEUDO_CONVERSATIONAL_COMMANDS = frozenset({CicsCommandType.RETURN})

# Signals the generated service is annotated @Transactional (a real unit of
# work exists in the program).
_TRANSACTIONAL_SIGNALS = frozenset(
    {
        CicsCommandType.SYNCPOINT,
        CicsCommandType.ABEND,
        CicsCommandType.RETURN,
        CicsCommandType.WRITE,
        CicsCommandType.REWRITE,
        CicsCommandType.DELETE,
        CicsCommandType.WRITEQ,
        CicsCommandType.DELETEQ,
        CicsCommandType.LINK,
        CicsCommandType.XCTL,
    }
)

_QUEUE_COMMANDS = frozenset(
    {
        CicsCommandType.WRITEQ,
        CicsCommandType.READQ,
        CicsCommandType.DELETEQ,
    }
)

_RESOURCE_COMMANDS = frozenset(
    {
        CicsCommandType.READ,
        CicsCommandType.WRITE,
        CicsCommandType.REWRITE,
        CicsCommandType.DELETE,
        CicsCommandType.STARTBR,
        CicsCommandType.READNEXT,
        CicsCommandType.READPREV,
        CicsCommandType.ENDBR,
    }
)


class CicsSpringMapper:
    """Maps one ``CicsApplication`` (CICS IR) to a ``CicsSpringApplication``.

    When a real COBOL program contains several ``EXEC CICS`` blocks, map each
    block into its own ``CicsApplication`` (via the CICS parser) and merge the
    resulting services with ``CicsSpringMapper.merge``.
    """

    def map(
        self,
        application: CicsApplication,
        *,
        program_id: str | None = None,
        application_id: str = "cics-application",
        base_package: str = "com.generated.cics",
    ) -> CicsSpringApplication:
        """Map a parsed CICS application to an explicit Java/Spring model."""
        source_program = (program_id or application.program_id or "UNKNOWN").strip()
        service_name = f"{pascal(source_program)}Service"
        commands = application.commands
        issues: list[CicsMappingIssue] = []

        flow: list[CicsFlowStep] = []
        terminal_ios: list[CicsTerminalIo] = []
        interactions: list[CicsProgramInteraction] = []
        accesses: list[CicsResourceAccess] = []
        boundaries: list[CicsTransactionBoundary] = []
        unsupported: list[CicsUnsupportedConstruct] = []
        host_variables: list[str] = []
        transactional = False

        for index, command in enumerate(commands):
            ctype = command.command_type
            classification = classify_command(ctype)
            raw = command.raw_text or ""

            if classification.status == CicsConstructStatus.UNSUPPORTED:
                unsupported.append(self._map_unsupported(command))
            elif classification.category == "TERMINAL_IO":
                terminal_ios.append(self._map_terminal_io(command))
            elif classification.category == "PROGRAM_INTERACTION":
                interactions.append(self._map_interaction(command))
                if ctype in _PSEUDO_CONVERSATIONAL_COMMANDS:
                    boundaries.append(self._map_boundary(command, source_program))
            elif classification.category == "RESOURCE_ACCESS":
                accesses.append(self._map_resource_access(command))
            elif classification.category == "BOUNDARY":
                boundaries.append(self._map_boundary(command, source_program))

            if ctype in _TRANSACTIONAL_SIGNALS:
                transactional = True

            for operand in command.operands:
                if operand.is_host_variable:
                    name = operand.value.lstrip(":")
                    if name and name not in host_variables:
                        host_variables.append(name)

            flow.append(
                CicsFlowStep(
                    index=index,
                    status=classification.status,
                    step_kind=ctype.value,
                    detail=self._flow_detail(command),
                    raw_text=raw,
                )
            )

        explicit = self._map_explicit(application)
        issues.extend(self._validate(application, source_program))

        service = CicsService(
            service_name=service_name,
            source_program=source_program,
            package=f"{base_package}.service",
            is_transactional=transactional,
            flow=tuple(flow),
            terminal_ios=tuple(terminal_ios),
            program_interactions=tuple(interactions),
            resource_accesses=tuple(accesses),
            transaction_boundaries=tuple(boundaries),
            explicit_constructs=tuple(explicit),
            unsupported_constructs=tuple(unsupported),
            host_variables=tuple(host_variables),
            issues=tuple(issues),
        )

        return CicsSpringApplication(
            application_id=application_id,
            base_package=base_package,
            services=(service,),
            source_program_ids=(source_program,),
            supported_subset_version=SUPPORTED_SUBSET_VERSION,
        )

    def merge(
        self,
        applications: list[CicsApplication],
        *,
        application_id: str = "cics-application",
        base_package: str = "com.generated.cics",
    ) -> CicsSpringApplication:
        """Merge multiple mapped programs into one application model.

        Each program's parser output (with ``program_id`` set) is mapped
        individually and combined deterministically.
        """
        if not applications:
            return CicsSpringApplication(
                application_id=application_id,
                base_package=base_package,
            )
        mapped = [
            self.map(
                app,
                program_id=app.program_id or None,
                application_id=application_id,
                base_package=base_package,
            )
            for app in applications
        ]
        services: list[CicsService] = []
        source_ids: list[str] = []
        for result in mapped:
            services.extend(result.services)
            for source_id in result.source_program_ids:
                if source_id not in source_ids:
                    source_ids.append(source_id)
        return CicsSpringApplication(
            application_id=application_id,
            base_package=base_package,
            services=tuple(services),
            source_program_ids=tuple(source_ids),
            supported_subset_version=SUPPORTED_SUBSET_VERSION,
        )

    # ------------------------------------------------------------------
    # Command mappers
    # ------------------------------------------------------------------

    def _map_terminal_io(self, command) -> CicsTerminalIo:
        kind = (
            CicsTerminalIoKind.SEND
            if command.command_type == CicsCommandType.SEND
            else CicsTerminalIoKind.RECEIVE
        )
        return CicsTerminalIo(
            kind=kind,
            map_name=command.map_name,
            mapset_name=command.mapset_name,
            terminal_id=self._value_name(command.terminal_id),
            data_field=self._value_name(command.into_field or command.from_field),
            length_field=self._value_name(command.length_field),
            transaction_id=self._value_name(command.transaction_id),
            raw_text=command.raw_text or "",
        )

    def _map_interaction(self, command) -> CicsProgramInteraction:
        kind = command.command_type.value  # LINK / XCTL / RETURN
        return CicsProgramInteraction(
            kind=kind,
            program=self._value_name(command.program_name),
            commarea=self._value_name(command.commarea_data),
            commarea_length=self._value_name(command.commarea_length),
            channel=command.channel_name,
            containers=tuple(command.container_names),
            transaction_id=self._value_name(command.transaction_id),
            raw_text=command.raw_text or "",
        )

    def _map_boundary(self, command, program_id: str) -> CicsTransactionBoundary:
        if command.command_type in _COMMIT_BOUNDARY_COMMANDS:
            kind = CicsBoundaryKind.COMMIT
        elif command.command_type in _ROLLBACK_BOUNDARY_COMMANDS:
            kind = CicsBoundaryKind.ROLLBACK
        else:
            kind = CicsBoundaryKind.PSEUDO_CONVERSATIONAL
        return CicsTransactionBoundary(
            kind=kind,
            program_id=program_id,
            transaction_id=self._value_name(command.transaction_id),
            commarea=self._value_name(command.commarea_data),
            raw_text=command.raw_text or "",
        )

    def _map_resource_access(self, command) -> CicsResourceAccess:
        resource_kind = (
            CicsResourceKind.QUEUE
            if command.command_type in _QUEUE_COMMANDS
            else CicsResourceKind.FILE
        )
        resp_policy, resp_field, resp2_field = self._resp_policy(command)
        return CicsResourceAccess(
            operation=command.command_type.value,
            resource_kind=resource_kind,
            resource=self._value_name(command.resource_name),
            key_field=self._value_name(command.key_field or command.rid_field),
            data_field=self._value_name(command.into_field or command.from_field),
            length_field=self._value_name(command.length_field),
            resp_field=resp_field,
            resp2_field=resp2_field,
            resp_policy=resp_policy,
            raw_text=command.raw_text or "",
        )

    def _map_unsupported(self, command) -> CicsUnsupportedConstruct:
        return CicsUnsupportedConstruct(
            command=command.command_type.value,
            raw_text=command.raw_text or "",
            reason=(
                f"Command {command.command_type.value} is outside the supported "
                "CICS subset (see engine.cics.subset). Kept explicit; not "
                "translated to runtime behavior."
            ),
        )

    def _map_explicit(self, application: CicsApplication) -> list[CicsExplicitConstruct]:
        """Carry HANDLE CONDITION / HANDLE AID / ASSIGN structures verbatim."""
        explicit: list[CicsExplicitConstruct] = []

        for condition in application.handle_conditions:
            explicit.append(CicsExplicitConstruct(
                kind=CicsExplicitKind.HANDLE_CONDITION,
                raw_text=f"HANDLE CONDITION {condition.condition.value}"
                f"({condition.paragraph})",
                details=(f"{condition.condition.value}({condition.paragraph})",),
            ))

        for aid in application.handle_aids:
            explicit.append(CicsExplicitConstruct(
                kind=CicsExplicitKind.HANDLE_AID,
                raw_text=f"HANDLE AID {aid.aid_type.value}({aid.paragraph})",
                details=(f"{aid.aid_type.value}({aid.paragraph})",),
            ))

        for assignment in application.assignments:
            explicit.append(CicsExplicitConstruct(
                kind=CicsExplicitKind.ASSIGN,
                raw_text=f"ASSIGN {assignment.field}(:{assignment.variable})",
                details=(f"{assignment.field}={assignment.variable}",),
            ))

        return explicit

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(
        self, application: CicsApplication, program_id: str
    ) -> list[CicsMappingIssue]:
        issues: list[CicsMappingIssue] = []
        commands = application.commands
        for index, command in enumerate(commands):
            ctype = command.command_type

            if ctype in _RESOURCE_COMMANDS and not command.resource_name:
                issues.append(CicsMappingIssue(
                    severity=CicsIssueSeverity.ERROR,
                    message=f"{ctype.value} at step {index} is missing a resource name",
                    program_id=program_id,
                ))
            if ctype in _QUEUE_COMMANDS and not command.resource_name:
                issues.append(CicsMappingIssue(
                    severity=CicsIssueSeverity.WARNING,
                    message=f"{ctype.value} at step {index} has no queue name",
                    program_id=program_id,
                ))
            if ctype in (CicsCommandType.LINK, CicsCommandType.XCTL) and not command.program_name:
                issues.append(CicsMappingIssue(
                    severity=CicsIssueSeverity.ERROR,
                    message=f"{ctype.value} at step {index} is missing a PROGRAM name",
                    program_id=program_id,
                ))
            if ctype == CicsCommandType.RETURN and index != len(commands) - 1:
                issues.append(CicsMappingIssue(
                    severity=CicsIssueSeverity.WARNING,
                    message="RETURN is not the final CICS command; subsequent "
                    "commands are outside the pseudo-conversational exchange",
                    program_id=program_id,
                ))

        if commands and commands[-1].command_type != CicsCommandType.RETURN:
            issues.append(CicsMappingIssue(
                severity=CicsIssueSeverity.WARNING,
                message="Program has no trailing RETURN; the pseudo-conversational "
                "boundary is incomplete",
                program_id=program_id,
            ))
        return issues

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _value_name(value: str) -> str:
        """Strip the leading ``:`` from a host variable operand."""
        return value.lstrip(":") if value else ""

    @staticmethod
    def _resp_policy(command):
        if command.resp_handling == CicsRespHandling.RESP_VARIABLE:
            return (
                CicsRespPolicy.RESP_VARIABLE,
                CicsSpringMapper._value_name(command.resp_field),
                CicsSpringMapper._value_name(command.resp2_field),
            )
        if command.resp_handling == CicsRespHandling.RESP2_VARIABLE:
            return (
                CicsRespPolicy.RESP2_VARIABLE,
                CicsSpringMapper._value_name(command.resp_field),
                CicsSpringMapper._value_name(command.resp2_field),
            )
        if command.resp_handling == CicsRespHandling.HANDLE_CONDITION:
            return (
                CicsRespPolicy.HANDLE_CONDITION,
                CicsSpringMapper._value_name(command.resp_field),
                CicsSpringMapper._value_name(command.resp2_field),
            )
        return (
            CicsRespPolicy.NO_HANDLE,
            CicsSpringMapper._value_name(command.resp_field),
            CicsSpringMapper._value_name(command.resp2_field),
        )

    @staticmethod
    def _flow_detail(command) -> str:
        """Primary operand detail for a flow step (map/resource/program)."""
        if command.map_name:
            return command.map_name
        if command.resource_name:
            return command.resource_name
        if command.program_name:
            return command.program_name
        if command.transaction_id:
            return command.transaction_id
        return ""
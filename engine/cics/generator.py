"""Java/Spring source generator for the CICS Java/Spring service model.

Consumes ``CicsSpringApplication`` and emits explicit, deterministic
Java + Spring source representing each CICS program as a Spring service.

Generated artifacts per application:

- ``CicsApplication.java``        — Spring Boot entry point (runner announces
                                    the mapped services; it does NOT execute
                                    CICS runtime behavior).
- ``cics/CicsRuntime.java``       — runtime seam interface (terminal I/O,
                                    resource access, transaction primitives).
- ``client/ProgramClient.java``   — delegation seam for LINK/XCTL targets.
- ``dto/<Program>CommArea.java``  — request/response data holder per program.
- ``service/<Program>Service.java`` — ``@Service`` class per CICS program,
                                    preserving CICS command order in
                                    ``execute()``.
- ``cics-mapping/<app>-CICS-MAPPING.md`` — explicit mapping report including
                                    every unsupported construct verbatim.

Honesty rules (enforced in the generated text):

- **No CICS TS runtime equivalence is claimed.** Every generated source file
  and the mapping report state that IBM CICS Transaction Server runtime
  behavior is not reproduced by this model.
- **Unsupported CICS constructs remain explicit.** They are emitted verbatim
  in the generated service and the mapping report — never dropped.
- Parametric values in seam calls are operand *references* (map / resource /
  host-variable names), never CICS runtime values.

Every generated artifact is deterministic: identical model input always
yields identical source output.
"""

from __future__ import annotations

from engine.cics.model import (
    CicsBoundaryKind,
    CicsConstructStatus,
    CicsGeneratedFile,
    CicsService,
    CicsSpringApplication,
    CicsTerminalIoKind,
)
from engine.cics.naming import camel, pascal

NO_EQUIVALENCE_DISCLAIMER = (
    "NOT CICS TS EQUIVALENCE: this generated representation preserves the\n"
    " *  structural shape of the CICS program (transaction boundaries,\n"
    " *  request/response, program interaction, resource access). It does NOT\n"
    " *  reproduce IBM CICS Transaction Server runtime behavior (RESP codes,\n"
    " *  commarea copy semantics, transaction isolation, pseudo-conversational\n"
    " *  state, terminal I/O)."
)

_RETURN_STEP = "RETURN"
_SYNC_STEP = "SYNCPOINT"
_ABEND_STEP = "ABEND"
_TERMINAL_STEP_KINDS = {CicsTerminalIoKind.RECEIVE, CicsTerminalIoKind.SEND}
_RESOURCE_STEP_KINDS = {
    "READ", "WRITE", "REWRITE", "DELETE", "STARTBR",
    "READNEXT", "READPREV", "ENDBR", "WRITEQ", "READQ", "DELETEQ",
}
_INTERACTION_STEP_KINDS = {"LINK", "XCTL"}


class CicsSpringGenerator:
    """Generate explicit Java/Spring source from a ``CicsSpringApplication``."""

    def generate(self, application: CicsSpringApplication) -> list[CicsGeneratedFile]:
        """Generate the full file set for a CICS application model."""
        files: list[CicsGeneratedFile] = []
        files.append(self._generate_main(application))
        files.append(self._generate_runtime(application))
        files.append(self._generate_program_client(application))
        for service in application.services:
            files.append(self._generate_service(application, service))
            files.append(self._generate_commarea(application, service))
        files.append(self._generate_mapping_report(application))
        return files

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def _generate_main(self, application: CicsSpringApplication) -> CicsGeneratedFile:
        package = application.base_package
        class_name = "CicsApplication"
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        service_names = [service.service_name for service in application.services]
        if service_names:
            runner_params = ", ".join(
                f"{name} {camel(name)}" for name in service_names
            )
            runner_body = (
                "            // Runtime seams are NOT implemented by default. Provide a\n"
                "            // CicsRuntime / ProgramClient implementation to replay the\n"
                "            // mapped flows.\n"
                f"            System.out.println(\"CICS application ready (services: "
                f"{', '.join(service_names)}).\");"
            )
        else:
            runner_params = ""
            runner_body = (
                '            System.out.println("CICS application ready (no services mapped).");'
            )

        runner = f"""
    @Bean
    CommandLineRunner cicsReplayRunner({runner_params}) {{
        return args -> {{
{runner_body}
        }};
    }}"""

        imports = "".join(
            f"import {package}.service.{name};\n" for name in service_names
        )

        source = f"""package {package};

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
{imports}
/**
 * CICS modernization entry point.
 *
 * {NO_EQUIVALENCE_DISCLAIMER}
 */
@SpringBootApplication
public class {class_name} {{

    public static void main(String[] args) {{
        SpringApplication.run({class_name}.class, args);
    }}
{runner}
}}
"""
        return CicsGeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    # ------------------------------------------------------------------
    # Runtime seam
    # ------------------------------------------------------------------

    def _generate_runtime(self, application: CicsSpringApplication) -> CicsGeneratedFile:
        package = f"{application.base_package}.cics"
        class_name = "CicsRuntime"
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        terminal_ios = [
            io
            for service in application.services
            for io in service.terminal_ios
        ]
        receives = [io for io in terminal_ios if io.kind == CicsTerminalIoKind.RECEIVE]
        sends = [io for io in terminal_ios if io.kind == CicsTerminalIoKind.SEND]
        ops = sorted({access.operation.lower() for service in application.services
                      for access in service.resource_accesses})
        boundaries = [b for service in application.services
                      for b in service.transaction_boundaries]
        has_commit = any(b.kind == CicsBoundaryKind.COMMIT for b in boundaries)
        has_rollback = any(b.kind == CicsBoundaryKind.ROLLBACK for b in boundaries)
        has_return = any(
            b.kind == CicsBoundaryKind.PSEUDO_CONVERSATIONAL for b in boundaries
        )

        lines = [
            f"package {package};",
            "",
            "/**",
            " * CICS runtime adapter seam.",
            " *",
            f" * {NO_EQUIVALENCE_DISCLAIMER}",
            " *",
            " * Parameter values carry operand references (map name, resource name,",
            " * host-variable name), never CICS runtime values. Implementing this",
            " * interface is a manual, reviewed step - it is never auto-generated.",
            " */",
            f"public interface {class_name} {{",
        ]

        section = False
        if receives or sends:
            lines.append("")
            lines.append("    // -- Terminal I/O (request/response) --")
            if receives:
                lines.append("    void receive(String mapName);")
                if any(io.data_field or io.length_field for io in receives):
                    lines.append(
                        "    void receive(String mapName, String intoField, String lengthField);"
                    )
            if sends:
                lines.append("    void send(String mapName);")
                if any(io.data_field or io.length_field for io in sends):
                    lines.append(
                        "    void send(String mapName, String fromField, String lengthField);"
                    )
            section = True
        if ops:
            if not section:
                lines.append("")
            lines.append("")
            lines.append("    // -- Resource access (file / temporary-storage queue) --")
            for op in ops:
                lines.append(f"    void {op}(String resource);")
            section = True
        if has_commit or has_rollback or has_return:
            if not section:
                lines.append("")
            lines.append("")
            lines.append("    // -- Transaction boundary --")
            if has_commit:
                lines.append("    void syncpoint();")
            if has_rollback:
                lines.append("    void abend();")
            if has_return:
                lines.append("    void returnControl();")

        # A completely empty seam still exposes the boundary contract.
        if not (receives or sends or ops or boundaries):
            lines.append("")
            lines.append("    // No CICS commands were mapped for this application.")

        lines.append("}")
        source = "\n".join(lines)

        return CicsGeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    # ------------------------------------------------------------------
    # Program client seam
    # ------------------------------------------------------------------

    def _generate_program_client(
        self, application: CicsSpringApplication
    ) -> CicsGeneratedFile:
        package = f"{application.base_package}.client"
        class_name = "ProgramClient"
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        targets: list[tuple[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for service in application.services:
            for interaction in service.program_interactions:
                if interaction.kind not in _INTERACTION_STEP_KINDS:
                    continue
                if not interaction.program:
                    continue
                key = (interaction.kind, interaction.program)
                if key in seen:
                    continue
                method_name = f"{interaction.kind.lower()}{pascal(interaction.program)}"
                targets.append((method_name, interaction))
                seen.add(key)

        lines = [
            f"package {package};",
            "",
            "/**",
            " * Delegation seam for CICS program/service interaction (LINK / XCTL).",
            " *",
            f" * {NO_EQUIVALENCE_DISCLAIMER}",
            " *",
            " * Each method corresponds to a LINK/XCTL target observed in the CICS",
            " * source. The body is the caller's responsibility and must be reviewed",
            " * against the originating CICS interaction.",
            " */",
            f"public interface {class_name} {{",
        ]
        for method_name, interaction in targets:
            lines.append("")
            lines.extend(self._client_method_doc(method_name, interaction))
        if not targets:
            lines.append("")
            lines.append("    // No LINK/XCTL interactions were mapped.")
        lines.append("}")
        source = "\n".join(lines)

        return CicsGeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    @staticmethod
    def _client_method_doc(method_name: str, interaction) -> list[str]:
        return [
            "    /**",
            f"     * {interaction.kind} PROGRAM({interaction.program}).",
            f"     * CICS source: {interaction.raw_text or method_name}",
            "     */",
            f"    void {method_name}();",
        ]

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------

    def _generate_service(
        self,
        application: CicsSpringApplication,
        service: CicsService,
    ) -> CicsGeneratedFile:
        package = service.package
        class_name = service.service_name
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        base = application.base_package
        unsupported_count = len(service.unsupported_constructs)

        lines = [
            f"package {package};",
            "",
            "import org.springframework.stereotype.Service;",
        ]
        if service.is_transactional:
            lines.append("import org.springframework.transaction.annotation.Transactional;")
        lines.extend(
            [
                f"import {base}.cics.CicsRuntime;",
                f"import {base}.client.ProgramClient;",
                "",
                "/**",
                f" * CICS program {service.source_program} mapped to a Spring service.",
                " *",
                f" * {NO_EQUIVALENCE_DISCLAIMER}",
            ]
        )
        if unsupported_count:
            lines.extend(
                [
                    " *",
                    f" * Unsupported CICS constructs: {unsupported_count} (kept explicit",
                    " * verbatim below and in the CICS-MAPPING report).",
                ]
            )
        lines.extend(
            [
                " */",
                "@Service",
            ]
        )
        if service.is_transactional:
            lines.append("@Transactional")
        lines.append(f"public class {class_name} {{")
        lines.extend(
            [
                "",
                "    private final CicsRuntime cics;",
                "    private final ProgramClient programClient;",
                "",
                f"    public {class_name}(CicsRuntime cics, ProgramClient programClient) {{",
                "        this.cics = cics;",
                "        this.programClient = programClient;",
                "    }",
                "",
                "    /**",
                "     * CICS program flow - command order preserved.",
                "     * Each step maps one CICS command verbatim.",
                "     */",
                "    public void execute() {",
            ]
        )
        for step in service.flow:
            lines.append(f"        step{step.index}();")
        lines.append("    }")
        lines.extend(self._generate_steps(service))
        if service.explicit_constructs:
            lines.extend(self._generate_explicit_block(service))
        if service.unsupported_constructs:
            lines.extend(self._generate_unsupported_block(service))
        lines.append("}")
        source = "\n".join(lines)

        return CicsGeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    def _generate_steps(self, service: CicsService) -> list[str]:
        """Generate one private step method per mapped flow step.

        Cursors index the grouping arrays in flow order; each rendered step
        also carries the original CICS text verbatim.
        """
        lines: list[str] = []
        io_cursor = 0
        access_cursor = 0
        interaction_cursor = 0
        boundary_cursor = 0
        for step in service.flow:
            lines.append("")
            lines.append(
                f"    /** Step {step.index} - {step.raw_text or step.step_kind} */"
            )
            body, io_cursor, access_cursor, interaction_cursor, boundary_cursor = (
                self._render_step(
                    service,
                    step,
                    io_cursor,
                    access_cursor,
                    interaction_cursor,
                    boundary_cursor,
                )
            )
            lines.append(f"    private void step{step.index}() {{")
            lines.append(f"        {body}")
            lines.append("    }")
        return lines

    def _render_step(
        self,
        service: CicsService,
        step,
        io_cursor: int,
        access_cursor: int,
        interaction_cursor: int,
        boundary_cursor: int,
    ) -> tuple[str, int, int, int, int]:
        kind = step.step_kind
        status = step.status

        if status == CicsConstructStatus.EXPLICIT_ONLY:
            return (
                f"// explicit-only ({kind}); not translated to runtime behavior",
                io_cursor,
                access_cursor,
                interaction_cursor,
                boundary_cursor,
            )

        if status == CicsConstructStatus.UNSUPPORTED:
            return (
                f"// CICS-UNSUPPORTED: {step.raw_text or kind}",
                io_cursor,
                access_cursor,
                interaction_cursor,
                boundary_cursor,
            )

        if kind in _TERMINAL_STEP_KINDS:
            io = service.terminal_ios[io_cursor]
            io_cursor += 1
            method = kind.lower()
            if io.data_field or io.length_field:
                args = ", ".join(
                    self._java_arg(value, quoted=True)
                    for value in (io.map_name, io.data_field, io.length_field)
                )
                return (
                    f"cics.{method}({args});",
                    io_cursor,
                    access_cursor,
                    interaction_cursor,
                    boundary_cursor,
                )
            return (
                f"cics.{method}({self._java_arg(io.map_name, quoted=True)});",
                io_cursor,
                access_cursor,
                interaction_cursor,
                boundary_cursor,
            )

        if kind in _RESOURCE_STEP_KINDS:
            access = service.resource_accesses[access_cursor]
            access_cursor += 1
            return (
                f"cics.{access.operation.lower()}({self._java_arg(access.resource, quoted=True)});",
                io_cursor,
                access_cursor,
                interaction_cursor,
                boundary_cursor,
            )

        if kind in _INTERACTION_STEP_KINDS:
            interaction = service.program_interactions[interaction_cursor]
            interaction_cursor += 1
            method = f"{kind.lower()}{pascal(interaction.program or 'Unknown')}"
            return (
                f"programClient.{method}();  // {kind} PROGRAM({interaction.program or '?'})",
                io_cursor,
                access_cursor,
                interaction_cursor,
                boundary_cursor,
            )

        if kind == _RETURN_STEP:
            # RETURN is classified as program interaction; align its cursor.
            while (
                interaction_cursor < len(service.program_interactions)
                and service.program_interactions[interaction_cursor].kind != "RETURN"
            ):
                interaction_cursor += 1
            if interaction_cursor < len(service.program_interactions):
                interaction_cursor += 1
            return (
                "cics.returnControl();",
                io_cursor,
                access_cursor,
                interaction_cursor,
                boundary_cursor,
            )

        if kind == _SYNC_STEP:
            boundary_cursor = self._advance_boundary(
                service, boundary_cursor, CicsBoundaryKind.COMMIT
            )
            return (
                "cics.syncpoint();",
                io_cursor,
                access_cursor,
                interaction_cursor,
                boundary_cursor,
            )

        if kind == _ABEND_STEP:
            boundary_cursor = self._advance_boundary(
                service, boundary_cursor, CicsBoundaryKind.ROLLBACK
            )
            return (
                "cics.abend();",
                io_cursor,
                access_cursor,
                interaction_cursor,
                boundary_cursor,
            )

        return (
            f"// unmapped ({kind}); kept explicit",
            io_cursor,
            access_cursor,
            interaction_cursor,
            boundary_cursor,
        )

    @staticmethod
    def _advance_boundary(service: CicsService, cursor: int, kind: str) -> int:
        """Advance the boundaries cursor past a boundary of the given kind."""
        while cursor < len(service.transaction_boundaries):
            boundary = service.transaction_boundaries[cursor]
            if boundary.kind == kind:
                return cursor + 1
            cursor += 1
        return cursor

    @staticmethod
    def _java_arg(value: str, quoted: bool) -> str:
        if not value:
            return "null"
        if quoted:
            return repr(value)
        return value

    def _generate_explicit_block(self, service: CicsService) -> list[str]:
        lines = [
            "",
            "    // -- CICS constructs carried explicitly (never auto-translated) --",
        ]
        for construct in service.explicit_constructs:
            lines.append(f"    // {construct.raw_text}")
        return lines

    def _generate_unsupported_block(self, service: CicsService) -> list[str]:
        lines = [
            "",
            "    // -- CICS constructs outside the supported subset (kept explicit) --",
            "    // They are NOT translated to runtime behavior and MUST be reviewed.",
        ]
        for construct in service.unsupported_constructs:
            lines.append(
                f"    // CICS-UNSUPPORTED [{construct.command}]: {construct.raw_text}"
            )
            lines.append(f"    //   reason: {construct.reason}")
        return lines

    # ------------------------------------------------------------------
    # CommArea DTO
    # ------------------------------------------------------------------

    def _generate_commarea(
        self,
        application: CicsSpringApplication,
        service: CicsService,
    ) -> CicsGeneratedFile:
        package = f"{application.base_package}.dto"
        class_name = f"{pascal(service.source_program)}CommArea"
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        fields = list(service.host_variables)
        lines = [
            f"package {package};",
            "",
            "/**",
            f" * Request/response data holder for CICS program {service.source_program}.",
            " *",
            " * NOT CICS TS EQUIVALENCE: this generated representation preserves the",
            " *  structural shape of the CICS program (transaction boundaries,",
            " *  request/response, program interaction, resource access). It does NOT",
            " *  reproduce IBM CICS Transaction Server runtime behavior (RESP codes,",
            " *  commarea copy semantics, transaction isolation, pseudo-conversational",
            " *  state, terminal I/O).",
            " *",
            " * Field names are derived from COBOL host variables used in the CICS",
            " * statements. COBOL PIC layouts are not present in the CICS IR and are",
            " * deliberately NOT re-invented here.",
            " */",
            f"public class {class_name} {{",
        ]
        for field in fields:
            field_name = camel(field)
            getter_literal = pascal(field)
            lines.extend(
                [
                    f"    private String {field_name};",
                    "",
                    f"    public String get{getter_literal}() {{",
                    f"        return this.{field_name};",
                    "    }",
                    "",
                    f"    public void set{getter_literal}(String {field_name}) {{",
                    f"        this.{field_name} = {field_name};",
                    "    }",
                    "",
                ]
            )
        lines.append("}")
        source = "\n".join(lines)

        return CicsGeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    # ------------------------------------------------------------------
    # Mapping report
    # ------------------------------------------------------------------

    def _generate_mapping_report(
        self, application: CicsSpringApplication
    ) -> CicsGeneratedFile:
        lines = [
            f"# CICS Java/Spring Mapping Report - {application.application_id}",
            "",
            NO_EQUIVALENCE_DISCLAIMER.replace(" *", ""),
            "",
            f"- Supported subset version: {application.supported_subset_version}",
            f"- Generator version: {application.generator_version}",
            f"- Programs: {len(application.services)}",
            "",
            "## Services",
            "",
        ]
        for service in application.services:
            lines.extend(self._report_service(service))
        lines.append("## Unsupported constructs (explicit, not translated)")
        lines.append("")
        unsupported = application.all_unsupported()
        if not unsupported:
            lines.append("None.")
        for construct in unsupported:
            lines.extend(
                [
                    f"- `{construct.command}` - `{construct.raw_text}`",
                    f"  - {construct.reason}",
                ]
            )
        lines.append("")
        source = "\n".join(lines)
        report_name = f"{application.application_id.lower()}-CICS-MAPPING.md"
        path = f"cics-mapping/{report_name}"
        return CicsGeneratedFile(
            filename=report_name,
            source_code=source,
            class_name="CICS-MAPPING",
            path=path,
        )

    @staticmethod
    def _report_service(service: CicsService) -> list[str]:
        lines = [
            f"### {service.source_program} -> {service.service_name}",
            "",
            f"- Transactional: {service.is_transactional}",
            f"- Flow steps: {len(service.flow)}",
            "",
        ]
        if service.transaction_boundaries:
            lines.append("**Transaction boundaries:**")
            for boundary in service.transaction_boundaries:
                extra = ""
                if boundary.transaction_id:
                    extra = f" (next TRANSID {boundary.transaction_id})"
                lines.append(f"- {boundary.kind}{extra}")
            lines.append("")
        if service.terminal_ios:
            lines.append("**Request/response (terminal I/O):**")
            for io in service.terminal_ios:
                lines.append(f"- {io.kind} {io.raw_text}")
            lines.append("")
        if service.program_interactions:
            lines.append("**Program/service interaction:**")
            for interaction in service.program_interactions:
                lines.append(f"- {interaction.kind} {interaction.raw_text}")
            lines.append("")
        if service.resource_accesses:
            lines.append("**Resource access:**")
            for access in service.resource_accesses:
                lines.append(f"- {access.operation} {access.raw_text}")
            lines.append("")
        if service.explicit_constructs:
            lines.append("**Explicit-only constructs (not translated):**")
            for construct in service.explicit_constructs:
                lines.append(f"- {construct.raw_text}")
            lines.append("")
        if service.has_unsupported:
            lines.append(
                f"**Unsupported constructs:** {len(service.unsupported_constructs)} "
                "(see report section below)"
            )
            lines.append("")
        return lines
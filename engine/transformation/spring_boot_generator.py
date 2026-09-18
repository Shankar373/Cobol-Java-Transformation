"""Spring Boot project generator — produces an executable Spring Boot project.

Consumes SpringBootApplication IR and generates a complete, buildable
Spring Boot project with Maven build configuration.

Architecture:

    SpringBootApplication
        ↓
    SpringBootGenerator
        ↓
    list[GeneratedFile]  (with project-relative paths)

Generator has ZERO imports from:
- engine.transformation.cobol_parser
- engine.transformation.ir
- engine.transformation.cobol_to_java_mapping

Imports only:
- engine.transformation.spring_boot_ir
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from engine.transformation.spring_boot_ir import (
    DataAccessStrategy,
    FileAccessStrategy,
    SpringBootApplication,
    SpringBootAdapter,
    SpringBootAdapterImplementation,
    SpringBootConfiguration,
    SpringBootDependency,
    SpringBootDependencyType,
    SpringBootEntryPoint,
    SpringBootRepository,
    SpringBootRepositoryImplementation,
    SpringBootService,
    SpringBootServiceMethod,
)


@dataclass(frozen=True)
class GeneratedFile:
    """A generated source file with project-relative path."""
    filename: str
    source_code: str
    class_name: str
    path: str = ""  # project-relative path (e.g. "src/main/java/com/app/App.java")


class SpringBootGenerator:
    """Generates a complete Spring Boot project from SpringBootApplication IR.

    This generator consumes ONLY SpringBootApplication.
    It has NO COBOL IR dependency.
    """

    def generate_project(self, application: SpringBootApplication) -> list[GeneratedFile]:
        """Generate a complete Spring Boot project.

        Returns list of GeneratedFile with proper project-relative paths.
        """
        files: list[GeneratedFile] = []

        # Maven build
        files.append(self._generate_pom(application))

        # Application properties
        files.append(self._generate_application_properties(application))

        # Entry point (pass services for batch execution)
        if application.entry_point:
            files.append(self._generate_entry_point(application.entry_point, application.services))

        # Services
        for service in application.services:
            files.append(self._generate_service(service))

        # Repositories (interfaces)
        for repo in application.repositories:
            files.append(self._generate_repository(repo))

        # Repository implementations
        for impl in application.repository_implementations:
            files.append(self._generate_repository_implementation(impl))

        # Adapters (interfaces/components)
        for adapter in application.adapters:
            files.append(self._generate_adapter(adapter))

        # Adapter implementations
        for impl in application.adapter_implementations:
            files.append(self._generate_adapter_implementation(impl))

        # Configuration
        if application.configuration:
            files.append(self._generate_configuration(application.configuration))

        return files

    def generate(self, application: SpringBootApplication) -> list[GeneratedFile]:
        """Backward-compatible: generate source files without project structure."""
        return self.generate_project(application)

    # ================================================================
    # POM GENERATION
    # ================================================================

    def _generate_pom(self, application: SpringBootApplication) -> GeneratedFile:
        """Generate Maven pom.xml from SpringBootDependency list."""
        deps = application.dependencies

        # Map dependency types to Maven scope/group
        dependency_entries: list[str] = []
        for dep in deps:
            group = _maven_group(dep)
            scope = _maven_scope(dep)
            dep_block = f"""        <dependency>
            <groupId>{group}</groupId>
            <artifactId>{dep.name}</artifactId>"""
            if dep.version:
                dep_block += f"""
            <version>{dep.version}</version>"""
            if scope:
                dep_block += f"""
            <scope>{scope}</scope>"""
            dep_block += """
        </dependency>"""
            dependency_entries.append(dep_block)

        dependencies_xml = "\n".join(dependency_entries)

        app_name = application.application_id.lower().replace(" ", "-").replace("_", "-")
        if not app_name:
            app_name = "generated-app"

        pom = f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.5</version>
        <relativePath/>
    </parent>

    <groupId>{application.base_package}</groupId>
    <artifactId>{app_name}</artifactId>
    <version>0.0.1-SNAPSHOT</version>
    <name>{application.application_id}</name>
    <description>Auto-generated from Java Application IR</description>

    <properties>
        <java.version>21</java.version>
    </properties>

    <dependencies>
{dependencies_xml}
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
"""
        return GeneratedFile(
            filename="pom.xml",
            source_code=pom,
            class_name="pom.xml",
            path="pom.xml",
        )

    # ================================================================
    # APPLICATION PROPERTIES
    # ================================================================

    def _generate_application_properties(self, application: SpringBootApplication) -> GeneratedFile:
        """Generate application.properties from configuration."""
        config = application.configuration
        lines = [
            f"# Auto-generated application properties",
            f"spring.application.name={application.application_id.lower().replace(' ', '-')}",
            f"spring.main.banner-mode=off",
            f"logging.level.root=OFF",
        ]

        if config and config.has_database:
            lines.append("# Database configuration — strategy UNSPECIFIED")
            lines.append("# Configure datasource when persistence strategy is selected")

        if config and config.has_web:
            lines.append("server.port=8080")

        source = "\n".join(lines) + "\n"

        return GeneratedFile(
            filename="application.properties",
            source_code=source,
            class_name="application.properties",
            path="src/main/resources/application.properties",
        )

    # ================================================================
    # ENTRY POINT
    # ================================================================

    def _generate_entry_point(
        self,
        entry: SpringBootEntryPoint,
        services: tuple[SpringBootService, ...] = (),
    ) -> GeneratedFile:
        """Generate the Spring Boot main application class.

        For batch programs: generates a CommandLineRunner that injects
        and executes service business logic, then terminates with System.exit().
        For web programs: generates a standard Spring Boot web application.
        """
        class_name = entry.class_name
        package = entry.package
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        # Check if this is a batch program (has business logic services)
        has_services = bool(services)

        if has_services:
            # Batch execution: inject services and execute business logic
            service_fields = []
            service_params = []
            service_assignments = []
            service_calls = []

            for i, svc in enumerate(services):
                field_name = svc.name[0].lower() + svc.name[1:] if svc.name else f"service{i}"
                service_fields.append(f"    private final {svc.name} {field_name};")
                service_params.append(f"{svc.name} {field_name}")
                service_assignments.append(f"        this.{field_name} = {field_name};")
                # Call the first method of each service
                if svc.methods:
                    method = svc.methods[0]
                    params = ", ".join(f"new {ptype.to_source()}()" if hasattr(ptype, 'to_source') else str(ptype) for ptype, pname in method.parameters)
                    service_calls.append(f"            {field_name}.{method.name}({params});")

            fields_block = "\n".join(service_fields) if service_fields else ""
            params_block = ",\n            ".join(service_params) if service_params else ""
            assigns_block = "\n".join(service_assignments) if service_assignments else ""
            calls_block = "\n".join(service_calls) if service_calls else "        System.out.println(\"No business logic to execute.\");"

            imports = [
                "import org.springframework.boot.CommandLineRunner;",
                "import org.springframework.boot.SpringApplication;",
                "import org.springframework.boot.autoconfigure.SpringBootApplication;",
                "import org.springframework.context.annotation.Bean;",
            ]
            for svc in services:
                svc_package = svc.package if hasattr(svc, 'package') and svc.package else package
                imports.append(f"import {svc_package}.{svc.name};")

            imports_block = "\n".join(imports)

            source = f"""package {package};

{imports_block}

/**
 * Spring Boot batch application entry point.
 * Application: {entry.application_name}
 * Auto-generated from Java Application IR.
 * Executes business logic and terminates.
 */
@SpringBootApplication
public class {class_name} {{

{fields_block}

    public {class_name}(
        {params_block}
    ) {{
{assigns_block}
    }}

    public static void main(String[] args) {{
        SpringApplication.run({class_name}.class, args);
    }}

    @Bean
    public CommandLineRunner runner() {{
        return args -> {{
{calls_block}
            System.exit(0);
        }};
    }}
}}
"""
        else:
            # Web execution: standard Spring Boot web application
            source = f"""package {package};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Spring Boot application entry point.
 * Application: {entry.application_name}
 * Auto-generated from Java Application IR.
 */
@SpringBootApplication
public class {class_name} {{

    public static void main(String[] args) {{
        SpringApplication.run({class_name}.class, args);
    }}
}}
"""
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    # ================================================================
    # SERVICES
    # ================================================================

    def _generate_service(self, service: SpringBootService) -> GeneratedFile:
        """Generate a Spring Boot service class with dependency injection and method bodies."""
        class_name = service.name
        package = service.package
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        lines = [
            f"package {package};",
            "",
            "import org.springframework.stereotype.Service;",
        ]

        if service.is_transactional:
            lines.append("import org.springframework.transaction.annotation.Transactional;")

        lines.extend([
            "",
            f"/**",
            f" * Service component for {service.source_program}.",
            f" * Auto-generated from Java Application IR.",
            f" */",
            f"@Service",
        ])

        if service.is_transactional:
            lines.append("@Transactional")

        lines.append(f"public class {class_name} {{")

        # Add field declarations from JavaClass fields
        for field in (service.fields or ()):
            init_val = ""
            if field.initializer:
                init_expr = self._expr_to_string(field.initializer)
                init_val = f" = {init_expr}"
            field_type = field.java_type.to_source() if field.java_type else "Object"
            lines.append(f"    private {field_type} {field.name}{init_val};")

        if service.fields:
            lines.append("")

        # Add dependency injection for each dependency
        for dep in service.depends_on:
            field_name = _to_field_name(dep)
            lines.extend([
                f"    private final {dep} {field_name};",
                "",
            ])

        # Constructor
        if service.depends_on:
            params = ", ".join(
                f"{dep} {_to_field_name(dep)}" for dep in service.depends_on
            )
            lines.extend([
                f"    public {class_name}({params}) {{",
            ])
            for dep in service.depends_on:
                field_name = _to_field_name(dep)
                lines.append(f"        this.{field_name} = {field_name};")
            lines.append("    }")
        else:
            lines.append(f"    public {class_name}() {{}}")

        # Generate method implementations from structured IR
        for method in service.methods:
            lines.append("")
            # Force non-static for Spring beans
            non_static = SpringBootServiceMethod(
                name=method.name,
                return_type=method.return_type,
                parameters=method.parameters,
                body_statements=method.body_statements,
                is_static=False,
                exceptions=method.exceptions,
            )
            lines.extend(self._generate_method_body(non_static))

        lines.extend([
            "",
            "}",
        ])

        source = "\n".join(lines)
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    def _generate_method_body(self, method: SpringBootServiceMethod) -> list[str]:
        """Generate a method implementation from structured IR."""
        # Build method signature
        params_str = ", ".join(
            f"{ptype.to_source()} {pname}" for ptype, pname in method.parameters
        )
        return_type_str = method.return_type.to_source()

        lines = []
        # Method signature
        if method.is_static:
            lines.append(f"    public static {return_type_str} {method.name}({params_str}) {{")
        else:
            lines.append(f"    public {return_type_str} {method.name}({params_str}) {{")

        # Generate method body from structured IR statements
        for stmt in method.body_statements:
            stmt_str = self._stmt_to_string(stmt)
            if stmt_str:
                # Indent each line of the statement
                for stmt_line in stmt_str.split("\n"):
                    lines.append(f"        {stmt_line}")

        lines.append("    }")
        return lines

    def _stmt_to_string(self, stmt) -> str:
        """Convert a Java IR statement to a Java source string."""
        from engine.transformation.java_ir import (
            JavaAssignment, JavaMethodCallStatement, JavaReturn,
            JavaComment, JavaIf, JavaBlock, JavaWhile, JavaFor,
            JavaThrow, JavaLocalVarDecl,
        )
        if isinstance(stmt, JavaAssignment):
            expr_str = self._expr_to_string(stmt.expression)
            if stmt.java_type:
                return f"{stmt.java_type.to_source()} {stmt.target} = {expr_str};"
            return f"{stmt.target} = {expr_str};"
        if isinstance(stmt, JavaLocalVarDecl):
            init_str = ""
            if stmt.initializer:
                init_str = f" = {self._expr_to_string(stmt.initializer)}"
            return f"{stmt.java_type.to_source()} {stmt.name}{init_str};"
        if isinstance(stmt, JavaMethodCallStatement):
            return self._method_call_to_string(stmt.call) + ";"
        if isinstance(stmt, JavaReturn):
            if stmt.expression:
                return f"return {self._expr_to_string(stmt.expression)};"
            return "return;"
        if isinstance(stmt, JavaComment):
            return f"// {stmt.text}"
        if isinstance(stmt, JavaThrow):
            if stmt.message:
                return f'throw new {stmt.exception_class}("{stmt.message}");'
            return f"throw new {stmt.exception_class}();"
        if isinstance(stmt, JavaIf):
            cond = self._expr_to_string(stmt.condition)
            lines = [f"if ({cond}) {{"]
            for s in stmt.then_body:
                inner = self._stmt_to_string(s)
                if inner:
                    for inner_line in inner.split("\n"):
                        lines.append(f"    {inner_line}")
            if stmt.else_body:
                lines.append("} else {")
                for s in stmt.else_body:
                    inner = self._stmt_to_string(s)
                    if inner:
                        for inner_line in inner.split("\n"):
                            lines.append(f"    {inner_line}")
            lines.append("}")
            return "\n".join(lines)
        if isinstance(stmt, JavaWhile):
            cond = self._expr_to_string(stmt.condition)
            lines = [f"while ({cond}) {{"]
            for s in stmt.body:
                inner = self._stmt_to_string(s)
                if inner:
                    for inner_line in inner.split("\n"):
                        lines.append(f"    {inner_line}")
            lines.append("}")
            return "\n".join(lines)
        if isinstance(stmt, JavaFor):
            init_str = self._stmt_to_string(stmt.init) if stmt.init else ""
            cond_str = self._expr_to_string(stmt.condition) if stmt.condition else ""
            update_str = self._stmt_to_string(stmt.update) if stmt.update else ""
            lines = [f"for ({init_str} {cond_str}; {update_str}) {{"]
            for s in stmt.body:
                inner = self._stmt_to_string(s)
                if inner:
                    for inner_line in inner.split("\n"):
                        lines.append(f"    {inner_line}")
            lines.append("}")
            return "\n".join(lines)
        if isinstance(stmt, JavaBlock):
            return "\n".join(self._stmt_to_string(s) for s in stmt.statements)
        return ""

    def _expr_to_string(self, expr) -> str:
        """Convert a Java IR expression to a Java source string."""
        from engine.transformation.java_ir import (
            JavaLiteral, JavaVariableRef, JavaBinaryOp, JavaUnaryOp,
            JavaMethodCall, JavaStringConcat, JavaCast, JavaNewObject,
            JavaTernary,
        )
        if isinstance(expr, JavaLiteral):
            if expr.java_type and expr.java_type.basic_type and \
               expr.java_type.basic_type.value == "String":
                return f'"{expr.value}"'
            if not expr.value.replace(".", "").replace("-", "").isdigit():
                if any(op in expr.value for op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||")):
                    return expr.value
                if not (expr.value.startswith('"') or expr.value.startswith("'")):
                    return f'"{expr.value}"'
            return expr.value
        if isinstance(expr, JavaVariableRef):
            return expr.name
        if isinstance(expr, JavaBinaryOp):
            left = self._expr_to_string(expr.left)
            right = self._expr_to_string(expr.right)
            return f"({left} {expr.operator} {right})"
        if isinstance(expr, JavaUnaryOp):
            operand = self._expr_to_string(expr.operand)
            return f"({expr.operator}{operand})"
        if isinstance(expr, JavaMethodCall):
            return self._method_call_to_string(expr)
        if isinstance(expr, JavaStringConcat):
            parts = []
            for p in expr.parts:
                rendered = self._expr_to_string(p)
                if isinstance(p, JavaLiteral) and not p.java_type:
                    if not rendered.startswith('"'):
                        rendered = f'"{rendered}"'
                parts.append(rendered)
            return " + ".join(parts)
        if isinstance(expr, JavaCast):
            inner = self._expr_to_string(expr.expression)
            return f"({expr.target_type.to_source()}) {inner}"
        if isinstance(expr, JavaNewObject):
            args = ", ".join(self._expr_to_string(a) for a in expr.arguments)
            return f"new {expr.class_name}({args})"
        if isinstance(expr, JavaTernary):
            cond = self._expr_to_string(expr.condition)
            true_str = self._expr_to_string(expr.true_expr)
            false_str = self._expr_to_string(expr.false_expr)
            return f"({cond} ? {true_str} : {false_str})"
        return ""

    def _method_call_to_string(self, call) -> str:
        """Convert a Java IR method call to a Java source string."""
        args = ", ".join(self._expr_to_string(a) for a in call.arguments)
        if call.is_static:
            return f"{call.class_name}.{call.method_name}({args})"
        if call.object_ref:
            return f"{self._expr_to_string(call.object_ref)}.{call.method_name}({args})"
        return f"{call.method_name}({args})"

    # ================================================================
    # REPOSITORIES
    # ================================================================

    def _generate_repository(self, repo: SpringBootRepository) -> GeneratedFile:
        """Generate a data-access repository interface."""
        class_name = repo.name
        package = repo.package
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        source = f"""package {package};

/**
 * Data access repository for {repo.table_name}.
 * Operations: {', '.join(repo.operations)}
 * Strategy: UNSPECIFIED — implementation selected later.
 * Auto-generated from Java Application IR.
 */
public interface {class_name} {{

    // Data access methods to be implemented
}}
"""
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    # ================================================================
    # FILE ADAPTERS
    # ================================================================

    def _generate_adapter(self, adapter: SpringBootAdapter) -> GeneratedFile:
        """Generate a file/resource adapter interface or component."""
        class_name = adapter.name
        package = adapter.package
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        source = f"""package {package};

/**
 * File resource adapter for {adapter.source_resource}.
 * Access mode: {adapter.access_mode}
 * Strategy: UNSPECIFIED — implementation selected later.
 * Auto-generated from Java Application IR.
 */
public interface {class_name} {{

    // File access methods to be implemented
}}
"""
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    # ================================================================
    # REPOSITORY IMPLEMENTATIONS
    # ================================================================

    def _generate_repository_implementation(self, impl: SpringBootRepositoryImplementation) -> GeneratedFile:
        """Generate a repository implementation based on strategy."""
        class_name = impl.name
        package = impl.package
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        if impl.strategy == DataAccessStrategy.UNSPECIFIED:
            return self._generate_unspecified_repository(impl, class_name, package, path)
        elif impl.strategy == DataAccessStrategy.JDBC:
            return self._generate_jdbc_repository(impl, class_name, package, path)
        elif impl.strategy == DataAccessStrategy.JPA:
            return self._generate_jpa_repository(impl, class_name, package, path)
        else:
            return self._generate_unspecified_repository(impl, class_name, package, path)

    def _generate_unspecified_repository(
        self, impl: SpringBootRepositoryImplementation,
        class_name: str, package: str, path: str,
    ) -> GeneratedFile:
        """Generate abstract repository for UNSPECIFIED strategy."""
        lines = [
            f"package {package};",
            "",
            "/**",
            f" * Abstract repository for {impl.table_name}.",
            f" * Strategy: UNSPECIFIED — implementation selected later.",
            f" * Source: {impl.source_repository}",
            f" * Auto-generated from Java Application IR.",
            " */",
            f"public abstract class {class_name} {{",
        ]

        for method in impl.methods:
            params = ", ".join(f"{ptype.to_source()} {pname}" for ptype, pname in method.parameters)
            lines.append(f"")
            lines.append(f"    /** {method.operation_type.value} operation on {method.table_name} */")
            lines.append(f"    public abstract {method.return_type.to_source()} {method.name}({params});")

        if not impl.methods:
            lines.append("")
            lines.append("    // Data access methods to be implemented")

        lines.append("}")
        lines.append("")

        source = "\n".join(lines)
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    def _generate_jdbc_repository(
        self, impl: SpringBootRepositoryImplementation,
        class_name: str, package: str, path: str,
    ) -> GeneratedFile:
        """Generate JDBC repository implementation."""
        lines = [
            f"package {package};",
            "",
            "import java.sql.Connection;",
            "import java.sql.PreparedStatement;",
            "import java.sql.ResultSet;",
            "import java.sql.SQLException;",
            "",
            "/**",
            f" * JDBC repository for {impl.table_name}.",
            f" * Strategy: JDBC.",
            f" * Source: {impl.source_repository}",
            f" * Auto-generated from Java Application IR.",
            " */",
            f"public class {class_name} {{",
            "",
            "    private final Connection connection;",
            "",
            f"    public {class_name}(Connection connection) {{",
            "        this.connection = connection;",
            "    }",
        ]

        for method in impl.methods:
            params = ", ".join(f"{ptype.to_source()} {pname}" for ptype, pname in method.parameters)
            lines.append("")
            lines.append(f"    /** {method.operation_type.value} operation on {method.table_name} */")
            lines.append(f"    public {method.return_type.to_source()} {method.name}({params}) {{")
            lines.append("        // JDBC implementation — parameterized query recommended")
            lines.append(f'        throw new UnsupportedOperationException("JDBC implementation pending for {method.operation_type.value}");')
            lines.append("    }")

        lines.append("}")
        lines.append("")

        source = "\n".join(lines)
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    def _generate_jpa_repository(
        self, impl: SpringBootRepositoryImplementation,
        class_name: str, package: str, path: str,
    ) -> GeneratedFile:
        """Generate JPA repository interface."""
        lines = [
            f"package {package};",
            "",
            "import org.springframework.data.jpa.repository.JpaRepository;",
            "import org.springframework.stereotype.Repository;",
            "",
            "/**",
            f" * JPA repository for {impl.table_name}.",
            f" * Strategy: JPA.",
            f" * Source: {impl.source_repository}",
            f" * Auto-generated from Java Application IR.",
            " */",
            "@Repository",
            f"public interface {class_name} extends JpaRepository<Object, Long> {{",
        ]

        for method in impl.methods:
            if method.operation_type.value == "SELECT":
                lines.append(f"")
                lines.append(f"    /** {method.operation_type.value} operation on {method.table_name} */")
                lines.append(f"    {method.return_type.to_source()} {method.name}({', '.join(f'{ptype.to_source()} {pname}' for ptype, pname in method.parameters)});")

        lines.append("}")
        lines.append("")

        source = "\n".join(lines)
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    # ================================================================
    # FILE ADAPTER IMPLEMENTATIONS
    # ================================================================

    def _generate_adapter_implementation(self, impl: SpringBootAdapterImplementation) -> GeneratedFile:
        """Generate an adapter implementation based on strategy."""
        class_name = impl.name
        package = impl.package
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        if impl.strategy == FileAccessStrategy.UNSPECIFIED:
            return self._generate_unspecified_adapter(impl, class_name, package, path)
        elif impl.strategy == FileAccessStrategy.JAVA_IO:
            return self._generate_javaio_adapter(impl, class_name, package, path)
        elif impl.strategy == FileAccessStrategy.NIO:
            return self._generate_nio_adapter(impl, class_name, package, path)
        else:
            return self._generate_unspecified_adapter(impl, class_name, package, path)

    def _generate_unspecified_adapter(
        self, impl: SpringBootAdapterImplementation,
        class_name: str, package: str, path: str,
    ) -> GeneratedFile:
        """Generate abstract adapter for UNSPECIFIED strategy."""
        lines = [
            f"package {package};",
            "",
            "/**",
            f" * Abstract adapter for {impl.source_resource}.",
            f" * Strategy: UNSPECIFIED — implementation selected later.",
            f" * Access mode: {impl.access_mode}",
            f" * Organization: {impl.file_organization}",
            f" * Source: {impl.source_adapter}",
            f" * Auto-generated from Java Application IR.",
            " */",
            f"public abstract class {class_name} {{",
        ]

        for method in impl.methods:
            params = ", ".join(f"{ptype.to_source()} {pname}" for ptype, pname in method.parameters)
            lines.append(f"")
            lines.append(f"    /** {method.operation_type.value} operation */")
            lines.append(f"    public abstract {method.return_type.to_source()} {method.name}({params});")

        if not impl.methods:
            lines.append("")
            lines.append("    // File access methods to be implemented")

        lines.append("}")
        lines.append("")

        source = "\n".join(lines)
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    def _generate_javaio_adapter(
        self, impl: SpringBootAdapterImplementation,
        class_name: str, package: str, path: str,
    ) -> GeneratedFile:
        """Generate Java IO adapter implementation."""
        lines = [
            f"package {package};",
            "",
            "import java.io.BufferedReader;",
            "import java.io.BufferedWriter;",
            "import java.io.Closeable;",
            "import java.io.FileReader;",
            "import java.io.FileWriter;",
            "import java.io.IOException;",
            "",
            "/**",
            f" * Java IO adapter for {impl.source_resource}.",
            f" * Strategy: JAVA_IO.",
            f" * Access mode: {impl.access_mode}",
            f" * Organization: {impl.file_organization}",
            f" * Source: {impl.source_adapter}",
            f" * Auto-generated from Java Application IR.",
            " */",
            f"public class {class_name} implements Closeable {{",
            "",
            "    private final String filePath;",
            "    private BufferedReader reader;",
            "    private BufferedWriter writer;",
            "",
            f"    public {class_name}(String filePath) {{",
            "        this.filePath = filePath;",
            "    }",
        ]

        if impl.access_mode in ("READ", "READ_WRITE"):
            lines.extend([
                "",
                "    /** Open for reading */",
                "    public void openForRead() throws IOException {",
                f'        this.reader = new BufferedReader(new FileReader(filePath));',
                "    }",
                "",
                "    /** Read a single record */",
                "    public String read() throws IOException {",
                "        if (reader == null) throw new IllegalStateException(\"Not opened for reading\");",
                "        // Record reading — delimiter and width from IR",
                "        return reader.readLine();",
                "    }",
            ])

        if impl.access_mode in ("WRITE", "READ_WRITE", "APPEND"):
            lines.extend([
                "",
                "    /** Open for writing */",
                "    public void openForWrite() throws IOException {",
                f'        this.writer = new BufferedWriter(new FileWriter(filePath));',
                "    }",
                "",
                "    /** Write a single record */",
                "    public void write(String record) throws IOException {",
                "        if (writer == null) throw new IllegalStateException(\"Not opened for writing\");",
                "        writer.write(record);",
                "        writer.newLine();",
                "    }",
            ])

        lines.extend([
            "",
            "    @Override",
            "    public void close() throws IOException {",
            "        if (reader != null) reader.close();",
            "        if (writer != null) writer.close();",
            "    }",
            "}",
            "",
        ])

        source = "\n".join(lines)
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    def _generate_nio_adapter(
        self, impl: SpringBootAdapterImplementation,
        class_name: str, package: str, path: str,
    ) -> GeneratedFile:
        """Generate Java NIO adapter implementation."""
        lines = [
            f"package {package};",
            "",
            "import java.io.Closeable;",
            "import java.io.IOException;",
            "import java.nio.charset.StandardCharsets;",
            "import java.nio.file.Files;",
            "import java.nio.file.Path;",
            "import java.nio.file.Paths;",
            "import java.nio.file.StandardOpenOption;",
            "import java.util.List;",
            "",
            "/**",
            f" * Java NIO adapter for {impl.source_resource}.",
            f" * Strategy: NIO.",
            f" * Access mode: {impl.access_mode}",
            f" * Organization: {impl.file_organization}",
            f" * Source: {impl.source_adapter}",
            f" * Auto-generated from Java Application IR.",
            " */",
            f"public class {class_name} implements Closeable {{",
            "",
            "    private final Path filePath;",
            "",
            f"    public {class_name}(String filePath) {{",
            "        this.filePath = Paths.get(filePath);",
            "    }",
        ]

        if impl.access_mode in ("READ", "READ_WRITE"):
            lines.extend([
                "",
                "    /** Read all records */",
                "    public List<String> readAll() throws IOException {",
                "        return Files.readAllLines(filePath, StandardCharsets.UTF_8);",
                "    }",
                "",
                "    /** Read a single record by index */",
                "    public String readRecord(int index) throws IOException {",
                "        List<String> lines = Files.readAllLines(filePath, StandardCharsets.UTF_8);",
                "        if (index < 0 || index >= lines.size()) {",
                '            throw new IndexOutOfBoundsException("Record index: " + index);',
                "        }",
                "        return lines.get(index);",
                "    }",
            ])

        if impl.access_mode in ("WRITE", "READ_WRITE", "APPEND"):
            open_option = "StandardOpenOption.CREATE, StandardOpenOption.APPEND" if impl.access_mode == "APPEND" else "StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING"
            lines.extend([
                "",
                "    /** Write a single record */",
                "    public void write(String record) throws IOException {",
                f"        Files.write(filePath, (record + System.lineSeparator()).getBytes(StandardCharsets.UTF_8),",
                f"            {open_option});",
                "    }",
                "",
                "    /** Write all records */",
                "    public void writeAll(List<String> records) throws IOException {",
                "        for (String record : records) {",
                "            write(record);",
                "        }",
                "    }",
            ])

        lines.extend([
            "",
            "    @Override",
            "    public void close() throws IOException {",
            "        // NIO resources are managed per-operation",
            "    }",
            "}",
            "",
        ])

        source = "\n".join(lines)
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )

    # ================================================================
    # CONFIGURATION
    # ================================================================

    def _generate_configuration(self, config: SpringBootConfiguration) -> GeneratedFile:
        """Generate Spring Boot application configuration class."""
        class_name = "AppConfig"
        package = f"{config.base_package}.config"
        path = f"src/main/java/{package.replace('.', '/')}/{class_name}.java"

        lines = [
            f"package {package};",
            "",
            "import org.springframework.context.annotation.Configuration;",
            "",
            "/**",
            f" * Application configuration for: {config.application_name}",
            " * Auto-generated from Java Application IR.",
            " */",
            "@Configuration",
            f"public class {class_name} {{",
            "",
            "    // Configuration properties to be implemented",
            "",
            "}",
        ]

        source = "\n".join(lines)
        return GeneratedFile(
            filename=f"{class_name}.java",
            source_code=source,
            class_name=class_name,
            path=path,
        )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _to_field_name(class_name: str) -> str:
    """Convert PascalCase class name to camelCase field name."""
    if not class_name:
        return ""
    return class_name[0].lower() + class_name[1:]


def _maven_group(dep: SpringBootDependency) -> str:
    """Derive Maven groupId for a dependency."""
    if dep.dependency_type == SpringBootDependencyType.CORE:
        return "org.springframework.boot"
    if dep.dependency_type == SpringBootDependencyType.CONTEXT:
        return "org.springframework"
    if dep.dependency_type == SpringBootDependencyType.DATA:
        return "org.springframework"
    if dep.dependency_type == SpringBootDependencyType.FILE_IO:
        return "org.springframework"
    if dep.dependency_type == SpringBootDependencyType.TRANSACTION:
        return "org.springframework"
    if dep.dependency_type == SpringBootDependencyType.TEST:
        return "org.springframework.boot"
    if dep.dependency_type == SpringBootDependencyType.WEB:
        return "org.springframework.boot"
    return "org.springframework"


def _maven_scope(dep: SpringBootDependency) -> str:
    """Derive Maven scope for a dependency."""
    if dep.dependency_type == SpringBootDependencyType.TEST:
        return "test"
    return ""


def compute_project_hash(files: list[GeneratedFile]) -> str:
    """Compute SHA-256 hash of all generated file contents."""
    hasher = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.path):
        hasher.update(f.path.encode())
        hasher.update(f.source_code.encode())
    return hasher.hexdigest()

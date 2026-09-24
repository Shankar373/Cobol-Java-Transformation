"""Application assembler — takes generated Java files and assembles them
into ONE deployable Spring Boot application.

This module:
    1. Collects per-program generated files
    2. Generates a Spring Boot project structure
    3. Creates pom.xml with dependencies
    4. Generates the entry point CommandLineRunner
    5. Generates the ServiceRegistry for multi-program apps
    6. Writes everything to a single output directory

The assembler does NOT transform COBOL. It packages already-generated Java
into a buildable Spring Boot project.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.modernization.transformation_plan import AssemblyPlan
from engine.transformation.java_generator import GeneratedFile


@dataclass(frozen=True)
class AssemblyResult:
    """Result of application assembly."""
    success: bool
    output_path: str
    files_written: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class ApplicationAssembler:
    """Assembles generated Java into a deployable Spring Boot application.

    Usage:
        assembler = ApplicationAssembler()
        result = assembler.assemble(generated_files, assembly_plan, output_dir)
    """

    def assemble(
        self,
        generated_files: tuple[GeneratedFile, ...],
        assembly_plan: AssemblyPlan,
        output_dir: str | Path,
    ) -> AssemblyResult:
        """Assemble generated files into a Spring Boot project."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        files_written: list[str] = []
        errors: list[str] = []

        try:
            # 1. Write program Java files
            for gf in generated_files:
                target = out / gf.filename
                target.write_text(gf.source_code, encoding="utf-8")
                files_written.append(str(target))

            # 2. Generate and write pom.xml if not present
            has_pom = any(gf.filename == "pom.xml" for gf in generated_files)
            if not has_pom:
                pom = self._generate_pom(assembly_plan)
                pom_path = out / "pom.xml"
                pom_path.write_text(pom, encoding="utf-8")
                files_written.append(str(pom_path))

            # 3. Generate application entry point if not present
            has_entry = any(gf.filename.endswith("Application.java") for gf in generated_files)
            if not has_entry and generated_files:
                entry = self._generate_entry_point(assembly_plan, generated_files)
                entry_path = out / f"{assembly_plan.application_name.title().replace('-', '')}Application.java"
                entry_path.write_text(entry, encoding="utf-8")
                files_written.append(str(entry_path))

        except Exception as e:
            errors.append(str(e))
            return AssemblyResult(
                success=False,
                output_path=str(out),
                files_written=tuple(files_written),
                errors=tuple(errors),
            )

        return AssemblyResult(
            success=True,
            output_path=str(out),
            files_written=tuple(files_written),
        )

    def _generate_pom(self, plan: AssemblyPlan) -> str:
        """Generate a Maven pom.xml for the application."""
        app_name = plan.application_name.lower().replace(" ", "-").replace("_", "-")
        if not app_name:
            app_name = "generated-app"

        return f"""<?xml version="1.0" encoding="UTF-8"?>
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

    <groupId>{plan.base_package}</groupId>
    <artifactId>{app_name}</artifactId>
    <version>0.0.1-SNAPSHOT</version>
    <name>{plan.application_name}</name>
    <description>Auto-generated from COBOL modernization</description>

    <properties>
        <java.version>21</java.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter</artifactId>
        </dependency>
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

    def _generate_entry_point(
        self,
        plan: AssemblyPlan,
        generated_files: tuple[GeneratedFile, ...],
    ) -> str:
        """Generate a Spring Boot entry point CommandLineRunner."""
        class_name = plan.application_name.title().replace("-", "").replace("_", "") + "Application"
        package = plan.base_package

        # Find program class names (exclude ServiceRegistry)
        program_classes = [
            gf.class_name for gf in generated_files
            if gf.class_name != "ServiceRegistry" and gf.filename.endswith(".java")
        ]

        # Build runner body
        runner_lines = []
        for cls in program_classes[:1]:  # Execute the primary program
            runner_lines.append(f"            {cls}.main(args);")

        runner_body = "\n".join(runner_lines) if runner_lines else "        System.out.println(\"No programs to execute.\");"

        return f"""package {package};

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

@SpringBootApplication
public class {class_name} {{

    public static void main(String[] args) {{
        SpringApplication.run({class_name}.class, args);
    }}

    @Bean
    public CommandLineRunner runner() {{
        return args -> {{
{runner_body}
            System.exit(0);
        }};
    }}
}}
"""

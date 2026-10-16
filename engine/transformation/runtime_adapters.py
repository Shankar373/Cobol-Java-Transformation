"""§32 Runtime Adapter Architecture.

The same semantic transformation (single COBOL parser + single Java
IR/mapper — never duplicated) is assembled into different Java runtime
targets through small runtime-specific adapters.  Runtime-specific
behavior lives here; configuration is validated fail-closed so an
unknown value names itself instead of silently falling back to another
target (Master README §32; backlog BL-088/BL-089/BL-090).
"""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

# Master README §32 "Example configuration" — the five keys and their
# supported value sets.  Deliberately narrow: a future build tool,
# packaging, execution mode, or Java version must be added here
# explicitly, never accepted silently.
SUPPORTED_TARGET_RUNTIMES: tuple[str, ...] = (
    "spring_boot",
    "plain_java",
    "jakarta_ee",
)
SUPPORTED_JAVA_VERSIONS: tuple[str, ...] = ("17", "21")
SUPPORTED_BUILD_TOOLS: tuple[str, ...] = ("maven",)
SUPPORTED_PACKAGINGS: tuple[str, ...] = ("jar",)
SUPPORTED_EXECUTION_MODES: tuple[str, ...] = ("batch",)

# Transformation-plan vocabulary for assembly output types.
PLAN_OUTPUT_TYPE_BY_TARGET: dict[str, str] = {
    "spring_boot": "SPRING_BOOT",
    "plain_java": "NATIVE_JAVA",
    "jakarta_ee": "JAKARTA_EE",
}
VALID_PLAN_OUTPUT_TYPES: tuple[str, ...] = tuple(
    PLAN_OUTPUT_TYPE_BY_TARGET.values()
)


class RuntimeAdapterNotImplementedError(ValueError):
    """A well-formed §32 target whose adapter is not implemented yet.

    Subclasses ``ValueError`` so callers can catch configuration and
    implementation gaps uniformly — but the message always distinguishes
    "unknown value" from "known target, adapter pending".
    """


def _require_one_of(field: str, value: str, supported: tuple[str, ...]) -> None:
    if not isinstance(value, str) or value not in supported:
        raise ValueError(
            f"invalid {field}: {value!r} — supported {field} values: "
            f"{', '.join(repr(v) for v in supported)}"
        )


@dataclass(frozen=True)
class RuntimeTargetConfig:
    """§32 runtime-target configuration (example-configuration shape).

    Validation is fail-closed at construction: an unsupported value in
    any field raises ``ValueError`` naming the field, the offending
    value, and the supported set.
    """

    target_runtime: str = "spring_boot"
    java_version: str = "21"
    build_tool: str = "maven"
    packaging: str = "jar"
    execution_mode: str = "batch"

    def __post_init__(self) -> None:
        _require_one_of(
            "target_runtime", self.target_runtime, SUPPORTED_TARGET_RUNTIMES
        )
        _require_one_of("java_version", self.java_version, SUPPORTED_JAVA_VERSIONS)
        _require_one_of("build_tool", self.build_tool, SUPPORTED_BUILD_TOOLS)
        _require_one_of("packaging", self.packaging, SUPPORTED_PACKAGINGS)
        _require_one_of(
            "execution_mode", self.execution_mode, SUPPORTED_EXECUTION_MODES
        )


def plan_output_type_for(target_runtime: str) -> str:
    """Map a configured target to the transformation-plan output type."""
    try:
        return PLAN_OUTPUT_TYPE_BY_TARGET[target_runtime]
    except KeyError:
        raise ValueError(
            f"invalid target_runtime: {target_runtime!r} — supported "
            f"target_runtime values: "
            f"{', '.join(repr(v) for v in SUPPORTED_TARGET_RUNTIMES)}"
        ) from None


@dataclass(frozen=True)
class AssemblyOutcome:
    """Result of a runtime adapter assembling one generated project."""

    project_dir: Path
    entrypoint: str


class RuntimeAdapter(ABC):
    """Assembles shared ``JavaApplication`` IR into one runtime target."""

    target_runtime: ClassVar[str]

    def assemble(
        self,
        java_application: Any,
        *,
        entry_program: str = "",
        copybook_models: Any = (),
        output_prefix: str = "generated-",
        runtime: RuntimeTargetConfig | None = None,
    ) -> AssemblyOutcome:
        runtime = runtime or RuntimeTargetConfig(target_runtime=self.target_runtime)
        return self._assemble(
            java_application,
            entry_program=entry_program,
            copybook_models=copybook_models,
            output_prefix=output_prefix,
            runtime=runtime,
        )

    @abstractmethod
    def _assemble(
        self,
        java_application: Any,
        *,
        entry_program: str,
        copybook_models: Any,
        output_prefix: str,
        runtime: RuntimeTargetConfig,
    ) -> AssemblyOutcome: ...


class SpringBootRuntimeAdapter(RuntimeAdapter):
    """Spring Boot assembly — the original pipeline path (behavior-identical)."""

    target_runtime: ClassVar[str] = "spring_boot"

    def _assemble(
        self,
        java_application: Any,
        *,
        entry_program: str,
        copybook_models: Any,
        output_prefix: str,
        runtime: RuntimeTargetConfig,
    ) -> AssemblyOutcome:
        from engine.transformation.java_to_spring_mapping import (
            map_java_application_to_spring_boot,
        )
        from engine.transformation.spring_boot_generator import SpringBootGenerator

        spring_app = map_java_application_to_spring_boot(
            java_application,
            entry_program=entry_program,
            copybook_models=copybook_models,
        )
        violations = spring_app.validate()
        if violations:
            raise RuntimeError(
                "Spring Boot mapping failed: " + "; ".join(violations)
            )

        files = SpringBootGenerator().generate_project(spring_app)
        if not files:
            raise RuntimeError("Spring Boot generation produced no files")

        project_dir = Path(tempfile.mkdtemp(prefix=output_prefix))
        project_dir.mkdir(parents=True, exist_ok=True)
        resolved_root = project_dir.resolve()
        for gen_file in files:
            rel = getattr(gen_file, "path", "") or gen_file.filename
            parts = [
                p
                for p in Path(rel).parts
                if p not in ("", ".", "..") and ":" not in p
            ]
            if not parts:
                continue
            target = (resolved_root / Path(*parts)).resolve()
            if target != resolved_root and resolved_root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(gen_file.source_code, encoding="utf-8")

        entry = spring_app.entry_point
        entry_fqn = (
            f"{entry.package}.{entry.class_name}"
            if entry and entry.package
            else (entry.class_name if entry else "")
        )
        if not entry_fqn:
            raise RuntimeError("Spring Boot mapping produced no entry point")
        return AssemblyOutcome(project_dir=project_dir, entrypoint=entry_fqn)


# Model package shared by the non-Spring targets (deterministic).
_PLAIN_MODEL_PACKAGE = "com.modernized.app.model"


class PlainJavaRuntimeAdapter(RuntimeAdapter):
    """Plain-Java assembly (BL-089): the SAME shared ``JavaApplication`` IR
    emitted by the single semantic-transform lane, wrapped in a
    dependency-free Maven jar project.

    Scope bound (documented, no universal equivalence claim): this lane
    generates; Phase 9's build+execute lane (offline Maven build in Docker,
    ``java -jar`` execution) produces fresh per-workload oracle-comparison
    evidence for the generated project.  No Spring dependency, wiring, or
    annotation is emitted anywhere in the project.
    """

    target_runtime: ClassVar[str] = "plain_java"

    def _assemble(
        self,
        java_application: Any,
        *,
        entry_program: str,
        copybook_models: Any,
        output_prefix: str,
        runtime: RuntimeTargetConfig,
    ) -> AssemblyOutcome:
        from dataclasses import replace

        from engine.transformation.copybook_model import render_model_class
        from engine.transformation.java_generator import JavaGenerator
        from engine.transformation.java_ir import JavaClass

        generator = JavaGenerator()
        program_files = generator.generate_from_java(java_application)
        if not program_files:
            raise RuntimeError("Plain Java generation produced no files")

        models = tuple(copybook_models or ())
        if not java_application.programs:
            raise RuntimeError("Plain Java assembly requires at least one program")

        # Deterministic entrypoint: requested program, else the first program.
        program_ids = [p.program_id for p in java_application.programs]
        resolved_entry = entry_program.strip() or program_ids[0]
        if resolved_entry not in program_ids:
            raise RuntimeError(
                f"Plain Java entrypoint {resolved_entry!r} is not one of the "
                f"generated programs: {', '.join(program_ids)}"
            )
        entry_class = generator._to_java_class_name(resolved_entry)

        project_dir = Path(tempfile.mkdtemp(prefix=output_prefix))
        project_dir.mkdir(parents=True, exist_ok=True)
        resolved_root = project_dir.resolve()

        def _write(rel_parts: tuple[str, ...], content: str) -> None:
            target = (resolved_root / Path(*rel_parts)).resolve()
            if target != resolved_root and resolved_root not in target.parents:
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        for gen_file in program_files:
            _write(("src", "main", "java", gen_file.filename), gen_file.source_code)

        seen_models: set[str] = set()
        for cls in models:
            if not isinstance(cls, JavaClass) or not cls.name or cls.name in seen_models:
                continue
            seen_models.add(cls.name)
            packaged = (
                cls if cls.package else replace(cls, package=self.model_package)
            )
            rel = (
                "src", "main", "java",
                *packaged.package.split("."),
                f"{packaged.name}.java",
            )
            _write(rel, render_model_class(packaged))

        _write(("pom.xml",), self._render_pom(
            application_id=java_application.application_id,
            entry_class=entry_class,
            java_version=runtime.java_version,
        ))

        return AssemblyOutcome(project_dir=project_dir, entrypoint=entry_class)

    model_package: ClassVar[str] = _PLAIN_MODEL_PACKAGE

    def _render_pom(
        self, *, application_id: str, entry_class: str, java_version: str
    ) -> str:
        return _plain_pom_xml(
            application_id=application_id,
            entry_class=entry_class,
            java_version=java_version,
        )


class JakartaEeRuntimeAdapter(PlainJavaRuntimeAdapter):
    """Jakarta-EE generation profile (BL-090): the SAME shared
    ``JavaApplication`` IR and source shape as ``plain_java``, assembled
    under a distinct Jakarta-EE-marked Maven pom profile.

    Scope bound (documented, no universal equivalence claim): the generated
    dependency-free jar builds/executes offline via the Maven lane with
    fresh per-workload oracle comparison (Phase 9) — no Jakarta EE server
    runtime is claimed and the target is never certified (Rung 0–1).
    """

    target_runtime: ClassVar[str] = "jakarta_ee"
    model_package: ClassVar[str] = "com.modernized.app.jakarta.model"

    def _render_pom(
        self, *, application_id: str, entry_class: str, java_version: str
    ) -> str:
        return _jakarta_pom_xml(
            application_id=application_id,
            entry_class=entry_class,
            java_version=java_version,
        )


def _plain_pom_xml(*, application_id: str, entry_class: str, java_version: str) -> str:
    """Dependency-free Maven jar pom for the plain_java target.

    Zero external dependencies ⇒ no hidden Spring/runtime coupling and a
    buildable shape under §33 (actual build execution is Phase 9 scope).
    """
    artifact = (application_id or "generated-app").lower().replace(" ", "-").replace("_", "-")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>com.modernized.app</groupId>
    <artifactId>{artifact}</artifactId>
    <version>0.0.1-SNAPSHOT</version>
    <name>{application_id}</name>
    <description>Auto-generated plain Java application (target_runtime=plain_java)</description>

    <properties>
        <maven.compiler.release>{java_version}</maven.compiler.release>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>

    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.11.0</version>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-resources-plugin</artifactId>
                <version>3.3.1</version>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.1.2</version>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-jar-plugin</artifactId>
                <version>3.3.0</version>
                <configuration>
                    <archive>
                        <manifest>
                            <mainClass>{entry_class}</mainClass>
                        </manifest>
                    </archive>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
"""


def _jakarta_pom_xml(*, application_id: str, entry_class: str, java_version: str) -> str:
    """Jakarta-EE-marked Maven pom for the jakarta_ee generation profile.

    Structurally distinct from the plain_java pom: Jakarta-EE groupId,
    a default-active ``jakarta-ee`` Maven profile carrying the Jakarta
    API-version marker, and an explicit scope note.  Zero ``<dependency>``
    elements are emitted (no offline Jakarta EE artifacts exist; the
    dependency-free jar builds/executes via the Maven lane — BL-090).
    Lifecycle plugin versions are pinned to those the offline Maven image
    caches, so the offline build resolves deterministically.
    """
    artifact = (application_id or "generated-app").lower().replace(" ", "-").replace("_", "-")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>com.modernized.app.jakarta</groupId>
    <artifactId>{artifact}-jakarta</artifactId>
    <version>0.0.1-SNAPSHOT</version>
    <name>{application_id}-jakarta</name>
    <description>Auto-generated Jakarta EE application profile (target_runtime=jakarta_ee) — dependency-free jar built via the Maven lane with per-workload fresh oracle comparison; no Jakarta EE server runtime claimed</description>

    <properties>
        <maven.compiler.release>{java_version}</maven.compiler.release>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <jakarta.ee.target>jakartaee10</jakarta.ee.target>
    </properties>

    <profiles>
        <profile>
            <id>jakarta-ee</id>
            <activation>
                <activeByDefault>true</activeByDefault>
            </activation>
            <properties>
                <jakarta.ee.profile>true</jakarta.ee.profile>
            </properties>
        </profile>
    </profiles>

    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.11.0</version>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-resources-plugin</artifactId>
                <version>3.3.1</version>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.1.2</version>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-jar-plugin</artifactId>
                <version>3.3.0</version>
                <configuration>
                    <archive>
                        <manifest>
                            <mainClass>{entry_class}</mainClass>
                        </manifest>
                    </archive>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
"""


_ADAPTER_FACTORIES: dict[str, type[RuntimeAdapter]] = {
    "spring_boot": SpringBootRuntimeAdapter,
    "plain_java": PlainJavaRuntimeAdapter,
    "jakarta_ee": JakartaEeRuntimeAdapter,
}


def implemented_target_runtimes() -> tuple[str, ...]:
    """Targets whose assembly adapters currently exist (deterministic order)."""
    return tuple(k for k in SUPPORTED_TARGET_RUNTIMES if k in _ADAPTER_FACTORIES)


def get_runtime_adapter(target_runtime: str) -> RuntimeAdapter:
    """Resolve the assembly adapter for a configured target, fail-closed.

    - unknown value → ``ValueError`` naming the field, value, supported set;
    - known §32 target not yet implemented → ``RuntimeAdapterNotImplementedError``
      naming the target and the implemented set (never a silent spring
      fallback — Master README §32 / BL-088).
    """
    factory = _ADAPTER_FACTORIES.get(target_runtime)
    if factory is not None:
        return factory()
    if target_runtime in SUPPORTED_TARGET_RUNTIMES:
        raise RuntimeAdapterNotImplementedError(
            f"target_runtime {target_runtime!r} is a declared §32 target but "
            f"its assembly adapter is not implemented yet — implemented "
            f"assembly targets: "
            f"{', '.join(repr(v) for v in implemented_target_runtimes())}"
        )
    raise ValueError(
        f"invalid target_runtime: {target_runtime!r} — supported "
        f"target_runtime values: "
        f"{', '.join(repr(v) for v in SUPPORTED_TARGET_RUNTIMES)}"
    )

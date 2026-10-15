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


_ADAPTER_FACTORIES: dict[str, type[RuntimeAdapter]] = {
    "spring_boot": SpringBootRuntimeAdapter,
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

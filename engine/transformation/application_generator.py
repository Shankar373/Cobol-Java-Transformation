"""Application-level transformation orchestration — P0 MVP.

The DISCOVERED application/program structure is the input to transformation.

Per-program transformation boundary:
    Each discovered ``CobolProgramUnit`` is mapped independently
    (``CobolProgram`` -> ``JavaProgram``) via the existing mapping layer and
    produces its own Java class. COBOL source files are NEVER concatenated.

Application assembly:
    The generated programs are assembled into ONE Java application artifact:
    a single project directory containing one generated class per discovered
    program (plus a ``ServiceRegistry`` when more than one program exists).

The output is UNTRUSTED: this module only generates Java source. Equivalence
claims are made exclusively by the validation pipeline (see engine/pipeline).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from engine.transformation.cobol_to_java_mapping import (
    map_cobol_programs_to_application,
)
from engine.transformation.copybook_model import (
    generate_copybook_model_sources,
    prepare_application_copybooks,
)
from engine.transformation.ir import CobolApplication
from engine.transformation.java_generator import GeneratedFile, JavaGenerator
from engine.transformation.java_ir import JavaApplication, JavaClass


@dataclass(frozen=True)
class ApplicationGenerationResult:
    """Result of transforming a discovered COBOL application."""

    success: bool
    generated_files: tuple[GeneratedFile, ...] = ()
    entrypoint: str = ""
    program_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    # The already-created JavaApplication IR from the single
    # map_cobol_programs_to_application() call. Downstream lanes (e.g. the
    # Spring Boot mapping in the API lane) SHOULD reuse this object instead
    # of invoking the mapping a second time. None when generation did not
    # reach the mapping stage.
    java_application: JavaApplication | None = None
    # Shared copybook model classes (M7): one JavaClass per resolved
    # copybook, materialized from copybook semantics. Data holders only —
    # never executable programs, never entrypoint candidates. Empty when
    # the application uses no copybooks.
    copybook_models: tuple[JavaClass, ...] = ()
    # Copybook preparation diagnostics (resolution/merge notes). Errors
    # here fail generation deterministically (see generate()).
    copybook_diagnostics: tuple[str, ...] = ()


def _normalise(name: str) -> str:
    """Normalise a program-id / class name for comparison.

    Case-, dash-, underscore- and whitespace-insensitive ("ALPHA-1",
    "Alpha_1" and "alpha1" all compare equal).
    """
    return re.sub(r"[-_\s]+", "", name or "").upper()


class ApplicationGenerator:
    """Discover-driven, per-program transformation + application assembly."""

    def __init__(self, generator: JavaGenerator | None = None) -> None:
        self._generator = generator or JavaGenerator()

    def generate(
        self,
        application: CobolApplication,
        entrypoint: str = "",
        source_root: str | Path | None = None,
    ) -> ApplicationGenerationResult:
        """Transform all discovered programs and assemble one Java application.

        Args:
            application: the DISCOVERED application structure (program units,
                copybooks, dependency edges) from ApplicationDiscovery.
            entrypoint: requested entrypoint (a COBOL program-id or generated
                class name). Deterministic fallback: the first discovered
                program's class.
            source_root: ingested source tree for COPYBOOK resolution
                (unit source paths are discovery-relative). When omitted,
                resolution falls back to the current working directory.

        Returns:
            ApplicationGenerationResult with one generated class per program
            (plus one shared model class per resolved copybook) and the
            resolved entrypoint class name.

        Copybook materialization (M7): COPY references are resolved to
        their .cpy files and their records merged into the owning program
        IR before mapping. Missing/ambiguous copybooks fail generation
        deterministically with explicit diagnostics — never silently
        skipped. COBOL sources are only read, never concatenated.
        """
        # 0. Materialize copybooks into program IR (no-op when the
        #    application references no copybooks).
        preparation = prepare_application_copybooks(
            application, source_root=source_root
        )
        if preparation.has_errors:
            return ApplicationGenerationResult(
                success=False,
                program_ids=tuple(
                    u.program_id for u in application.programs
                ),
                errors=preparation.error_messages(),
                copybook_diagnostics=preparation.error_messages(),
            )
        materialized = preparation.application

        programs = tuple(
            u.program for u in materialized.programs if u.program is not None
        )
        if not programs:
            return ApplicationGenerationResult(
                success=False,
                errors=("No COBOL programs discovered in application",),
            )

        java_app = map_cobol_programs_to_application(
            programs=programs,
            application_id=materialized.application_id,
            copybooks=materialized.copybooks,
            edges=materialized.edges,
        )

        try:
            files = tuple(self._generator.generate_from_java(java_app))
        except Exception as exc:  # survive no required semantics (honest failure)
            return ApplicationGenerationResult(
                success=False,
                program_ids=tuple(p.program_id for p in programs),
                errors=(f"Java generation failed: {exc}",),
            )

        # Shared copybook model sources (data holders, not programs).
        model_sources = generate_copybook_model_sources(preparation.plans)
        model_files = tuple(
            GeneratedFile(
                filename=Path(path).name,
                source_code=source,
                class_name=plan.class_name,
            )
            for plan, (path, source) in zip(preparation.plans, model_sources)
        )
        files = files + model_files

        if not files:
            return ApplicationGenerationResult(
                success=False,
                program_ids=tuple(p.program_id for p in programs),
                errors=("Java generation produced no files",),
            )

        model_names = {plan.class_name for plan in preparation.plans}
        resolved_entry = self._resolve_entrypoint(
            files, entrypoint, exclude=model_names
        )

        return ApplicationGenerationResult(
            success=True,
            generated_files=files,
            entrypoint=resolved_entry,
            program_ids=tuple(p.program_id for p in programs),
            java_application=java_app,
            copybook_models=tuple(preparation.model_classes),
        )

    @staticmethod
    def _resolve_entrypoint(
        files: tuple[GeneratedFile, ...],
        requested: str,
        exclude: set[str] | frozenset[str] = frozenset(),
    ) -> str:
        """Resolve the application entrypoint class deterministically.

        Only actual COBOL program units may be entrypoints. Excluded names
        (assembly helpers like ``ServiceRegistry`` and M7 shared copybook
        ``*Record`` model classes) are never selected, even when explicitly
        requested.
        """
        candidates = [f.class_name for f in files]
        program_classes = [
            name
            for name in candidates
            if name != "ServiceRegistry" and name not in exclude
        ] or [name for name in candidates if name not in exclude]

        if not program_classes:
            return ""

        requested_class = requested.strip() if requested else ""
        if requested_class:
            for name in program_classes:
                if _normalise(name) == _normalise(requested_class):
                    return name

        # Deterministic fallback: first discovered program's class.
        return program_classes[0]

    @staticmethod
    def write_to_directory(
        files: tuple[GeneratedFile, ...] | ApplicationGenerationResult,
        output_dir: str | Path,
    ) -> Path:
        """Write all generated files of an application into one project dir.

        Accepts either an ``ApplicationGenerationResult`` or a tuple/list of
        ``GeneratedFile``. Filenames are sanitised to their basename so a
        malicious filename can never escape ``output_dir`` (Zip-Slip style
        traversal). Nothing is written outside the requested directory.
        """
        if isinstance(files, ApplicationGenerationResult):
            gen_files: tuple[GeneratedFile, ...] = files.generated_files
        else:
            gen_files = tuple(files)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        resolved_out = out.resolve()
        for gen_file in gen_files:
            # Basename-only: strip any directory components from the filename.
            safe_name = Path(gen_file.filename).name
            if not safe_name:
                continue
            target = (resolved_out / safe_name).resolve()
            # Belt-and-braces: refuse anything that escapes the output dir.
            if target != resolved_out and resolved_out not in target.parents:
                continue
            target.write_text(gen_file.source_code, encoding="utf-8")
        return out
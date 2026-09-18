"""JCL application discovery and COBOL integration.

Discovers JCL job structures and links them to COBOL programs.
Provides:
- JCL file discovery from directories
- JCL parsing and IR construction
- JCL ↔ COBOL program linking
- Dataset ↔ file linking
- Combined dependency graph

Architecture:

    JCL Source Directory
        ↓
    JCL Discovery
        ↓
    JclApplication
        ├── JclJob
        │   ├── JclStep
        │   │   ├── JclExec (PGM/PROC)
        │   │   ├── JclDD (datasets)
        │   │   └── JclCondition
        │   └── step order
        └── JclDependency graph

    JclApplication + CobolApplication
        ↓
    Combined dependency graph with:
        JCL_EXEC, JCL_DD, JCL_STEP_ORDER
        CALL, COPY, FILE_READ, FILE_WRITE
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.jcl_parser import JclParser
from engine.transformation.ir import (
    CobolApplication,
    JclApplication,
    JclDependency,
    JclJob,
)


class JclDiscovery:
    """Discovers JCL application structure and links to COBOL.

    Usage:
        discovery = JclDiscovery()
        jcl_app = discovery.discover(jcl_directory)
        combined = discovery.link_with_cobol(jcl_app, cobol_app)
    """

    def __init__(self, parser: JclParser | None = None) -> None:
        self._parser = parser or JclParser()

    def discover(
        self,
        source_dir: str | Path,
    ) -> JclApplication:
        """Discover JCL application structure from a source directory.

        Args:
            source_dir: directory containing JCL source files

        Returns:
            JclApplication with discovered jobs and dependencies
        """
        source_path = Path(source_dir)
        if not source_path.exists():
            raise ValueError(f"Source directory does not exist: {source_dir}")

        # Find all JCL files
        jcl_files = self._find_jcl_files(source_path)

        if not jcl_files:
            return JclApplication(source_path=str(source_path))

        # Parse each JCL file
        jobs: list[JclJob] = []
        for jcl_file in jcl_files:
            try:
                source = jcl_file.read_text(encoding="utf-8")
                job = self._parser.parse(source)
                jobs.append(JclJob(
                    name=job.name,
                    parameters=job.parameters,
                    steps=job.steps,
                    comments=job.comments,
                    source_path=str(jcl_file.relative_to(source_path)),
                ))
            except Exception:
                continue

        # Build dependencies
        dependencies = self._build_dependencies(jobs)

        return JclApplication(
            jobs=tuple(jobs),
            dependencies=tuple(dependencies),
            source_path=str(source_path),
        )

    def link_with_cobol(
        self,
        jcl_app: JclApplication,
        cobol_app: CobolApplication,
    ) -> JclApplication:
        """Link JCL application with COBOL application.

        Creates dependencies for:
        - JCL EXEC PGM → COBOL PROGRAM-ID
        - JCL DD DSN → COBOL file dependency

        Args:
            jcl_app: discovered JCL application
            cobol_app: discovered COBOL application

        Returns:
            JclApplication with COBOL links added
        """
        dependencies = list(jcl_app.dependencies)

        # Build program ID lookup
        known_programs = {p.program_id for p in cobol_app.programs}

        # Build file dependency lookup: dataset_name → (program_id, file_name)
        file_lookup: dict[str, tuple[str, str]] = {}
        for program in cobol_app.programs:
            for fd in program.file_dependencies:
                file_lookup[fd.file_name] = (program.program_id, fd.file_name)

        # Link JCL steps to COBOL programs
        for job in jcl_app.jobs:
            for step in job.steps:
                if step.exec_ and step.exec_.program:
                    program_id = step.exec_.program
                    if program_id in known_programs:
                        dependencies.append(JclDependency(
                            source=f"{job.name}.{step.name}",
                            target=program_id,
                            dependency_type="COBOL_PROGRAM",
                            metadata="resolution=RESOLVED",
                        ))
                    else:
                        dependencies.append(JclDependency(
                            source=f"{job.name}.{step.name}",
                            target=program_id,
                            dependency_type="COBOL_PROGRAM",
                            metadata="resolution=UNRESOLVED",
                        ))

                # Link DD datasets to COBOL files
                for dd in step.dd_statements:
                    if dd.dataset:
                        # Try to match dataset to COBOL file
                        for file_key, (prog_id, file_name) in file_lookup.items():
                            if dd.dataset.upper() in file_name.upper() or file_name.upper() in dd.dataset.upper():
                                dependencies.append(JclDependency(
                                    source=f"{job.name}.{step.name}.{dd.name}",
                                    target=f"{prog_id}.{file_name}",
                                    dependency_type="COBOL_FILE",
                                    metadata=f"dsn={dd.dataset}",
                                ))

        return JclApplication(
            jobs=jcl_app.jobs,
            procedures=jcl_app.procedures,
            symbols=jcl_app.symbols,
            dependencies=tuple(dependencies),
            source_path=jcl_app.source_path,
        )

    def _find_jcl_files(self, source_path: Path) -> list[Path]:
        """Find all JCL source files in the directory tree."""
        jcl_extensions = {".jcl", ".JCL", ".jcllib"}
        jcl_files: list[Path] = []

        for ext in jcl_extensions:
            jcl_files.extend(source_path.rglob(f"*{ext}"))

        # Also check for files with no extension that look like JCL
        for f in source_path.rglob("*"):
            if f.is_file() and f.suffix == "":
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    # JCL typically starts with //
                    if content.lstrip().startswith("//"):
                        jcl_files.append(f)
                except Exception:
                    continue

        return sorted(set(jcl_files))

    def _build_dependencies(
        self,
        jobs: list[JclJob],
    ) -> list[JclDependency]:
        """Build all dependencies from parsed jobs."""
        dependencies: list[JclDependency] = []

        for job in jobs:
            # Step order dependencies
            for i in range(len(job.steps) - 1):
                current = job.steps[i]
                next_step = job.steps[i + 1]

                if current.condition is None:
                    dependencies.append(JclDependency(
                        source=current.name,
                        target=next_step.name,
                        dependency_type="JCL_STEP_ORDER",
                        metadata=f"job={job.name}",
                    ))

            # EXEC program references
            for step in job.steps:
                if step.exec_ and step.exec_.program:
                    dependencies.append(JclDependency(
                        source=f"{job.name}.{step.name}",
                        target=step.exec_.program,
                        dependency_type="JCL_EXEC",
                        metadata=f"job={job.name}",
                    ))

            # DD dataset references
            for step in job.steps:
                for dd in step.dd_statements:
                    if dd.dataset:
                        dependencies.append(JclDependency(
                            source=f"{job.name}.{step.name}.{dd.name}",
                            target=dd.dataset,
                            dependency_type="JCL_DD",
                            metadata=f"disp={dd.disposition}" if dd.disposition else "",
                        ))

        return dependencies

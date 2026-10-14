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

from dataclasses import replace
from pathlib import Path

from engine.transformation.jcl_parser import JclParser
from engine.transformation.ir import (
    CobolApplication,
    JclApplication,
    JclDependency,
    JclJob,
)
from engine.transformation.jcl_dependencies import build_all_dependencies


def _dataset_matches_file(dataset: str, file_key: str) -> bool:
    """Precise dataset↔COBOL-file match (BL-074).

    ``file_key`` is the upper-cased COBOL file name.  A dataset matches
    only when it equals the file name or ends with ``.<file name>``
    (qualified tail, e.g. ``PAY.INPUT`` ↔ ``INPUT``).  Substring
    fragments never match.
    """
    if not file_key:
        return False
    dsn = dataset.upper()
    return dsn == file_key or dsn.endswith("." + file_key)


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
                # One job per JOB statement (multi-job members are split,
                # never merged — BL-072); replace() preserves every field.
                for job in self._parser.parse_jobs(source):
                    jobs.append(replace(
                        job,
                        source_path=str(jcl_file.relative_to(source_path)),
                    ))
            except Exception:
                continue

        # Build dependencies
        dependencies = build_all_dependencies(jobs)

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

        # Index every COBOL file dependency by file name (case-insensitive),
        # keeping ALL programs that declare the same file: a shared file must
        # not silently overwrite its other readers (BL-074).  Empty file
        # names are skipped — they would match every dataset.
        file_lookup: dict[str, list[tuple[str, str]]] = {}
        for program in cobol_app.programs:
            for fd in program.file_dependencies:
                if not fd.file_name:
                    continue
                file_lookup.setdefault(fd.file_name.upper(), []).append(
                    (program.program_id, fd.file_name)
                )

        # Link JCL steps to COBOL programs
        for job in jcl_app.jobs:
            for step in job.steps:
                if step.exec_ and step.exec_.program:
                    program_id = step.exec_.program
                    resolution = (
                        "RESOLVED" if program_id in known_programs else "UNRESOLVED"
                    )
                    dependencies.append(JclDependency(
                        source=f"{job.name}.{step.name}",
                        target=program_id,
                        dependency_type="COBOL_PROGRAM",
                        metadata=f"resolution={resolution}",
                    ))

                # Link DD datasets to COBOL files.  Matching is precise:
                # DSN equals the file name, or DSN ends with ".<file name>"
                # (qualified tail).  Loose bidirectional substring matching
                # produced phantom and wrong-target edges (BL-074).
                for dd in step.dd_statements:
                    if not dd.dataset:
                        continue
                    for file_key, decls in file_lookup.items():
                        if not _dataset_matches_file(dd.dataset, file_key):
                            continue
                        resolution = "AMBIGUOUS" if len(decls) > 1 else "RESOLVED"
                        for prog_id, file_name in decls:
                            dependencies.append(JclDependency(
                                source=f"{job.name}.{step.name}.{dd.name}",
                                target=f"{prog_id}.{file_name}",
                                dependency_type="COBOL_FILE",
                                metadata=(
                                    f"dsn={dd.dataset};resolution={resolution}"
                                ),
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
        jcl_exts = {".jcl", ".jcllib"}
        jcl_files: list[Path] = []
        for f in source_path.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() in jcl_exts:
                jcl_files.append(f)
            elif f.suffix == "":
                # Also check for files with no extension that look like JCL
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    # JCL typically starts with //
                    if content.lstrip().startswith("//"):
                        jcl_files.append(f)
                except Exception:
                    continue

        return sorted(set(jcl_files))

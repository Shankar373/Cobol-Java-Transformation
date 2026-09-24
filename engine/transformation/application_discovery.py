"""Multi-program COBOL application discovery.

Discovers and models COBOL applications consisting of multiple programs,
copybooks, and their dependency relationships.

This module provides:
- Application discovery from source directories
- CALL dependency extraction
- COPY dependency extraction
- Entry point discovery
- File dependency discovery
- Dependency graph construction
- Application validation

Architecture:

    Source Directory
        ↓
    Application Discovery
        ↓
    CobolApplication
        ├── CobolProgramUnit (per source file)
        │   ├── CobolProgram (parsed IR)
        │   ├── ProgramCall dependencies
        │   ├── CopybookReference dependencies
        │   └── FileDependency relationships
        └── DependencyEdge graph
"""

from __future__ import annotations

import re
from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import (
    CobolApplication,
    CobolProgram,
    CobolProgramUnit,
    CopybookReference,
    DependencyEdge,
    FileDependency,
    ProgramCall,
)


class ApplicationDiscovery:
    """Discovers COBOL application structure from source files.

    Usage:
        discovery = ApplicationDiscovery()
        app = discovery.discover(source_directory)
    """

    def __init__(self, parser: CobolParser | None = None) -> None:
        self._parser = parser or CobolParser()

    def discover(
        self,
        source_dir: str | Path,
        application_id: str | None = None,
    ) -> CobolApplication:
        """Discover COBOL application structure from a source directory.

        Args:
            source_dir: directory containing COBOL source files
            application_id: explicit application ID (default: directory name)

        Returns:
            CobolApplication with discovered programs and dependencies
        """
        source_path = Path(source_dir)
        if not source_path.exists():
            raise ValueError(f"Source directory does not exist: {source_dir}")

        # Discover all COBOL source files
        cobol_files = self._find_cobol_files(source_path)

        if not cobol_files:
            return CobolApplication(
                application_id=application_id or source_path.name,
                programs=(),
                copybooks=(),
                edges=(),
            )

        # Parse each program
        program_units: list[CobolProgramUnit] = []
        all_copybooks: set[str] = set()

        for cobol_file in cobol_files:
            unit = self._parse_program_unit(cobol_file, source_path)
            if unit is not None:
                program_units.append(unit)
                for cb in unit.copybooks:
                    all_copybooks.add(cb.copybook_name)

        # Build dependency graph
        edges = self._build_dependency_graph(program_units)

        return CobolApplication(
            application_id=application_id or source_path.name,
            programs=tuple(program_units),
            copybooks=tuple(sorted(all_copybooks)),
            edges=tuple(edges),
        )

    def _find_cobol_files(self, source_path: Path) -> list[Path]:
        """Find all COBOL source files in the directory tree."""
        cobol_extensions = {".cob", ".cbl", ".COB", ".CBL"}
        cobol_files: list[Path] = []

        for ext in cobol_extensions:
            cobol_files.extend(source_path.rglob(f"*{ext}"))

        # Also check for files without extension that might be COBOL
        for f in source_path.rglob("*"):
            if f.is_file() and f.suffix == "":
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    if "IDENTIFICATION DIVISION" in content.upper():
                        cobol_files.append(f)
                except Exception:
                    pass

        return sorted(set(cobol_files))

    def _parse_program_unit(
        self,
        cobol_file: Path,
        source_root: Path,
    ) -> CobolProgramUnit | None:
        """Parse a single COBOL file into a program unit."""
        try:
            source = cobol_file.read_text(encoding="utf-8")
            program = self._parser.parse(source)

            # Extract dependencies from source
            calls = self._extract_calls(source, program.program_id)
            copybooks = self._extract_copybooks(source, program.program_id)
            entry_points = self._extract_entry_points(source)
            file_deps = self._extract_file_dependencies(source, program.program_id)

            # Update program with dependency information
            program_with_deps = CobolProgram(
                program_id=program.program_id,
                file_definitions=program.file_definitions,
                working_storage=program.working_storage,
                paragraphs=program.paragraphs,
                threshold_rules=program.threshold_rules,
                input_record_mappings=program.input_record_mappings,
                status_codes=program.status_codes,
                output_formats=program.output_formats,
                lookup_operations=program.lookup_operations,
                match_outcome_labels=program.match_outcome_labels,
                summary_fields=program.summary_fields,
                report_header=program.report_header,
                linkage_section=program.linkage_section,
                using_parameters=program.using_parameters,
                called_programs=tuple(c.target for c in calls),
                copybooks=tuple(cb.copybook_name for cb in copybooks),
                entry_points=tuple(entry_points),
            )

            return CobolProgramUnit(
                program_id=program.program_id,
                source_path=str(cobol_file.relative_to(source_root)),
                program=program_with_deps,
                calls=tuple(calls),
                copybooks=tuple(copybooks),
                entry_points=tuple(entry_points),
                file_dependencies=tuple(file_deps),
            )

        except Exception as e:
            # Log error but continue with other files
            print(f"Warning: Failed to parse {cobol_file}: {e}")
            return None

    def _extract_calls(self, source: str, caller_id: str) -> list[ProgramCall]:
        """Extract CALL statements from COBOL source."""
        calls: list[ProgramCall] = []
        upper = source.upper()

        # Find CALL statements
        call_pattern = re.compile(
            r"CALL\s+(?:\"([^\"]+)\"|\'([^\']+)\'|(\S+))",
            re.IGNORECASE,
        )

        for match in call_pattern.finditer(source):
            target = match.group(1) or match.group(2) or match.group(3)
            target = target.rstrip(".")

            # Check for USING arguments
            rest = source[match.end():]
            using_match = re.search(
                r"USING\s+(.+?)(?:\.|$)",
                rest, re.IGNORECASE,
            )
            arguments = ()
            if using_match:
                args_str = using_match.group(1).strip()
                arguments = tuple(args_str.split())

            is_literal = bool(match.group(1) or match.group(2))
            calls.append(ProgramCall(
                caller=caller_id,
                target=target,
                arguments=arguments,
                call_type="STATIC" if is_literal else "DYNAMIC",
                resolution="UNRESOLVED",
            ))

        return calls

    def _extract_copybooks(self, source: str, source_program: str) -> list[CopybookReference]:
        """Extract COPY statements from COBOL source."""
        copybooks: list[CopybookReference] = []

        # Find COPY statements
        copy_pattern = re.compile(
            r"COPY\s+(\S+)",
            re.IGNORECASE,
        )

        for match in copy_pattern.finditer(source):
            copybook_name = match.group(1).rstrip(".")

            # Skip if it's a REPLACING clause
            if copybook_name.upper() == "REPLACING":
                continue

            copybooks.append(CopybookReference(
                source_program=source_program,
                copybook_name=copybook_name,
            ))

        return copybooks

    def _extract_entry_points(self, source: str) -> list[str]:
        """Extract ENTRY statements from COBOL source."""
        entry_points: list[str] = []

        # Find ENTRY statements
        entry_pattern = re.compile(
            r"ENTRY\s+\"([^\"]+)\"|ENTRY\s+\'([^\']+)\'",
            re.IGNORECASE,
        )

        for match in entry_pattern.finditer(source):
            entry_name = match.group(1) or match.group(2)
            entry_points.append(entry_name)

        return entry_points

    def _extract_file_dependencies(
        self,
        source: str,
        program_id: str,
    ) -> list[FileDependency]:
        """Extract file access dependencies from COBOL source."""
        deps: list[FileDependency] = []

        # Find OPEN statements
        open_pattern = re.compile(
            r"OPEN\s+(INPUT|OUTPUT|I-O|EXTEND)\s+(\S+)",
            re.IGNORECASE,
        )

        for match in open_pattern.finditer(source):
            mode = match.group(1).upper()
            file_name = match.group(2).rstrip(".")
            deps.append(FileDependency(
                program_id=program_id,
                file_name=file_name,
                operation="OPEN",
                mode=mode,
            ))

        # Find READ statements
        read_pattern = re.compile(
            r"READ\s+(\S+)",
            re.IGNORECASE,
        )

        for match in read_pattern.finditer(source):
            file_name = match.group(1).rstrip(".")
            deps.append(FileDependency(
                program_id=program_id,
                file_name=file_name,
                operation="READ",
            ))

        # Find WRITE statements
        write_pattern = re.compile(
            r"WRITE\s+(\S+)",
            re.IGNORECASE,
        )

        for match in write_pattern.finditer(source):
            record_name = match.group(1).rstrip(".")
            deps.append(FileDependency(
                program_id=program_id,
                file_name=record_name,
                operation="WRITE",
            ))

        return deps

    def _build_dependency_graph(
        self,
        program_units: list[CobolProgramUnit],
    ) -> list[DependencyEdge]:
        """Build dependency graph from program units."""
        edges: list[DependencyEdge] = []

        # Build program ID set for resolution
        known_programs = {p.program_id for p in program_units}

        for unit in program_units:
            # Add CALL edges. Dynamic CALLs (CALL data-item) never resolve
            # to a static edge even when the item name coincides with a
            # program-id — the target is a runtime value.
            for call in unit.calls:
                if call.call_type == "DYNAMIC":
                    resolution = "UNRESOLVED"
                else:
                    resolution = "RESOLVED" if call.target in known_programs else "UNRESOLVED"
                edges.append(DependencyEdge(
                    source=unit.program_id,
                    target=call.target,
                    edge_type="CALL",
                    metadata=f"resolution={resolution};call_type={call.call_type}",
                ))

            # Add COPY edges
            for cb in unit.copybooks:
                edges.append(DependencyEdge(
                    source=unit.program_id,
                    target=cb.copybook_name,
                    edge_type="COPY",
                ))

            # Add FILE edges
            for fd in unit.file_dependencies:
                edge_type = "FILE_READ" if fd.operation == "READ" else "FILE_WRITE"
                edges.append(DependencyEdge(
                    source=unit.program_id,
                    target=fd.file_name,
                    edge_type=edge_type,
                    metadata=f"mode={fd.mode}" if fd.mode else "",
                ))

        return edges

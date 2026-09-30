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

import hashlib
import re
from dataclasses import replace
from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.copybook_model import parse_copybook
from engine.transformation.copybook_resolver import (
    AmbiguousCopybookError, CopybookResolutionError, resolve_copybook,
)
from engine.transformation.ir import (
    CobolApplication,
    CobolProgramUnit,
    CopybookReference,
    DependencyEdge,
    DiscoveryIssue,
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
        discovery_issues: list[DiscoveryIssue] = []
        search_dirs = tuple(sorted({source_path, *(p.parent for p in source_path.rglob("*") if p.is_file())}))

        for cobol_file in cobol_files:
            unit = self._parse_program_unit(cobol_file, source_path)
            references = tuple(self._resolve_copybook(cb, search_dirs, source_path) for cb in unit.copybooks)
            unit = replace(unit, copybooks=references)
            program_units.append(unit)
            if unit.status != "PARSED":
                discovery_issues.append(DiscoveryIssue(
                    source_path=unit.source_path,
                    program_id=unit.program_id,
                    status=unit.status,
                    message=unit.diagnostic,
                    source_hash=self._source_hash(cobol_file),
                ))
            for cb in unit.copybooks:
                all_copybooks.add(cb.copybook_name)
                if cb.resolution != "RESOLVED":
                    discovery_issues.append(DiscoveryIssue(
                        source_path=unit.source_path, program_id=unit.program_id,
                        status=f"COPY_{cb.resolution}", message=cb.diagnostic,
                        source_hash=cb.source_hash,
                    ))

        identities: dict[str, list[CobolProgramUnit]] = {}
        for unit in program_units:
            identities.setdefault(unit.program_id.upper(), []).append(unit)
        for identity, units in sorted(identities.items()):
            if len(units) > 1:
                paths = ", ".join(sorted(unit.source_path for unit in units))
                for unit in units:
                    discovery_issues.append(DiscoveryIssue(
                        source_path=unit.source_path, program_id=identity,
                        status="DUPLICATE_PROGRAM_ID",
                        message=f"Duplicate PROGRAM-ID {identity}: {paths}",
                        source_hash=self._source_hash(source_path / unit.source_path),
                    ))

        # Build dependency graph
        edges = self._build_dependency_graph(program_units)

        application = CobolApplication(
            application_id=application_id or source_path.name,
            programs=tuple(program_units),
            copybooks=tuple(sorted(all_copybooks)),
            edges=tuple(edges),
            discovery_complete=not discovery_issues,
            discovery_issues=tuple(discovery_issues),
        )
        for message in application.validate():
            # Duplicate diagnostics above retain every conflicting source.
            # Cycles are valid graph structure, though not necessarily transformable.
            if message.startswith(("Duplicate PROGRAM-ID:", "Cyclic dependency detected:")):
                continue
            discovery_issues.append(DiscoveryIssue(
                source_path="", program_id="", status="INVALID_DEPENDENCY_GRAPH", message=message,
            ))
        return replace(application, discovery_complete=not discovery_issues,
                       discovery_issues=tuple(discovery_issues))

    def _resolve_copybook(
        self, reference: CopybookReference, search_dirs: tuple[Path, ...], source_root: Path,
    ) -> CopybookReference:
        path = None
        try:
            path = resolve_copybook(reference.copybook_name, search_dirs,
                                    program_id=reference.source_program).path
            text = path.read_text(encoding="utf-8")
            if self._extract_copybooks(text, reference.source_program):
                raise ValueError("nested COPY is not yet supported")
            for line_number, line in enumerate(text.splitlines(), start=1):
                code = line.strip()
                if not code or code.startswith(("*", "/")):
                    continue
                if not re.match(
                    r"(?:\d{1,2}\s+[\w-]+|(?:PIC(?:TURE)?|VALUE|USAGE|OCCURS|"
                    r"REDEFINES|SIGN|JUSTIFIED|SYNC(?:HRONIZED)?|INDEXED|DEPENDING)\b)",
                    code, re.IGNORECASE,
                ):
                    raise ValueError(f"Unsupported or invalid copybook data description at line {line_number}")
            model = parse_copybook(path)
            if not model.records:
                raise ValueError("COPY must contain supported data definitions")
            return replace(reference, resolution="RESOLVED",
                           resolved_path=str(path.relative_to(source_root)),
                           source_hash=self._source_hash(path))
        except AmbiguousCopybookError as exc:
            status, message = "AMBIGUOUS", str(exc)
        except CopybookResolutionError as exc:
            status, message = "MISSING", str(exc)
        except (OSError, UnicodeError) as exc:
            status, message = "UNREADABLE", str(exc)
        except ValueError as exc:
            status, message = "INVALID", str(exc)
        return replace(reference, resolution=status,
                       resolved_path=str(path.relative_to(source_root)) if path else "",
                       source_hash=self._source_hash(path) if path else None,
                       diagnostic=f"COPY {reference.copybook_name} at {reference.location}: {message}")

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
                except (OSError, UnicodeError):
                    continue

        return sorted(set(cobol_files))

    @staticmethod
    def _source_hash(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _parse_program_unit(
        self,
        cobol_file: Path,
        source_root: Path,
    ) -> CobolProgramUnit:
        """Parse a single COBOL file; failures remain in the inventory."""
        relative_path = str(cobol_file.relative_to(source_root))
        try:
            source = cobol_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return CobolProgramUnit(program_id=cobol_file.stem.upper() or "UNKNOWN", source_path=relative_path, program=None, status="READ_FAILED", diagnostic=f"Unable to read COBOL source: {exc}")
        try:
            diagnostics = getattr(self._parser, "_diagnostics", None)
            previous_errors = len(diagnostics.errors) if diagnostics is not None else 0
            program = self._parser.parse(source, source_name=relative_path)
            errors = diagnostics.errors[previous_errors:] if diagnostics is not None else []
            if errors:
                raise ValueError("; ".join(f"{error.code.value}: {error.message}" for error in errors))
            if program.program_id == "UNKNOWN":
                return CobolProgramUnit(program_id=cobol_file.stem.upper() or "UNKNOWN", source_path=relative_path, program=None, status="PARSE_FAILED", diagnostic="Parser returned UNKNOWN program identity")

            # Extract dependencies from source
            calls = self._extract_calls(source, program.program_id)
            copybooks = self._extract_copybooks(source, program.program_id)
            entry_points = self._extract_entry_points(source)
            file_deps = self._extract_file_dependencies(source, program.program_id)

            # Update program with dependency information
            program_with_deps = replace(
                program,
                called_programs=tuple(c.target for c in calls),
                copybooks=tuple(cb.copybook_name for cb in copybooks),
                entry_points=tuple(entry_points),
            )

            return CobolProgramUnit(
                program_id=program.program_id,
                source_path=relative_path,
                program=program_with_deps,
                status="PARSED",
                calls=tuple(calls),
                copybooks=tuple(copybooks),
                entry_points=tuple(entry_points),
                file_dependencies=tuple(file_deps),
            )

        except Exception as exc:
            return CobolProgramUnit(program_id=cobol_file.stem.upper() or "UNKNOWN", source_path=relative_path, program=None, status="PARSE_FAILED", diagnostic=f"Failed to parse COBOL source: {exc}")

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

        # Preserve line positions while ignoring comments and quoted text that
        # merely mentions COPY. A directive need not start a physical line.
        source = re.sub(r"(?m)^(?:[ 0-9]{6}[*\/]|\s*\*)[^\n]*", "", source)
        copy_pattern = re.compile(
            r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|\*>[^\n]*|"
            r"\bCOPY\s+(?P<name>[\w-]+|'[^']+'|\"[^\"]+\")",
            re.IGNORECASE,
        )

        for match in copy_pattern.finditer(source):
            if match.group("name") is None:
                continue
            copybook_name = match.group("name").strip("\"'")

            # Skip if it's a REPLACING clause
            if copybook_name.upper() == "REPLACING":
                continue

            copybooks.append(CopybookReference(
                source_program=source_program,
                copybook_name=copybook_name,
                location=str(source.count("\n", 0, match.start()) + 1),
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
            if unit.status != "PARSED" or unit.program is None:
                continue
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
                    metadata=f"resolution={cb.resolution};path={cb.resolved_path};sha256={cb.source_hash or ''}",
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

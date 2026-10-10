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

from engine.transformation.cobol_parser import CobolParser, CobolParseError
from engine.transformation.copybook_resolver import (
    AmbiguousCopybookError,
    CopybookResolutionError,
    resolve_copybook,
)
from engine.transformation.ir import (
    CobolApplication,
    CobolProgram,
    CobolProgramUnit,
    CopybookReference,
    DependencyEdge,
    FileDefinition,
    FileDependency,
    ProgramCall,
)
from engine.transformation.diagnostics import DiagnosticCode

# ---------------------------------------------------------------------------
# File-operation scanning patterns.
#
# Each verb is guarded by ``(?<![\w-])`` so that only a *statement* verb is
# matched.  Without the guard ``READ`` inside ``END-READ`` and ``WRITE``
# inside ``REWRITE`` are silently treated as file statements, which produced
# phantom file dependencies with unresolvable names.
# ---------------------------------------------------------------------------
_FILE_VERB_OPEN = re.compile(
    r"(?<![\w-])OPEN\s+(INPUT|OUTPUT|I-O|EXTEND)\s+([A-Za-z0-9][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)
_FILE_VERB_READ = re.compile(
    r"(?<![\w-])READ\s+([A-Za-z0-9][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)
_FILE_VERB_WRITE = re.compile(
    r"(?<![\w-])WRITE\s+([A-Za-z0-9][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)
_COBOL_STRING_LITERAL = re.compile(r'"[^"\n]*"|' r"'[^'\n]*'")
_COBOL_COMMENT_LINE = re.compile(r"(?m)^[ \t]*\*")
_COBOL_INLINE_COMMENT = re.compile(r"\*>.*$", re.MULTILINE)


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
        discovery_errors: list[str] = []
        all_copybooks: set[str] = set()
        copybook_dirs = self._copybook_search_dirs(source_path)

        for cobol_file in cobol_files:
            unit, error = self._parse_program_unit(
                cobol_file, source_path, copybook_dirs
            )
            if unit is not None:
                program_units.append(unit)
                for cb in unit.copybooks:
                    all_copybooks.add(cb.copybook_name)
            if error is not None:
                discovery_errors.append(error)

        # Build dependency graph
        edges = self._build_dependency_graph(program_units)

        return CobolApplication(
            application_id=application_id or source_path.name,
            programs=tuple(program_units),
            copybooks=tuple(sorted(all_copybooks)),
            edges=tuple(edges),
            discovery_errors=tuple(discovery_errors),
        )

    def _copybook_search_dirs(self, source_path: Path) -> tuple[Path, ...]:
        """Directories searched for COPY targets.

        The resolver is deliberately non-recursive per directory, so every
        directory that holds a source file is offered; the discovery root
        comes first so it wins a precedence tie deterministically.
        """
        dirs: list[Path] = [source_path]
        seen: set[Path] = {source_path.resolve()}
        try:
            candidates = sorted({p.parent for p in source_path.rglob("*") if p.is_file()})
        except OSError:
            candidates = []
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            dirs.append(candidate)
        return tuple(dirs)

    def _find_cobol_files(self, source_path: Path) -> list[Path]:
        """Find all COBOL source files in the directory tree."""
        cobol_exts = {".cob", ".cbl"}
        cobol_files: list[Path] = [
            f
            for f in source_path.rglob("*")
            if f.is_file() and f.suffix.lower() in cobol_exts
        ]

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
        copybook_dirs: tuple[Path, ...] | None = None,
    ) -> tuple[CobolProgramUnit | None, str | None]:
        """Parse a single COBOL file into a program unit.

        Returns ``(unit, error)`` where ``error`` is a discovery_errors entry
        when the file could not be processed at all.

        Fail-closed contract:
        - Files that contain no identifiable COBOL structure (no
          IDENTIFICATION DIVISION / no PROGRAM-ID) are excluded (return
          ``(None, None)``).  These are genuinely not COBOL programs.
        - Files that have a valid COBOL identity but contain unsupported
          sub-constructs (e.g. signed PIC clauses, unsupported divisions) are
          included with a stub IR and source_text preserved so that
          CapabilityAnalyzer can classify them via source scan.  Dropping them
          here would hide them from the capability graph and produce incorrect
          "empty application" results downstream.
        - Files whose bytes cannot be read or decoded as UTF-8 (declared COBOL
          source that cannot even be parsed) are excluded AND recorded as a
          discovery error so downstream pipeline stages fail closed instead of
          presenting a silently incomplete application.
        - Unexpected internal errors are excluded and recorded the same way.
        """
        try:
            source = cobol_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as e:
            # Declared COBOL source that cannot be read or decoded can never
            # be parsed — record it instead of silently shrinking the app.
            print(f"Warning: Cannot read {cobol_file}: {e}")
            return None, (
                f"{cobol_file.relative_to(source_root)}: "
                "COBOL source could not be parsed"
            )

        # Always extract the program ID directly from source text — this is
        # robust even when the full parser fails on unsupported constructs.
        program_id = self._extract_program_id_from_source(source)
        if not program_id:
            # No IDENTIFICATION DIVISION / PROGRAM-ID found — not a COBOL
            # source file; exclude it from discovery (not an error).
            return None, None

        # Snapshot so diagnostics raised by this unit can be attributed to it
        # even though the parser instance is shared across files.
        diags_before = self._parser.diagnostics.all
        parse_diagnostics: tuple[str, ...] = ()

        def _collected_diagnostics() -> tuple[str, ...]:
            # PARTIAL_SUPPORT diagnostics describe a recognised, bounded
            # narrowing (e.g. COMP/COMP-3 byte encoding) that the capability
            # analyzer classifies from IR at PARTIAL.  Feeding them into the
            # loss channel would wrongly force the program to UNSUPPORTED.
            return tuple(
                f"{d.code.name}: {d.message}"
                for d in self._parser.diagnostics.all[len(diags_before):]
                if d.code is not DiagnosticCode.PARTIAL_SUPPORT
            )

        try:
            program = self._parser.parse(source)
            parse_diagnostics = _collected_diagnostics()

            # Extract dependencies from source
            calls = self._extract_calls(source, program.program_id)
            copybooks = self._extract_copybooks(
                source,
                program.program_id,
                search_dirs=copybook_dirs or (source_root, cobol_file.parent),
            )
            entry_points = self._extract_entry_points(source)
            file_deps = self._extract_file_dependencies(
                source,
                program.program_id,
                file_definitions=program.file_definitions,
            )
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
                source_text=source,
                parse_diagnostics=parse_diagnostics,
            ), None

        except CobolParseError as e:
            # The file has valid COBOL identity but contains an unsupported
            # construct that the parser cannot represent in the IR (e.g. a
            # signed PIC clause, an unsupported division).  Do NOT exclude it
            # from the application — that would silently remove it from the
            # capability graph, causing downstream planner/CALL/entrypoint
            # failures.  Instead, register it with a minimal stub IR and
            # preserve source_text so CapabilityAnalyzer can classify it via
            # source scan as UNSUPPORTED.
            print(
                f"Info: {cobol_file} has unsupported construct (will be "
                f"classified UNSUPPORTED by capability analyzer): {e}"
            )
            calls = self._extract_calls(source, program_id)
            copybooks = self._extract_copybooks(
                source,
                program_id,
                search_dirs=copybook_dirs or (source_root, cobol_file.parent),
            )
            entry_points = self._extract_entry_points(source)
            file_deps = self._extract_file_dependencies(source, program_id)
            stub_program = CobolProgram(
                program_id=program_id,
                called_programs=tuple(c.target for c in calls),
                copybooks=tuple(cb.copybook_name for cb in copybooks),
                entry_points=tuple(entry_points),
            )
            return CobolProgramUnit(
                program_id=program_id,
                source_path=str(cobol_file.relative_to(source_root)),
                program=stub_program,
                calls=tuple(calls),
                copybooks=tuple(copybooks),
                entry_points=tuple(entry_points),
                file_dependencies=tuple(file_deps),
                source_text=source,
                parse_error=str(e),
                parse_diagnostics=_collected_diagnostics(),
            ), None

        except Exception as e:
            # Unexpected internal error — we cannot safely process this file.
            # Record it so discovery reports an incomplete application.
            print(f"Warning: Unexpected error parsing {cobol_file}: {e}")
            return None, (
                f"{cobol_file.relative_to(source_root)}: "
                "COBOL source could not be parsed"
            )


    @staticmethod
    def _extract_program_id_from_source(source: str) -> str:
        """Extract PROGRAM-ID directly from COBOL source text.

        Returns the program ID string, or empty string if no IDENTIFICATION
        DIVISION / PROGRAM-ID is found.  This is intentionally a lightweight
        regex scan that does NOT require a full parser pass so it succeeds even
        when the parser would raise CobolParseError.
        """
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("*") or not stripped:
                continue
            # Fixed-format source carries a 6-column sequence number, so the
            # verb does not start the (stripped) line.  Search rather than
            # anchor on the column start, otherwise the file is silently
            # excluded from discovery.
            m = re.search(r"PROGRAM-ID[.\s]+([A-Z0-9][A-Z0-9\-]*)", stripped, re.IGNORECASE)
            if m:
                return m.group(1).rstrip(".").strip()
        return ""

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

    def _extract_copybooks(
        self,
        source: str,
        source_program: str,
        search_dirs: tuple[Path, ...] = (),
    ) -> list[CopybookReference]:
        """Extract COPY statements from COBOL source and resolve them on disk.

        Resolution is recorded, never guessed: a reference is RESOLVED only
        when exactly one candidate matches the resolver's precedence rules.
        """
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

            resolution, resolved_path = self._resolve_copybook(
                copybook_name, source_program, search_dirs
            )
            copybooks.append(CopybookReference(
                source_program=source_program,
                copybook_name=copybook_name,
                resolution=resolution,
                resolved_path=resolved_path,
            ))

        return copybooks

    @staticmethod
    def _resolve_copybook(
        copybook_name: str,
        source_program: str,
        search_dirs: tuple[Path, ...],
    ) -> tuple[str, str]:
        """Resolve one COPY reference.

        Returns ``(resolution, path)`` where resolution is one of
        ``RESOLVED`` / ``UNRESOLVED`` / ``AMBIGUOUS``.
        """
        if not search_dirs:
            return "UNRESOLVED", ""
        try:
            resolved = resolve_copybook(
                copybook_name, search_dirs, program_id=source_program
            )
        except AmbiguousCopybookError:
            return "AMBIGUOUS", ""
        except CopybookResolutionError:
            return "UNRESOLVED", ""
        return "RESOLVED", str(resolved.path)

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
        file_definitions: tuple[FileDefinition, ...] = (),
    ) -> list[FileDependency]:
        """Extract file access dependencies from COBOL source.

        The scanner only considers *statement* verbs.  String literals and
        comment lines are removed first so that ``DISPLAY "READ: ..."`` or
        ``DISPLAY "WRITE/READ DEMO STARTED"`` cannot produce a file
        dependency, and the ``(?<![\\w-])`` guard keeps ``END-READ`` and
        ``REWRITE`` from being read as ``READ`` / ``WRITE``.

        ``WRITE`` (and ``READ`` when the record name is used) names a record,
        not a file.  When the record belongs to a declared ``FD`` the record
        name is resolved to its owning file so that CapabilityAnalyzer can
        evaluate it against the FILE-CONTROL declarations.  Anything that
        cannot be resolved to a declared file is kept verbatim and stays
        fail-closed downstream (``File dependency X has no FILE definition``).
        """
        scan_source = _COBOL_STRING_LITERAL.sub(" ", source)
        scan_source = _COBOL_COMMENT_LINE.sub(" ", scan_source)
        scan_source = _COBOL_INLINE_COMMENT.sub(" ", scan_source)

        record_to_file = {
            fd.record_name: fd.name
            for fd in file_definitions
            if fd.record_name and fd.name
        }

        def _resolve(target: str) -> str:
            return record_to_file.get(target, target)

        deps: list[FileDependency] = []

        for match in _FILE_VERB_OPEN.finditer(scan_source):
            mode = match.group(1).upper()
            file_name = _resolve(match.group(2))
            deps.append(FileDependency(
                program_id=program_id,
                file_name=file_name,
                operation="OPEN",
                mode=mode,
            ))

        for match in _FILE_VERB_READ.finditer(scan_source):
            deps.append(FileDependency(
                program_id=program_id,
                file_name=_resolve(match.group(1)),
                operation="READ",
            ))

        for match in _FILE_VERB_WRITE.finditer(scan_source):
            deps.append(FileDependency(
                program_id=program_id,
                file_name=_resolve(match.group(1)),
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

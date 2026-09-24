"""CICS → Java/Spring mapping facade for the CICS modernization lane.

This module is the primary entry point for the CICS lane.  It:

1. Extracts embedded ``EXEC CICS ... END-EXEC`` blocks from real COBOL source
   and the ``PROGRAM-ID`` of each program.
2. Parses each block with ``engine.transformation.cics_parser.CicsParser``.
3. Maps the resulting CICS IR to the explicit Java/Spring service model
   (``engine.cics.model.CicsSpringApplication``) via ``CicsSpringMapper``.
4. Generates explicit Java/Spring source + a mapping report via
   ``CicsSpringGenerator``.

The shared transformation modules (``cobol_parser``, ``ir``, the mapping and
generator modules, ``pipeline.py``) are NOT modified: this lane stays isolated.

Honesty rules:
- No CICS TS runtime equivalence is claimed.
- Unsupported CICS constructs remain explicit in the model, generated source,
  and report.
"""

from __future__ import annotations

import re

from engine.cics.generator import CicsGeneratedFile, CicsSpringGenerator
from engine.cics.mapper import CicsSpringMapper
from engine.cics.model import CicsSpringApplication
from engine.transformation.cics_parser import CicsParser
from engine.transformation.contracts import GeneratedFile as SharedGeneratedFile
from engine.transformation.ir import CicsApplication

_PROGRAM_ID_RE = re.compile(
    r"PROGRAM-ID\.\s*([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE
)
_EXEC_CICS_RE = re.compile(
    r"EXEC\s+CICS\b(.*?)END-EXEC", re.IGNORECASE | re.DOTALL
)

MAPPER_VERSION = "1.0.0"


class CicsJavaMappingError(Exception):
    """Raised when CICS extraction/mapping cannot be performed."""


def extract_cics_blocks(cobol_source: str) -> list[CicsApplication]:
    """Extract every embedded CICS block from COBOL source.

    Returns one ``CicsApplication`` per ``EXEC CICS ... END-EXEC`` block with
    ``program_id`` set from the enclosing program's ``PROGRAM-ID``.

    Unbalanced blocks (no terminating ``END-EXEC``) are silently treated as
    parse failures: the block is skipped so unsupported text is never invented.
    """
    if not cobol_source:
        return []

    program_id = _detect_program_id(cobol_source)
    parser = CicsParser()
    applications: list[CicsApplication] = []

    for match in _EXEC_CICS_RE.finditer(cobol_source):
        block_text = match.group(1)
        application = parser.parse_embedded_cics(block_text)
        application = _with_program_id(application, program_id)
        applications.append(application)

    return applications


def _detect_program_id(cobol_source: str) -> str:
    match = _PROGRAM_ID_RE.search(cobol_source)
    if not match:
        return "UNKNOWN"
    return match.group(1).upper()


def _with_program_id(application: CicsApplication, program_id: str) -> CicsApplication:
    """Return a copy of ``application`` with ``program_id`` set.

    ``CicsApplication`` is frozen; this reconstruction preserves every field.
    """
    return CicsApplication(
        program_id=program_id or application.program_id,
        commands=application.commands,
        handle_conditions=application.handle_conditions,
        handle_aids=application.handle_aids,
        assignments=application.assignments,
        channels=application.channels,
        transactions=application.transactions,
        file_resources=application.file_resources,
        queue_resources=application.queue_resources,
        program_resources=application.program_resources,
        map_resources=application.map_resources,
        terminal_resources=application.terminal_resources,
        host_variables=application.host_variables,
        raw_text=application.raw_text,
    )


def map_cics_programs(
    cobol_source: str | None = None,
    *,
    applications: list[CicsApplication] | None = None,
    application_id: str = "cics-application",
    base_package: str = "com.generated.cics",
) -> CicsSpringApplication:
    """Map CICS applications to the explicit Java/Spring model.

    Provide either raw ``cobol_source`` (blocks are extracted automatically)
    or pre-parsed ``applications``.

    When a COBOL program contains several ``EXEC CICS`` blocks, they are
    consolidated by ``PROGRAM-ID`` before mapping so exactly one service is
    produced per program.
    """
    if applications is None:
        applications = extract_cics_blocks(cobol_source or "")
    consolidated = _consolidate_by_program(applications)
    mapper = CicsSpringMapper()
    return mapper.merge(
        consolidated,
        application_id=application_id,
        base_package=base_package,
    )


def _consolidate_by_program(
    applications: list[CicsApplication],
) -> list[CicsApplication]:
    """Group per-block applications by ``PROGRAM-ID``, concatenating commands.

    Blocks from the same program keep their source order; every IR structure
    (handles, aids, assignments, resources, host variables) is preserved
    across blocks.
    """
    grouped: dict[str, list[CicsApplication]] = {}
    order: list[str] = []
    for app in applications:
        key = (app.program_id or "UNKNOWN").strip()
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(app)

    result: list[CicsApplication] = []
    for key in order:
        blocks = grouped[key]
        result.append(
            CicsApplication(
                program_id=key,
                commands=tuple(
                    command for app in blocks for command in app.commands
                ),
                handle_conditions=tuple(
                    condition
                    for app in blocks
                    for condition in app.handle_conditions
                ),
                handle_aids=tuple(
                    aid for app in blocks for aid in app.handle_aids
                ),
                assignments=tuple(
                    assignment
                    for app in blocks
                    for assignment in app.assignments
                ),
                channels=tuple(
                    channel for app in blocks for channel in app.channels
                ),
                transactions=tuple(
                    transaction for app in blocks for transaction in app.transactions
                ),
                file_resources=_union_resource(blocks, "file_resources"),
                queue_resources=_union_resource(blocks, "queue_resources"),
                program_resources=_union_resource(blocks, "program_resources"),
                map_resources=_union_resource(blocks, "map_resources"),
                terminal_resources=_union_resource(blocks, "terminal_resources"),
                host_variables=_union_resource(blocks, "host_variables"),
                raw_text="\n".join(block.raw_text for block in blocks if block.raw_text),
            )
        )
    return result


def _union_resource(
    blocks: list[CicsApplication], attribute: str
) -> tuple[str, ...]:
    """Union a tuple-valued IR attribute across blocks, preserving order."""
    seen: list[str] = []
    for app in blocks:
        for value in getattr(app, attribute):
            if value not in seen:
                seen.append(value)
    return tuple(seen)


def generate_cics_spring(
    application: CicsSpringApplication,
) -> list[CicsGeneratedFile]:
    """Generate explicit Java/Spring source + report for a CICS model."""
    return CicsSpringGenerator().generate(application)


def map_and_generate_cics(
    cobol_source: str | None = None,
    *,
    applications: list[CicsApplication] | None = None,
    application_id: str = "cics-application",
    base_package: str = "com.generated.cics",
) -> list[CicsGeneratedFile]:
    """Map CICS source/IR and return the generated CICS file representation.

    This is the map-plus-generate entry point: it returns the CICS lane's
    native ``list[CicsGeneratedFile]`` without claiming CICS TS runtime
    equivalence.  Use :func:`to_shared_generated_files` only when a consumer
    needs the shared ``contracts.GeneratedFile`` shape.
    """
    application = map_cics_programs(
        cobol_source,
        applications=applications,
        application_id=application_id,
        base_package=base_package,
    )
    return generate_cics_spring(application)


def to_shared_generated_files(
    files: list[CicsGeneratedFile],
) -> list[SharedGeneratedFile]:
    """Convert CICS lane files to shared ``contracts.GeneratedFile`` objects.

    The conversion is lossy by design: it preserves filename/source text and
    records a language marker, while CICS-specific ``class_name`` and
    project-relative ``path`` metadata remain in the native ``CicsGeneratedFile``.
    """
    shared: list[SharedGeneratedFile] = []
    for generated in files:
        language = "java" if generated.path.endswith(".java") else "markdown"
        shared.append(
            SharedGeneratedFile(
                filename=generated.filename,
                source_code=generated.source_code,
                language=language,
            )
        )
    return shared


def transform_cics_program(
    cobol_source: str,
    *,
    application_id: str = "cics-application",
    base_package: str = "com.generated.cics",
) -> tuple[CicsSpringApplication, list[CicsGeneratedFile]]:
    """End-to-end CICS lane: COBOL source → model + generated files."""
    application = map_cics_programs(
        cobol_source,
        application_id=application_id,
        base_package=base_package,
    )
    files = generate_cics_spring(application)
    return application, files
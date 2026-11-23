"""Backward-compatible views: the Application IR's CALL, COPY and FILE relationships as the legacy discovery values.

Consumers (capability analysis, planning, generation) still read ``CobolApplication`` (``DependencyEdge``,
``CopybookReference``, ``FileDependency``).  This module derives the same values from the IR, so the old and new sources can
be compared value for value before any consumer relies on the IR.  Each view reproduces discovery's own semantics (for
example FILE dependencies are OPEN/READ/WRITE only) and invents nothing; where the IR cannot reproduce a value (a FILE
``ownership_note``) the comparison fails and the consumer keeps discovery's value.
"""

from __future__ import annotations

from pathlib import Path

from engine.application_ir.model import ApplicationIR
from engine.transformation.ir import CopybookReference, DependencyEdge, FileDependency


def call_edges(ir: ApplicationIR) -> tuple[DependencyEdge, ...]:
    """The legacy CALL edges: caller program name, target name (the variable for a dynamic call), RESOLVED only when the
    target is a program of the IR (a subsystem entry, an unknown name, a dynamic target and a nested program are UNRESOLVED,
    as ``ApplicationDiscovery`` states them)."""
    names = {p.decl_id: p.name for p in ir.programs}
    out = []
    for edge in ir.edges:
        if edge.kind != "call":
            continue
        attributes = dict(edge.attributes)
        dynamic = attributes.get("call_type") == "DYNAMIC"
        resolved = edge.resolution.state == "resolved" and not attributes.get("external") and not dynamic
        out.append(DependencyEdge(
            source=names.get(edge.source, edge.source), target=attributes.get("target", ""), edge_type="CALL",
            resolution="RESOLVED" if resolved else "UNRESOLVED", call_type=attributes.get("call_type", "STATIC")))
    return tuple(out)


# ----- COPY and FILE relationships (M3) ------------------------------------------------------------------------------

def _program_names(ir: ApplicationIR) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """``[(scope, program name)]`` longest scope first, and ``file -> program name`` for COPY sites."""
    scopes = sorted(((p.scope, p.name) for p in ir.programs), key=lambda pair: -len(pair[0]))
    by_file: dict[str, str] = {}
    for p in ir.programs:
        by_file.setdefault(p.file, p.name)
    return scopes, by_file


def copybook_references(ir: ApplicationIR, root: str) -> dict[str, tuple[CopybookReference, ...]]:
    """Legacy ``CopybookReference`` tuples per source file (a PROGRAM-ID may repeat across files), from the IR's COPY-site edges (source order).

    ``location`` is ``file:line`` and ``resolved_path`` is ``root`` joined with the checkpoint-relative path the resolver
    returned (what discovery records); AMBIGUOUS and UNRESOLVED carry no path.  A COPY site the IR did not resolve
    (``unsupported``) is projected as UNRESOLVED, which is what discovery states when it has no search directories.
    """
    _scopes, by_file = _program_names(ir)
    out: dict[str, list[CopybookReference]] = {}
    for edge in sorted((e for e in ir.edges if e.kind == "copy-site"),
                       key=lambda e: (e.span.file if e.span else "", e.span.line if e.span else 0,
                                      e.span.column if e.span else 0)):
        attributes = dict(edge.attributes)
        state = edge.resolution.state
        resolution = {"resolved": "RESOLVED", "ambiguous": "AMBIGUOUS"}.get(state, "UNRESOLVED")
        path = str(Path(root) / edge.resolution.candidates[0]) if state == "resolved" else ""
        program = by_file.get(edge.span.file if edge.span else "", attributes.get("program", ""))
        out.setdefault(edge.span.file if edge.span else "", []).append(CopybookReference(
            source_program=attributes.get("program", program), copybook_name=attributes["member"],
            location=attributes["location"], resolution=resolution, resolved_path=path))
    return {program: tuple(refs) for program, refs in out.items()}


def file_dependencies(ir: ApplicationIR) -> dict[str, tuple[FileDependency, ...]]:
    """Legacy ``FileDependency`` tuples per source file (a PROGRAM-ID may repeat across files) from the IR's file references, with discovery's own semantics: every
    OPEN (with its mode), every READ, every WRITE (REWRITE, DELETE, START and CLOSE are not file dependencies there), in that
    order and in source order.  ``ownership_note`` is never produced (the IR does not restate it): a program whose legacy
    dependencies carry one differs, and the consumer keeps discovery's values."""
    scopes, _by_file = _program_names(ir)
    rank = {"open": 0, "read": 1, "write": 2}
    rows: dict[str, list[tuple[int, str, int, int, FileDependency]]] = {}
    for ref in ir.references:
        if ref.kind != "file" or ref.access not in rank or ref.span is None:
            continue
        role = ref.role
        if ref.access == "open":
            operation, mode = "OPEN", role.partition(":")[2]
        elif role != "file":
            continue                        # file:start, file:rewrite, file:delete
        else:
            operation, mode = ref.access.upper(), ""
        program = next((name for scope, name in scopes if ref.owner_stmt.startswith(f"stmt:{scope}/")), "")
        rows.setdefault(ref.span.file, []).append((rank[ref.access], ref.span.file, ref.span.line, ref.span.column,
                                             FileDependency(program_id=program, file_name=ref.name, operation=operation,
                                                            mode=mode)))
    return {program: tuple(r[-1] for r in sorted(items, key=lambda r: r[:4])) for program, items in rows.items()}

"""Backward-compatible view: the Application IR's CALL edges as the legacy ``DependencyEdge`` tuples.

Consumers (capability analysis, planning) still read ``CobolApplication.edges``.  This module is the bridge that lets each be
migrated behind a differential test: it derives the same ``DependencyEdge`` values from the IR, so the old and new sources
can be compared edge for edge before any consumer switches.  Only CALL edges are projected: the IR has no COPY edges (COPY text
is not expanded by the facts builder) and no per-statement FILE_READ/FILE_WRITE operation, and a view must not invent them.
"""

from __future__ import annotations

from engine.application_ir.model import ApplicationIR
from engine.transformation.ir import DependencyEdge


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

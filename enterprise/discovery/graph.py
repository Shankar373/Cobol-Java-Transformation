"""Estate dependency graph model and deterministic serialisation.

Adapted from the generic graph of the Stage 1 Pascal discovery (nodes + traceable edges + unresolved tracking), with
the COBOL estate vocabulary:

* **Every edge is traceable.**  An edge without a source file and a ``(line, column)`` span cannot exist.
* **Unresolved is data, not noise.**  An unresolved edge stays in the edge list *and* in ``unresolved`` with a reason
  from the closed set below and a ``blocking`` flag; deleting one is a test failure.
* **Four resolutions.**  ``resolved`` (target found in the estate), ``external`` (a platform-provided target such as a
  system utility or the IMS interface, which the estate cannot contain), ``ambiguous`` (several candidates), and
  ``unresolved`` (the target is not in the estate and is not known to be provided by the platform).
* **Byte-identical output.**  Nodes and edges are keyed and sorted by stable strings; no set iteration order, no clock,
  no absolute paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Node", "Edge", "DependencyGraph", "RESOLUTIONS", "UNRESOLVED_REASONS", "BLOCKING_REASONS", "SCHEMA_VERSION"]

SCHEMA_VERSION = "systemaops.dependency-graph/1.0"

RESOLUTIONS = ("resolved", "external", "ambiguous", "unresolved")

#: Reason -> whether the missing artefact blocks a complete discovery.  A blocking reason means a source artefact the
#: customer owns is absent from the upload; a non-blocking one is information the operator should confirm.
UNRESOLVED_REASONS: dict[str, bool] = {
    "missing-program": True,
    "missing-copybook": True,
    "missing-procedure": True,
    "missing-include": True,
    "missing-mapset": True,
    "missing-source": True,
    "dynamic-target": False,
    "external-table": False,
    "unbound-ddname": False,
    "missing-dd": False,
    "undefined-transaction": False,
    "library-not-in-estate": False,
}
BLOCKING_REASONS = frozenset(reason for reason, blocking in UNRESOLVED_REASONS.items() if blocking)


@dataclass(frozen=True)
class Node:
    """A vertex.  ``origin`` is ``input`` (an artefact in the upload), ``platform`` (provided by the mainframe
    environment), ``catalog`` (a dataset/table the estate refers to but the upload cannot contain) or ``absent``."""

    id: str
    kind: str
    path: str = ""
    sha256: str = ""
    origin: str = "input"

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"id": self.id, "kind": self.kind, "origin": self.origin}
        if self.path:
            out["path"] = self.path
        if self.sha256:
            out["sha256"] = self.sha256
        return out


@dataclass(frozen=True)
class Edge:
    """A dependency with its exact source location and resolution."""

    src: str
    dst: str
    relation: str
    clause: str
    file: str
    line: int
    column: int
    resolution: str = "resolved"
    reason: str = ""
    dynamic: bool = False
    variable: str = ""
    candidates: tuple[str, ...] = ()
    detail: tuple[tuple[str, str], ...] = ()

    def key(self) -> tuple[object, ...]:
        return (self.src, self.dst, self.relation, self.clause, self.file, self.line, self.column, self.reason, self.detail)

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "clause": self.clause, "column": self.column, "file": self.file, "from": self.src, "line": self.line,
            "relation": self.relation, "resolution": self.resolution, "to": self.dst,
        }
        if self.reason:
            out["reason"] = self.reason
            out["blocking"] = UNRESOLVED_REASONS[self.reason]
        if self.dynamic:
            out["dynamic"] = True
        if self.variable:
            out["variable"] = self.variable
        if self.candidates:
            out["candidates"] = list(self.candidates)
        if self.detail:
            out["detail"] = dict(self.detail)
        return out


@dataclass
class DependencyGraph:
    """Accumulates nodes and edges, then emits them in canonical order."""

    nodes: dict[str, Node] = field(default_factory=dict)
    _edges: dict[tuple[object, ...], Edge] = field(default_factory=dict)
    duplicates: int = 0

    def add_node(self, node: Node) -> Node:
        """Insert ``node``; a node that carries a path replaces a bare placeholder, otherwise the first one wins."""
        existing = self.nodes.get(node.id)
        if existing is None or (not existing.path and node.path):
            self.nodes[node.id] = node
            return node
        return existing

    def add_edge(self, edge: Edge) -> bool:
        if edge.resolution not in RESOLUTIONS:
            raise ValueError(f"invalid resolution {edge.resolution!r}")
        if edge.resolution == "unresolved" and edge.reason not in UNRESOLVED_REASONS:
            raise ValueError(f"an unresolved edge needs a known reason, got {edge.reason!r}")
        if edge.resolution != "unresolved" and edge.reason:
            raise ValueError("only an unresolved edge carries a reason")
        if not edge.file or edge.line < 1 or edge.column < 1:
            raise ValueError("every edge needs a source file, line and column")
        key = edge.key()
        if key in self._edges:
            self.duplicates += 1
            return False
        self._edges[key] = edge
        return True

    def edges(self) -> list[Edge]:
        return [self._edges[k] for k in sorted(self._edges, key=lambda k: tuple(str(x) for x in k))]

    def unresolved(self) -> list[Edge]:
        return [e for e in self.edges() if e.resolution == "unresolved"]

    def ambiguous(self) -> list[Edge]:
        return [e for e in self.edges() if e.resolution == "ambiguous"]

    def stats(self) -> dict[str, object]:
        edges = self.edges()
        counts = {name: sum(1 for e in edges if e.resolution == name) for name in RESOLUTIONS}
        reasons: dict[str, int] = {}
        for edge in edges:
            if edge.reason:
                reasons[edge.reason] = reasons.get(edge.reason, 0) + 1
        return {
            "blocking_unresolved": sum(1 for e in edges if e.reason in BLOCKING_REASONS),
            "duplicate_edges_ignored": self.duplicates,
            "edges": len(edges),
            "nodes": len(self.nodes),
            "resolutions": counts,
            "unresolved_by_reason": dict(sorted(reasons.items())),
        }

    def to_dict(self) -> dict[str, object]:
        edges = self.edges()
        return {
            "edges": [e.as_dict() for e in edges],
            "nodes": [self.nodes[k].as_dict() for k in sorted(self.nodes)],
            "schema_version": SCHEMA_VERSION,
            "stats": self.stats(),
            "unresolved": [e.as_dict() for e in edges if e.resolution == "unresolved"],
        }

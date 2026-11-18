"""Modernization traceability: a ``generated-from`` / ``verified-by`` overlay on a discovery graph (Layer 3, gap 7).

Identity model
--------------
``graph_id`` is the content address of a graph's nodes and edges, so *adding* edges to a discovery graph would
change its identity and break every reference to it.  Traceability therefore never mutates the discovery graph.  It
builds an **overlay**: a new graph document that contains every parent node and edge unchanged plus the Java,
test and run nodes and the ``generated-from`` / ``verified-by`` / ``contains`` edges added by modernization.  The
overlay has

* its own derived ``graph_id`` (``overlay_id``), the sha256 of its own nodes and edges, and
* ``header.parent_graph_id`` = the discovery graph's ``graph_id``, ``header.created_from`` = ``traceability``.

The discovery graph keeps its identity forever (``parent_graph_id`` is the stable key through modernization), the
overlay is reproducible (same parent, same generated files, same evidence gives the same ``overlay_id``) and both are
persisted through :class:`KGStore`.  Evidence manifests carry both ids.

Edge shapes (direction is always ``from`` the newer artefact ``to`` the one it depends on)::

    java-class  --generated-from--> program | copybook          (derived)
    java-method --generated-from--> paragraph | program         (derived)
    java-class  --contains--------> java-method
    program | java-class --verified-by--> run | test-case       (certain; checksum + artifact path required)

Cross-graph edges are rejected: a caller names the ``graph_id`` it believes it is annotating, and a COBOL node that is
not part of the parent graph is refused.
"""

from __future__ import annotations

from typing import Any

from .graph import CONFIDENCE_VALUES, DependencyGraph, Edge, Node
from .kg_query import as_document, impact
from .kg_store import KGStore

__all__ = ["TraceabilityOverlay", "GraphTraceability", "modernization_impact", "TraceabilityError",
           "GENERATED_KINDS", "COBOL_ORIGIN_KINDS", "EVIDENCE_KINDS", "SUBJECT_KINDS", "java_class_id",
           "java_method_id", "evidence_node_id"]

#: Node kinds a generated Java artefact may be recorded as.
GENERATED_KINDS = ("java-class", "java-method")
#: Node kinds a Java artefact may be generated from.
COBOL_ORIGIN_KINDS = ("program", "paragraph", "section", "data-item", "record-layout", "copybook")
#: Node kinds that carry verification evidence.
EVIDENCE_KINDS = ("run", "test-case")
#: Node kinds verification evidence may be attached to.
SUBJECT_KINDS = ("program", "java-class")
#: Confidences ``verified-by`` may carry; ``certain`` only when a checksum and an artefact path exist.
_VERIFIED_CONFIDENCES = ("certain", "derived")


class TraceabilityError(ValueError):
    """A traceability record that would be wrong (cross-graph, unknown node, missing evidence)."""


def java_class_id(name: str) -> str:
    return f"java-class:{name}"


def java_method_id(class_name: str, method: str) -> str:
    return f"java-method:{class_name}.{method}"


def evidence_node_id(kind: str, name: str) -> str:
    if kind not in EVIDENCE_KINDS:
        raise TraceabilityError(f"evidence kind must be one of {EVIDENCE_KINDS}, got {kind!r}")
    return f"{kind}:{name}"


def _detail(values: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """``Edge.detail`` / ``Node.detail`` is a hashable, sorted tuple of string pairs, never a dict."""
    return tuple(sorted((str(k), str(v)) for k, v in values.items()))


class TraceabilityOverlay:
    """A traceability overlay over one discovery graph; see the module docstring for the identity model."""

    def __init__(self, parent: Any, store: KGStore | None = None, *, tool: str = "systemaops-modernization") -> None:
        document = as_document(parent)
        header = document.get("header") or {}
        parent_id = str(header.get("graph_id") or "")
        parent_graph = DependencyGraph.from_dict(document)
        recomputed = parent_graph.graph_id()
        if not parent_id:
            parent_id = recomputed
        if recomputed != parent_id:
            raise TraceabilityError(
                f"parent graph does not reproduce its own graph_id ({parent_id} != {recomputed}); refusing to overlay")
        self._parent = parent_graph
        self.parent_graph_id = parent_id
        self.store = store
        self.tool = tool
        self.graph = DependencyGraph.from_dict(document)
        self.graph.parent_graph_id = parent_id
        self.graph.created_from = "traceability"

    # -- identity ----------------------------------------------------------------------------------------------
    @property
    def overlay_id(self) -> str:
        """The overlay's own content address (differs from the parent as soon as one record is added)."""
        return self.graph.graph_id()

    @property
    def graph_id(self) -> str:
        """Alias of :attr:`overlay_id`."""
        return self.overlay_id

    def _check_graph_id(self, graph_id: str | None) -> None:
        if graph_id is not None and graph_id not in (self.parent_graph_id, self.overlay_id):
            raise TraceabilityError(
                f"cannot create cross-graph edge: graph {graph_id!r} is neither the parent {self.parent_graph_id!r} "
                f"nor this overlay")

    def _parent_node(self, node_id: str, kinds: tuple[str, ...], role: str) -> Node:
        node = self._parent.nodes.get(node_id)
        if node is None:
            raise TraceabilityError(
                f"cannot create cross-graph edge: {role} node {node_id!r} is not in graph {self.parent_graph_id}")
        if node.kind not in kinds:
            raise TraceabilityError(f"{role} node {node_id!r} has kind {node.kind!r}, expected one of {kinds}")
        return node

    # -- generated-from -----------------------------------------------------------------------------------------
    def record_generated_from(self, generated_id: str, generated_kind: str, origin_id: str, *, path: str,
                              sha256: str = "", line: int = 1, source_digest: str = "", graph_id: str | None = None,
                              confidence: str = "derived", rule: str = "traceability-generated",
                              extra: dict[str, str] | None = None) -> Edge:
        """Record ``generated_id --generated-from--> origin_id`` and return the edge.

        ``origin_id`` must be a COBOL node of the *parent* graph.  ``path`` is the generated file (relative), ``line``
        the declaration line: they are the edge's source location.
        """
        self._check_graph_id(graph_id)
        if generated_kind not in GENERATED_KINDS:
            raise TraceabilityError(f"generated kind must be one of {GENERATED_KINDS}, got {generated_kind!r}")
        if confidence not in CONFIDENCE_VALUES or confidence in ("unresolved",):
            raise TraceabilityError(f"invalid confidence {confidence!r} for generated-from")
        self._parent_node(origin_id, COBOL_ORIGIN_KINDS, "origin")
        if not path:
            raise TraceabilityError("a generated artefact needs its file path")
        self.graph.add_node(Node(generated_id, generated_kind, path=path, sha256=sha256, origin="derived"))
        edge = Edge(
            src=generated_id, dst=origin_id, relation="generated-from",
            clause=f"generated-from:{self.tool}", file=path, line=max(1, line), column=1, resolution="resolved",
            rule=rule, confidence=confidence, mode="", scope="",
            detail=_detail({"source_digest": source_digest, "tool": self.tool, "parent_graph_id": self.parent_graph_id,
                            **(extra or {})}))
        self.graph.add_edge(edge)
        return edge

    def record_contains(self, class_id: str, method_id: str, *, path: str, line: int = 1) -> Edge:
        """``java-class --contains--> java-method``; both must already be recorded."""
        for node_id, kind in ((class_id, "java-class"), (method_id, "java-method")):
            node = self.graph.nodes.get(node_id)
            if node is None or node.kind != kind:
                raise TraceabilityError(f"{node_id!r} is not a recorded {kind}")
        edge = Edge(class_id, method_id, "contains", "contains:java", path, max(1, line), 1, "resolved",
                    rule="definition-contains", confidence="derived", mode="", scope="")
        self.graph.add_edge(edge)
        return edge

    # -- verified-by --------------------------------------------------------------------------------------------
    def record_verified_by(self, subject_id: str, evidence_kind: str, evidence_name: str, *, checksum: str,
                           artifact_path: str, graph_id: str | None = None, confidence: str = "certain",
                           line: int = 1) -> Edge:
        """Record ``subject --verified-by--> run|test-case``.

        The subject is a COBOL program of the parent graph or an already-recorded Java class.  Evidence without a
        checksum and an artefact path is refused: ``certain`` exists only when the evidence does.
        """
        self._check_graph_id(graph_id)
        if confidence not in _VERIFIED_CONFIDENCES:
            raise TraceabilityError(f"verified-by confidence must be one of {_VERIFIED_CONFIDENCES}, got {confidence!r}")
        if not checksum or not artifact_path:
            raise TraceabilityError("verified-by needs the evidence checksum and artifact path; none was supplied")
        if subject_id in self._parent.nodes:
            self._parent_node(subject_id, SUBJECT_KINDS, "subject")
        else:
            node = self.graph.nodes.get(subject_id)
            if node is None or node.kind not in SUBJECT_KINDS:
                raise TraceabilityError(
                    f"cannot create cross-graph edge: subject {subject_id!r} is not in graph {self.parent_graph_id} "
                    f"or this overlay")
        evidence_id = evidence_node_id(evidence_kind, evidence_name)
        self.graph.add_node(Node(evidence_id, evidence_kind, path=artifact_path, sha256=checksum, origin="derived"))
        edge = Edge(
            src=subject_id, dst=evidence_id, relation="verified-by", clause=f"verified-by:{evidence_name}",
            file=artifact_path, line=max(1, line), column=1, resolution="resolved", rule="traceability-verified",
            confidence=confidence, mode="", scope="",
            detail=_detail({"artifact_path": artifact_path, "checksum": checksum, "evidence_kind": evidence_kind,
                            "parent_graph_id": self.parent_graph_id}))
        self.graph.add_edge(edge)
        return edge

    # -- views --------------------------------------------------------------------------------------------------
    def document(self) -> dict[str, Any]:
        """The overlay as a canonical graph document (header carries ``parent_graph_id``)."""
        return self.graph.to_dict()

    def classes(self) -> list[str]:
        return sorted(n.id for n in self.graph.nodes.values() if n.kind == "java-class")

    def untraced_classes(self) -> list[str]:
        """Recorded Java classes without a ``generated-from`` edge into the parent graph (criterion 9 violations)."""
        traced = {e.src for e in self.graph.edges() if e.relation == "generated-from" and e.dst in self._parent.nodes
                  and self._parent.nodes[e.dst].kind in ("program", "copybook", "record-layout")}
        return [c for c in self.classes() if c not in traced]

    def merge(self, other: "TraceabilityOverlay") -> "TraceabilityOverlay":
        """A new overlay holding both; refused unless both annotate the same parent graph."""
        if self.parent_graph_id != other.parent_graph_id:
            raise TraceabilityError(
                f"cannot merge overlays of different graphs: {self.parent_graph_id} vs {other.parent_graph_id}")
        merged = TraceabilityOverlay(self._parent, self.store or other.store, tool=self.tool)
        for source in (self.graph, other.graph):
            for node in source.nodes.values():
                merged.graph.add_node(node)
            for edge in source.edges():
                merged.graph.add_edge(edge)
        merged.graph.duplicates = 0
        return merged

    # -- persistence --------------------------------------------------------------------------------------------
    def save(self, *, application: str = "") -> str:
        """Persist the parent (if absent) and the overlay; returns the overlay id.  Needs a store."""
        if self.store is None:
            raise RuntimeError("no KGStore provided; construct the overlay with a store")
        try:
            self.store.load(self.parent_graph_id)
        except KeyError:
            self.store.save(self._parent.to_dict(), application=application)
        return self.store.save(self.document(), application=application)

    @classmethod
    def load(cls, store: KGStore, overlay_id: str) -> "TraceabilityOverlay":
        """Re-open a stored overlay; its parent must be stored too (lineage is never dangling)."""
        document = store.load(overlay_id)
        parent_id = str((document.get("header") or {}).get("parent_graph_id") or "")
        if not parent_id:
            raise TraceabilityError(f"snapshot {overlay_id} is not a traceability overlay (no parent_graph_id)")
        parent = store.load(parent_id)
        overlay = cls(parent, store)
        for node in DependencyGraph.from_dict(document).nodes.values():
            overlay.graph.add_node(node)
        for edge in DependencyGraph.from_dict(document).edges():
            overlay.graph.add_edge(edge)
        overlay.graph.duplicates = 0  # re-adding the parent's own edges is not a duplicate the document had
        return overlay


#: Backwards-compatible name for the overlay class.
GraphTraceability = TraceabilityOverlay


def modernization_impact(doc: Any, node_id: str) -> dict[str, list[str]]:
    """What a change to COBOL node ``node_id`` touches in an overlay document: dependents, Java and tests.

    Upstream closure (``impact(..., "in")``) reaches the program, the Java method/class generated from the node and
    their containers; ``verified-by`` edges from any program or Java class in that closure then give the evidence.
    """
    document = as_document(doc)
    nodes = {str(n["id"]): str(n["kind"]) for n in document["nodes"]}
    if node_id not in nodes:
        raise KeyError(f"node {node_id!r} is not in the graph")
    affected = impact(document, node_id, "in") | {node_id}
    evidence = sorted({str(e["to"]) for e in document["edges"]
                       if e["relation"] == "verified-by" and str(e["from"]) in affected})
    return {
        "cobol": sorted(n for n in affected if nodes.get(n) not in (*GENERATED_KINDS, *EVIDENCE_KINDS)),
        "java_classes": sorted(n for n in affected if nodes.get(n) == "java-class"),
        "java_methods": sorted(n for n in affected if nodes.get(n) == "java-method"),
        "evidence": evidence,
    }

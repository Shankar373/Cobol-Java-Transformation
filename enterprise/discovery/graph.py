"""Estate knowledge graph model and deterministic serialisation.

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
* **Content-addressed identity (Layer 3).**  ``header.graph_id`` is the sha256 of the canonical JSON of the node and
  edge sets only, so two runs over the same input produce the same identity whatever order the files arrived in, and
  metadata churn (checkpoint, tool version) never changes it.

Schema ``systemaops.knowledge-graph/2.0`` is a superset of ``systemaops.dependency-graph/1.0``: every 1.0 key is still
emitted (``nodes``, ``edges``, ``stats``, ``unresolved``, ``schema_version``), the 1.0 projection is available through
:meth:`Edge.as_dict_1_0` / ``DependencyGraph.to_dict(v1=True)``, and a 1.0 document read back through
:meth:`DependencyGraph.from_dict` is upgraded rather than rejected.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .findings import Detail

__all__ = [
    "Node", "Edge", "DependencyGraph", "RESOLUTIONS", "UNRESOLVED_REASONS", "BLOCKING_REASONS", "SCHEMA_VERSION",
    "COMPATIBLE_SCHEMA_VERSION", "NODE_KINDS", "EDGE_RELATIONS", "CONFIDENCE_VALUES", "EDGE_MODES", "EDGE_SCOPES",
    "RESOLVER_RULES", "edge_identity", "confidence_for", "graph_id_of", "stamp_graph_id",
]

SCHEMA_VERSION = "systemaops.knowledge-graph/2.0"
#: The pre-Layer-3 schema.  Still emitted as ``compatible_schema_version`` and still readable.
COMPATIBLE_SCHEMA_VERSION = "systemaops.dependency-graph/1.0"
SCHEMA_MINOR_VERSION = "2"
#: How ``graph_id`` was computed, recorded in the header so an algorithm change is visible, never silent.
GRAPH_ID_ALGORITHM = "sha256"
TOOL_NAME = "systemaops-discovery"

RESOLUTIONS = ("resolved", "external", "ambiguous", "unresolved")

#: Reason -> whether the missing artefact blocks a complete discovery.  A blocking reason means a source artefact the
#: customer owns is absent from the upload; a non-blocking one is information the operator should confirm.
#: ``missing-paragraph`` and ``missing-data-item`` are non-blocking on purpose: they come from the intra-program
#: control-flow and data-flow scan, which cannot see a name a real preprocessor would expand, so they are findings to
#: confirm, never a gate on the whole estate.
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
    "missing-paragraph": False,
    "missing-data-item": False,
    "missing-logical-file": False,
}
BLOCKING_REASONS = frozenset(reason for reason, blocking in UNRESOLVED_REASONS.items() if blocking)

#: Entity types the graph may hold.  A consumer that does not know a kind must still render it, never drop it.
NODE_KINDS: tuple[str, ...] = (
    "application", "file", "directory", "program", "copybook", "proc", "job", "jcl-member", "step",
    "load-module", "source-member", "source-file",
    "section", "paragraph", "data-item", "record-layout", "column", "screen-field",
    "table", "dd", "logical-file", "dataset", "vsam-cluster", "uss-path", "external-file", "sysout", "dummy",
    "instream",
    "bms-mapset", "bms-map", "transaction", "cics-file", "cics-queue", "mq-queue", "mq-interface", "mq-object",
    "ims-interface", "ims-psb", "ims-segment", "db2-plan", "db2-subsystem", "stored-procedure",
    "utility", "runtime", "dynamic",
    "java-class", "java-method", "test-case", "requirement", "run",
)

#: Every relationship the graph may express.  A relation not in this tuple cannot be constructed (fail closed).
EDGE_RELATIONS: tuple[str, ...] = (
    # -- what an artefact is, and what contains it ------------------------------------------------------------
    "defines", "contains",
    # -- calls and copybooks ----------------------------------------------------------------------------------
    "calls", "copies",
    # -- build, link, include ---------------------------------------------------------------------------------
    "builds", "links", "includes", "uses-library", "binds-ddname",
    # -- execution ---------------------------------------------------------------------------------------------
    "executes", "starts-transaction", "runs-utility", "assigns-file", "uses-dataset", "creates-dataset",
    # -- data access ------------------------------------------------------------------------------------------
    "accesses-table", "reads-file", "writes-file", "rewrites-file",
    "reads-item", "writes-item", "moves-to",
    "sql-reads", "sql-writes", "sql-binds-hostvar",
    # -- control flow ------------------------------------------------------------------------------------------
    "performs", "goes-to",
    # -- definitions the estate makes of its own resources -----------------------------------------------------
    "defines-dataset", "defines-queue", "defines-resource", "defines-table",
    # -- subsystem resources ----------------------------------------------------------------------------------
    "uses-ims", "uses-mq", "uses-queue", "uses-map", "uses-cics-file", "uses-db2", "uses-runtime",
    "cics-link", "cics-xctl", "cics-load", "cics-op",
    "mq-put", "mq-get", "ims-call",
    # -- modernization traceability ---------------------------------------------------------------------------
    "generated-from", "verified-by", "implements",
)

#: How far an edge can be trusted.  ``unresolved`` only ever appears on an edge whose resolution is ``unresolved``.
CONFIDENCE_VALUES: tuple[str, ...] = ("certain", "derived", "heuristic", "unresolved")

#: Closed set of access modes.  ``mode`` describes the operation performed **on the destination node**, so
#: ``reads-file`` carries ``read`` and ``writes-file`` carries ``write``.  ``""`` means the relation carries no
#: operation (calls, control flow, structure).
EDGE_MODES: tuple[str, ...] = (
    "", "read", "write", "read-write", "create", "delete", "update", "search",
    "execute", "invoke", "control", "declare", "copy", "allocate", "route", "send", "receive", "put", "get", "bind",
)

#: Closed set of scopes: what the edge is relative to.  ``""`` means estate-wide.
EDGE_SCOPES: tuple[str, ...] = ("", "estate", "application", "program", "paragraph", "job", "proc", "step", "file")

#: Resolver rules that are named explicitly.  Every other relation gets the generic ``definition-<relation>`` rule,
#: appended below so :data:`RESOLVER_RULES` is a closed, import-time fixed set.
_EXPLICIT_RESOLVER_RULES: frozenset[str] = frozenset({
    "copy-name", "copy-qualifier", "copy-library-order", "copy-procedure-division", "copy-file-name",
    "copy-replacing", "copy-no-replacing",
    "call-in-program", "call-external", "call-class", "call-dynamic",
    "dd-binding", "dd-binding-dynamic", "jcl-copybook-library", "jcl-exec", "proc-expansion",
    "build-command", "include-path",
    "file-verb", "data-flow", "control-flow", "embedded-statement", "subsystem-operation",
    "traceability-generated", "traceability-verified",
})
#: Closed set of resolver rule ids; constructing an edge outside it raises ``ValueError``.
RESOLVER_RULES: tuple[str, ...] = tuple(sorted(
    _EXPLICIT_RESOLVER_RULES | {f"definition-{relation}" for relation in EDGE_RELATIONS}
))


def confidence_for(resolution: str) -> str:
    """Default confidence for a resolution: an unresolved edge is never ``certain``, an ambiguous one only heuristic."""
    if resolution == "unresolved":
        return "unresolved"
    if resolution == "ambiguous":
        return "heuristic"
    return "certain"


def edge_identity(src: str, dst: str, relation: str, rule: str, line: int, detail: Any = (), *,
                  file: str = "", column: int = 1, clause: str = "") -> str:
    """Stable edge identity ``from|to|relation|rule|file|line|column[|<digest>]``.

    An edge is a fact *at a source position*, and :meth:`Edge.key` says which facts are distinct: two edges that
    differ in their ``file`` (three variant files declaring one program) or ``column`` (two references to one name
    on a single line) are distinct facts, and ``kg_edge`` stores them as separate rows under this id — so both are
    part of the identity, and an id can never collapse two rows of the table.  ``clause`` and ``detail`` complete
    the identity when present and are folded into a digest so the common case stays readable.  ``detail`` is a
    mapping or an iterable of ``(key, value)`` pairs.

    ``reason``/``resolution``/``confidence`` are deliberately *not* part of it: the same edge resolving one day and
    going unresolved the next is one edge whose content changed, which is what :func:`kg_query.diff` must report
    as ``changed`` rather than as a remove-plus-add.  Two edges that differ only in those fields would therefore
    share an id; the store refuses such a document instead of dropping a row, and the exporters disambiguate.

    Node ids containing ``|`` can still make two identities concatenate to the same text (``"a|b" -> "c"`` versus
    ``"a" -> "b|c"``); that collision is refused by the store and disambiguated by the exporters, never dropped.
    """
    pairs = sorted((str(k), str(v)) for k, v in (detail.items() if isinstance(detail, dict) else detail))
    base = f"{src}|{dst}|{relation}|{rule}|{file}|{line}|{column}"
    if not pairs and not clause:
        return base
    folded = {"clause": clause, "detail": pairs}
    digest = hashlib.sha256(json.dumps(folded, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
    return f"{base}|{digest}"


def _json_default(value: Any) -> Any:
    if isinstance(value, (set, frozenset, tuple)):
        return sorted(value)
    if hasattr(value, "as_dict"):
        return value.as_dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Canonical JSON: sorted keys, compact separators, ASCII only — the bytes ``graph_id`` is taken over."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=_json_default).encode("utf-8")


def graph_id_of(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    """Content address of a node/edge set: sha256 of its canonical JSON, independent of input order."""
    return hashlib.sha256(_canonical_bytes({"edges": edges, "nodes": nodes})).hexdigest()


def stamp_graph_id(document: dict[str, Any]) -> str:
    """Set (or refresh) ``document['header']['graph_id']`` from the document's own nodes and edges; returns it.

    The emitted file is rewritten on its way out (local paths scrubbed), so the identity is stamped *after* that
    rewrite: the recorded ``graph_id`` always matches the bytes actually written.
    """
    digest = graph_id_of(list(document.get("nodes", [])), list(document.get("edges", [])))
    document.setdefault("header", {})["graph_id"] = digest
    return digest


@dataclass(frozen=True)
class Node:
    """A vertex.  ``origin`` is ``input`` (an artefact in the upload), ``platform`` (provided by the mainframe
    environment), ``catalog`` (a dataset/table the estate refers to but the upload cannot contain) or ``absent``."""

    id: str
    kind: str
    path: str = ""
    sha256: str = ""
    origin: str = "input"
    #: Optional structured provenance (Layer 3): what the node is made of, where it was expanded from.
    detail: Detail = ()

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"id": self.id, "kind": self.kind, "origin": self.origin}
        if self.path:
            out["path"] = self.path
        if self.sha256:
            out["sha256"] = self.sha256
        if self.detail:
            out["detail"] = dict(self.detail)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Node:
        detail = tuple(sorted((str(k), str(v)) for k, v in dict(data.get("detail", {})).items()))
        return cls(str(data["id"]), str(data["kind"]), str(data.get("path", "")), str(data.get("sha256", "")),
                   str(data.get("origin", "input")), detail)


@dataclass(frozen=True)
class Edge:
    """A dependency with its exact source location, resolution and (Layer 3) how it was resolved.

    ``rule`` says which resolver rule produced the edge, ``confidence`` how much it can be trusted, ``mode`` the
    operation performed on ``dst`` and ``scope`` what the edge is relative to.  All four are validated against closed
    sets in ``__post_init__``, as are the relation, the resolution and the reason: constructing an edge outside them
    raises ``ValueError`` (fail closed, never approximate).
    """

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
    detail: Detail = ()
    #: Which resolver rule produced this edge (closed set :data:`RESOLVER_RULES`).
    rule: str = ""
    #: How much this edge can be trusted (closed set :data:`CONFIDENCE_VALUES`).
    confidence: str = ""
    #: Operation performed on ``dst`` (closed set :data:`EDGE_MODES`).
    mode: str = ""
    #: What the edge is relative to (closed set :data:`EDGE_SCOPES`).
    scope: str = ""

    def __post_init__(self) -> None:
        # Fail closed: an unknown value is a defect in the producer, never something to guess at.
        if not self.file or self.line < 1 or self.column < 1:
            raise ValueError("every edge needs a source file, line and column")
        if self.relation not in EDGE_RELATIONS:
            raise ValueError(f"unknown relation {self.relation!r}")
        if self.resolution not in RESOLUTIONS:
            raise ValueError(f"invalid resolution {self.resolution!r}")
        if self.resolution == "unresolved" and self.reason not in UNRESOLVED_REASONS:
            raise ValueError(f"an unresolved edge needs a known reason, got {self.reason!r}")
        if self.resolution != "unresolved" and self.reason:
            raise ValueError("only an unresolved edge carries a reason")
        if self.rule not in RESOLVER_RULES:
            raise ValueError(f"unknown resolver rule {self.rule!r}")
        if self.confidence not in CONFIDENCE_VALUES:
            raise ValueError(f"unknown confidence {self.confidence!r}")
        if self.mode not in EDGE_MODES:
            raise ValueError(f"unknown mode {self.mode!r}")
        if self.scope not in EDGE_SCOPES:
            raise ValueError(f"unknown scope {self.scope!r}")
        if (self.confidence == "unresolved") != (self.resolution == "unresolved"):
            raise ValueError("confidence 'unresolved' and resolution 'unresolved' must agree")

    def key(self) -> tuple[object, ...]:
        return (self.src, self.dst, self.relation, self.clause, self.file, self.line, self.column, self.reason,
                self.detail)

    @property
    def blocking(self) -> bool:
        """Whether a consumer must stop on this edge; ``False`` when the edge resolves (or is merely informative)."""
        return UNRESOLVED_REASONS.get(self.reason, False)

    @property
    def id(self) -> str:
        """Stable identity used by the query API: ``from|to|relation|rule|file|line|column`` plus a digest of
        ``clause`` and ``detail`` — injective over :meth:`key` apart from ``reason``, whose change must read as
        the same edge resolving differently (see :func:`edge_identity`)."""
        return edge_identity(self.src, self.dst, self.relation, self.rule, self.line, self.detail,
                             file=self.file, column=self.column, clause=self.clause)

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "clause": self.clause, "column": self.column, "file": self.file, "from": self.src, "line": self.line,
            "relation": self.relation, "resolution": self.resolution, "to": self.dst,
            "rule": self.rule, "confidence": self.confidence, "mode": self.mode, "scope": self.scope,
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

    def as_dict_1_0(self) -> dict[str, object]:
        """The pre-Layer-3 projection: the same edge without ``rule``/``confidence``/``mode``/``scope``."""
        out = self.as_dict()
        for key in ("rule", "confidence", "mode", "scope"):
            out.pop(key, None)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Edge:
        """Rebuild an edge from either schema.  A 1.0 document has no ``rule``/``confidence``/``mode``/``scope``; those
        are derived from the relation and the resolution (a documented compatibility mapping, not a guess about the
        source) instead of being dropped."""
        resolution = str(data.get("resolution", "resolved"))
        relation = str(data["relation"])
        detail = tuple(sorted((str(k), str(v)) for k, v in dict(data.get("detail", {})).items()))
        return cls(
            str(data.get("from", data.get("src", ""))), str(data.get("to", data.get("dst", ""))), relation,
            str(data.get("clause", "")), str(data.get("file", "")), int(data.get("line", 1)),
            int(data.get("column", 1)), resolution, str(data.get("reason", "")), bool(data.get("dynamic", False)),
            str(data.get("variable", "")), tuple(str(c) for c in data.get("candidates", ())), detail,
            rule=str(data.get("rule") or f"definition-{relation}"),
            confidence=str(data.get("confidence") or confidence_for(resolution)),
            mode=str(data.get("mode", "")), scope=str(data.get("scope", "")),
        )


@dataclass
class DependencyGraph:
    """Accumulates nodes and edges, then emits them in canonical order."""

    nodes: dict[str, Node] = field(default_factory=dict)
    _edges: dict[tuple[object, ...], Edge] = field(default_factory=dict)
    duplicates: int = 0
    #: Canonically sorted edge list, rebuilt lazily after ``add_edge`` and per-file index of it.
    _sorted: list[Edge] | None = field(default=None, repr=False, compare=False)
    _by_file: dict[str, list[Edge]] | None = field(default=None, repr=False, compare=False)
    # -- document provenance (Layer 3 header; never part of ``graph_id``) ---------------------------------------
    checkpoint: dict[str, Any] = field(default_factory=dict)
    checkpoint_id: str = ""
    source_digest: str = ""
    parent_graph_id: str = ""
    #: ``discovery`` for a scanner-built graph, ``traceability`` for one augmented by modernization/certification.
    created_from: str = "discovery"
    tool_version: str = __version__
    scanner_version: str = SCHEMA_VERSION

    def add_node(self, node: Node) -> Node:
        """Insert ``node``; a node that carries a path replaces a bare placeholder, otherwise the first one wins."""
        existing = self.nodes.get(node.id)
        if existing is None or (not existing.path and node.path):
            self.nodes[node.id] = node
            return node
        return existing

    def add_edge(self, edge: Edge) -> bool:
        # ``Edge.__post_init__`` already validated the edge; these are the same checks kept here so a future field
        # added without validation still cannot reach the store.
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
        self._sorted = None
        self._by_file = None
        return True

    def _sorted_edges(self) -> list[Edge]:
        if self._sorted is None:
            self._sorted = [self._edges[k] for k in sorted(self._edges, key=lambda k: tuple(str(x) for x in k))]
        return self._sorted

    def edges(self) -> list[Edge]:
        """Every edge in canonical order (a fresh list; the sort itself is cached until the next ``add_edge``)."""
        return list(self._sorted_edges())

    def edges_in_file(self, path: str) -> list[Edge]:
        """The edges whose source ``file`` is ``path``, in canonical order."""
        if self._by_file is None:
            index: dict[str, list[Edge]] = {}
            for edge in self._sorted_edges():
                index.setdefault(edge.file, []).append(edge)
            self._by_file = index
        return list(self._by_file.get(path, ()))

    def unresolved(self) -> list[Edge]:
        return [e for e in self.edges() if e.resolution == "unresolved"]

    def ambiguous(self) -> list[Edge]:
        return [e for e in self.edges() if e.resolution == "ambiguous"]

    def graph_id(self) -> str:
        """Content address of this graph's nodes and edges (see :func:`graph_id_of`)."""
        return graph_id_of([n.as_dict() for n in (self.nodes[k] for k in sorted(self.nodes))],
                           [e.as_dict() for e in self.edges()])

    def header(self) -> dict[str, Any]:
        """Document header: schema, content address and provenance.  ``graph_id`` covers nodes and edges only."""
        return {
            "schema_version": SCHEMA_VERSION,
            "schema_minor": SCHEMA_MINOR_VERSION,
            "compatible_schema_version": COMPATIBLE_SCHEMA_VERSION,
            "graph_id": self.graph_id(),
            "graph_id_algorithm": GRAPH_ID_ALGORITHM,
            "checkpoint_id": self.checkpoint_id,
            "source_digest": self.source_digest,
            "parent_graph_id": self.parent_graph_id,
            "created_from": self.created_from,
            "tool": {"name": TOOL_NAME, "version": self.tool_version, "scanner_version": self.scanner_version},
        }

    def stats(self) -> dict[str, object]:
        edges = self.edges()
        counts = {name: sum(1 for e in edges if e.resolution == name) for name in RESOLUTIONS}
        reasons: dict[str, int] = {}
        relations: dict[str, int] = {}
        confidences: dict[str, int] = {}
        rules: dict[str, int] = {}
        modes: dict[str, int] = {}
        kinds: dict[str, int] = {}
        origins: dict[str, int] = {}
        for node in (self.nodes[k] for k in sorted(self.nodes)):
            kinds[node.kind] = kinds.get(node.kind, 0) + 1
            origins[node.origin] = origins.get(node.origin, 0) + 1
        for edge in edges:
            if edge.reason:
                reasons[edge.reason] = reasons.get(edge.reason, 0) + 1
            relations[edge.relation] = relations.get(edge.relation, 0) + 1
            confidences[edge.confidence] = confidences.get(edge.confidence, 0) + 1
            rules[edge.rule] = rules.get(edge.rule, 0) + 1
            if edge.mode:
                modes[edge.mode] = modes.get(edge.mode, 0) + 1
        return {
            "blocking_unresolved": sum(1 for e in edges if e.reason in BLOCKING_REASONS),
            "duplicate_edges_ignored": self.duplicates,
            "edges": len(edges),
            "nodes": len(self.nodes),
            "resolutions": counts,
            "unresolved_by_reason": dict(sorted(reasons.items())),
            # Layer 3 projections; additive, the 1.0 keys above are unchanged.
            "by_kind": dict(sorted(kinds.items())),
            "by_origin": dict(sorted(origins.items())),
            "by_relation": dict(sorted(relations.items())),
            "by_confidence": dict(sorted(confidences.items())),
            "by_rule": dict(sorted(rules.items())),
            "by_mode": dict(sorted(modes.items())),
            "graph_id": self.graph_id(),
        }

    def to_dict(self, v1: bool = False) -> dict[str, Any]:
        """The document written to disk.  ``v1=True`` projects the pre-Layer-3 schema for 1.0 readers."""
        edges = self.edges()
        nodes = [self.nodes[k].as_dict() for k in sorted(self.nodes)]
        if v1:
            return {
                "edges": [e.as_dict_1_0() for e in edges],
                "nodes": nodes,
                "schema_version": COMPATIBLE_SCHEMA_VERSION,
                "stats": self.stats(),
                "unresolved": [e.as_dict_1_0() for e in edges if e.resolution == "unresolved"],
            }
        header = self.header()
        if self.checkpoint:
            header["checkpoint"] = self.checkpoint
        return {
            "edges": [e.as_dict() for e in edges],
            "nodes": nodes,
            "schema_version": SCHEMA_VERSION,
            "compatible_schema_version": COMPATIBLE_SCHEMA_VERSION,
            "header": header,
            "stats": self.stats(),
            "unresolved": [e.as_dict() for e in edges if e.resolution == "unresolved"],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DependencyGraph:
        """Read a 1.0 or 2.0 document back.  Missing Layer-3 fields are derived, never dropped."""
        graph = cls()
        for node in (Node.from_dict(n) for n in payload.get("nodes", ())):
            graph.add_node(node)
        for edge in (Edge.from_dict(e) for e in payload.get("edges", ())):
            graph.add_edge(edge)
        header = payload.get("header") or {}
        graph.checkpoint = dict(payload.get("checkpoint", header.get("checkpoint", {})))
        graph.checkpoint_id = str(header.get("checkpoint_id", ""))
        graph.source_digest = str(header.get("source_digest", ""))
        graph.parent_graph_id = str(header.get("parent_graph_id", ""))
        graph.created_from = str(header.get("created_from", "discovery"))
        tool = header.get("tool") or payload.get("tool") or {}
        graph.tool_version = str(tool.get("version", __version__))
        graph.scanner_version = str(tool.get("scanner_version", SCHEMA_VERSION))
        return graph

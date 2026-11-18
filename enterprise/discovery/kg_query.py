"""Pure query functions over an in-memory knowledge-graph document.

Everything here is a total, deterministic function of its arguments: no clock, no I/O, no set-iteration order in any
returned sequence.  A document is the dict produced by :meth:`DependencyGraph.to_dict` (a ``DependencyGraph`` itself
is accepted and normalised through ``to_dict()``).  A structurally malformed document raises ``ValueError``; a
merely-absent node id yields an empty result — asking about a node the graph does not have is a query, not an error.

Result shapes:

* :func:`neighbors` and :func:`path` return sorted lists (a path is ordered start to end).
* :func:`reachable`, :func:`impact` and the buckets of :func:`diff` return sets: unordered by nature, deterministic
  in content (``diff(x, x)`` is empty; a set-valued result should be passed to ``sorted()`` for display).
* :func:`slice` returns a new document with its own header and its own ``graph_id``.

Traversal direction follows the document's edges: ``"out"`` walks ``from -> to`` (downstream), ``"in"`` walks
``to -> from`` (upstream), ``"both"`` ignores direction.  An unknown direction raises.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from .graph import COMPATIBLE_SCHEMA_VERSION, SCHEMA_VERSION, DependencyGraph, UNRESOLVED_REASONS, edge_identity, graph_id_of

__all__ = [
    "as_document", "edge_endpoints", "edge_key", "edge_blocking", "neighbors", "reachable", "impact", "slice",
    "path", "diff", "DIRECTIONS", "DEFAULT_LIMIT",
]

#: The three directions every directional query accepts.
DIRECTIONS = ("out", "in", "both")
#: Page size for :func:`neighbors` when the caller does not ask for one; ``None`` means "no limit".
DEFAULT_LIMIT = 1000


def as_document(doc: Any) -> dict[str, Any]:
    """Normalise ``doc`` (a document dict or a ``DependencyGraph``) and reject structurally malformed input.

    Validation is deliberately structural only — identity, endpoint and shape checks.  Vocabulary (unknown node
    kinds, future relations) is data here and is never rejected, so query and export stay total; closed-set
    validation belongs to :class:`Edge` when a document is turned back into graph objects.
    """
    if isinstance(doc, DependencyGraph):
        return doc.to_dict()
    if not isinstance(doc, dict):
        raise TypeError(f"expected a graph document dict or DependencyGraph, got {type(doc).__name__}")
    nodes, edges = doc.get("nodes"), doc.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("malformed graph document: 'nodes' and 'edges' must be lists")
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not isinstance(node.get("kind"), str):
            raise ValueError(f"malformed graph document: node #{index} needs a string 'id' and 'kind'")
        if "detail" in node and not isinstance(node["detail"], dict):
            raise ValueError(f"malformed graph document: node #{index} 'detail' must be a dict")
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise ValueError(f"malformed graph document: edge #{index} must be a dict")
        if not isinstance(edge.get("relation"), str):
            raise ValueError(f"malformed graph document: edge #{index} needs a string 'relation'")
        if not isinstance(_edge_src(edge), str) or not isinstance(_edge_dst(edge), str):
            raise ValueError(f"malformed graph document: edge #{index} needs 'from' and 'to' endpoint ids")
        if "detail" in edge and not isinstance(edge["detail"], dict):
            raise ValueError(f"malformed graph document: edge #{index} 'detail' must be a dict")
        for field in ("line", "column"):
            if field in edge and not isinstance(edge[field], int):
                raise ValueError(f"malformed graph document: edge #{index} '{field}' must be an int")
    return doc


def _edge_src(edge: dict[str, Any]) -> Any:
    return edge.get("from", edge.get("src"))


def _edge_dst(edge: dict[str, Any]) -> Any:
    return edge.get("to", edge.get("dst"))


def edge_endpoints(edge: dict[str, Any]) -> tuple[str, str]:
    """``(from, to)`` of an edge, accepting both the document keys and the ``src``/``dst`` spelling."""
    return _edge_src(edge), _edge_dst(edge)


def edge_key(edge: dict[str, Any]) -> str:
    """Stable identity of a document edge: ``from|to|relation|rule|file|line|column[|digest]`` — the dict form of
    ``Edge.id``, injective over the fields that make two document edges distinct facts (a variant file, another
    column on the same line, a different clause or detail).  ``reason`` stays out so a resolution change reads as
    the same edge with different content — :func:`diff` reports it as ``changed``, not as a remove-plus-add.

    The rule is derived as ``definition-<relation>`` when absent, mirroring :meth:`Edge.from_dict`, so a 1.0 edge
    and its 2.0 upgrade share one key.
    """
    relation = str(edge["relation"])
    src, dst = edge_endpoints(edge)
    rule = str(edge.get("rule") or f"definition-{relation}")
    return edge_identity(src, dst, relation, rule, int(edge.get("line", 1)), dict(edge.get("detail") or {}),
                         file=str(edge.get("file", "")), column=int(edge.get("column", 1)),
                         clause=str(edge.get("clause", "")))


def edge_blocking(edge: dict[str, Any]) -> int:
    """``1`` when the edge blocks a complete discovery, else ``0`` — the dict form of ``Edge.blocking``."""
    if "blocking" in edge:
        return 1 if edge["blocking"] else 0
    return 1 if UNRESOLVED_REASONS.get(str(edge.get("reason", "")), False) else 0


def _check_direction(direction: str) -> str:
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r}, expected one of {', '.join(DIRECTIONS)}")
    return direction


def _check_depth(depth: int | None) -> None:
    if depth is not None and (not isinstance(depth, int) or depth < 0):
        raise ValueError(f"depth must be a non-negative int or None, got {depth!r}")


def _adjacency(document: dict[str, Any], direction: str) -> dict[str, list[str]]:
    """Neighbour map in the requested direction; every list is sorted, so traversal order is deterministic."""
    neighbours: dict[str, set[str]] = {}
    for edge in document["edges"]:
        src, dst = edge_endpoints(edge)
        if direction in ("out", "both"):
            neighbours.setdefault(src, set()).add(dst)
        if direction in ("in", "both"):
            neighbours.setdefault(dst, set()).add(src)
    return {node: sorted(ids) for node, ids in neighbours.items()}


def _traverse(document: dict[str, Any], node: str, direction: str, depth: int | None) -> set[str]:
    """Breadth-first closure from ``node``; the start node itself is never in the result."""
    if not isinstance(node, str):
        raise TypeError(f"node must be a node id string, got {type(node).__name__}")
    _check_depth(depth)
    adjacency = _adjacency(document, direction)
    seen: set[str] = {node}
    frontier: list[str] = [node]
    reached: set[str] = set()
    hops = 0
    while frontier and (depth is None or hops < depth):
        next_frontier: list[str] = []
        for current in frontier:
            for neighbour in adjacency.get(current, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    reached.add(neighbour)
                    next_frontier.append(neighbour)
        frontier = next_frontier
        hops += 1
    return reached


def neighbors(doc: Any, node: str, direction: str = "both", relation: str | None = None,
              limit: int | None = DEFAULT_LIMIT) -> list[str]:
    """Sorted ids adjacent to ``node``, optionally filtered to one relation; ``limit=None`` disables paging.

    An absent ``node`` returns ``[]``.  Endpoints of matching edges are reported even when the document has no node
    entry for them — an unresolved target is still a neighbour the caller should see.
    """
    document = as_document(doc)
    _check_direction(direction)
    if relation is not None and not isinstance(relation, str):
        raise ValueError(f"relation must be a string or None, got {relation!r}")
    if limit is not None and (not isinstance(limit, int) or limit < 0):
        raise ValueError(f"limit must be a non-negative int or None, got {limit!r}")
    found: set[str] = set()
    for edge in document["edges"]:
        if relation is not None and edge["relation"] != relation:
            continue
        src, dst = edge_endpoints(edge)
        if direction in ("out", "both") and src == node:
            found.add(dst)
        if direction in ("in", "both") and dst == node:
            found.add(src)
    ordered = sorted(found)
    return ordered if limit is None else ordered[:limit]


def reachable(doc: Any, node: str, direction: str = "out", depth: int | None = 1) -> set[str]:
    """Nodes reachable from ``node`` within ``depth`` hops, excluding ``node`` itself; ``depth=0`` is empty.

    ``depth=None`` walks to the fixpoint (the full transitive set); the default is one hop.
    """
    return _traverse(as_document(doc), node, _check_direction(direction), depth)


def impact(doc: Any, node: str, direction: str = "in", depth: int | None = None) -> set[str]:
    """Affected nodes: the breadth-first closure from ``node``, upstream by default, unlimited by default.

    ``depth=None`` walks to the fixpoint (the full transitive set); a ``depth`` bounds the number of hops.  The
    queried node is not part of its own impact.
    """
    return _traverse(as_document(doc), node, _check_direction(direction), depth)


def slice(doc: Any, node: str, depth: int | None = None) -> dict[str, Any]:
    """The subgraph centred on ``node``: both-direction closure within ``depth`` hops, as a new document.

    The result has its own ``header`` (its ``graph_id`` hashes only the slice; the source document's id is recorded
    as ``parent_graph_id`` and in ``header['slice_of']``), and contains only nodes inside the slice and only edges
    whose *both* endpoints are inside it.  An absent ``node`` yields an empty document rather than an error.
    """
    document = as_document(doc)
    _check_depth(depth)
    inside = _traverse(document, node, "both", depth)
    inside.add(node)
    nodes_out = sorted((n for n in document["nodes"] if n["id"] in inside), key=lambda n: n["id"])
    edges_out = [e for e in document["edges"] if edge_endpoints(e)[0] in inside and edge_endpoints(e)[1] in inside]
    source_header = document.get("header") or {}
    if not isinstance(source_header, dict):
        raise ValueError("malformed graph document: 'header' must be a dict")
    parent_graph_id = str(source_header.get("graph_id", ""))
    header = dict(source_header)
    header.update({
        "schema_version": SCHEMA_VERSION,
        "graph_id": graph_id_of(nodes_out, edges_out),
        "parent_graph_id": parent_graph_id,
        "created_from": "slice",
        "slice_of": {"graph_id": parent_graph_id, "node": str(node), "depth": depth},
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "compatible_schema_version": COMPATIBLE_SCHEMA_VERSION,
        "header": header,
        "nodes": nodes_out,
        "edges": edges_out,
        "unresolved": [e for e in edges_out if e.get("resolution") == "unresolved"],
    }


def path(doc: Any, src: str, dst: str, direction: str = "both") -> list[str]:
    """A shortest path from ``src`` to ``dst`` as ``[src, ..., dst]``, or ``[]`` when no path exists.

    Breadth-first with neighbours expanded in sorted id order, so the answer is deterministic (tie-broken by node
    id).  ``direction="both"`` (the default) ignores edge direction; ``"out"``/``"in"`` follow or reverse the
    document's edges.  ``src == dst`` returns ``[src]`` when the node exists.  Unknown ids give ``[]``.
    """
    document = as_document(doc)
    _check_direction(direction)
    if not isinstance(src, str) or not isinstance(dst, str):
        raise TypeError("src and dst must be node id strings")
    adjacency = _adjacency(document, direction)
    known = set(adjacency)
    known.update(n["id"] for n in document["nodes"])
    if src not in known or dst not in known:
        return []
    previous: dict[str, str | None] = {src: None}
    queue: deque[str] = deque([src])
    while queue:
        current = queue.popleft()
        if current == dst:
            break
        for neighbour in adjacency.get(current, ()):
            if neighbour not in previous:
                previous[neighbour] = current
                queue.append(neighbour)
    if dst not in previous:
        return []
    walk = [dst]
    while (parent := previous[walk[-1]]) is not None:
        walk.append(parent)
    walk.reverse()
    return walk


def diff(a: Any, b: Any) -> dict[str, dict[str, set[str]]]:
    """Describe going **from ``a`` to ``b``**: added/removed/changed ids for nodes and edges.

    Nodes are keyed by ``id`` and edges by :func:`edge_key`; ``changed`` means the same key with different content,
    so ``diff(x, x)`` is empty everywhere.  Each bucket is a set of ids (edge keys for edges).
    """
    left, right = as_document(a), as_document(b)
    left_nodes = {n["id"]: n for n in left["nodes"]}
    right_nodes = {n["id"]: n for n in right["nodes"]}
    left_edges = {edge_key(e): e for e in left["edges"]}
    right_edges = {edge_key(e): e for e in right["edges"]}

    def buckets(before: dict[str, Any], after: dict[str, Any]) -> dict[str, set[str]]:
        added = set(after) - set(before)
        removed = set(before) - set(after)
        changed = {key for key in set(before) & set(after) if before[key] != after[key]}
        return {"added": added, "removed": removed, "changed": changed}

    return {"nodes": buckets(left_nodes, right_nodes), "edges": buckets(left_edges, right_edges)}

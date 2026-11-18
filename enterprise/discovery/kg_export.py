"""Deterministic exporters for a knowledge-graph document: JSON, DOT, GraphML and CSV.

Every exporter is total over the document's vocabulary: an unknown node kind or a future relation is emitted like
any other, never dropped.  Two exports of the same document are byte-identical — there is no clock, no random id
and no set iteration anywhere in the output.  Formats:

* ``json`` — canonical text (sorted keys, compact separators, ASCII): exactly the bytes
  :meth:`KGStore.save` persists, so an export of a stored snapshot equals its ``document`` column.
* ``dot`` — GraphViz digraph, nodes sorted by id, edges sorted by :func:`edge_key`, labels escaped for DOT.
* ``graphml`` — XML via ``xml.etree`` with a declared namespace; attributes are escaped by the serialiser.
* ``csv`` — the node table immediately followed by the edge table, each with its own header row (the ``csv``
  module's minimal quoting, ``\\n`` line endings, stable column order).  :func:`nodes_csv` / :func:`edges_csv`
  return either table alone.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from .kg_query import as_document, edge_blocking, edge_endpoints, edge_key

__all__ = [
    "export", "canonical_json", "canonical_value", "nodes_csv", "edges_csv", "FORMATS", "NODE_COLUMNS",
    "EDGE_COLUMNS", "export_edges", "graphml_id",
]

#: The formats :func:`export` accepts; anything else raises ``ValueError`` (fail closed).
FORMATS = ("json", "dot", "graphml", "csv")

GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"

#: Column order of the CSV node table.
NODE_COLUMNS = ("id", "kind", "origin", "path", "sha256", "detail")
#: Column order of the CSV edge table.
EDGE_COLUMNS = ("edge_id", "from", "to", "relation", "resolution", "reason", "blocking", "rule", "confidence",
                "mode", "scope", "file", "line", "column", "detail")

_NODE_KEYS = (("original_id", "string"), ("kind", "string"), ("origin", "string"), ("path", "string"), ("sha256", "string"),
              ("detail", "string"))
_EDGE_KEYS = (("edge_id", "string"), ("relation", "string"), ("resolution", "string"), ("reason", "string"), ("blocking", "int"),
              ("rule", "string"), ("confidence", "string"), ("mode", "string"), ("scope", "string"),
              ("file", "string"), ("line", "int"), ("column", "int"), ("detail", "string"))


def _json_default(value: Any) -> Any:
    """Sets and tuples serialise sorted — the same mapping ``graph_id_of`` uses, so identities stay comparable."""
    if isinstance(value, (set, frozenset, tuple)):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_value(value: Any) -> str:
    """Canonical JSON of a single value (sorted keys, compact, ASCII) — the serialiser behind every exporter."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_json_default)


def canonical_json(document: Any) -> str:
    """The canonical text of a document: sorted keys, compact separators, ASCII — the bytes the store persists."""
    return canonical_value(as_document(document))


def export(document: Any, format: str) -> str:
    """Render ``document`` (a dict or a ``DependencyGraph``) in ``format``; an unknown format raises ``ValueError``."""
    if format not in FORMATS:
        raise ValueError(f"unknown export format {format!r}, expected one of {', '.join(FORMATS)}")
    if format == "json":
        return canonical_json(document)
    if format == "dot":
        return _dot(as_document(document))
    if format == "graphml":
        return _graphml(as_document(document))
    return nodes_csv(document) + edges_csv(document)


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, str]:
    """Total order over edges: ``edge_key`` first, then the canonical content, so two edges that share an
    ``edge_key`` still sort identically whatever order the input listed them in."""
    return edge_key(edge), canonical_value(edge)


def export_edges(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """``(export_id, edge)`` pairs in deterministic order.

    ``edge_key`` is ``from|to|relation|rule|line``; it ignores the column, file and detail, so two distinct edges can
    share it (two ``COPY`` of one book on one line, ``|`` inside a node id).  Chosen policy: **disambiguate, never
    drop and never fail** - a colliding edge keeps its ``edge_key`` plus ``#<n>``, where ``n`` is its position (from 1)
    among the colliding edges sorted by canonical content.  A key held by one edge is unchanged, so the common case
    is identical to :func:`edge_key`; the numbering depends only on the content, not on the input order.
    """
    ordered = sorted(document["edges"], key=_edge_sort_key)
    totals: dict[str, int] = {}
    for edge in ordered:
        key = edge_key(edge)
        totals[key] = totals.get(key, 0) + 1
    seen: dict[str, int] = {}
    pairs: list[tuple[str, dict[str, Any]]] = []
    for edge in ordered:
        key = edge_key(edge)
        seen[key] = seen.get(key, 0) + 1
        pairs.append((key if totals[key] == 1 else f"{key}#{seen[key]}", edge))
    return pairs


def _escape_dot(text: str) -> str:
    """Quote-safe DOT string content: backslashes and quotes doubled, newlines escaped, CR dropped."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")


def _dot(document: dict[str, Any]) -> str:
    lines = ["digraph knowledge_graph {"]
    for node in sorted(document["nodes"], key=lambda n: n["id"]):
        node_id = str(node["id"])
        kind = str(node["kind"])
        label = f"{node_id} ({kind})"
        lines.append(f'  "{_escape_dot(node_id)}" [label="{_escape_dot(label)}", kind="{_escape_dot(kind)}"];')
    for _, edge in export_edges(document):
        src, dst = edge_endpoints(edge)
        relation = str(edge["relation"])
        resolution = str(edge.get("resolution", "resolved"))
        label = relation if resolution in ("", "resolved") else f"{relation} [{resolution}]"
        lines.append(f'  "{_escape_dot(str(src))}" -> "{_escape_dot(str(dst))}" [label="{_escape_dot(label)}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return canonical_value(value)
    return str(value)


_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_SLUG_LIMIT = 40
#: Characters XML 1.0 cannot carry in text: controls other than tab/LF/CR, lone surrogates, U+FFFE and U+FFFF.
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def graphml_id(prefix: str, original: str) -> str:
    """An XML-safe, deterministic identifier for ``original``.

    ``<prefix>-<slug>-<16 hex of sha256(original)>``: the slug (at most 40 characters of ``[A-Za-z0-9_.-]``) keeps
    the id readable, the digest of the *whole* original keeps it unique after sanitising, and the result is a pure
    function of ``original`` - no counter, no dependence on the other nodes.  It starts with a letter and is bounded
    in length whatever the input (quotes, ``<``, ``&``, unicode, leading digits, 10 000 characters).
    """
    slug = _SLUG_UNSAFE.sub("_", original)[:_SLUG_LIMIT]
    digest = hashlib.sha256(original.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    return f"{prefix}-{slug}-{digest}" if slug else f"{prefix}-{digest}"


def _xml_replacement(match: "re.Match[str]") -> str:
    code = ord(match.group(0))
    return f"\\x{code:02x}" if code < 256 else f"\\u{code:04x}"


def _xml_text(value: Any) -> str:
    """Text valid in XML 1.0: a forbidden character becomes a visible ``\\xNN`` / ``\\uNNNN`` escape, not a hole."""
    return _XML_INVALID.sub(_xml_replacement, _text(value))


def _graphml_nodes(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """``(safe_id, node)`` for every node, plus a placeholder for each edge endpoint that is not a node, so every
    ``<edge>`` refers to a declared ``<node>``.  Two distinct originals that sanitise to one id, or one id held by two
    nodes, raise ``ValueError`` (fail closed) instead of writing an ambiguous document."""
    nodes: dict[str, dict[str, Any]] = {}
    for node in document["nodes"]:
        original = str(node["id"])
        if original in nodes:
            raise ValueError(f"duplicate node id {original!r}: GraphML cannot represent it unambiguously")
        nodes[original] = node
    for edge in document["edges"]:
        for endpoint in edge_endpoints(edge):
            nodes.setdefault(str(endpoint), {"id": str(endpoint), "kind": "unresolved-endpoint", "origin": "absent"})
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for original in sorted(nodes):
        safe = graphml_id("n", original)
        if safe in out:
            raise ValueError(f"node ids {out[safe][1]['id']!r} and {original!r} collide as GraphML id {safe!r}")
        out[safe] = (safe, nodes[original])
    return list(out.values())


def _graphml(document: dict[str, Any]) -> str:
    ET.register_namespace("", GRAPHML_NS)

    def tag(name: str) -> str:
        return f"{{{GRAPHML_NS}}}{name}"

    root = ET.Element(tag("graphml"))
    for name, attr_type in _NODE_KEYS:
        ET.SubElement(root, tag("key"),
                      {"id": f"n_{name}", "for": "node", "attr.name": name, "attr.type": attr_type})
    for name, attr_type in _EDGE_KEYS:
        ET.SubElement(root, tag("key"),
                      {"id": f"e_{name}", "for": "edge", "attr.name": name, "attr.type": attr_type})
    header = document.get("header") if isinstance(document.get("header"), dict) else {}
    graph = ET.SubElement(root, tag("graph"),
                          {"id": graphml_id("g", str(header.get("graph_id") or "G")), "edgedefault": "directed"})
    for safe, node in _graphml_nodes(document):
        element = ET.SubElement(graph, tag("node"), {"id": safe})
        for name, _ in _NODE_KEYS:
            value = node["id"] if name == "original_id" else node.get(name, "")
            ET.SubElement(element, tag("data"), {"key": f"n_{name}"}).text = _xml_text(value)
    for export_id, edge in export_edges(document):
        src, dst = edge_endpoints(edge)
        element = ET.SubElement(graph, tag("edge"), {"id": graphml_id("e", export_id),
                                                     "source": graphml_id("n", str(src)),
                                                     "target": graphml_id("n", str(dst))})
        for name, _ in _EDGE_KEYS:
            if name == "edge_id":
                value: Any = export_id
            else:
                value = edge_blocking(edge) if name == "blocking" else edge.get(name, "")
            ET.SubElement(element, tag("data"), {"key": f"e_{name}"}).text = _xml_text(value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _detail_text(container: dict[str, Any]) -> str:
    detail = container.get("detail") or ""
    return canonical_value(detail) if detail else ""


def nodes_csv(document: Any) -> str:
    """The node table alone: :data:`NODE_COLUMNS` header, one row per node, nodes sorted by id."""
    doc = as_document(document)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(NODE_COLUMNS)
    for node in sorted(doc["nodes"], key=lambda n: n["id"]):
        writer.writerow([
            node["id"], node.get("kind", ""), node.get("origin", ""), node.get("path", ""), node.get("sha256", ""),
            _detail_text(node),
        ])
    return buffer.getvalue()


def edges_csv(document: Any) -> str:
    """The edge table alone: :data:`EDGE_COLUMNS` header, one row per edge, edges sorted by :func:`edge_key`."""
    doc = as_document(document)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EDGE_COLUMNS)
    for export_id, edge in export_edges(doc):
        src, dst = edge_endpoints(edge)
        writer.writerow([
            export_id, src, dst, edge["relation"], edge.get("resolution", "resolved"), edge.get("reason", ""),
            edge_blocking(edge), edge.get("rule", ""), edge.get("confidence", ""), edge.get("mode", ""),
            edge.get("scope", ""), edge.get("file", ""), edge.get("line", ""), edge.get("column", ""),
            _detail_text(edge),
        ])
    return buffer.getvalue()

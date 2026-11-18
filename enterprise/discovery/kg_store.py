"""Queryable store for knowledge-graph snapshots: ``kg_snapshot`` / ``kg_node`` / ``kg_edge`` / ``kg_unresolved``.

The canonical JSON document stays the source of truth — :meth:`KGStore.save` persists it byte-for-byte in
``kg_snapshot.document`` — while the three row tables make the graph queryable **without** loading that document
(acceptance criterion 11): every method below reads only the tables it needs, through parameterised SQL.

Guarantees:

* **Fail closed.**  A document whose ``header.graph_id`` does not hash to its own nodes and edges, or that does not
  survive a canonical JSON round-trip, or whose ``unresolved`` section disagrees with its edge list, is refused
  with ``ValueError`` — never stored unverifiable.
* **Idempotent.**  Re-saving the same ``graph_id`` replaces that snapshot's rows with the incoming document's;
  counts never drift and no row is duplicated.
* **Lossless (criterion 10).**  Every unresolved or blocking edge of the JSON gets a ``kg_unresolved`` row, and
  distinct edges that would collapse into one ``edge_id`` are refused rather than silently dropped.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from enterprise.db import migrate, open_database

from .graph import graph_id_of
from .kg_export import canonical_json, canonical_value
from .kg_query import DIRECTIONS, as_document, edge_blocking, edge_endpoints, edge_key

__all__ = ["KGStore", "DEFAULT_LIMIT"]

#: Page size when a caller does not pass ``limit``; ``None`` means "no limit" (offset then requires a limit).
DEFAULT_LIMIT = 1000


def _page(sql: str, params: list[Any], limit: int | None, offset: int) -> tuple[str, list[Any]]:
    """Append a portable ``LIMIT``/``OFFSET`` tail; values are always bound, never interpolated."""
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError(f"limit must be a non-negative int or None, got {limit!r}")
        sql += " LIMIT ?"
        params.append(limit)
    if offset:
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError(f"offset must be a non-negative int, got {offset!r}")
        if limit is None:
            # SQLite has no bare OFFSET; Postgres has no portable "unbounded" literal — ask for a limit instead.
            raise ValueError("offset requires a non-None limit")
        sql += " OFFSET ?"
        params.append(offset)
    return sql, params


def _detail(row: dict[str, Any]) -> dict[str, Any]:
    """Parse a stored JSON ``detail`` text back into a dict for query results."""
    text = row.get("detail")
    if not text:
        return {}
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


class KGStore:
    """A sqlite (or DSN-addressed) store of graph snapshots, bootstrapped with the repository migrations."""

    def __init__(self, path: str | Path) -> None:
        self._db = open_database(str(path))
        migrate(self._db)

    # -- lifecycle ------------------------------------------------------------------------------------------
    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "KGStore":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- write ----------------------------------------------------------------------------------------------
    def save(self, document: Any, *, application: str = "") -> str:
        """Persist ``document`` idempotently and return its ``graph_id``.

        Accepts a document dict or a ``DependencyGraph``.  ``header.graph_id`` must equal
        ``graph_id_of(nodes, edges)`` and must survive the canonical JSON round-trip; the ``unresolved`` section
        (when present) must match the document's unresolved edges.  Anything else raises ``ValueError`` before a
        single row is written.  Re-saving an existing ``graph_id`` replaces its rows (same document, same rows).
        """
        payload = as_document(document)
        if not isinstance(application, str):
            raise TypeError(f"application must be a string, got {type(application).__name__}")
        header = payload.get("header")
        if not isinstance(header, dict) or not isinstance(header.get("graph_id"), str):
            raise ValueError("document has no header.graph_id; only Layer-3 documents can be stored")
        recorded = header["graph_id"]
        expected = graph_id_of(payload["nodes"], payload["edges"])
        if recorded != expected:
            raise ValueError(f"graph_id mismatch: header records {recorded}, nodes and edges hash to {expected}")
        text = canonical_json(payload)
        reparsed = json.loads(text)
        if graph_id_of(reparsed["nodes"], reparsed["edges"]) != recorded:
            raise ValueError("document does not survive its canonical JSON round-trip; refusing to store it")
        section = payload.get("unresolved")
        if section is not None:
            if not isinstance(section, list):
                raise ValueError("malformed graph document: 'unresolved' must be a list")
            section_keys = sorted(edge_key(e) for e in section)
            edge_keys = sorted(edge_key(e) for e in payload["edges"] if e.get("resolution") == "unresolved")
            if section_keys != edge_keys:
                raise ValueError("'unresolved' does not match the document's unresolved edges; refusing to store")
        nodes, edges = payload["nodes"], payload["edges"]
        node_ids = [str(n["id"]) for n in nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("duplicate node id; two nodes would collapse into one kg_node row")
        seen: set[str] = set()
        for edge in edges:
            key = edge_key(edge)
            if key in seen:
                raise ValueError(f"duplicate edge id {key!r}; two distinct edges would collapse into one row")
            seen.add(key)
        unresolved_rows = [e for e in edges if e.get("resolution") == "unresolved" or edge_blocking(e)]
        blocking_count = sum(edge_blocking(e) for e in edges)
        created_at = datetime.now(timezone.utc).isoformat()
        schema_version = str(payload.get("schema_version") or header.get("schema_version") or "")
        try:
            self._db.execute("DELETE FROM kg_unresolved WHERE graph_id = ?", (recorded,))
            self._db.execute("DELETE FROM kg_edge WHERE graph_id = ?", (recorded,))
            self._db.execute("DELETE FROM kg_node WHERE graph_id = ?", (recorded,))
            self._db.execute("DELETE FROM kg_snapshot WHERE graph_id = ?", (recorded,))
            self._db.execute(
                "INSERT INTO kg_snapshot (graph_id, schema_version, checkpoint_id, source_digest,"
                " parent_graph_id, application, created_at, node_count, edge_count, unresolved_count,"
                " blocking_count, document) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (recorded, schema_version, str(header.get("checkpoint_id", "")),
                 str(header.get("source_digest", "")), str(header.get("parent_graph_id", "")), application,
                 created_at, len(nodes), len(edges), len(unresolved_rows), blocking_count, text),
            )
            for node in nodes:
                self._db.execute(
                    "INSERT INTO kg_node (graph_id, id, kind, origin, path, sha256, detail) VALUES (?,?,?,?,?,?,?)",
                    (recorded, str(node["id"]), str(node["kind"]), str(node.get("origin", "")),
                     str(node.get("path", "")), str(node.get("sha256", "")),
                     canonical_value(node.get("detail") or {})),
                )
            for edge in edges:
                src, dst = edge_endpoints(edge)
                self._db.execute(
                    'INSERT INTO kg_edge (graph_id, edge_id, src, dst, relation, resolution, reason, blocking,'
                    ' rule, confidence, mode, scope, file, line, "column", detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (recorded, edge_key(edge), str(src), str(dst), str(edge["relation"]),
                     str(edge.get("resolution", "resolved")), str(edge.get("reason", "")), edge_blocking(edge),
                     str(edge.get("rule", "")), str(edge.get("confidence", "")), str(edge.get("mode", "")),
                     str(edge.get("scope", "")), str(edge.get("file", "")), int(edge.get("line", 1)),
                     int(edge.get("column", 1)), canonical_value(edge.get("detail") or {})),
                )
            for edge in unresolved_rows:
                src, dst = edge_endpoints(edge)
                self._db.execute(
                    "INSERT INTO kg_unresolved (graph_id, edge_id, reason, blocking, src, dst, relation)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (recorded, edge_key(edge), str(edge.get("reason", "")), edge_blocking(edge),
                     str(src), str(dst), str(edge["relation"])),
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return recorded

    # -- read: documents and metadata ------------------------------------------------------------------------
    def load(self, graph_id: str) -> dict[str, Any]:
        """The stored canonical document (``DependencyGraph.from_dict`` accepts it); ``KeyError`` when absent."""
        row = self._db.execute("SELECT document FROM kg_snapshot WHERE graph_id = ?", (graph_id,)).fetchone()
        if row is None:
            raise KeyError(f"no snapshot for graph_id {graph_id!r}")
        return json.loads(row["document"])

    def latest(self, application: str = "") -> str | None:
        """Most recently stored ``graph_id`` (newest ``created_at``, ties broken by id); ``None`` when empty.

        ``application=""`` means any application; any other value filters on that tag.
        """
        if not isinstance(application, str):
            raise TypeError(f"application must be a string, got {type(application).__name__}")
        if application:
            row = self._db.execute(
                "SELECT graph_id FROM kg_snapshot WHERE application = ?"
                " ORDER BY created_at DESC, graph_id DESC LIMIT 1", (application,)).fetchone()
        else:
            row = self._db.execute(
                "SELECT graph_id FROM kg_snapshot ORDER BY created_at DESC, graph_id DESC LIMIT 1").fetchone()
        return None if row is None else row["graph_id"]

    def list_snapshots(self) -> list[dict[str, Any]]:
        """Snapshot metadata, newest first; the ``document`` columns are not read."""
        return self._db.execute(
            "SELECT graph_id, schema_version, checkpoint_id, source_digest, parent_graph_id, application,"
            " created_at, node_count, edge_count, unresolved_count, blocking_count"
            " FROM kg_snapshot ORDER BY created_at DESC, graph_id DESC").fetchall()

    def counts(self, graph_id: str) -> dict[str, int]:
        """Row counts for one snapshot: ``nodes``, ``edges``, ``unresolved``, ``blocking``; ``KeyError`` when absent."""
        if self._db.execute("SELECT 1 AS present FROM kg_snapshot WHERE graph_id = ?", (graph_id,)).fetchone() is None:
            raise KeyError(f"no snapshot for graph_id {graph_id!r}")
        return {
            "nodes": self._db.execute(
                "SELECT COUNT(*) AS n FROM kg_node WHERE graph_id = ?", (graph_id,)).fetchone()["n"],
            "edges": self._db.execute(
                "SELECT COUNT(*) AS n FROM kg_edge WHERE graph_id = ?", (graph_id,)).fetchone()["n"],
            "unresolved": self._db.execute(
                "SELECT COUNT(*) AS n FROM kg_unresolved WHERE graph_id = ?", (graph_id,)).fetchone()["n"],
            "blocking": self._db.execute(
                "SELECT COUNT(*) AS n FROM kg_edge WHERE graph_id = ? AND blocking = 1",
                (graph_id,)).fetchone()["n"],
        }

    def rows_equal(self, graph_id: str) -> dict[str, int]:
        """Stored row counts per table (``kg_snapshot``, ``kg_node``, ``kg_edge``, ``kg_unresolved``).

        Used to prove criterion 10: for a stored snapshot these equal the JSON's own counts.  An unknown id yields
        zeros rather than an exception — it is a diagnostic, not a lookup.
        """
        def count(sql: str) -> int:
            return self._db.execute(sql, (graph_id,)).fetchone()["n"]

        return {
            "kg_snapshot": count("SELECT COUNT(*) AS n FROM kg_snapshot WHERE graph_id = ?"),
            "kg_node": count("SELECT COUNT(*) AS n FROM kg_node WHERE graph_id = ?"),
            "kg_edge": count("SELECT COUNT(*) AS n FROM kg_edge WHERE graph_id = ?"),
            "kg_unresolved": count("SELECT COUNT(*) AS n FROM kg_unresolved WHERE graph_id = ?"),
        }

    # -- read: row-level queries (never touch the document column) --------------------------------------------
    def nodes(self, graph_id: str, kind: str | None = None, limit: int | None = DEFAULT_LIMIT,
              offset: int = 0) -> list[dict[str, Any]]:
        """Node rows for one snapshot, sorted by id; ``kind`` is filtered in SQL.  ``detail`` comes back parsed."""
        sql = "SELECT id, kind, origin, path, sha256, detail FROM kg_node WHERE graph_id = ?"
        params: list[Any] = [graph_id]
        if kind is not None:
            if not isinstance(kind, str):
                raise TypeError(f"kind must be a string or None, got {type(kind).__name__}")
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY id"
        sql, params = _page(sql, params, limit, offset)
        rows = self._db.execute(sql, params).fetchall()
        for row in rows:
            row["detail"] = _detail(row)
        return rows

    def edges(self, graph_id: str, relation: str | None = None, src: str | None = None, dst: str | None = None,
              limit: int | None = DEFAULT_LIMIT, offset: int = 0) -> list[dict[str, Any]]:
        """Edge rows for one snapshot, sorted by endpoints; filters are applied in SQL.  ``detail`` is parsed."""
        sql = ('SELECT edge_id, src, dst, relation, resolution, reason, blocking, rule, confidence, mode, scope,'
               ' file, line, "column", detail FROM kg_edge WHERE graph_id = ?')
        params: list[Any] = [graph_id]
        for column, value in (("relation", relation), ("src", src), ("dst", dst)):
            if value is not None:
                if not isinstance(value, str):
                    raise TypeError(f"{column} must be a string or None, got {type(value).__name__}")
                sql += f" AND {column} = ?"  # column is one of three fixed literals, never user input
                params.append(value)
        sql += ' ORDER BY src, dst, relation, file, line, "column", edge_id'
        sql, params = _page(sql, params, limit, offset)
        rows = self._db.execute(sql, params).fetchall()
        for row in rows:
            row["detail"] = _detail(row)
        return rows

    def neighbors(self, graph_id: str, node: str, direction: str = "both", relation: str | None = None,
                  limit: int | None = DEFAULT_LIMIT) -> list[str]:
        """Sorted ids adjacent to ``node`` — same contract as :func:`kg_query.neighbors`, answered from edge rows."""
        if direction not in DIRECTIONS:
            raise ValueError(f"unknown direction {direction!r}, expected one of {', '.join(DIRECTIONS)}")
        if not isinstance(node, str):
            raise TypeError(f"node must be a node id string, got {type(node).__name__}")
        if relation is not None and not isinstance(relation, str):
            raise ValueError(f"relation must be a string or None, got {relation!r}")
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ValueError(f"limit must be a non-negative int or None, got {limit!r}")
        found: set[str] = set()
        extra, params = ("", [graph_id, node]) if relation is None else (" AND relation = ?", [graph_id, node, relation])
        if direction in ("out", "both"):
            found.update(row["dst"] for row in self._db.execute(
                f"SELECT DISTINCT dst FROM kg_edge WHERE graph_id = ? AND src = ?{extra}", params).fetchall())
        if direction in ("in", "both"):
            found.update(row["src"] for row in self._db.execute(
                f"SELECT DISTINCT src FROM kg_edge WHERE graph_id = ? AND dst = ?{extra}", params).fetchall())
        ordered = sorted(found)
        return ordered if limit is None else ordered[:limit]

    def impact(self, graph_id: str, node: str, direction: str = "in", depth: int | None = None) -> set[str]:
        """Breadth-first closure from ``node`` (same contract as :func:`kg_query.impact`), one indexed lookup per hop."""
        if direction not in DIRECTIONS:
            raise ValueError(f"unknown direction {direction!r}, expected one of {', '.join(DIRECTIONS)}")
        if not isinstance(node, str):
            raise TypeError(f"node must be a node id string, got {type(node).__name__}")
        if depth is not None and (not isinstance(depth, int) or depth < 0):
            raise ValueError(f"depth must be a non-negative int or None, got {depth!r}")
        seen: set[str] = {node}
        frontier = [node]
        reached: set[str] = set()
        hops = 0
        while frontier and (depth is None or hops < depth):
            next_frontier: list[str] = []
            for current in frontier:
                for neighbour in self.neighbors(graph_id, current, direction, limit=None):
                    if neighbour not in seen:
                        seen.add(neighbour)
                        reached.add(neighbour)
                        next_frontier.append(neighbour)
            frontier = next_frontier
            hops += 1
        return reached

    def unresolved(self, graph_id: str, blocking: bool | None = None, reason: str | None = None,
                   limit: int | None = DEFAULT_LIMIT) -> list[dict[str, Any]]:
        """``kg_unresolved`` rows for one snapshot, sorted deterministically; filters are applied in SQL."""
        sql = "SELECT edge_id, reason, blocking, src, dst, relation FROM kg_unresolved WHERE graph_id = ?"
        params: list[Any] = [graph_id]
        if blocking is not None:
            sql += " AND blocking = ?"
            params.append(1 if blocking else 0)
        if reason is not None:
            if not isinstance(reason, str):
                raise TypeError(f"reason must be a string or None, got {type(reason).__name__}")
            sql += " AND reason = ?"
            params.append(reason)
        sql += " ORDER BY reason, src, dst, relation, edge_id"
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                raise ValueError(f"limit must be a non-negative int or None, got {limit!r}")
            sql += " LIMIT ?"
            params.append(limit)
        return self._db.execute(sql, params).fetchall()

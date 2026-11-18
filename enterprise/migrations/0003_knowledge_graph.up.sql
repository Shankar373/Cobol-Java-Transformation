CREATE TABLE IF NOT EXISTS kg_snapshot (
    graph_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL DEFAULT '',
    source_digest TEXT NOT NULL DEFAULT '',
    parent_graph_id TEXT NOT NULL DEFAULT '',
    application TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    unresolved_count INTEGER NOT NULL DEFAULT 0,
    blocking_count INTEGER NOT NULL DEFAULT 0,
    document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kg_node (
    graph_id TEXT NOT NULL,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (graph_id, id)
);
CREATE INDEX IF NOT EXISTS kg_node_graph_kind ON kg_node (graph_id, kind);
CREATE TABLE IF NOT EXISTS kg_edge (
    graph_id TEXT NOT NULL,
    edge_id TEXT NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    relation TEXT NOT NULL,
    resolution TEXT NOT NULL DEFAULT 'resolved',
    reason TEXT NOT NULL DEFAULT '',
    blocking INTEGER NOT NULL DEFAULT 0,
    rule TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    file TEXT NOT NULL DEFAULT '',
    line INTEGER NOT NULL DEFAULT 0,
    "column" INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (graph_id, edge_id)
);
CREATE INDEX IF NOT EXISTS kg_edge_graph_src ON kg_edge (graph_id, src);
CREATE INDEX IF NOT EXISTS kg_edge_graph_dst ON kg_edge (graph_id, dst, src, relation, file, line, "column", edge_id);
CREATE INDEX IF NOT EXISTS kg_edge_graph_relation ON kg_edge (graph_id, relation);
CREATE TABLE IF NOT EXISTS kg_unresolved (
    graph_id TEXT NOT NULL,
    edge_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    blocking INTEGER NOT NULL DEFAULT 0,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY (graph_id, edge_id)
);

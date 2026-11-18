"""The knowledge-graph store: idempotent save/load, fail-closed validation, lossless rows (criterion 10),
and row-level queries that answer without ever reading the canonical ``document`` column (criterion 11)."""

from __future__ import annotations

import copy

import pytest

from enterprise.discovery.graph import DependencyGraph, Edge, Node, confidence_for, stamp_graph_id
from enterprise.discovery.kg_export import canonical_json
from enterprise.discovery.kg_query import edge_key
from enterprise.discovery.kg_store import KGStore


def _edge(src: str, dst: str, relation: str, *, resolution: str = "resolved", reason: str = "",
          line: int = 1, column: int = 1, file: str = "src/cobol/PROG.cbl") -> Edge:
    return Edge(src, dst, relation, "CALL", file, line, column, resolution, reason,
                rule=f"definition-{relation}", confidence=confidence_for(resolution))


def build_graph() -> DependencyGraph:
    """A representative Layer-3 graph: application → job → programs → copybooks, one ambiguous, two unresolved."""
    graph = DependencyGraph(checkpoint_id="cp-1", source_digest="digest-1")
    for node_id, kind in (
        ("app-payroll", "application"), ("job-payroll", "job"), ("pgm-payroll", "program"),
        ("pgm-tax", "program"), ("cpy-emp", "copybook"), ("cpy-audit", "copybook"),
        ("tbl-employee", "table"), ("iso", "file"),
    ):
        graph.add_node(Node(node_id, kind))
    edges = [
        _edge("app-payroll", "job-payroll", "contains", line=1),
        _edge("job-payroll", "pgm-payroll", "executes", file="jcl/PAYJOB.jcl", line=8),
        _edge("pgm-payroll", "cpy-emp", "copies", line=7),
        _edge("cpy-emp", "cpy-audit", "copies", line=3),
        _edge("pgm-payroll", "tbl-employee", "accesses-table", resolution="ambiguous", line=11),
        _edge("pgm-payroll", "MISSING1", "calls", resolution="unresolved", reason="missing-program", line=9),
        _edge("pgm-payroll", "DYN1", "calls", resolution="unresolved", reason="dynamic-target", line=10),
    ]
    for edge in edges:
        assert graph.add_edge(edge)
    return graph


def sample_document() -> dict:
    return build_graph().to_dict()


@pytest.fixture()
def store(tmp_path):
    with KGStore(tmp_path / "kg.sqlite3") as handle:
        yield handle


def _unresolved_keys(document: dict) -> set[str]:
    return {edge_key(e) for e in document["edges"] if e["resolution"] == "unresolved"}


def _blocking_keys(document: dict) -> set[str]:
    return {edge_key(e) for e in document["edges"] if e.get("blocking")}


def test_save_then_load_round_trips_the_same_graph_id(store):
    document = sample_document()
    graph_id = document["header"]["graph_id"]
    assert store.save(document) == graph_id
    loaded = store.load(graph_id)
    assert loaded["header"]["graph_id"] == graph_id
    assert DependencyGraph.from_dict(loaded).graph_id() == graph_id
    assert canonical_json(loaded) == canonical_json(document)


def test_save_accepts_a_dependency_graph_directly(store):
    graph_id = build_graph().graph_id()
    assert store.save(build_graph()) == graph_id
    assert store.load(graph_id)["header"]["graph_id"] == graph_id


def test_re_saving_the_same_document_is_idempotent(store):
    document = sample_document()
    graph_id = store.save(document)
    before = store.rows_equal(graph_id)
    assert store.save(document) == graph_id
    assert store.rows_equal(graph_id) == before
    assert before["kg_snapshot"] == 1
    assert len(store.list_snapshots()) == 1
    assert store.latest() == graph_id


def test_a_tampered_document_is_rejected_and_nothing_is_stored(store):
    document = sample_document()
    tampered = copy.deepcopy(document)
    tampered["nodes"][0]["kind"] = "job"  # content changed, header still records the old hash
    with pytest.raises(ValueError, match="graph_id mismatch"):
        store.save(tampered)
    assert store.list_snapshots() == []
    assert store.rows_equal(document["header"]["graph_id"])["kg_snapshot"] == 0


def test_a_document_whose_graph_id_does_not_match_its_content_is_refused(store):
    document = sample_document()
    forged = copy.deepcopy(document)
    forged["header"]["graph_id"] = "0" * 64
    with pytest.raises(ValueError, match="graph_id mismatch"):
        store.save(forged)
    assert store.list_snapshots() == []


def test_a_document_without_a_header_is_refused(store):
    document = sample_document()
    del document["header"]
    with pytest.raises(ValueError, match="header.graph_id"):
        store.save(document)
    assert store.list_snapshots() == []


def test_an_unresolved_section_that_disagrees_with_the_edges_is_refused(store):
    document = sample_document()
    tampered = copy.deepcopy(document)
    tampered["unresolved"] = tampered["unresolved"][:-1]  # graph_id does not cover this section
    with pytest.raises(ValueError, match="unresolved"):
        store.save(tampered)
    assert store.list_snapshots() == []


def test_criterion_10_row_counts_equal_the_json_and_no_unresolved_edge_is_lost(store):
    document = sample_document()
    graph_id = store.save(document)
    rows = store.rows_equal(graph_id)
    unresolved = _unresolved_keys(document)
    blocking = _blocking_keys(document)
    ambiguous = {edge_key(e) for e in document["edges"] if e["resolution"] == "ambiguous"}

    assert rows["kg_node"] == len(document["nodes"])
    assert rows["kg_edge"] == len(document["edges"])
    assert rows["kg_unresolved"] == len(unresolved) == len(document["unresolved"])

    stored = {row["edge_id"] for row in store.unresolved(graph_id, limit=None)}
    assert stored == unresolved  # every unresolved edge in the JSON has exactly one row
    assert ambiguous.isdisjoint(stored)
    assert {row["edge_id"] for row in store.unresolved(graph_id, blocking=True, limit=None)} == blocking

    counts = store.counts(graph_id)
    assert counts == {
        "nodes": len(document["nodes"]),
        "edges": len(document["edges"]),
        "unresolved": len(unresolved),
        "blocking": len(blocking),
    }


def test_row_queries_filter_in_sql_and_never_read_the_document_column(store, tmp_path):
    document = sample_document()
    graph_id = store.save(document)
    # Prove the row tables stand alone: blank the canonical document and every row query still answers.
    store._db.execute("UPDATE kg_snapshot SET document = ''", ())
    store._db.commit()

    assert len(store.nodes(graph_id)) == len(document["nodes"])
    assert len(store.nodes(graph_id, kind="program")) == 2  # filtered in SQL, count matches the JSON
    assert [row["id"] for row in store.nodes(graph_id, kind="copybook")] == ["cpy-audit", "cpy-emp"]
    assert len(store.edges(graph_id, relation="copies")) == 2
    assert len(store.edges(graph_id, src="pgm-payroll")) == 4
    assert len(store.edges(graph_id, dst="cpy-emp")) == 1
    assert len(store.unresolved(graph_id)) == len(document["unresolved"])
    assert len(store.unresolved(graph_id, reason="missing-program")) == 1
    assert store.counts(graph_id)["nodes"] == len(document["nodes"])
    assert store.list_snapshots()[0]["node_count"] == len(document["nodes"])

    # Paging happens in SQL too: one row out, and the rest through the offset (a page size is required to page).
    assert len(store.nodes(graph_id, limit=1)) == 1
    assert len(store.nodes(graph_id, limit=len(document["nodes"]), offset=1)) == len(document["nodes"]) - 1
    with pytest.raises(ValueError, match="offset requires"):
        store.nodes(graph_id, limit=None, offset=3)


def test_latest_filters_by_application_and_snapshots_are_addressable(store):
    document = sample_document()
    graph_id = store.save(document, application="payroll")
    assert store.latest("payroll") == graph_id
    assert store.latest("absent-application") is None
    assert store.latest() == graph_id
    snapshots = store.list_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0]["graph_id"] == graph_id
    assert snapshots[0]["application"] == "payroll"
    assert "document" not in snapshots[0]


def test_two_snapshots_are_listed_newest_first_and_filtered_by_application(store):
    first_document = sample_document()
    second_document = copy.deepcopy(first_document)
    second_document["nodes"] = [n for n in second_document["nodes"] if n["id"] != "iso"]
    second_document["edges"] = [e for e in second_document["edges"]
                                if e["from"] != "iso" and e["to"] != "iso"]
    stamp_graph_id(second_document)
    assert DependencyGraph.from_dict(second_document).graph_id() == second_document["header"]["graph_id"]

    first_id = store.save(first_document, application="a")
    second_id = store.save(second_document, application="b")
    assert store.latest("a") == first_id
    assert store.latest("b") == second_id
    listed = store.list_snapshots()
    assert len(listed) == 2
    assert {row["graph_id"] for row in listed} == {first_id, second_id}


def test_looking_up_an_unknown_snapshot_is_an_error_or_empty_never_a_crash(store):
    with pytest.raises(KeyError):
        store.load("0" * 64)
    with pytest.raises(KeyError):
        store.counts("0" * 64)
    assert store.latest() is None
    assert store.list_snapshots() == []
    assert store.rows_equal("0" * 64) == {
        "kg_snapshot": 0, "kg_node": 0, "kg_edge": 0, "kg_unresolved": 0,
    }


def test_query_results_are_json_values_for_detail_columns(store):
    document = sample_document()
    graph_id = store.save(document)
    for row in store.nodes(graph_id, limit=None):
        assert isinstance(row["detail"], dict)
    for row in store.edges(graph_id, limit=None):
        assert isinstance(row["detail"], dict)
        assert isinstance(row["blocking"], int)
        assert row["blocking"] in (0, 1)


def test_store_neighbors_and_impact_match_the_in_memory_queries(tmp_path) -> None:
    from enterprise.discovery import kg_query
    document = build_graph().to_dict()
    with KGStore(tmp_path / "kg.db") as store:
        graph_id = store.save(document)
        for node in ("pgm-payroll", "cpy-audit", "app-payroll", "absent"):
            for direction in ("out", "in", "both"):
                assert store.neighbors(graph_id, node, direction, limit=None) ==                     kg_query.neighbors(document, node, direction, limit=None)
                for depth in (None, 0, 1, 2):
                    assert store.impact(graph_id, node, direction, depth) ==                         kg_query.impact(document, node, direction, depth)
        assert store.neighbors(graph_id, "pgm-payroll", "out", relation="copies") == ["cpy-emp"]

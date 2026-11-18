"""Pure query functions over a document: neighbors, reachability, impact (brute-force checked, criterion 7
style), slice, shortest path and diff (criterion 8 — empty against itself)."""

from __future__ import annotations

import copy

import pytest

from enterprise.discovery.graph import DependencyGraph, Edge, Node, confidence_for, graph_id_of
from enterprise.discovery import kg_query as kg


def _edge(src: str, dst: str, relation: str, *, resolution: str = "resolved", reason: str = "",
          line: int = 1, column: int = 1, file: str = "src/cobol/PROG.cbl") -> Edge:
    return Edge(src, dst, relation, "CALL", file, line, column, resolution, reason,
                rule=f"definition-{relation}", confidence=confidence_for(resolution))


def build_graph() -> DependencyGraph:
    graph = DependencyGraph(checkpoint_id="cp-1", source_digest="digest-1")
    for node_id, kind in (
        ("app-payroll", "application"), ("job-payroll", "job"), ("pgm-payroll", "program"),
        ("pgm-tax", "program"), ("cpy-emp", "copybook"), ("cpy-audit", "copybook"),
        ("tbl-employee", "table"), ("iso", "file"),
    ):
        graph.add_node(Node(node_id, kind))
    for edge in (
        _edge("app-payroll", "job-payroll", "contains", line=1),
        _edge("job-payroll", "pgm-payroll", "executes", file="jcl/PAYJOB.jcl", line=8),
        _edge("pgm-payroll", "cpy-emp", "copies", line=7),
        _edge("cpy-emp", "cpy-audit", "copies", line=3),
        _edge("pgm-payroll", "tbl-employee", "accesses-table", resolution="ambiguous", line=11),
        _edge("pgm-payroll", "MISSING1", "calls", resolution="unresolved", reason="missing-program", line=9),
        _edge("pgm-payroll", "DYN1", "calls", resolution="unresolved", reason="dynamic-target", line=10),
    ):
        assert graph.add_edge(edge)
    return graph


def sample_document() -> dict:
    return build_graph().to_dict()


def brute_force_closure(document: dict, node: str, reverse: bool) -> set[str]:
    """Transitive closure over the raw edge list, repeated until it stops growing (no helper code under test)."""
    reached = {node}
    changed = True
    while changed:
        changed = False
        for edge in document["edges"]:
            src, dst = edge["from"], edge["to"]
            if reverse:
                src, dst = dst, src
            if src in reached and dst not in reached:
                reached.add(dst)
                changed = True
    return reached - {node}


# -- diff (criterion 8) -------------------------------------------------------------------------------


def test_diff_of_a_document_against_itself_is_empty():
    document = sample_document()
    result = kg.diff(document, document)
    assert result == {
        "nodes": {"added": set(), "removed": set(), "changed": set()},
        "edges": {"added": set(), "removed": set(), "changed": set()},
    }
    assert not any(bucket for section in result.values() for bucket in section.values())


def test_diff_reports_an_added_edge_and_an_added_node():
    document = sample_document()

    with_edge = copy.deepcopy(document)
    new_edge = {
        "clause": "CALL", "column": 1, "file": "src/cobol/TAX.cbl", "from": "pgm-tax", "line": 5,
        "relation": "copies", "resolution": "resolved", "to": "cpy-emp",
        "rule": "definition-copies", "confidence": "certain", "mode": "", "scope": "",
    }
    with_edge["edges"].append(new_edge)
    result = kg.diff(document, with_edge)
    assert result["edges"]["added"] == {kg.edge_key(new_edge)}
    assert result["edges"]["removed"] == set()
    assert result["edges"]["changed"] == set()
    assert result["nodes"]["added"] == set()

    with_node = copy.deepcopy(document)
    with_node["nodes"].append({"id": "pgm-new", "kind": "program", "origin": "input"})
    with_node["edges"].append({**new_edge, "from": "pgm-new", "line": 6})
    result = kg.diff(document, with_node)
    assert result["nodes"]["added"] == {"pgm-new"}
    assert len(result["edges"]["added"]) == 1
    assert result["edges"]["added"] == {kg.edge_key(with_node["edges"][-1])}


def test_diff_reports_removed_and_changed():
    document = sample_document()

    without_edge = copy.deepcopy(document)
    removed = without_edge["edges"].pop()
    result = kg.diff(document, without_edge)
    assert result["edges"]["removed"] == {kg.edge_key(removed)}
    assert result["edges"]["added"] == set()

    changed_node = copy.deepcopy(document)
    index = next(i for i, n in enumerate(changed_node["nodes"]) if n["id"] == "pgm-tax")
    changed_node["nodes"][index]["kind"] = "utility"
    result = kg.diff(document, changed_node)
    assert result["nodes"]["changed"] == {"pgm-tax"}
    assert result["nodes"]["added"] == set() and result["nodes"]["removed"] == set()

    # A content field outside the edge key (mode) changes the edge without changing its identity.
    changed_edge = copy.deepcopy(document)
    changed_edge["edges"][0]["mode"] = "execute"
    result = kg.diff(document, changed_edge)
    assert result["edges"]["changed"] == {kg.edge_key(changed_edge["edges"][0])}
    assert result["edges"]["added"] == set() and result["edges"]["removed"] == set()


# -- impact and reachability (criterion 7 style) -------------------------------------------------------


def test_impact_upstream_equals_a_brute_force_transitive_set():
    document = sample_document()
    for node in document["nodes"]:
        assert kg.impact(document, node["id"], direction="in") == brute_force_closure(document, node["id"], True)
    # The copybook's impact is programs, jobs and applications — the criterion-7 shape.
    assert kg.impact(document, "cpy-emp") == {"pgm-payroll", "job-payroll", "app-payroll"}


def test_reachable_downstream_equals_a_brute_force_transitive_set():
    document = sample_document()
    for node in document["nodes"]:
        assert kg.reachable(document, node["id"], direction="out", depth=None) == \
            brute_force_closure(document, node["id"], False)
    assert kg.reachable(document, "app-payroll", depth=None) == {
        "job-payroll", "pgm-payroll", "cpy-emp", "cpy-audit", "tbl-employee", "MISSING1", "DYN1",
    }


def test_depth_bounds_the_traversal():
    document = sample_document()
    assert kg.reachable(document, "app-payroll", depth=0) == set()
    assert kg.reachable(document, "app-payroll", depth=1) == {"job-payroll"}
    assert kg.reachable(document, "app-payroll", depth=2) == {"job-payroll", "pgm-payroll"}
    assert kg.impact(document, "cpy-emp", depth=1) == {"pgm-payroll"}
    assert kg.impact(document, "cpy-emp", depth=2) == {"pgm-payroll", "job-payroll"}
    with pytest.raises(ValueError, match="depth"):
        kg.reachable(document, "cpy-emp", depth=-1)


# -- neighbors ----------------------------------------------------------------------------------------


def test_neighbors_are_sorted_and_filter_by_direction_and_relation():
    document = sample_document()
    assert kg.neighbors(document, "cpy-emp") == ["cpy-audit", "pgm-payroll"]
    assert kg.neighbors(document, "cpy-emp", direction="out") == ["cpy-audit"]
    assert kg.neighbors(document, "cpy-emp", direction="in") == ["pgm-payroll"]
    assert kg.neighbors(document, "pgm-payroll", relation="calls") == ["DYN1", "MISSING1"]
    assert kg.neighbors(document, "cpy-emp", relation="executes") == []
    assert kg.neighbors(document, "cpy-emp", limit=1) == ["cpy-audit"]
    assert kg.neighbors(document, "cpy-emp", limit=None) == ["cpy-audit", "pgm-payroll"]
    with pytest.raises(ValueError, match="direction"):
        kg.neighbors(document, "cpy-emp", direction="sideways")
    with pytest.raises(ValueError, match="limit"):
        kg.neighbors(document, "cpy-emp", limit=-1)


# -- path ----------------------------------------------------------------------------------------------


def test_path_finds_a_known_path_and_returns_empty_when_none_exists():
    document = sample_document()
    assert kg.path(document, "cpy-audit", "job-payroll") == [
        "cpy-audit", "cpy-emp", "pgm-payroll", "job-payroll",
    ]
    assert kg.path(document, "job-payroll", "cpy-audit") == [
        "job-payroll", "pgm-payroll", "cpy-emp", "cpy-audit",
    ]
    assert kg.path(document, "iso", "job-payroll") == []  # an isolated node connects nowhere
    assert kg.path(document, "ghost", "job-payroll") == []  # absent ids are empty, never an exception
    assert kg.path(document, "iso", "iso") == ["iso"]


def test_path_tie_breaks_deterministically_by_node_id():
    graph = DependencyGraph()
    for node_id in ("a", "b", "c", "d"):
        graph.add_node(Node(node_id, "program"))
    graph.add_edge(_edge("a", "b", "calls", line=1))
    graph.add_edge(_edge("a", "c", "calls", line=2))
    graph.add_edge(_edge("b", "d", "calls", line=3))
    graph.add_edge(_edge("c", "d", "calls", line=4))
    document = graph.to_dict()
    assert kg.path(document, "a", "d") == ["a", "b", "d"]  # b < c, every time
    assert kg.path(document, "a", "d") == kg.path(document, "a", "d")


# -- slice -----------------------------------------------------------------------------------------------


def test_slice_contains_only_in_slice_nodes_and_edges():
    document = sample_document()
    result = kg.slice(document, "cpy-emp", depth=1)
    inside = {n["id"] for n in result["nodes"]}
    assert inside == {"cpy-emp", "cpy-audit", "pgm-payroll"}
    assert [n["id"] for n in result["nodes"]] == sorted(inside)
    assert "job-payroll" not in inside
    assert len(result["edges"]) == 2
    for edge in result["edges"]:
        assert edge["from"] in inside and edge["to"] in inside
    # Its own header: a fresh graph_id over the slice, the source as parent.
    assert result["header"]["graph_id"] == graph_id_of(result["nodes"], result["edges"])
    assert result["header"]["parent_graph_id"] == document["header"]["graph_id"]
    assert result["header"]["slice_of"] == {"graph_id": document["header"]["graph_id"],
                                            "node": "cpy-emp", "depth": 1}
    # ... and it is a document DependencyGraph accepts, round-tripping to that same id.
    assert DependencyGraph.from_dict(result).graph_id() == result["header"]["graph_id"]


def test_slice_of_an_absent_node_is_an_empty_document():
    document = sample_document()
    result = kg.slice(document, "ghost")
    assert result["nodes"] == [] and result["edges"] == []
    assert result["header"]["graph_id"] == graph_id_of([], [])


# -- determinism, absence and malformed input ----------------------------------------------------------


def test_all_results_are_deterministic_across_calls():
    document = sample_document()
    assert kg.neighbors(document, "pgm-payroll", limit=None) == kg.neighbors(document, "pgm-payroll", limit=None)
    assert kg.slice(document, "cpy-emp", depth=2) == kg.slice(document, "cpy-emp", depth=2)
    assert kg.diff(document, document) == kg.diff(document, document)
    assert kg.impact(document, "cpy-emp") == kg.impact(document, "cpy-emp")


def test_absent_nodes_yield_empty_results_never_an_exception():
    document = sample_document()
    assert kg.neighbors(document, "ghost") == []
    assert kg.reachable(document, "ghost") == set()
    assert kg.impact(document, "ghost") == set()
    assert kg.path(document, "ghost", "ghost") == []
    assert kg.slice(document, "ghost")["nodes"] == []


def test_malformed_documents_raise():
    document = sample_document()
    with pytest.raises(ValueError, match="must be lists"):
        kg.neighbors({"nodes": [], "edges": "not-a-list"}, "x")
    with pytest.raises(ValueError, match="string 'id'"):
        kg.diff(document, {"nodes": [{"kind": "program"}], "edges": []})
    with pytest.raises(ValueError, match="relation"):
        kg.neighbors({"nodes": [], "edges": [{"from": "a", "to": "b"}]}, "a")
    with pytest.raises(TypeError):
        kg.reachable(42, "x")

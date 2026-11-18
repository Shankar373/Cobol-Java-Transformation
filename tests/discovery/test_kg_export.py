"""Exporters: canonical JSON that equals the stored bytes, DOT/GraphML/CSV that carry every node and edge,
byte-identical across runs, and total over unknown node kinds and relations."""

from __future__ import annotations

import csv
import io
import json
import re
from xml.etree import ElementTree as ET

import pytest

from enterprise.discovery import kg_export as kg
from enterprise.discovery.graph import DependencyGraph, Edge, Node, confidence_for
from enterprise.discovery.kg_query import edge_key
from enterprise.discovery.kg_store import KGStore

GRAPHML_NS = {"g": "http://graphml.graphdrawing.org/xmlns"}


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


def _original_ids(root) -> dict[str, str]:
    """GraphML node id -> the original id held in the ``original_id`` data element."""
    out = {}
    for node in root.findall(".//g:node", GRAPHML_NS):
        data = node.find("g:data[@key='n_original_id']", GRAPHML_NS)
        out[node.get("id")] = data.text or ""
    return out


@pytest.mark.parametrize("fmt", ["json", "dot", "graphml", "csv"])
def test_every_export_is_byte_identical_across_runs(fmt):
    document = sample_document()
    first = kg.export(document, fmt)
    assert kg.export(document, fmt) == first
    # A freshly rebuilt graph with the same content exports identically: no clock, no hidden state.
    assert kg.export(build_graph(), fmt) == first


def test_json_export_equals_the_stored_bytes_and_round_trips_the_graph_id(tmp_path):
    document = sample_document()
    with KGStore(tmp_path / "kg.sqlite3") as store:
        graph_id = store.save(document)
        stored = store._db.execute(
            "SELECT document FROM kg_snapshot WHERE graph_id = ?", (graph_id,)).fetchone()["document"]
    text = kg.export(document, "json")
    assert text == stored
    assert json.loads(text)["header"]["graph_id"] == graph_id
    assert DependencyGraph.from_dict(json.loads(text)).graph_id() == graph_id


def test_dot_carries_every_node_and_edge_and_has_one_line_each():
    document = sample_document()
    dot = kg.export(document, "dot")
    assert dot.startswith("digraph knowledge_graph {") and dot.rstrip().endswith("}")
    for node in document["nodes"]:
        assert f'"{node["id"]}" [' in dot
        assert node["kind"] in dot
    for edge in document["edges"]:
        assert f'"{edge["from"]}" -> "{edge["to"]}" [label="{edge["relation"]}' in dot
    # One line per node and edge plus header and brace — nothing collapsed, nothing duplicated.
    assert len(dot.splitlines()) == 2 + len(document["nodes"]) + len(document["edges"])


def test_dot_escapes_quotes_and_newlines_in_labels():
    graph = DependencyGraph()
    graph.add_node(Node('odd"quoted\nname', "file"))
    graph.add_node(Node("plain", "file"))
    graph.add_edge(_edge('odd"quoted\nname', "plain", "includes", line=1))
    dot = kg.export(graph, "dot")
    assert 'odd\\"quoted\\nname' in dot  # escaped, so the line structure survives
    assert len(dot.splitlines()) == 2 + 2 + 1  # header, two nodes, one edge, closing brace


def test_graphml_parses_and_carries_every_node_and_edge():
    document = sample_document()
    root = ET.fromstring(kg.export(document, "graphml"))
    originals = _original_ids(root)
    # Every document node is present; edges to nodes the document lacks get a declared placeholder.
    assert {n["id"] for n in document["nodes"]} <= set(originals.values())
    assert set(originals.values()) - {n["id"] for n in document["nodes"]} == {"MISSING1", "DYN1"}
    edges = root.findall(".//g:edge", GRAPHML_NS)
    assert len(edges) == len(document["edges"])
    assert {(originals[e.get("source")], originals[e.get("target")]) for e in edges} == \
        {(e["from"], e["to"]) for e in document["edges"]}
    relations = {data.text for data in root.findall(".//g:edge/g:data[@key='e_relation']", GRAPHML_NS)}
    assert relations == {e["relation"] for e in document["edges"]}


def test_graphml_escapes_attributes_so_they_round_trip_through_a_parser():
    hostile = 'a&b<c>"d"'
    graph = DependencyGraph()
    graph.add_node(Node(hostile, "file"))
    graph.add_node(Node("other", "file"))
    graph.add_edge(_edge(hostile, "other", "includes", line=1))
    root = ET.fromstring(kg.export(graph, "graphml"))
    assert set(_original_ids(root).values()) == {hostile, "other"}


def test_csv_parses_and_carries_every_node_and_edge():
    document = sample_document()
    rows = list(csv.reader(io.StringIO(kg.export(document, "csv"))))
    assert rows[0] == list(kg.NODE_COLUMNS)
    node_rows = rows[1:1 + len(document["nodes"])]
    assert rows[1 + len(document["nodes"])] == list(kg.EDGE_COLUMNS)
    edge_rows = rows[2 + len(document["nodes"]):]
    assert len(node_rows) == len(document["nodes"])
    assert len(edge_rows) == len(document["edges"])
    assert {row[0] for row in node_rows} == {n["id"] for n in document["nodes"]}
    assert {row[0] for row in edge_rows} == {edge_key(e) for e in document["edges"]}


def test_nodes_csv_and_edges_csv_return_one_table_each():
    document = sample_document()
    node_rows = list(csv.reader(io.StringIO(kg.nodes_csv(document))))
    edge_rows = list(csv.reader(io.StringIO(kg.edges_csv(document))))
    assert node_rows[0] == list(kg.NODE_COLUMNS) and len(node_rows) == 1 + len(document["nodes"])
    assert edge_rows[0] == list(kg.EDGE_COLUMNS) and len(edge_rows) == 1 + len(document["edges"])


def test_export_accepts_a_dependency_graph():
    assert kg.export(build_graph(), "dot") == kg.export(sample_document(), "dot")


def test_an_unknown_format_raises():
    with pytest.raises(ValueError, match="unknown export format"):
        kg.export(sample_document(), "svg")


def test_export_is_total_over_unknown_kinds_and_relations():
    document = {
        "nodes": [{"id": "future-node", "kind": "future-kind", "origin": "input"}],
        "edges": [{"from": "future-node", "to": "future-target", "relation": "future-relation",
                   "resolution": "resolved", "file": "x", "line": 1, "column": 1}],
    }
    dot = kg.export(document, "dot")
    assert '"future-node"' in dot and "future-kind" in dot and "future-relation" in dot

    csv_text = kg.export(document, "csv")
    assert "future-kind" in csv_text and "future-relation" in csv_text

    root = ET.fromstring(kg.export(document, "graphml"))
    assert set(_original_ids(root).values()) == {"future-node", "future-target"}
    relations = {data.text for data in root.findall(".//g:edge/g:data[@key='e_relation']", GRAPHML_NS)}
    assert relations == {"future-relation"}

    assert "future-kind" in kg.export(document, "json")


# --- hostile ids, id collisions, edge_key collisions --------------------------------------------------------------

NCNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
HOSTILE = [
    'quote"d', "apos'trophe", "<lt>", "a&b", "&amp;", "café-日本語", "9starts-with-digit",
    "  spaced id  ", "x" * 10_000, "line\nbreak", "tab\tchar", "pipe|in|id", "", "\u0001ctrl", "emoji-\U0001f600",
]


def _hostile_doc(ids=HOSTILE) -> dict:
    nodes = [{"id": i, "kind": "file", "origin": "input"} for i in ids]
    edges = [{"from": ids[k], "to": ids[(k + 1) % len(ids)], "relation": "includes", "resolution": "resolved",
              "file": "f", "line": k + 1, "column": 1} for k in range(len(ids))]
    return {"nodes": nodes, "edges": edges}


def test_graphml_ids_are_xml_safe_unique_and_keep_the_original_in_a_mapping_attribute():
    document = _hostile_doc()
    root = ET.fromstring(kg.export(document, "graphml"))
    originals = _original_ids(root)
    assert set(originals.values()) == {kg._xml_text(i) for i in HOSTILE}  # XML-forbidden chars are shown escaped
    assert len(originals) == len(HOSTILE)
    for safe in originals:
        assert NCNAME.match(safe) and len(safe) < 80
    edge_ids = [e.get("id") for e in root.findall(".//g:edge", GRAPHML_NS)]
    assert len(set(edge_ids)) == len(HOSTILE)
    for element in root.findall(".//g:edge", GRAPHML_NS):
        assert element.get("source") in originals and element.get("target") in originals
        assert NCNAME.match(element.get("id"))


def test_graphml_ids_do_not_collide_when_they_sanitise_to_the_same_slug():
    document = _hostile_doc(["a b", "a_b", "a/b", "a<b"])
    root = ET.fromstring(kg.export(document, "graphml"))
    assert len(_original_ids(root)) == 4  # the digest of the whole original separates them


def test_graphml_ids_are_a_pure_function_of_the_original():
    assert kg.graphml_id("n", "same") == kg.graphml_id("n", "same")
    assert kg.graphml_id("n", "same") != kg.graphml_id("e", "same")
    one = ET.fromstring(kg.export(_hostile_doc(HOSTILE[:6]), "graphml"))
    two = ET.fromstring(kg.export(_hostile_doc(list(reversed(HOSTILE[:6]))), "graphml"))
    assert set(_original_ids(one)) == set(_original_ids(two))


def test_graphml_is_byte_identical_whatever_the_input_order():
    document = _hostile_doc()
    shuffled = {"nodes": list(reversed(document["nodes"])), "edges": list(reversed(document["edges"]))}
    assert kg.export(document, "graphml") == kg.export(shuffled, "graphml")


def test_graphml_survives_characters_xml_cannot_carry():
    document = {"nodes": [{"id": "n1", "kind": "file", "origin": "in\x00put\ud800"}],
                "edges": []}
    root = ET.fromstring(kg.export(document, "graphml"))  # raises if the text is not valid XML
    origin = root.find(".//g:node/g:data[@key='n_origin']", GRAPHML_NS).text
    assert origin == "in\\x00put\\ud800"


def test_duplicate_node_ids_fail_closed_in_graphml():
    document = {"nodes": [{"id": "dup", "kind": "file"}, {"id": "dup", "kind": "program"}], "edges": []}
    with pytest.raises(ValueError, match="duplicate node id"):
        kg.export(document, "graphml")


def _colliding_edges() -> list[dict]:
    base = {"from": "a", "to": "b", "relation": "copies", "resolution": "resolved", "rule": "copy-name", "line": 7}
    return [dict(base, file="x.cbl", column=9), dict(base, file="x.cbl", column=30),
            dict(base, file="y.cbl", column=9)]


def test_edge_key_collisions_are_disambiguated_deterministically_never_dropped():
    edges = _colliding_edges()
    assert len({edge_key(e) for e in edges}) == 1  # precondition: one edge_key, three distinct edges
    document = {"nodes": [{"id": "a", "kind": "program"}, {"id": "b", "kind": "copybook"}], "edges": edges}
    ids = [export_id for export_id, _ in kg.export_edges(document)]
    assert ids == [f"{edge_key(edges[0])}#{n}" for n in (1, 2, 3)]
    reordered = dict(document, edges=list(reversed(edges)))
    assert [(i, e["file"], e["column"]) for i, e in kg.export_edges(reordered)] == \
        [(i, e["file"], e["column"]) for i, e in kg.export_edges(document)]
    for fmt in ("dot", "csv", "graphml"):
        assert kg.export(document, fmt) == kg.export(reordered, fmt)
    rows = list(csv.reader(io.StringIO(kg.edges_csv(document))))[1:]
    assert len({row[0] for row in rows}) == 3
    root = ET.fromstring(kg.export(document, "graphml"))
    assert len({e.get("id") for e in root.findall(".//g:edge", GRAPHML_NS)}) == 3


def test_a_unique_edge_key_is_exported_unchanged():
    document = sample_document()
    assert {i for i, _ in kg.export_edges(document)} == {edge_key(e) for e in document["edges"]}


def test_pipe_in_node_ids_cannot_merge_two_different_edges():
    # ("a|b" -> "c") and ("a" -> "b|c") build the same edge_key text; both edges must survive with distinct ids.
    edges = [
        {"from": "a|b", "to": "c", "relation": "copies", "line": 1, "file": "f", "column": 1},
        {"from": "a", "to": "b|c", "relation": "copies", "line": 1, "file": "f", "column": 1},
    ]
    document = {"nodes": [], "edges": edges}
    assert len({i for i, _ in kg.export_edges(document)}) == 2
    root = ET.fromstring(kg.export(document, "graphml"))
    assert len(root.findall(".//g:edge", GRAPHML_NS)) == 2

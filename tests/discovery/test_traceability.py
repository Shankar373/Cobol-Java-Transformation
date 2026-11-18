"""Traceability overlay: generated-from / verified-by edges, identity preservation, cross-graph rejection, persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterprise.discovery.graph import DependencyGraph, Edge, Node
from enterprise.discovery.kg_store import KGStore
from enterprise.discovery.traceability import (
    GraphTraceability,
    TraceabilityError,
    TraceabilityOverlay,
    modernization_impact,
)

PARA = "paragraph:HELLO/MAIN-PARA"


def _parent() -> DependencyGraph:
    graph = DependencyGraph()
    for node_id, kind in (("program:HELLO", "program"), (PARA, "paragraph"), ("copybook:CPY", "copybook"),
                          ("data-item:HELLO/WS-A", "data-item")):
        graph.add_node(Node(node_id, kind, path="HELLO.cob"))
    graph.add_edge(Edge("program:HELLO", PARA, "contains", "contains", "HELLO.cob", 5, 8, "resolved",
                        rule="definition-contains", confidence="certain"))
    graph.checkpoint_id = "ckpt-1"
    graph.source_digest = "digest-1"
    return graph


def _overlay(store: KGStore | None = None) -> TraceabilityOverlay:
    return TraceabilityOverlay(_parent().to_dict(), store)


def _generate(overlay: TraceabilityOverlay) -> None:
    overlay.record_generated_from("java-class:Hello", "java-class", "program:HELLO", path="src/Hello.java",
                                  sha256="aa", line=1, source_digest="digest-1")
    overlay.record_generated_from("java-method:Hello.MAIN_PARA", "java-method", PARA, path="src/Hello.java",
                                  sha256="aa", line=3)
    overlay.record_contains("java-class:Hello", "java-method:Hello.MAIN_PARA", path="src/Hello.java", line=3)


def test_edge_detail_is_a_hashable_tuple_and_edge_is_valid():
    overlay = _overlay()
    edge = overlay.record_generated_from("java-class:Hello", "java-class", "program:HELLO", path="Hello.java",
                                         source_digest="d")
    assert isinstance(edge.detail, tuple)
    hash(edge.key())
    assert edge.rule == "traceability-generated" and edge.confidence == "derived"
    assert dict(edge.detail)["source_digest"] == "d"
    assert (edge.src, edge.dst, edge.relation) == ("java-class:Hello", "program:HELLO", "generated-from")


def test_parent_identity_is_preserved_and_overlay_has_its_own_id():
    parent = _parent()
    parent_id = parent.graph_id()
    overlay = TraceabilityOverlay(parent.to_dict())
    assert overlay.overlay_id == parent_id  # nothing recorded yet
    _generate(overlay)
    assert overlay.overlay_id != parent_id
    assert overlay.parent_graph_id == parent_id
    assert parent.graph_id() == parent_id  # the discovery graph object is untouched
    document = overlay.document()
    assert document["header"]["parent_graph_id"] == parent_id
    assert document["header"]["created_from"] == "traceability"
    assert document["header"]["graph_id"] == overlay.overlay_id
    parent_nodes = {n["id"] for n in parent.to_dict()["nodes"]}
    assert parent_nodes <= {n["id"] for n in document["nodes"]}


def test_overlay_is_deterministic_regardless_of_record_order():
    first, second = _overlay(), _overlay()
    _generate(first)
    second.record_generated_from("java-method:Hello.MAIN_PARA", "java-method", PARA, path="src/Hello.java",
                                 sha256="aa", line=3)
    second.record_generated_from("java-class:Hello", "java-class", "program:HELLO", path="src/Hello.java",
                                 sha256="aa", line=1, source_digest="digest-1")
    second.record_contains("java-class:Hello", "java-method:Hello.MAIN_PARA", path="src/Hello.java", line=3)
    assert first.overlay_id == second.overlay_id
    assert first.document() == second.document()


def test_cross_graph_generated_from_is_rejected():
    overlay = _overlay()
    with pytest.raises(TraceabilityError, match="cross-graph"):
        overlay.record_generated_from("java-class:X", "java-class", "program:HELLO", path="X.java",
                                      graph_id="f" * 64)
    with pytest.raises(TraceabilityError, match="cross-graph"):  # origin node belongs to some other graph
        overlay.record_generated_from("java-class:X", "java-class", "program:OTHER", path="X.java")
    assert overlay.untraced_classes() == []


def test_cross_graph_verified_by_is_rejected():
    overlay = _overlay()
    with pytest.raises(TraceabilityError, match="cross-graph"):
        overlay.record_verified_by("program:HELLO", "run", "r1", checksum="c", artifact_path="m.json",
                                   graph_id="f" * 64)
    with pytest.raises(TraceabilityError, match="cross-graph"):
        overlay.record_verified_by("program:OTHER", "run", "r1", checksum="c", artifact_path="m.json")


def test_generated_from_origin_kind_is_enforced():
    parent = _parent()
    parent.add_node(Node("file:HELLO.cob", "file"))
    overlay = TraceabilityOverlay(parent.to_dict())
    with pytest.raises(TraceabilityError, match="expected one of"):
        overlay.record_generated_from("java-class:X", "java-class", "file:HELLO.cob", path="X.java")
    with pytest.raises(TraceabilityError, match="file path"):
        overlay.record_generated_from("java-class:X", "java-class", "program:HELLO", path="")
    with pytest.raises(TraceabilityError, match="generated kind"):
        overlay.record_generated_from("x", "table", "program:HELLO", path="X.java")


def test_verified_by_requires_evidence():
    overlay = _overlay()
    with pytest.raises(TraceabilityError, match="checksum and artifact path"):
        overlay.record_verified_by("program:HELLO", "run", "r1", checksum="", artifact_path="m.json")
    with pytest.raises(TraceabilityError, match="checksum and artifact path"):
        overlay.record_verified_by("program:HELLO", "run", "r1", checksum="c", artifact_path="")
    with pytest.raises(TraceabilityError, match="confidence"):
        overlay.record_verified_by("program:HELLO", "run", "r1", checksum="c", artifact_path="m", confidence="heuristic")


def test_verified_by_carries_checksum_and_artifact_path():
    overlay = _overlay()
    _generate(overlay)
    edge = overlay.record_verified_by("java-class:Hello", "test-case", "HelloTest", checksum="abc",
                                      artifact_path="tests/HelloTest.java")
    assert edge.confidence == "certain" and edge.dst == "test-case:HelloTest"
    assert dict(edge.detail)["checksum"] == "abc"
    node = overlay.graph.nodes["test-case:HelloTest"]
    assert node.sha256 == "abc" and node.path == "tests/HelloTest.java"


def test_impact_of_a_paragraph_reaches_java_method_class_and_tests():
    overlay = _overlay()
    _generate(overlay)
    overlay.record_verified_by("java-class:Hello", "test-case", "HelloTest", checksum="abc", artifact_path="t.java")
    overlay.record_verified_by("program:HELLO", "run", "run-1", checksum="def", artifact_path="manifest.json")
    result = modernization_impact(overlay.document(), PARA)
    assert result["java_methods"] == ["java-method:Hello.MAIN_PARA"]
    assert result["java_classes"] == ["java-class:Hello"]
    assert result["evidence"] == ["run:run-1", "test-case:HelloTest"]
    assert "program:HELLO" in result["cobol"]


def test_untraced_classes_reports_classes_without_origin_edge():
    overlay = _overlay()
    overlay.graph.add_node(Node("java-class:Orphan", "java-class", path="Orphan.java", origin="derived"))
    _generate(overlay)
    assert overlay.untraced_classes() == ["java-class:Orphan"]


def test_persistence_round_trip(tmp_path: Path):
    with KGStore(tmp_path / "kg.sqlite3") as store:
        overlay = _overlay(store)
        _generate(overlay)
        overlay.record_verified_by("program:HELLO", "run", "run-1", checksum="def", artifact_path="m.json")
        overlay_id = overlay.save(application="HELLO")
        assert overlay_id == overlay.overlay_id
        assert store.counts(overlay.parent_graph_id)["nodes"] == 4  # the discovery graph is stored unchanged
        assert store.load(overlay_id)["header"]["parent_graph_id"] == overlay.parent_graph_id
        assert {e["src"] for e in store.edges(overlay_id, relation="generated-from")} == {
            "java-class:Hello", "java-method:Hello.MAIN_PARA"}
        assert store.edges(overlay_id, relation="verified-by")[0]["confidence"] == "certain"
        reloaded = TraceabilityOverlay.load(store, overlay_id)
        assert reloaded.overlay_id == overlay_id
        assert reloaded.parent_graph_id == overlay.parent_graph_id
        assert reloaded.document() == overlay.document()
        overlay.save()  # idempotent
        assert store.rows_equal(overlay_id)["kg_edge"] == len(overlay.document()["edges"])


def test_save_without_store_raises():
    with pytest.raises(RuntimeError, match="no KGStore"):
        _overlay().save()


def test_a_parent_that_does_not_reproduce_its_graph_id_is_refused():
    document = _parent().to_dict()
    document["header"]["graph_id"] = "0" * 64
    with pytest.raises(TraceabilityError, match="does not reproduce"):
        TraceabilityOverlay(document)


def test_merge_requires_same_parent_and_unions_records():
    first, second = _overlay(), _overlay()
    first.record_generated_from("java-class:A", "java-class", "program:HELLO", path="A.java")
    second.record_generated_from("java-class:B", "java-class", "copybook:CPY", path="B.java")
    merged = first.merge(second)
    assert merged.classes() == ["java-class:A", "java-class:B"]
    other_parent = _parent()
    other_parent.add_node(Node("program:EXTRA", "program"))
    with pytest.raises(TraceabilityError, match="different graphs"):
        first.merge(TraceabilityOverlay(other_parent.to_dict()))


def test_legacy_alias():
    assert GraphTraceability is TraceabilityOverlay

"""Discovery graph -> transformation -> traceability, end to end (Layer 3 acceptance criterion 9).

Discovery builds the graph; the modernization pipeline consults it (program set), generates Java, and records a
``generated-from`` edge for every generated class and method in a traceability overlay of the *same* ``graph_id``.
Evidence is recorded as ``verified-by``; the lineage is carried by the sealed evidence manifest.  No Docker, no LLM.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from api import serialization
from engine.graph_traceability import (
    program_closure,
    record_verification,
    scan_java_project,
    trace_generation,
)
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.kg_store import KGStore
from enterprise.discovery.traceability import TraceabilityError, TraceabilityOverlay, modernization_impact

MAIN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM  PIC 9(4) VALUE 42.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CALC-PARA
           CALL 'SUBPGM' USING WS-NUM.
           DISPLAY WS-NUM
           STOP RUN.
       CALC-PARA.
           ADD 1 TO WS-NUM.
"""
SUB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPGM.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-NUM  PIC 9(4).
       PROCEDURE DIVISION USING LK-NUM.
       SUB-PARA.
           DISPLAY 'SUB'.
           GOBACK.
"""
CHECKSUM = "b" * 64


@pytest.fixture()
def estate(tmp_path: Path) -> dict:
    src = tmp_path / "src"
    src.mkdir()
    (src / "MAINPGM.cob").write_text(MAIN, encoding="utf-8")
    (src / "SUBPGM.cob").write_text(SUB, encoding="utf-8")
    result = discover(DiscoveryRequest("directory", str(src)), tmp_path / "store")
    return {"src": src, "graph_path": result.outdir / "dependency-graph.json", "root": tmp_path}


def _run(estate: dict, out: str = "out", store: bool = False):
    root = estate["root"]
    return UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(estate["src"]), output_dir=str(root / out), application_id="app", entrypoint="MAINPGM",
        docker_available=True, target_runtime="plain_java", knowledge_graph_path=str(estate["graph_path"]),
        knowledge_graph_store=str(root / "kg.sqlite3") if store else "")).execute()


def test_every_generated_class_traces_to_a_program_node_of_the_same_graph(estate) -> None:
    graph = json.loads(estate["graph_path"].read_text(encoding="utf-8"))
    report = _run(estate)
    assert report.generation_success, report.generation_errors
    assert report.knowledge_graph_id == graph["header"]["graph_id"]
    assert report.traceability_overlay_id != report.knowledge_graph_id
    assert report.traceability["untraced"] == []

    overlay = json.loads((Path(report.output_dir) / "traceability-overlay.json").read_text(encoding="utf-8"))
    assert overlay["header"]["parent_graph_id"] == graph["header"]["graph_id"]
    program_nodes = {n["id"] for n in graph["nodes"] if n["kind"] == "program"}
    generated = [e for e in overlay["edges"] if e["relation"] == "generated-from"]
    traced_classes = {e["from"] for e in generated if e["from"].startswith("java-class:") and e["to"] in program_nodes}
    on_disk = {f"java-class:{c.name}" for c in scan_java_project(report.generated_project_dir)}
    assert on_disk == {"java-class:Mainpgm", "java-class:Subpgm", "java-class:ServiceRegistry"}
    assert traced_classes == on_disk  # criterion 9: no generated class without an edge into the graph
    assert {n["id"] for n in graph["nodes"]} <= {n["id"] for n in overlay["nodes"]}


def test_transformation_consults_the_graph_for_its_program_set(estate) -> None:
    graph = json.loads(estate["graph_path"].read_text(encoding="utf-8"))
    assert program_closure(graph, "MAINPGM") == ["MAINPGM", "SUBPGM"]
    assert program_closure(graph, "SUBPGM") == ["SUBPGM"]
    with pytest.raises(KeyError):
        program_closure(graph, "NOPE")
    report = _run(estate)
    assert report.graph_program_set == ("MAINPGM", "SUBPGM")
    assert not any("differs" in line for line in report.limitations)


def test_impact_of_a_cobol_paragraph_reaches_its_java_method_and_tests(estate) -> None:
    report = _run(estate)
    overlay_doc = json.loads((Path(report.output_dir) / "traceability-overlay.json").read_text(encoding="utf-8"))
    parent = json.loads(estate["graph_path"].read_text(encoding="utf-8"))
    overlay = TraceabilityOverlay(parent)
    trace_generation(overlay, report.generated_project_dir, program_ids=report.generated_program_ids,
                     entry_program="MAINPGM", source_digest=parent["header"]["source_digest"])
    assert overlay.document() == overlay_doc  # re-tracing the same project reproduces the overlay byte for byte

    tests = record_verification(
        overlay, run_id="run-1", manifest_hash=CHECKSUM, verdict_state="VERIFIED", artifact_path="manifest.json",
        subjects=["program:MAINPGM"], test_cases=[("MainpgmEquivalence", "c" * 64, "evidence/stdout.cmp")])
    assert tests == ["run:run-1", "test-case:MainpgmEquivalence"]
    impact = modernization_impact(overlay.document(), "paragraph:MAINPGM/CALC-PARA")
    assert "java-method:Mainpgm.CALC_PARA" in impact["java_methods"]
    assert "java-class:Mainpgm" in impact["java_classes"]
    assert impact["evidence"] == ["run:run-1", "test-case:MainpgmEquivalence"]
    assert "program:MAINPGM" in impact["cobol"]


def test_unverified_run_records_no_verified_by(estate) -> None:
    report = _run(estate)
    overlay = TraceabilityOverlay(json.loads(estate["graph_path"].read_text(encoding="utf-8")))
    trace_generation(overlay, report.generated_project_dir, program_ids=report.generated_program_ids)
    before = overlay.overlay_id
    assert record_verification(overlay, run_id="run-2", manifest_hash=CHECKSUM, verdict_state="NOT_VERIFIED",
                               artifact_path="m.json", subjects=["program:MAINPGM"]) == []
    assert overlay.overlay_id == before


def test_overlay_is_deterministic_and_persists(estate) -> None:
    first = _run(estate, "out-a", store=True)
    second = _run(estate, "out-b")
    assert first.traceability_overlay_id == second.traceability_overlay_id  # same input, same overlay id
    assert dict(first.graph_traceability) == {"graph_id": first.knowledge_graph_id,
                                              "traceability_overlay_id": first.traceability_overlay_id}
    with KGStore(estate["root"] / "kg.sqlite3") as store:
        assert {s["graph_id"] for s in store.list_snapshots()} == {
            first.knowledge_graph_id, first.traceability_overlay_id}
        reloaded = TraceabilityOverlay.load(store, first.traceability_overlay_id)
        assert reloaded.parent_graph_id == first.knowledge_graph_id
        assert reloaded.untraced_classes() == []


def test_untraceable_generated_class_fails_the_run(estate, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "src").mkdir(parents=True)
    (project / "src" / "Stray.java").write_text("public class Stray {\n    void f() {\n    }\n}\n", encoding="utf-8")
    overlay = TraceabilityOverlay(json.loads(estate["graph_path"].read_text(encoding="utf-8")))
    report = trace_generation(overlay, project)
    assert report.untraced == ["java-class:Stray"]
    assert overlay.untraced_classes() == []  # nothing was guessed and recorded


def test_pipeline_refuses_when_a_class_has_no_graph_origin(estate, tmp_path: Path) -> None:
    partial = json.loads(estate["graph_path"].read_text(encoding="utf-8"))
    partial["nodes"] = [n for n in partial["nodes"] if n["id"] != "program:SUBPGM"]
    partial["edges"] = [e for e in partial["edges"] if "program:SUBPGM" not in (e["from"], e["to"])]
    from enterprise.discovery.graph import stamp_graph_id
    partial["unresolved"] = []
    stamp_graph_id(partial)
    path = tmp_path / "partial-graph.json"
    path.write_text(json.dumps(partial), encoding="utf-8")
    report = UniversalModernizationPipeline(ModernizationConfig(
        source_dir=str(estate["src"]), output_dir=str(tmp_path / "out-partial"), application_id="app",
        entrypoint="MAINPGM", docker_available=True, target_runtime="plain_java",
        knowledge_graph_path=str(path))).execute()
    assert report.generation_success is False
    assert report.generated_project_dir == ""
    assert any("java-class:Subpgm" in e for e in report.generation_errors)


def test_graph_id_travels_in_the_sealed_evidence_manifest() -> None:
    from tests.test_persistence_integrity import _manifest

    base = _manifest()
    pairs = (("graph_id", "g" * 64), ("traceability_overlay_id", "o" * 64))
    traced = dataclasses.replace(base, graph_traceability=pairs)
    assert traced.manifest_hash != base.manifest_hash  # lineage is covered by the seal
    decoded = serialization.decode_evidence_manifest(serialization.encode_evidence_manifest(traced))
    assert decoded is not None and decoded.graph_traceability == pairs
    assert decoded.manifest_hash == traced.manifest_hash
    untouched = serialization.decode_evidence_manifest(serialization.encode_evidence_manifest(base))
    assert untouched is not None and untouched.graph_traceability == ()
    assert untouched.manifest_hash == base.manifest_hash


def test_parent_that_does_not_reproduce_its_id_is_refused(estate) -> None:
    graph = json.loads(estate["graph_path"].read_text(encoding="utf-8"))
    graph["header"]["graph_id"] = "0" * 64
    with pytest.raises(TraceabilityError, match="does not reproduce"):
        TraceabilityOverlay(graph)

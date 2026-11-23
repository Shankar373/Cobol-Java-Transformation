"""Layer 6: the Application IR is a deterministic, faithful, tamper-evident projection of the Layer 5 facts."""

from __future__ import annotations

import copy
import dataclasses
import random
from pathlib import Path

import pytest

from engine.application_ir.model import EDGE_KINDS, NOTE_KINDS, ApplicationIR
from engine.application_ir.project import canonical, coverage, ir_id_of, project, sha256_of, to_dict, verify
from engine.semantic_facts.build import build_semantic_facts

REPO = Path(__file__).resolve().parents[2]
FIXTURES = sorted(p for p in (REPO / "fixtures").rglob("*") if p.is_file() and p.suffix.lower() in (".cob", ".cbl"))
SOURCES = {p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8", errors="replace") for p in FIXTURES}

CALLER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(5).
       01 B PIC 9(4).
       PROCEDURE DIVISION.
       MAIN.
           MOVE A TO B.
           CALL 'SUB1' USING A B.
           CALL 'GHOST' USING A.
           PERFORM NEXT1.
           STOP RUN.
       NEXT1.
           ADD 1 TO B.
"""
CALLEE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUB1.
       DATA DIVISION.
       LINKAGE SECTION.
       01 P1 PIC X(10).
       01 P2 PIC 9(4).
       PROCEDURE DIVISION USING P1 P2.
       MAIN.
           GOBACK.
"""


@pytest.fixture(scope="module")
def small():
    document = build_semantic_facts({"caller.cbl": CALLER, "sub1.cbl": CALLEE}).as_dict()
    return document, project(document)


@pytest.fixture(scope="module")
def corpus():
    document = build_semantic_facts(SOURCES).as_dict()
    return document, project(document)


def test_the_corpus_projects_without_loss_and_without_invention(corpus):
    document, ir = corpus
    assert coverage(ir, document) == []
    assert verify(to_dict(ir), document) == []
    assert len(ir.declarations) == len(document["declarations"]) and len(ir.references) == len(document["references"])


def test_every_fact_kind_of_the_document_has_a_projection(corpus):
    from engine.application_ir.project import DECLARATION_FACTS, EDGE_FACTS, REFERENCE_FACTS

    kinds = {f["kind"] for f in corpus[0]["facts"]}
    assert kinds <= DECLARATION_FACTS | REFERENCE_FACTS | EDGE_FACTS | set(NOTE_KINDS)


def test_a_new_fact_kind_without_a_projection_is_reported(small):
    document, ir = small
    forged = copy.deepcopy(document)
    forged["facts"].append({**forged["facts"][0], "kind": "future-kind", "fact_id": "fact:forged"})
    assert any("no projection" in p for p in coverage(ir, forged))


def test_projection_is_deterministic_and_input_order_free():
    items = list(SOURCES.items())[:20]
    reference = project(build_semantic_facts(dict(items)).as_dict())
    random.Random(7).shuffle(items)
    again = project(build_semantic_facts(dict(items)).as_dict())
    assert canonical(reference) == canonical(again) and ir_id_of(reference) == ir_id_of(again)


def test_the_projection_never_mutates_its_document(small):
    document, _ = small
    before = copy.deepcopy(document)
    project(document)
    assert document == before


def test_elements_are_immutable(small):
    _, ir = small
    with pytest.raises(dataclasses.FrozenInstanceError):
        ir.declarations[0].name = "X"  # type: ignore[misc]
    assert isinstance(ir, ApplicationIR)
    assert all(isinstance(t, tuple) for t in (ir.programs, ir.declarations, ir.references, ir.edges, ir.notes))


def test_layer5_identity_span_resolution_and_confidence_survive_verbatim(small):
    document, ir = small
    by_id = {d["decl_id"]: d for d in document["declarations"]}
    for d in ir.declarations:
        raw = by_id[d.decl_id]
        assert (d.kind, d.name, d.qualification, d.parent, d.unsupported) == (
            raw["kind"], raw["name"], tuple(raw["qualification"]), raw["parent"], raw["unsupported"])
        assert (d.span.as_dict() if d.span else None) == raw["span"]
    raw_refs = {r["ref_id"]: r for r in document["references"]}
    for r in ir.references:
        raw = raw_refs[r.ref_id]
        assert (r.resolution.state, r.resolution.confidence, r.resolution.reason, list(r.resolution.candidates)) == (
            raw["resolution"]["state"], raw["resolution"]["confidence"], raw["resolution"]["reason"],
            raw["resolution"]["candidates"])
        assert (r.span.as_dict() if r.span else None) == raw["span"]


def test_edges_are_typed_and_every_edge_names_its_layer5_origin(small):
    document, ir = small
    known = {f["fact_id"] for f in document["facts"]} | {r["ref_id"] for r in document["references"]}
    assert {e.kind for e in ir.edges} <= set(EDGE_KINDS)
    assert all(e.provenance in known for e in ir.edges)
    calls = {dict(e.attributes)["target"]: e for e in ir.edges if e.kind == "call"}
    assert calls["SUB1"].resolution.state == "resolved" and calls["SUB1"].target.endswith("program:SUB1#1")
    assert calls["SUB1"].source.endswith("program:CALLER#1")
    assert calls["GHOST"].resolution.reason == "missing-program" and calls["GHOST"].target == ""
    kinds = {e.kind for e in ir.edges}
    assert {"reads-item", "writes-item", "performs", "call-arity", "call-binding"} <= kinds


def test_modify_access_projects_to_both_a_read_and_a_write_edge(small):
    _, ir = small
    add = [e for e in ir.edges if dict(e.attributes).get("access") == "modify" and dict(e.attributes).get("name") == "B"]
    assert {e.kind for e in add} == {"reads-item", "writes-item"}


def test_programs_list_their_declarations(small):
    _, ir = small
    caller = next(p for p in ir.programs if p.name == "CALLER")
    assert len(caller.paragraphs) == 2 and len(caller.data_roots) == 2
    callee = next(p for p in ir.programs if p.name == "SUB1")
    assert len(callee.data_roots) == 2 and callee.file == "sub1.cbl"


def test_the_ir_id_binds_the_semantic_id_and_any_binding_change():
    sources = {"caller.cbl": CALLER, "sub1.cbl": CALLEE}
    plain = project(build_semantic_facts(sources).as_dict())
    other_graph = project(build_semantic_facts(sources, graph_id="a" * 64).as_dict())
    assert plain.binding("semantic_id") != other_graph.binding("semantic_id")
    assert ir_id_of(plain) != ir_id_of(other_graph)
    edited = project(build_semantic_facts(
        {"caller.cbl": CALLER.replace("MOVE A TO B", "MOVE B TO A"), "sub1.cbl": CALLEE}).as_dict())
    assert ir_id_of(edited) != ir_id_of(plain)


def _forged(small, mutate):
    document, ir = small
    serialised = copy.deepcopy(to_dict(ir))
    mutate(serialised)
    return verify(serialised, document)


def _flip(access):
    return "write" if access != "write" else "read"


@pytest.mark.parametrize("name,mutate", [
    ("edge target", lambda d: d["edges"][0].__setitem__("target", "sym:forged")),
    ("edge dropped", lambda d: d["edges"].pop()),
    ("edge invented", lambda d: d["edges"].append({**d["edges"][0], "edge_id": "edge:forged", "provenance": "fact:nope"})),
    ("declaration name", lambda d: d["declarations"][0].__setitem__("name", "FORGED")),
    ("reference access", lambda d: d["references"][0].__setitem__("access", _flip(d["references"][0]["access"]))),
    ("resolution confidence", lambda d: d["references"][0]["resolution"].__setitem__("confidence", "heuristic")),
    ("span line", lambda d: next(x for x in d["declarations"] if x["span"])["span"].__setitem__("line", 999)),
    ("program dropped", lambda d: d["programs"].pop()),
    ("complete flag", lambda d: d.__setitem__("complete", not d["complete"])),
    ("binding", lambda d: d["header"]["bindings"].__setitem__("semantic_id", "e" * 64)),
    ("ir_id", lambda d: d["header"].__setitem__("ir_id", "e" * 64)),
])
def test_any_tampering_is_detected(small, name, mutate):
    assert _forged(small, mutate), name


def test_a_forged_ir_with_a_recomputed_id_is_still_not_the_projection(small):
    document, ir = small
    forged = copy.deepcopy(to_dict(ir))
    forged["edges"][0]["target"] = "sym:forged"
    body = {k: v for k, v in forged.items() if k not in ("schema", "header")}
    forged["header"]["ir_id"] = sha256_of(
        {"bindings": forged["header"]["bindings"], "body": body, "tool": forged["header"]["tool"]})
    problems = verify(forged, document)
    assert problems and not any("ir_id does not match" in p for p in problems)

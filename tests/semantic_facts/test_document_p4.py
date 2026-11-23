"""Layer 5 P4: the canonical, content-addressed facts document (docs/architecture/LAYER5_DESIGN.md, section 5)."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from engine.semantic_facts.build import build_semantic_facts, source_digest_of
from engine.semantic_facts.document import FACT_KINDS, SCHEMA, Fact, verify
from engine.semantic_facts.references import Resolution
from enterprise.discovery import graph

REPO = Path(__file__).resolve().parents[2]
FIXTURES = sorted(p for p in (REPO / "fixtures").rglob("*") if p.is_file() and p.suffix.lower() in (".cob", ".cbl"))

CLEAN = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {name}.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
    "       01 A PIC 9(3).\n       01 B PIC 9(3).\n       PROCEDURE DIVISION.\n       MAIN.\n           MOVE A TO B.\n"
    "           PERFORM SUB1.\n           STOP RUN.\n       SUB1.\n           ADD 1 TO A.\n       SUB2.\n           ADD 1 TO B.\n"
)


def _clean(name: str = "P") -> str:
    return CLEAN.format(name=name)


def test_canonical_bytes_are_the_graph_encoder() -> None:
    from engine.semantic_facts import document

    assert document.canonical_bytes is graph.canonical_bytes is graph._canonical_bytes


def test_a_clean_program_is_complete_and_verifies() -> None:
    doc = build_semantic_facts({"src/P.cbl": _clean()})
    assert doc.complete and doc.header["unsupported_summary"] == {}
    assert verify(doc.as_dict()) == []
    assert doc.as_dict()["schema"] == SCHEMA
    kinds = {f["kind"] for f in doc.facts}
    assert {"program", "paragraph", "data-item", "data-ref", "paragraph-ref", "performs", "falls-through"} <= kinds
    assert kinds <= set(FACT_KINDS)


def test_two_runs_give_identical_bytes() -> None:
    sources = {"src/P.cbl": _clean(), "src/Q.cbl": _clean("Q")}
    assert build_semantic_facts(sources).canonical() == build_semantic_facts(sources).canonical()


def test_input_order_does_not_matter() -> None:
    sources = {f"src/{n}.cbl": _clean(n) for n in "ABCDEF"}
    items = list(sources.items())
    reference = build_semantic_facts(sources)
    for seed in range(5):
        random.Random(seed).shuffle(items)
        shuffled = build_semantic_facts(dict(items))
        assert shuffled.semantic_id == reference.semantic_id and shuffled.canonical() == reference.canonical()


def test_the_repo_fixtures_build_verify_and_are_order_independent() -> None:
    sources = {p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8", errors="replace") for p in FIXTURES}
    doc = build_semantic_facts(sources)
    assert verify(doc.as_dict()) == [] and len(doc.declarations) > 500
    reverse = build_semantic_facts(dict(reversed(list(sources.items()))))
    assert reverse.semantic_id == doc.semantic_id
    # everything in the document is plain JSON with no absolute paths
    text = doc.canonical().decode("ascii")
    leaked = ("C:\\" in text) or (str(REPO).replace("\\", "/") in text)
    assert not leaked


def test_no_fact_has_a_nondeterministic_or_timestamp_field() -> None:
    doc = build_semantic_facts({"src/P.cbl": _clean()})
    text = json.dumps(doc.as_dict())
    assert "created_at" not in text and "timestamp" not in text


def test_facts_digest_is_body_only_and_semantic_id_covers_the_bindings() -> None:
    sources = {"src/P.cbl": _clean()}
    plain = build_semantic_facts(sources, graph_id="a" * 64)
    other_graph = build_semantic_facts(sources, graph_id="b" * 64)
    assert plain.facts_digest == other_graph.facts_digest
    assert plain.semantic_id != other_graph.semantic_id
    other_profile = build_semantic_facts(sources, graph_id="a" * 64, profile_ids=(("src/P.cbl", "c" * 64),))
    assert other_profile.semantic_id != plain.semantic_id and other_profile.facts_digest == plain.facts_digest
    other_checkpoint = build_semantic_facts(sources, graph_id="a" * 64, checkpoint_id="cp-2")
    assert other_checkpoint.semantic_id != plain.semantic_id


def test_editing_a_source_changes_the_digests() -> None:
    first = build_semantic_facts({"src/P.cbl": _clean()})
    edited = build_semantic_facts({"src/P.cbl": _clean().replace("MOVE A TO B", "MOVE B TO A")})
    assert first.facts_digest != edited.facts_digest and first.semantic_id != edited.semantic_id
    assert source_digest_of({"a": "x"}) != source_digest_of({"a": "y"}) != source_digest_of({"b": "y"})


def _tampered(mutate) -> list[str]:
    document = copy.deepcopy(build_semantic_facts({"src/P.cbl": _clean()}).as_dict())
    mutate(document)
    return verify(document)


@pytest.mark.parametrize("name,mutate", [
    ("fact kind", lambda d: d["facts"][0].__setitem__("kind", "data-item" if d["facts"][0]["kind"] != "data-item" else "program")),
    ("reference span", lambda d: d["references"][0]["span"].__setitem__("line", 999)),
    ("declaration name", lambda d: d["declarations"][0].__setitem__("name", "FORGED")),
    ("dropped fact", lambda d: d["facts"].pop()),
    ("header binding", lambda d: d["header"].__setitem__("graph_id", "e" * 64)),
    ("facts digest", lambda d: d["header"].__setitem__("facts_digest", "e" * 64)),
])
def test_tampering_with_any_part_is_detected(name, mutate) -> None:
    assert _tampered(mutate), name


def test_a_forged_but_self_consistent_resolution_is_still_caught() -> None:
    def forge(document) -> None:
        ref = document["references"][0]
        ref["resolution"] = {**ref["resolution"], "candidates": ["sym:program:P/data-item:NOPE#1"]}
        body = {k: document[k] for k in ("declarations", "facts", "references", "scopes")}
        document["header"]["facts_digest"] = graph_digest(body)
        document["header"]["semantic_id"] = graph_digest(
            {"bindings": {k: document["header"][k] for k in ("checkpoint_id", "graph_id", "profile_ids", "source_digest")},
             "body": body})

    problems = _tampered(forge)
    assert any("undeclared id" in p for p in problems)


def graph_digest(payload) -> str:
    from engine.semantic_facts.document import sha256_of

    return sha256_of(payload)


def test_a_refused_file_is_recorded_as_a_refusal_and_the_document_is_incomplete() -> None:
    mixed = "\n".join(_clean().split("\n")[:5]) + "\r\n" + "\r".join(_clean().split("\n")[5:]) + "\n"
    doc = build_semantic_facts({"src/BAD.cbl": mixed})
    refusals = [f for f in doc.facts if f["kind"] == "refusal"]
    assert refusals and all(f["resolution"]["state"] == "unsupported" for f in refusals)
    assert not doc.complete and doc.header["unsupported_summary"].get("UNSUPPORTED_CONSTRUCT", 0) >= 1
    assert verify(doc.as_dict()) == []


def test_duplicate_program_ids_across_files_keep_distinct_scopes_and_ids() -> None:
    doc = build_semantic_facts({"a/P.cbl": _clean(), "b/P.cbl": _clean()})
    scopes = sorted(s["scope_id"] for s in doc.scopes)
    assert scopes == ["program:P@a/P.cbl", "program:P@b/P.cbl"]
    ids = [d["decl_id"] for d in doc.declarations]
    assert len(ids) == len(set(ids)) and verify(doc.as_dict()) == []


def test_unmodelled_compiler_options_make_the_document_incomplete_and_listing_ones_do_not() -> None:
    sources = {"src/P.cbl": _clean()}
    listing = build_semantic_facts(sources, options={"src/P.cbl": ["XREF", "STD(COBOL2002)"]})
    assert listing.complete
    semantic = build_semantic_facts(sources, options={"src/P.cbl": ["XREF", "TRUNC(BIN)"]})
    assert not semantic.complete and semantic.header["unsupported_summary"] == {"COMPILER_OPTION_UNMODELLED": 1}
    assert {f["attributes"]["class"] for f in semantic.facts if f["kind"] == "option"} == {"LISTING", "SEMANTIC"}


def test_nested_programs_and_copybooks_are_named_not_hidden() -> None:
    nested = _clean("OUTER") + (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. INNER.\n       PROCEDURE DIVISION.\n       IN1.\n"
        "           STOP RUN.\n       END PROGRAM INNER.\n       END PROGRAM OUTER.\n")
    doc = build_semantic_facts({"src/N.cbl": nested})
    assert not doc.complete and "NESTED_PROGRAM_NOT_MODELLED" in doc.header["unsupported_summary"]
    copied = _clean().replace("       01 B PIC 9(3).\n", "       COPY CPY1.\n")
    doc = build_semantic_facts({"src/C.cbl": copied})
    assert doc.header["unsupported_summary"].get("COPYBOOK_NOT_EXPANDED") == 1


def test_every_non_resolved_reference_says_why_or_what() -> None:
    doc = build_semantic_facts({p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8", errors="replace") for p in FIXTURES})
    for ref in doc.references:
        res = ref["resolution"]
        assert res["state"] == "resolved" or res["reason"] or res["candidates"]
        assert res["state"] in ("resolved", "ambiguous", "unresolved")


def test_a_fact_outside_the_closed_vocabulary_cannot_be_constructed() -> None:
    with pytest.raises(ValueError):
        Fact("made-up", "x", None, Resolution("resolved", ("x",)), "")


def test_facts_are_sorted_by_position_then_id() -> None:
    doc = build_semantic_facts({"src/P.cbl": _clean()})
    keys = [((f["span"] or {}).get("file", ""), (f["span"] or {}).get("line", 0), (f["span"] or {}).get("column", 0))
            for f in doc.facts]
    assert keys == sorted(keys)

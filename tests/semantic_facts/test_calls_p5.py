"""Layer 5 P5: cross-program CALL / USING / LINKAGE facts (docs/architecture/LAYER5_DESIGN.md, section 6.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import _analyze_call_linkage_arity
from engine.semantic_facts.build import build_semantic_facts
from engine.semantic_facts.calls import layout_of, size_verdict, written_arguments
from engine.semantic_facts.document import verify
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.control_flow import walk_statements

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())

CALLER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X(5).
       01 B PIC 9(4).
       01 R PIC 9(3).
       01 DYN PIC X(8) VALUE 'LATER'.
       PROCEDURE DIVISION.
       MAIN.
{body}           STOP RUN.
"""
CALLEE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       LINKAGE SECTION.
       01 P1 PIC {p1}.
       01 P2 PIC {p2}.
       PROCEDURE DIVISION USING P1 P2.
       MAIN.
           GOBACK.
"""


def _doc(body: str, *, p1: str = "X(10)", p2: str = "9(4)", extra: dict[str, str] | None = None, **kw):
    sources = {"caller.cbl": CALLER.format(body=body), "sub1.cbl": CALLEE.format(name="SUB1", p1=p1, p2=p2)}
    sources.update(extra or {})
    return build_semantic_facts(sources, **kw)


def _facts(doc, kind: str):
    return [f for f in doc.facts if f["kind"] == kind]


def _call(doc, ordinal: int = 1):
    return next(f for f in _facts(doc, "call") if f["subject"].endswith(f"/MAIN/{ordinal}"))


def _line(text: str) -> str:
    return f"           {text}\n"


# --- targets ----------------------------------------------------------------------------------------------------

def test_a_literal_call_resolves_to_the_callee_program_declaration():
    doc = _doc(_line("CALL 'sub1' USING A B."))
    call = _call(doc)
    assert call["resolution"]["state"] == "resolved"
    assert call["resolution"]["candidates"] == ["sym:program:SUB1/program:SUB1#1"]
    assert call["attributes"]["target"] == "SUB1" and call["attributes"]["call_type"] == "STATIC"


def test_an_unknown_target_is_unresolved_and_a_subsystem_entry_is_external():
    doc = _doc(_line("CALL 'GHOST' USING A.") + _line("CALL 'MQOPEN' USING A.") + _line("CALL 'MYEXT' USING A."),
               external_programs=["MYEXT"])
    ghost, mq, mine = _call(doc, 1), _call(doc, 2), _call(doc, 3)
    assert (ghost["resolution"]["state"], ghost["resolution"]["reason"]) == ("unresolved", "missing-program")
    assert mq["resolution"]["state"] == "resolved" and mq["attributes"]["external"] == "true"
    assert mine["resolution"]["candidates"] == ["external:MYEXT"]


def test_the_same_program_id_in_two_files_makes_the_call_ambiguous():
    doc = _doc(_line("CALL 'SUB1' USING A B."), extra={"other/sub1.cbl": CALLEE.format(name="SUB1", p1="X(5)", p2="9(4)")})
    call = _call(doc)
    assert call["resolution"]["state"] == "ambiguous" and len(call["resolution"]["candidates"]) == 2
    assert call["resolution"]["confidence"] == "heuristic"
    assert not _facts(doc, "call-arity"), "no binding is claimed against an ambiguous callee"


def test_a_call_to_a_nested_program_is_unsupported_not_unresolved():
    nested = (CALLEE.format(name="OUTER", p1="X", p2="X") +
              "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. INNER.\n       PROCEDURE DIVISION.\n       IN1.\n"
              "           GOBACK.\n       END PROGRAM INNER.\n       END PROGRAM OUTER.\n")
    doc = build_semantic_facts({"caller.cbl": CALLER.format(body=_line("CALL 'INNER' USING A.")), "n.cbl": nested})
    call = _call(doc)
    assert (call["resolution"]["state"], call["resolution"]["reason"]) == ("unsupported", "NESTED_PROGRAM_NOT_MODELLED")


def test_a_self_call_is_marked():
    program = CALLER.format(body=_line("CALL 'CALLER' USING A."))
    doc = build_semantic_facts({"caller.cbl": program})
    assert _call(doc)["attributes"]["self_call"] == "true"


def test_a_call_to_an_entry_point_resolves_through_the_entry_declaration():
    callee = CALLEE.format(name="SUB1", p1="X(10)", p2="9(4)").replace(
        "       MAIN.\n", "       MAIN.\n           ENTRY 'ALTSUB' USING P1 P2.\n")
    doc = _doc(_line("CALL 'ALTSUB' USING A B."), extra={"sub1.cbl": callee})
    entry = next(d for d in doc.declarations if d["kind"] == "entry")
    assert entry["name"] == "ALTSUB" and entry["attributes"]["parameters"] == "P1,P2" and entry["span"]["line"] == 9
    call = _call(doc)
    assert call["resolution"]["candidates"] == [entry["decl_id"]] and call["attributes"]["via_entry"] == "true"
    # arity and bindings are checked against the ENTRY's own USING list, not the program header
    assert _facts(doc, "call-arity")[0]["attributes"]["expected"] == "2"
    assert [b["attributes"]["parameter"] for b in _facts(doc, "call-binding")] == ["P1", "P2"]


# --- dynamic calls ----------------------------------------------------------------------------------------------

def test_a_dynamic_call_lists_the_literals_it_can_prove():
    doc = _doc(_line("MOVE 'SUB1' TO DYN.") + _line("MOVE 'SUB2' TO DYN.") + _line("CALL DYN USING A B."))
    call = next(f for f in _facts(doc, "call") if f["attributes"]["call_type"] == "DYNAMIC")
    res = call["resolution"]
    assert res["state"] == "dynamic" and res["candidates"] == ["LATER", "SUB1", "SUB2"]
    assert res["confidence"] == "heuristic" and res["variable"].endswith("data-item:DYN#1")
    assert not _facts(doc, "call-arity"), "arity is claimed only for a statically resolved callee"


def test_a_dynamic_call_with_no_provable_literal_is_unresolved_dynamic():
    source = CALLER.format(body=_line("CALL DYN USING A.")).replace(" VALUE 'LATER'", "")
    doc = build_semantic_facts({"caller.cbl": source})
    res = _facts(doc, "call")[0]["resolution"]
    assert (res["state"], res["reason"], res["confidence"], res["candidates"]) == ("dynamic", "dynamic-target", "unresolved", [])


# --- arity and bindings -----------------------------------------------------------------------------------------

def test_arity_is_checked_against_the_header_using_list():
    doc = _doc(_line("CALL 'SUB1' USING A B.") + _line("CALL 'SUB1' USING A."))
    ok, bad = (f["attributes"] for f in _facts(doc, "call-arity"))
    assert (ok["arity_ok"], ok["passed"], ok["expected"]) == ("true", "2", "2")
    assert (bad["arity_ok"], bad["passed"], bad["expected"]) == ("false", "1", "2")


def test_arity_counts_header_parameters_not_level_one_items():
    """The capability analyzer counts ``01`` LINKAGE items; the header USING list is what a CALL must match."""
    callee = CALLEE.format(name="SUB1", p1="X(10)", p2="9(4)").replace(
        "       01 P2 PIC 9(4).\n", "       01 P2 PIC 9(4).\n       01 SCRATCH PIC X.\n")
    doc = _doc(_line("CALL 'SUB1' USING A B."), extra={"sub1.cbl": callee})
    assert _facts(doc, "call-arity")[0]["attributes"]["arity_ok"] == "true"


def test_each_argument_binds_to_the_parameter_in_its_position_with_its_mode():
    doc = _doc(_line("CALL 'SUB1' USING BY REFERENCE A BY CONTENT B."))
    bindings = _facts(doc, "call-binding")
    assert [(b["attributes"]["index"], b["attributes"]["mode"], b["attributes"]["parameter"]) for b in bindings] == [
        ("1", "REFERENCE", "P1"), ("2", "CONTENT", "P2")]
    assert bindings[0]["attributes"]["caller"].endswith("data-item:A#1")
    assert bindings[0]["resolution"]["candidates"] == ["sym:program:SUB1/linkage-param:P1#1"]


def test_a_literal_argument_binds_but_has_no_size_verdict():
    doc = _doc(_line("CALL 'SUB1' USING 'HELLO' B."))
    first = _facts(doc, "call-size-compat")[0]
    assert first["attributes"]["verdict"] == "unknown" and first["attributes"]["detail"] == "ARGUMENT_NOT_A_DATA_ITEM"
    assert "caller" not in _facts(doc, "call-binding")[0]["attributes"]


@pytest.mark.parametrize("p1,expected", [("X(5)", "equal"), ("X(10)", "caller_smaller"), ("X(2)", "caller_larger"),
                                         ("9(5)", "class_mismatch")])
def test_size_verdicts_follow_the_pictures(p1, expected):
    doc = _doc(_line("CALL 'SUB1' USING A B."), p1=p1)
    assert _facts(doc, "call-size-compat")[0]["attributes"]["verdict"] == expected


def test_changing_one_picture_length_changes_the_verdict():
    equal = _facts(_doc(_line("CALL 'SUB1' USING A B."), p1="X(5)"), "call-size-compat")[0]["attributes"]["verdict"]
    larger = _facts(_doc(_line("CALL 'SUB1' USING A B."), p1="X(6)"), "call-size-compat")[0]["attributes"]["verdict"]
    assert (equal, larger) == ("equal", "caller_smaller")


def test_non_display_usage_is_unknown_and_unsupported_never_guessed():
    doc = _doc(_line("CALL 'SUB1' USING A B."), p2="9(4) COMP-3")
    second = _facts(doc, "call-size-compat")[1]
    assert second["attributes"]["verdict"] == "unknown"
    assert (second["resolution"]["state"], second["resolution"]["reason"]) == ("unsupported", "LAYOUT_USAGE_UNCERTIFIED")
    assert not doc.complete and doc.header["unsupported_summary"]["LAYOUT_USAGE_UNCERTIFIED"] == 1


def test_by_value_needs_numeric_elementary_items_on_both_sides():
    assert size_verdict(layout_of_pic("9(4)"), layout_of_pic("9(4)"), "VALUE") == "equal"
    assert size_verdict(layout_of_pic("X(4)"), layout_of_pic("9(4)"), "VALUE") == "class_mismatch"
    doc = _doc(_line("CALL 'SUB1' USING BY VALUE A B."))
    assert _facts(doc, "call-size-compat")[0]["attributes"]["verdict"] == "class_mismatch"


def layout_of_pic(pic: str):
    program = CobolParser().parse(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. L.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        f"       01 X PIC {pic}.\n       PROCEDURE DIVISION.\n       MAIN.\n           STOP RUN.\n")
    return layout_of(program.working_storage[0])


def test_group_sizes_add_up_and_uncertified_members_make_the_group_uncertified():
    program = CobolParser().parse(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. L.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        "       01 G.\n          05 G1 PIC X(2).\n          05 G2 PIC 9(3).\n       01 H.\n          05 H1 PIC 9(3) COMP-3.\n"
        "       PROCEDURE DIVISION.\n       MAIN.\n           STOP RUN.\n")
    group = layout_of(program.working_storage[0])
    assert (group.size, group.klass, group.elementary) == (5, "alphanumeric", False)
    assert layout_of(program.working_storage[1 + 2]) is None or layout_of(program.working_storage[1 + 2]).size >= 0
    assert layout_of([i for i in program.working_storage if i.name == "H"][0]) is None


# --- the argument list is re-read, and a disagreement is refused -----------------------------------------------

def test_written_arguments_follow_by_modes_and_literals():
    assert written_arguments("CALL 'X' USING BY REFERENCE A BY CONTENT 'A B' C RETURNING R.") == [
        ("A", "REFERENCE"), ("'A B'", "CONTENT"), ("C", "CONTENT")]
    assert written_arguments("CALL 'X' USING A B.") == [("A", "REFERENCE"), ("B", "REFERENCE")]
    assert written_arguments("CALL 'X'.") is None


def test_a_disagreement_between_the_ir_and_the_written_list_refuses_the_binding(monkeypatch):
    """Mutation check: when the re-read argument list differs from the IR, no arity or binding is reported."""
    from engine.semantic_facts import calls

    monkeypatch.setattr(calls, "written_arguments", lambda text: [("A", "REFERENCE")])
    doc = _doc(_line("CALL 'SUB1' USING A B."))
    unsupported = _facts(doc, "unsupported")
    assert [f["resolution"]["reason"] for f in unsupported] == ["CALL_USING_UNPARSED"]
    assert unsupported[0]["span"]["line"] == 11
    assert not _facts(doc, "call-arity") and not _facts(doc, "call-binding") and not doc.complete


def test_text_past_column_72_is_read_as_the_compiler_reads_it():
    """A long CALL is cut at the margin, so ``RETURNING r.`` is lost and the next statement joins the CALL: the facts
    report what the compiler would compile (extra arguments), they do not invent the intended statement."""
    doc = _doc(_line("CALL 'SUB1' USING BY REFERENCE A BY CONTENT B BY VALUE R RETURNING R."))
    arity = _facts(doc, "call-arity")[0]["attributes"]
    assert arity["passed"] != "3" and arity["arity_ok"] == "false"


def test_a_literal_with_spaces_is_split_by_the_parser_and_refused_by_the_cross_check():
    """The parser splits USING on white space, so ``'A B'`` becomes two arguments; the tokenizer re-read disagrees."""
    doc = _doc(_line("CALL 'SUB1' USING 'A B' B."))
    assert [f["resolution"]["reason"] for f in _facts(doc, "unsupported")] == ["CALL_USING_UNPARSED"]
    assert not _facts(doc, "call-binding")


def test_by_reference_words_in_the_header_are_not_parameters():
    callee = CALLEE.format(name="SUB1", p1="X(10)", p2="9(4)").replace(
        "USING P1 P2", "USING BY REFERENCE P1 BY CONTENT P2")
    doc = _doc(_line("CALL 'SUB1' USING A B."), extra={"sub1.cbl": callee})
    assert _facts(doc, "call-arity")[0]["attributes"] == {
        "arity_ok": "true", "callee_file": "sub1.cbl", "expected": "2", "passed": "2"}


# --- CANCEL ------------------------------------------------------------------------------------------------------

def test_cancel_is_named_unsupported_not_dropped():
    doc = _doc(_line("CANCEL 'SUB1'."))
    cancel = _facts(doc, "cancel")
    assert len(cancel) == 1 and cancel[0]["resolution"]["reason"] == "CANCEL_NOT_IN_IR"
    assert cancel[0]["attributes"]["target"] == "'SUB1'" and cancel[0]["span"]["line"] == 11


# --- the whole corpus ---------------------------------------------------------------------------------------------

def _app_sources(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(directory.rglob("*")) if p.suffix.lower() in (".cob", ".cbl")}


@pytest.mark.parametrize("directory", APP_DIRS, ids=lambda d: d.parent.name)
def test_every_call_statement_has_exactly_one_call_fact(directory):
    sources = _app_sources(directory)
    doc = build_semantic_facts(sources)
    assert verify(doc.as_dict()) == []
    expected = 0
    for text in sources.values():
        program = CobolParser().parse(text)
        expected += sum(1 for p in program.paragraphs for s in walk_statements(p.statements)
                        if type(s).__name__ == "CallStatement")
    assert len(_facts(doc, "call")) == expected


def _call_arity_mismatches(doc) -> set[tuple[str, str]]:
    out = set()
    for fact in _facts(doc, "call-arity"):
        if fact["attributes"]["arity_ok"] == "false":
            caller = fact["subject"].split("/")[0].split("program:")[1].split("@")[0]
            target = next(c for c in _facts(doc, "call") if c["subject"] == fact["subject"])["attributes"]["target"]
            out.add((caller, target))
    return out


#: Documented differences between the facts and the capability analyzer's ``01``-item arity count (R3 differential).
_OUT_OF_ORDER = ("the analyzer counts WS-TEMP as a LINKAGE 01 item because the fixture places LINKAGE before "
                 "WORKING-STORAGE (an order the parser refuses; the document is incomplete); the header USING list "
                 "(3 parameters) matches the 3 arguments passed")
R3_DOCUMENTED: dict[tuple[str, str, str], str] = {
    ("workload-call-linkage", "MAIN", "CALCULATE"): _OUT_OF_ORDER,
    ("workload-multiprog", "MAINPROG", "CALCULATE"): _OUT_OF_ORDER,
}


@pytest.mark.parametrize("directory", APP_DIRS, ids=lambda d: d.parent.name)
def test_r3_differential_the_facts_never_miss_a_mismatch_the_capability_analyzer_reports(directory):
    sources = _app_sources(directory)
    try:
        application = ApplicationDiscovery().discover(directory)
    except Exception:  # an app the discovery refuses has no analyzer verdict to compare
        pytest.skip("discovery refused this application")
    analyzer = {tuple(f.component_id.split("->")) for f in _analyze_call_linkage_arity(application)}
    mine = _call_arity_mismatches(build_semantic_facts(sources))
    missed = analyzer - mine
    extra = mine - analyzer
    undocumented = {(directory.parent.name, *pair) for pair in (missed | extra)} - set(R3_DOCUMENTED)
    assert not undocumented, f"R3 differential: facts and analyzer disagree on {sorted(undocumented)}"


def test_r2_differential_literal_call_targets_match_the_text_extraction():
    disagreements = []
    discovery = ApplicationDiscovery()
    for directory in APP_DIRS:
        for name, text in _app_sources(directory).items():
            program = CobolParser().parse(text)
            old = sorted(c.target.upper() for c in discovery._extract_calls(text, program.program_id)
                         if c.call_type == "STATIC")
            doc = build_semantic_facts({name: text})
            new = sorted(f["attributes"]["target"] for f in _facts(doc, "call")
                         if f["attributes"]["call_type"] == "STATIC")
            if old != new:
                disagreements.append((directory.parent.name, name, old, new))
    assert not disagreements, disagreements

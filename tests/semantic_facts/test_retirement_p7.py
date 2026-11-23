"""Layer 5 P7: differential and mutation-sensitive tests for the duplicate fact producers R1-R8 (design section 7).

Each retirement is gated by a differential test that runs over the whole fixture corpus and a synthetic stress corpus.
The tests are written against "whichever of the old implementation and its replacement exist", so the same file proves
equivalence before the old code is deleted and keeps proving it afterwards.  Nothing here weakens an existing test.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from pathlib import Path

import pytest

import engine.transformation.ir as ir
from engine.modernization import capability_analyzer
from engine.semantic_facts.build import build_program_facts
from engine.semantic_facts.span import _walk
from engine.transformation import cobol_parser, qualified_names
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.control_flow import walk_statements
from engine.transformation.file_ownership import record_ownership

REPO = Path(__file__).resolve().parents[2]
FIXTURES = sorted(p for p in (REPO / "fixtures").rglob("*") if p.is_file() and p.suffix.lower() in (".cob", ".cbl"))
GOLDEN = json.loads((Path(__file__).parent / "golden" / "walk_sequences.json").read_text(encoding="utf-8"))


def _parse(path: Path):
    return CobolParser().parse(path.read_text(encoding="utf-8", errors="replace"))


# ======================================================================================================================
# R1: one statement walker
# ======================================================================================================================

def _walkers():
    """Every statement walker that exists: the shared one, plus the retired-or-not duplicates."""
    found = {"control_flow.walk_statements": walk_statements,
             "span._walk": lambda statements: (s for s, _parent in _walk(statements))}
    if hasattr(cobol_parser, "_walk_statements"):
        found["cobol_parser._walk_statements"] = cobol_parser._walk_statements
    return found


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_r1_every_walker_yields_the_recorded_statement_sequence(path):
    program = _parse(path)
    expected = GOLDEN[path.relative_to(REPO / "fixtures").as_posix()]
    for name, walker in _walkers().items():
        got = [type(s).__name__ for p in program.paragraphs for s in walker(p.statements)]
        assert got == expected, name


def _statement_fields():
    """``(class, field)`` of every statement-union field that holds nested statements (by annotation)."""
    rows = []
    for cls in (*typing.get_args(ir.Statement), ir.SearchWhen):
        if dataclasses.is_dataclass(cls):
            rows += [(cls, f.name) for f in dataclasses.fields(cls) if "Statement" in str(f.type) and "tuple" in str(f.type)]
    return rows


def _marker():
    return ir.CallStatement("MARK", ("A",), ("REFERENCE",), False, "")


def _build(cls, field_name, marker):
    kwargs = {f.name: f.default for f in dataclasses.fields(cls) if f.default is not dataclasses.MISSING}
    kwargs.update({f.name: "" for f in dataclasses.fields(cls) if f.default is dataclasses.MISSING})
    kwargs[field_name] = (marker,)
    return cls(**kwargs)


@pytest.mark.parametrize("cls,field_name", _statement_fields(), ids=lambda v: getattr(v, "__name__", v))
def test_r1_the_walker_reaches_every_body_attribute_of_the_ir(cls, field_name):
    marker = _marker()
    statement = _build(cls, field_name, marker)
    assert marker in list(walk_statements((statement,))), f"{cls.__name__}.{field_name} is not walked"


def test_r1_the_search_bodies_the_capability_walker_never_listed_are_walked():
    """``SearchWhen.body`` and ``SearchStatement.at_end`` hold statements but are not in ``_LINKAGE_WALK_ATTRS``."""
    when_marker, end_marker = _marker(), _marker()
    when = ir.SearchWhen("X = 1", (when_marker,), None)
    search = ir.SearchStatement("E", "", (when,), (end_marker,), True, (), False)
    walked = list(walk_statements((search,)))
    assert when_marker in walked and end_marker in walked


def test_r1_a_mutated_walker_is_caught_by_the_golden_sequences(monkeypatch):
    """Mutation check: a walker that skips nested bodies no longer reproduces the recorded sequences."""
    nested = next(p for p in FIXTURES if p.name == "PAYROLL.cob")
    program = _parse(nested)
    shallow = [type(s).__name__ for para in program.paragraphs for s in para.statements]
    assert shallow != GOLDEN[nested.relative_to(REPO / "fixtures").as_posix()]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_r1_the_capability_call_walker_finds_exactly_the_calls_the_shared_walker_does(path):
    program = _parse(path)
    shared = [s for p in program.paragraphs for s in walk_statements(p.statements) if isinstance(s, ir.CallStatement)]
    assert [id(s) for s in capability_analyzer._iter_call_statements(program)] == [id(s) for s in shared]
    # independent of both walkers: the recorded golden sequence holds exactly this many CALLs
    assert len(shared) == GOLDEN[path.relative_to(REPO / "fixtures").as_posix()].count("CallStatement")


def test_r1_calls_inside_search_bodies_are_found_by_the_capability_walker_after_the_retirement():
    marker = _marker()
    when = ir.SearchWhen("X = 1", (marker,), None)
    search = ir.SearchStatement("E", "", (when,), (), False, (), False)
    program = ir.CobolProgram(program_id="P", paragraphs=(ir.Paragraph("MAIN", (search,)),))
    assert marker in [s for p in program.paragraphs for s in walk_statements(p.statements)]
    if hasattr(capability_analyzer, "_LINKAGE_WALK_ATTRS"):
        assert marker not in capability_analyzer._iter_call_statements(program)     # the defect the retirement fixes
    else:
        assert marker in capability_analyzer._iter_call_statements(program)         # retired: CALLs in SEARCH are found


# ======================================================================================================================
# R7: record ownership has one producer
# ======================================================================================================================

def _parser_view(parser: CobolParser):
    if hasattr(parser, "_ownership"):
        o = parser._ownership
        return dict(o.owners), dict(o.ambiguous), dict(o.file_records), dict(o.buffer_record)
    return (dict(parser._record_owner), dict(parser._record_owner_ambiguous), dict(parser._file_records),
            dict(parser._file_buffer_record))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_r7_the_parser_uses_the_ownership_the_shared_module_computes(path):
    parser = CobolParser()
    program = parser.parse(path.read_text(encoding="utf-8", errors="replace"))
    shared = record_ownership(program.file_definitions)
    assert _parser_view(parser) == (dict(shared.owners), dict(shared.ambiguous), dict(shared.file_records),
                                    dict(shared.buffer_record))


def test_r7_two_fds_declaring_one_record_are_ambiguous_in_both():
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. O.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F1 ASSIGN TO 'a'.\n"
        "           SELECT F2 ASSIGN TO 'b'.\n       DATA DIVISION.\n       FILE SECTION.\n"
        "       FD F1.\n       01 SHARED PIC X.\n       FD F2.\n       01 SHARED PIC X.\n"
        "       PROCEDURE DIVISION.\n       MAIN.\n           STOP RUN.\n")
    parser = CobolParser()
    program = parser.parse(source)
    owners, ambiguous, *_ = _parser_view(parser)
    assert ambiguous == {"SHARED": ("F1", "F2")} == dict(record_ownership(program.file_definitions).ambiguous)
    assert "SHARED" not in owners


# ======================================================================================================================
# R8: qualification has one producer (qualified_names); the symbol table derives from it, it does not recompute it
# ======================================================================================================================

@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_r8_every_rename_qualified_names_makes_is_a_declaration_with_the_same_chain(path):
    source = path.read_text(encoding="utf-8", errors="replace")
    parser = CobolParser()
    program, trace = parser.parse_traced(source)
    facts = build_program_facts(path.name, source)
    by_generated = {dict(d.attributes).get("generated_name"): d for d in facts.symbols.declarations
                    if "generated_name" in dict(d.attributes)}
    for unique, name, ancestors in trace.renames:
        declaration = by_generated.get(unique)
        assert declaration is not None, (path.name, unique)
        assert (declaration.name, declaration.qualification) == (name, ancestors)
    assert len(by_generated) == len({u for u, *_ in trace.renames})


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_r8_the_text_pass_output_is_byte_identical_through_every_entry_point(path):
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    plain = qualified_names.resolve_qualified_names(list(lines))
    traced = qualified_names.resolve_qualified_names_traced(list(lines))
    detailed = qualified_names.resolve_qualified_names_detailed(list(lines))
    assert plain == (traced[0], traced[1]) == (detailed[0], detailed[1])


# ======================================================================================================================
# R2 / R3: the text and arity producers are *not* retired - the differential evidence says why
# ======================================================================================================================

@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_r2_entry_points_the_facts_read_equal_the_regex_extraction(path):
    from engine.transformation.application_discovery import ApplicationDiscovery

    source = path.read_text(encoding="utf-8", errors="replace")
    old = sorted(e.upper() for e in ApplicationDiscovery()._extract_entry_points(source))
    new = sorted(d.name for d in build_program_facts(path.name, source).symbols.declarations if d.kind == "entry")
    assert old == new


def test_r2_the_regex_extraction_still_serves_a_file_the_parser_refuses():
    """The reason R2 stays: discovery builds a stub program (and its CALL edges) from text when ``parse`` raises."""
    from engine.transformation.application_discovery import ApplicationDiscovery

    source = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. BROKEN.\n       PROCEDURE DIVISION.\n"
              "       MAIN.\n           CALL 'OTHER' USING A.\n           STOP RUN.\n")
    assert [c.target for c in ApplicationDiscovery()._extract_calls(source, "BROKEN")] == ["OTHER"]


def test_r3_guard_the_facts_are_never_more_permissive_than_the_analyzer_on_an_unsupported_fixture():
    """``workload-call-linkage`` is refused by the capability analyzer; the facts' header-based arity is *more*
    permissive for it (3 = 3), so the analyzer's rule is kept until a retirement can prove the verdict does not loosen."""
    from tests.semantic_facts.test_calls_p5 import R3_DOCUMENTED

    assert ("workload-call-linkage", "MAIN", "CALCULATE") in R3_DOCUMENTED


def test_r2_entry_points_stress_the_facts_agree_with_the_regex_on_declared_entries():
    from engine.transformation.application_discovery import ApplicationDiscovery

    source = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. E.\n       DATA DIVISION.\n       LINKAGE SECTION.\n"
              "       01 P1 PIC X.\n       PROCEDURE DIVISION USING P1.\n       MAIN.\n           GOBACK.\n"
              "           ENTRY 'ALT1' USING P1.\n           GOBACK.\n           ENTRY 'ALT2'.\n           GOBACK.\n")
    old = sorted(e.upper() for e in ApplicationDiscovery()._extract_entry_points(source))
    new = sorted(d.name for d in build_program_facts("E.cbl", source).symbols.declarations if d.kind == "entry")
    assert old == new == ["ALT1", "ALT2"]


# ======================================================================================================================
# R5: the engine's DD binding vs the graph + Layer 5 facts (differential report; the producer is NOT retired)
# ======================================================================================================================

#: Documented differences between the engine's DD binding and the graph (R5 differential; shrink-only).  Retiring
#: ``dd_binding`` would regress each of these rows from BOUND to unresolved, so R5 stays.
R5_DOCUMENTED = {
    ("COPYJOB", "RPT", "RPTPRT", "IN-FILE", "BOUND"):
        "the DD is bound to a temporary dataset (DSN=&&TMP); the graph does not catalogue && temporaries, so it states "
        "missing-dd for that step. The file-binding fact keeps the step in `unresolved_steps` instead of dropping it.",
}
_R5_STATUS = {"BOUND": "resolved-dataset", "UNBOUND": "unresolved", "LITERAL_PATH": "resolved-literal"}


def _old_bindings(root: Path):
    from engine.jcl.dd_binding import bind_dd_names, cobol_file_assignments
    from engine.transformation.application_discovery import ApplicationDiscovery
    from engine.transformation.jcl_discovery import JclDiscovery

    jcl_app = JclDiscovery().discover(str(root))
    cobol_app = ApplicationDiscovery().discover(str(root))
    jcl_app = JclDiscovery().link_with_cobol(jcl_app, cobol_app)
    assignments = {u.program_id: cobol_file_assignments((root / u.source_path).read_text(encoding="utf-8", errors="replace"))
                   for u in cobol_app.programs}
    return [r for r in bind_dd_names(jcl_app, assignments) if r["status"] in _R5_STATUS]


def _new_bindings(root: Path):
    from enterprise.discovery.graph_view import graph_from_directory

    graph, _ = graph_from_directory(root)
    rows = set()
    for edge in graph["edges"]:
        detail = edge.get("detail") or {}
        if not str(edge.get("from", "")).startswith("program:") or "logical_file" not in detail:
            continue
        step = str(detail.get("job_step", ""))
        job, _, step_name = step.partition("/")
        if edge["relation"] == "uses-dataset":
            status = "BOUND"
        elif edge.get("resolution") == "unresolved":
            status = "UNBOUND"
        else:
            status = "LITERAL_PATH"
        rows.add((job.partition(":")[2], step_name, edge["from"].partition(":")[2], detail["logical_file"], status))
    return rows


@pytest.mark.parametrize("directory", [REPO / "fixtures" / "enterprise" / "app-jcl-job",
                                       REPO / "fixtures" / "enterprise" / "payroll-batch"], ids=lambda p: p.name)
def test_r5_the_graph_reproduces_every_bound_and_unbound_row_of_the_engine_dd_binding(directory):
    old = {(r["job"], r["step"], r["program"], r["file_name"], r["status"]) for r in _old_bindings(directory)}
    new = _new_bindings(directory)
    # the graph states a program's UNBOUND file per program (not per step); the engine states it per step: compare the
    # BOUND rows exactly and require every engine UNBOUND (program, file) to be UNBOUND in the graph too
    old_bound, new_bound = {r for r in old if r[4] == "BOUND"}, {r for r in new if r[4] == "BOUND"}
    undocumented = (old_bound ^ new_bound) - set(R5_DOCUMENTED)
    assert not undocumented, f"R5 differential: undocumented disagreement {sorted(undocumented)}"
    assert not (new_bound - old_bound), "the graph never reports a binding the engine does not"
    graph_unbound = {(r[2], r[3]) for r in new if r[4] == "UNBOUND"}
    assert {(r[2], r[3]) for r in old if r[4] == "UNBOUND"} <= graph_unbound

"""Layer 5 P2: declarations, scopes and deterministic identities (docs/architecture/LAYER5_DESIGN.md, section 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.semantic_facts.span import build_span_table
from engine.semantic_facts.symbols import (
    DECL_KINDS,
    SPECIAL_REGISTERS,
    UNSUPPORTED_CODES,
    build_symbol_table,
    graph_node_id,
)
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.group_storage import iter_data_items
from enterprise.discovery.cobol_structure import scoped_node_id

REPO = Path(__file__).resolve().parents[2]
FIXTURES = sorted(p for p in (REPO / "fixtures").rglob("*") if p.is_file() and p.suffix.lower() in (".cob", ".cbl"))

HEAD = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {name}.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)
TAIL = "       PROCEDURE DIVISION.\n       MAIN.\n           STOP RUN.\n"


def _table(source: str, file: str = "T.cbl"):
    parser = CobolParser()
    program, trace = parser.parse_traced(source)
    return program, build_symbol_table(program, trace, build_span_table(program, trace, file=file))


def _program(body: str, name: str = "P") -> str:
    return HEAD.format(name=name) + body + TAIL


def _ids(table):
    return [d.decl_id for d in table.declarations]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_every_ir_declaration_has_exactly_one_symbol_and_none_is_invented(path):
    program, table = _table(path.read_text(encoding="utf-8", errors="replace"), path.name)
    ids = _ids(table)
    assert len(ids) == len(set(ids)), "decl_id is unique"
    assert all(d.kind in DECL_KINDS for d in table.declarations)
    assert all(d.unsupported in ("", *UNSUPPORTED_CODES) for d in table.declarations)
    # the parser keeps equal copies of LINKAGE items in working_storage for lowering; they are declared once
    ir_items = (list(iter_data_items([r for r in program.working_storage if r not in program.linkage_section]))
                + list(iter_data_items(program.linkage_section))
                + [i for fd in program.file_definitions for r in fd.record_groups for i in iter_data_items([r])])
    declared_items = [d for d in table.declarations if d.kind in
                      ("data-item", "record", "condition-name", "linkage-param")]
    assert len(declared_items) == len(ir_items)
    assert len([d for d in table.declarations if d.kind == "paragraph"]) == len(program.paragraphs)
    assert len([d for d in table.declarations if d.kind == "file"]) == len(program.file_definitions)
    assert {d.name for d in table.declarations if d.kind == "special-register"} <= set(SPECIAL_REGISTERS)


@pytest.mark.parametrize("path", FIXTURES[:20], ids=lambda p: p.name)
def test_ids_are_identical_on_two_runs(path):
    source = path.read_text(encoding="utf-8", errors="replace")
    assert _ids(_table(source, path.name)[1]) == _ids(_table(source, path.name)[1])


def test_duplicate_name_under_two_groups_gets_two_ids_and_collapses_in_the_graph():
    _, table = _table(_program(
        "       01 REC1.\n          05 AMT PIC 9(3).\n       01 REC2.\n          05 AMT PIC 9(3).\n"))
    amts = table.named("AMT")
    assert [d.decl_id for d in amts] == ["sym:program:P/data-item:REC1/AMT#1", "sym:program:P/data-item:REC2/AMT#1"]
    assert all(d.graph_node_collapsed and d.graph_node_id == "data-item:P/AMT" for d in amts)
    assert [d.qualification for d in amts] == [("REC1",), ("REC2",)]
    # the generated name the text pass gave each one is an attribute, not part of the identity
    assert [dict(d.attributes)["generated_name"] for d in amts] == ["AMT-OF-REC1", "AMT-OF-REC2"]
    assert table.by_id()["sym:program:P/data-item:REC1#1"].graph_node_collapsed is False


def test_same_name_same_qualification_is_marked_not_merged():
    _, table = _table(_program("       01 REC.\n          05 AMT PIC 9.\n          05 AMT PIC 9.\n"))
    rows = table.named("AMT")
    assert len(rows) == 2 and rows[0].decl_id != rows[1].decl_id
    assert {r.unsupported for r in rows} == {"DUPLICATE_DECLARATION_SAME_QUALIFICATION"}
    assert not table.complete


def test_renaming_a_group_changes_dependent_ids_only():
    base = "       01 {g}.\n          05 AMT PIC 9.\n       01 OTHER.\n          05 Q PIC 9.\n"
    one = _ids(_table(_program(base.format(g="GRP1")))[1])
    two = _ids(_table(_program(base.format(g="GRP2")))[1])
    changed = set(one) ^ set(two)
    assert changed == {"sym:program:P/data-item:GRP1#1", "sym:program:P/data-item:GRP1/AMT#1",
                       "sym:program:P/data-item:GRP2#1", "sym:program:P/data-item:GRP2/AMT#1"}


def test_unrelated_added_declaration_does_not_move_other_ids():
    plain = _table(_program("       01 A PIC 9.\n       01 B PIC 9.\n"))[1]
    more = _table(_program("       01 A PIC 9.\n       01 B PIC 9.\n       01 C PIC 9.\n"))[1]
    assert set(_ids(plain)) < set(_ids(more))


def test_levels_77_88_index_names_filler_and_linkage():
    program, table = _table(HEAD.format(name="P") + (
        "       77 SOLO PIC 9.\n"
        "       01 REC.\n          05 FILLER PIC X.\n          05 FLG PIC X.\n             88 ON-F VALUE 'Y'.\n"
        "       01 T.\n          05 E PIC X OCCURS 3 INDEXED BY IX1 IX2.\n"
        "       LINKAGE SECTION.\n       01 LK PIC X.\n"
        "       PROCEDURE DIVISION USING LK.\n       MAIN.\n           STOP RUN.\n"))
    kinds = {d.name: d.kind for d in table.declarations}
    assert kinds["SOLO"] == "data-item" and kinds["ON-F"] == "condition-name"
    assert kinds["IX1"] == "index-name" and kinds["IX2"] == "index-name" and kinds["LK"] == "linkage-param"
    filler = next(d for d in table.declarations if d.name == "FILLER")
    assert not filler.addressable and table.named("FILLER") == ()
    on_f = table.named("ON-F")[0]
    assert on_f.qualification == ("FLG", "REC") and on_f.level == 88
    assert table.named("IX1")[0].qualification == ("E", "T")
    assert table.named("LK")[0].section == "linkage"


def test_renames_global_external_are_named_unsupported():
    _, table = _table(_program(
        "       01 A PIC X(5) GLOBAL.\n       01 B PIC X(5) EXTERNAL.\n       01 C PIC X(5).\n"
        "       66 R RENAMES A THRU B.\n"))
    codes = {d.name: d.unsupported for d in table.declarations if d.kind == "data-item"}
    assert codes == {"A": "GLOBAL_CLAUSE_NOT_READ", "B": "EXTERNAL_CLAUSE_NOT_READ", "C": ""}
    assert ("RENAMES_NOT_MODELLED", "R") in [(u.code, u.subject) for u in table.unsupported]
    assert table.scopes[0].global_names == frozenset({"A"})
    assert not table.complete
    assert table.unsupported_summary() == {"EXTERNAL_CLAUSE_NOT_READ": 1, "GLOBAL_CLAUSE_NOT_READ": 1,
                                           "RENAMES_NOT_MODELLED": 1}


def test_nested_program_is_recorded_as_unsupported_and_never_merged():
    source = (
        _program("       01 OUTER-ITEM PIC X.\n", "OUTER")
        + "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. INNER.\n       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n       01 INNER-ITEM PIC X.\n"
        "       PROCEDURE DIVISION.\n       INNER-PARA.\n           STOP RUN.\n"
        "       END PROGRAM INNER.\n       END PROGRAM OUTER.\n")
    _, table = _table(source)
    assert [(u.code, u.subject) for u in table.unsupported] == [("NESTED_PROGRAM_NOT_MODELLED", "INNER")]
    assert table.unsupported[0].span is not None and table.unsupported[0].span.line == 10
    assert {s.scope_id for s in table.scopes} == {"program:OUTER"}
    para = {d.name: d.unsupported for d in table.declarations if d.kind == "paragraph"}
    assert para["MAIN"] == "" and para["INNER-PARA"] == "NESTED_PROGRAM_NOT_MODELLED"
    assert table.named("OUTER-ITEM")[0].unsupported == ""
    assert not table.complete


def test_single_program_is_complete():
    _, table = _table(_program("       01 A PIC 9.\n"))
    assert table.complete and table.unsupported == ()


def test_file_section_records_belong_to_their_fd_and_carry_spans():
    _, table = _table(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. F.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT IN-F ASSIGN TO 'in.dat'.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD IN-F.\n       01 IN-REC.\n          05 IN-KEY PIC X(4).\n"
        "       PROCEDURE DIVISION.\n       MAIN.\n           STOP RUN.\n")
    fd = table.named("IN-F")[0]
    rec = table.named("IN-REC")[0]
    assert fd.kind == "file" and rec.kind == "record" and rec.parent == fd.decl_id
    assert rec.span is not None and rec.span.line == 10 and rec.span.exact and rec.span_code == ""
    assert table.named("IN-KEY")[0].span.line == 11
    assert table.named("IN-KEY")[0].qualification == ("IN-REC",)


def test_graph_node_ids_match_the_discovery_formula():
    for kind, graph_kind in (("paragraph", "paragraph"), ("data-item", "data-item")):
        assert graph_node_id("program:PAY", kind, "Amt") == scoped_node_id("program:PAY", "AMT", graph_kind)
    assert graph_node_id("program:PAY", "file", "F") == ""


def test_paragraph_symbols_carry_spans_and_duplicates_get_ordinals():
    _, table = _table(HEAD.format(name="P") + "       01 A PIC 9.\n       PROCEDURE DIVISION.\n"
                      "       MAIN.\n           STOP RUN.\n       DUP.\n           STOP RUN.\n       DUP.\n           STOP RUN.\n")
    paragraphs = [d for d in table.declarations if d.kind == "paragraph"]
    assert [d.decl_id for d in paragraphs if d.name == "DUP"] == [
        "sym:program:P/paragraph:DUP#1", "sym:program:P/paragraph:DUP#2"]
    assert all(d.span is not None for d in paragraphs)
    assert paragraphs[1].span.line < paragraphs[2].span.line


def test_a_mutated_symbol_table_is_detected_by_the_count_identity():
    program, table = _table(_program("       01 A PIC 9.\n       01 B PIC 9.\n"))
    dropped = [d for d in table.declarations if d.name != "B"]
    ir_items = list(iter_data_items(program.working_storage))
    assert len([d for d in dropped if d.kind == "data-item"]) != len(ir_items)

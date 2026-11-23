"""Layer 5 P3: typed references, access classification and resolution (docs/architecture/LAYER5_DESIGN.md, section 4)."""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

import engine.transformation.ir as ir
from engine.semantic_facts import references as refs
from engine.semantic_facts.references import (
    ACCESS,
    CONFIDENCE,
    REASONS,
    STATEMENT_RULES,
    Resolution,
    build_reference_table,
    parse_operand,
    split_operands,
)
from engine.semantic_facts.span import build_span_table
from engine.semantic_facts.symbols import build_symbol_table
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.control_flow import walk_statements
from enterprise.discovery import graph

REPO = Path(__file__).resolve().parents[2]
FIXTURES = sorted(p for p in (REPO / "fixtures").rglob("*") if p.is_file() and p.suffix.lower() in (".cob", ".cbl"))

HEAD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
    "       01 A PIC 9(3).\n       01 B PIC 9(3).\n       01 C PIC 9(3).\n       01 R PIC 9(3).\n"
    "       01 S PIC X(5).\n       01 T.\n          05 E PIC 9 OCCURS 3 INDEXED BY IX.\n"
    "       01 FLG PIC X.\n          88 ON-F VALUE 'Y'.\n       PROCEDURE DIVISION.\n       MAIN.\n"
)


def _table(source: str, file: str = "T.cbl"):
    parser = CobolParser()
    program, trace = parser.parse_traced(source)
    spans = build_span_table(program, trace, file=file)
    symbols = build_symbol_table(program, trace, spans)
    return program, build_reference_table(program, trace, spans, symbols, source=source), symbols


def _body(*statements: str) -> str:
    return HEAD + "".join(f"           {s}\n" for s in statements) + "           STOP RUN.\n"


def _uses(*statements: str) -> list[tuple[str, str, str]]:
    _, table, _ = _table(_body(*statements))
    return [(r.name, r.access, r.role) for r in table.references]


# --- the classification table is exhaustive ----------------------------------------------------------------------

def test_every_statement_class_of_the_ir_union_has_a_classification_row():
    union = {cls.__name__ for cls in typing.get_args(ir.Statement)}
    assert union <= set(STATEMENT_RULES), union - set(STATEMENT_RULES)
    assert {"SearchWhen", "InspectPhrase"} <= set(STATEMENT_RULES)


def test_a_class_without_a_row_would_be_caught(monkeypatch):
    monkeypatch.delitem(STATEMENT_RULES, "AddStatement")
    assert not {c.__name__ for c in typing.get_args(ir.Statement)} <= set(STATEMENT_RULES)


def test_vocabularies_agree_with_the_graph():
    assert set(REASONS) <= set(graph.UNRESOLVED_REASONS)
    assert set(CONFIDENCE) == set(graph.CONFIDENCE_VALUES)
    assert {"read", "write", "modify"} <= set(ACCESS)


# --- access direction per class ----------------------------------------------------------------------------------

@pytest.mark.parametrize("statement,expected", [
    ("MOVE A TO B.", [("A", "read", "source"), ("B", "write", "target")]),
    ("MOVE A TO B C.", [("A", "read", "source"), ("B", "write", "target"), ("C", "write", "target")]),
    ("ADD A TO B.", [("A", "read", "source"), ("B", "modify", "target")]),
    ("ADD A B TO C.", [("A", "read", "source"), ("B", "read", "source"), ("C", "modify", "target")]),
    ("SUBTRACT A FROM B.", [("A", "read", "source"), ("B", "modify", "target")]),
    ("MULTIPLY A BY B.", [("A", "read", "source"), ("B", "modify", "target")]),
    ("DIVIDE A INTO B.", [("B", "read", "dividend"), ("A", "read", "divisor"), ("B", "modify", "target")]),
    ("DIVIDE A BY B GIVING C REMAINDER R.", [("A", "read", "dividend"), ("B", "read", "divisor"),
                                              ("C", "write", "target"), ("R", "write", "remainder")]),
    ("COMPUTE A = B + C * 2.", [("A", "write", "target"), ("B", "read", "expression"), ("C", "read", "expression")]),
    ("DISPLAY A ' ' B.", [("A", "read", "part"), ("B", "read", "part")]),
    ("ACCEPT S FROM DATE.", [("S", "write", "target")]),
    ("INITIALIZE S.", [("S", "write", "target")]),
    ("SET IX UP BY 1.", [("IX", "modify", "target")]),
    ("INSPECT S TALLYING A FOR ALL 'X'.", [("S", "read", "target"), ("A", "modify", "counter")]),
    ("INSPECT S REPLACING ALL 'X' BY 'Y'.", [("S", "modify", "target")]),
    ("SET ON-F TO TRUE.", [("ON-F", "write", "condition")]),
])
def test_access_direction(statement, expected):
    assert _uses(statement) == expected


def test_if_reads_every_name_in_the_condition_and_its_nested_statements_are_found():
    uses = _uses("IF ON-F AND A > B", "   MOVE C TO R", "END-IF.")
    assert [(n, a) for n, a, _ in uses] == [("ON-F", "read"), ("A", "read"), ("B", "read"), ("C", "read"), ("R", "write")]


def test_a_statement_nested_below_a_leading_if_is_reached():
    program, table, _ = _table(_body("IF A > 1", "   PERFORM MAIN-X", "   MOVE B TO C", "END-IF."))
    nested = {(r.name, r.access, r.owner_stmt.rsplit("/", 1)[1]) for r in table.references}
    assert ("B", "read", "1.2") in nested and ("C", "write", "1.2") in nested and ("MAIN-X", "perform", "1.1") in nested
    assert ("A", "read", "1") in nested


def test_not_inside_a_condition_is_a_keyword_not_a_data_name():
    _, table, _ = _table(_body("IF A NOT = B DISPLAY 'x' END-IF."))
    assert [(r.name, r.resolution.state) for r in table.references] == [("A", "resolved"), ("B", "resolved")]


def test_perform_varying_modifies_the_index_and_reads_its_bounds_and_condition():
    _, table, _ = _table(_body("PERFORM VARYING A FROM B BY C UNTIL A > 5", "   MOVE 1 TO R", "END-PERFORM."))
    head = [(r.name, r.access, r.role) for r in table.references if r.owner_stmt.endswith("/1")]
    assert head == [("A", "modify", "varying"), ("B", "read", "from"), ("C", "read", "by"), ("A", "read", "until")]
    assert table.unsupported == ()


def test_perform_until_and_paragraph_references():
    _, table, _ = _table(_body("PERFORM SUB1 UNTIL A > 3.") + "       SUB1.\n           ADD 1 TO A.\n")
    by = {(r.kind, r.name): r for r in table.references if r.owner_stmt.endswith("/MAIN/1")}
    assert by[("paragraph", "SUB1")].access == "perform" and by[("paragraph", "SUB1")].resolution.state == "resolved"
    assert by[("data", "A")].access == "read" and by[("data", "A")].role == "until"


def test_a_missing_paragraph_is_unresolved_with_the_graph_reason():
    _, table, _ = _table(_body("PERFORM NOWHERE."))
    ref = next(r for r in table.references if r.kind == "paragraph")
    assert ref.resolution.state == "unresolved" and ref.resolution.reason == "missing-paragraph"
    assert ref.resolution.confidence == "unresolved"


def test_call_arguments_follow_their_passing_mode_and_returning_is_written():
    uses = _uses("CALL 'SUBPROG' USING BY REFERENCE A BY CONTENT B RETURNING R.", "CALL 'S2' USING BY VALUE C.")
    assert [(n, a) for n, a, _ in uses] == [("A", "modify"), ("B", "read"), ("R", "write"), ("C", "read")]


def test_file_statements_reference_the_file_and_its_record():
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. F.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT IN-F ASSIGN TO 'in.dat'.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD IN-F.\n       01 IN-REC PIC X(4).\n"
        "       WORKING-STORAGE SECTION.\n       01 W PIC X(4).\n       PROCEDURE DIVISION.\n       MAIN.\n"
        "           OPEN INPUT IN-F.\n           READ IN-F INTO W.\n           CLOSE IN-F.\n           STOP RUN.\n")
    _, table, _ = _table(source)
    got = [(r.kind, r.name, r.access) for r in table.references]
    assert ("file", "IN-F", "open") in got and ("file", "IN-F", "read") in got and ("file", "IN-F", "close") in got
    assert ("data", "W", "write") in got
    assert all(r.resolution.state == "resolved" for r in table.references if r.kind == "file")


def test_subscripts_and_reference_modification():
    _, table, _ = _table(_body("MOVE E(IX) TO A.", "MOVE S(1:A) TO S."))
    first = next(r for r in table.references if r.name == "E")
    assert first.subscripts and not first.refmod
    sub = next(r for r in table.references if r.ref_id == first.subscripts[0])
    assert (sub.name, sub.kind, sub.access, sub.role) == ("IX", "index", "read", "subscript")
    refmod = next(r for r in table.references if r.name == "S" and r.refmod)
    assert [next(x for x in table.references if x.ref_id == i).name for i in refmod.subscripts] == ["A"]


# --- resolution --------------------------------------------------------------------------------------------------

DUPLICATES = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. D.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
    "       01 REC1.\n          05 AMT PIC 9(3).\n       01 REC2.\n          05 AMT PIC 9(3).\n"
    "       01 N PIC 9(3).\n       PROCEDURE DIVISION.\n       MAIN.\n"
)


def test_qualified_use_resolves_to_the_one_declaration_and_unqualified_use_is_ambiguous():
    _, table, symbols = _table(DUPLICATES + "           MOVE 1 TO AMT OF REC1.\n           MOVE AMT TO N.\n"
                               "           STOP RUN.\n")
    qualified = next(r for r in table.references if r.owner_stmt.endswith("/1"))
    assert qualified.resolution.state == "resolved" and qualified.resolution.confidence == "derived"
    assert qualified.resolution.candidates == ("sym:program:D/data-item:REC1/AMT#1",)
    ambiguous = next(r for r in table.references if r.owner_stmt.endswith("/2") and r.name == "AMT")
    assert ambiguous.resolution.state == "ambiguous"
    assert ambiguous.resolution.candidates == ("sym:program:D/data-item:REC1/AMT#1", "sym:program:D/data-item:REC2/AMT#1")
    assert ambiguous.resolution.confidence == "heuristic"


def test_a_qualifier_that_names_no_ancestor_is_unresolved():
    _, table, _ = _table(DUPLICATES + "           MOVE 1 TO AMT OF NOWHERE.\n           STOP RUN.\n")
    refs_ = [r for r in table.references if r.name == "AMT"]
    assert all(r.resolution.state in ("unresolved", "ambiguous") for r in refs_)


def test_special_registers_resolve_and_unknown_names_do_not():
    _, table, _ = _table(_body("MOVE TALLY TO A.", "MOVE GHOST TO A."))
    by = {r.name: r for r in table.references if r.access == "read"}
    assert by["TALLY"].resolution.state == "resolved" and by["TALLY"].resolution.rule == "l5.special-register"
    assert by["GHOST"].resolution.state == "unresolved" and by["GHOST"].resolution.reason == "missing-data-item"


def test_a_condition_name_is_a_condition_reference_not_a_data_reference():
    _, table, _ = _table(_body("IF ON-F DISPLAY 'Y' END-IF."))
    assert [(r.kind, r.name) for r in table.references] == [("condition", "ON-F")]


@pytest.mark.parametrize("args", [
    dict(state="resolved", candidates=()), dict(state="ambiguous", candidates=("x",)),
    dict(state="unresolved", reason="made-up", confidence="unresolved"), dict(state="unresolved"),
    dict(state="resolved", candidates=("x",), rule="l5.nope"),
])
def test_a_malformed_resolution_cannot_be_constructed(args):
    with pytest.raises(ValueError):
        Resolution(**args)


# --- operands ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,kind", [
    ("'ABC'", "literal"), ("12.5", "literal"), ("-3", "literal"), ("ZERO", "figurative"), ("ALL '*'", "figurative"),
    ("WS-A", "name"), ("TBL(I J)", "name"), ("FUNCTION LENGTH(WS-A)", "intrinsic"), ("(((", "unparsed"),
])
def test_operand_kinds(raw, kind):
    assert parse_operand(raw).kind == kind


def test_a_literal_with_spaces_stays_one_operand():
    assert split_operands("'A B' C D(1 2)") == ["'A B'", "C", "D(1 2)"]


def test_qualified_operand_text_keeps_its_qualifiers_nearest_first():
    operand = parse_operand("AMT OF GRP2 OF REC")
    assert (operand.name, operand.qualifiers) == ("AMT", ("GRP2", "REC"))


# --- identity, determinism, walker ------------------------------------------------------------------------------

def test_ids_are_deterministic_and_paths_do_not_collide():
    source = _body("IF A > 1", "   MOVE B TO C", "ELSE", "   MOVE C TO B", "END-IF.")
    first = [r.ref_id for r in _table(source)[1].references]
    assert first == [r.ref_id for r in _table(source)[1].references] and len(first) == len(set(first))
    rows = _table(source)[1].statements
    assert len({row.stmt_id for row in rows}) == len(rows)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_every_fixture_is_walked_like_control_flow_and_every_reference_is_resolved_and_located(path):
    source = path.read_text(encoding="utf-8", errors="replace")
    program, table, symbols = _table(source, path.name)
    walked = [s for p in program.paragraphs for s in walk_statements(p.statements)]
    assert len(table.statements) == len(walked), "one walker: same statements as control_flow.walk_statements"
    assert len({r.ref_id for r in table.references}) == len(table.references)
    lines = source.replace("\r\n", "\n").split("\n")
    for ref in table.references:
        assert isinstance(ref.resolution, Resolution) and ref.kind in refs.REF_KINDS and ref.access in ACCESS
        if ref.span is not None and ref.span.exact:
            text = lines[ref.span.line - 1]
            token = text[ref.span.column - 1: ref.span.end_column - 1]
            assert token.upper() == (ref.name if ref.name in token.upper() else token.upper()) or token.upper() in ref.name
            assert re.fullmatch(r"[A-Za-z0-9][\w-]*", token), (path.name, ref.span, token)
    assert all(code in refs.UNSUPPORTED_USE_CODES for code in (u.code for u in table.unsupported))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_no_declared_name_used_by_a_statement_is_dropped(path):
    """Independent of the classification table: every declared data name an IR statement mentions (outside nested
    bodies and outside quoted text) must appear among that statement's references, or the statement is named
    unsupported."""
    source = path.read_text(encoding="utf-8", errors="replace")
    program, table, symbols = _table(source, path.name)
    declared = {dict(d.attributes).get("generated_name", d.name) for d in symbols.declarations
                if d.addressable and d.kind in ("data-item", "linkage-param", "condition-name", "index-name", "record")}
    by_stmt: dict[str, set[str]] = {}
    for r in table.references:
        by_stmt.setdefault(r.owner_stmt, set()).add(r.name)
    flagged = {u.owner_stmt for u in table.unsupported}
    stmt_ids = {id(s): row.stmt_id for row, s in zip(
        table.statements, (x for p in program.paragraphs for x in walk_statements(p.statements)))}
    for paragraph in program.paragraphs:
        for statement in walk_statements(paragraph.statements):
            stmt_id = stmt_ids[id(statement)]
            if stmt_id in flagged or type(statement).__name__ in ("InspectPhrase", "ExecSqlStatement", "SearchWhen"):
                continue
            for name in _mentioned(statement) & declared:
                assert name in by_stmt.get(stmt_id, set()), (path.name, stmt_id, name)


def _mentioned(statement) -> set[str]:
    found: set[str] = set()

    def visit(value) -> None:
        if isinstance(value, str):
            masked = re.sub(r"'[^']*'|\"[^\"]*\"", " ", value)
            for token in re.findall(r"(?<![\w-])[A-Za-z][\w-]*", masked):
                found.add(token.upper())
        elif isinstance(value, (tuple, list)):
            for item in value:
                if not hasattr(item, "__dataclass_fields__") or type(item).__name__ in ("FieldReference",):
                    visit(item)
        elif hasattr(value, "__dataclass_fields__") and type(value).__name__ not in ("Literal",):
            for item in vars(value).values():
                if not (isinstance(item, (tuple, list)) and any(hasattr(i, "__dataclass_fields__") and
                                                                type(i).__name__ in _STATEMENT_NAMES for i in item)):
                    visit(item)

    for key, value in vars(statement).items():
        if key in ("condition", "expression", "source", "target", "reasons", "sql", "kind", "mode", "operator",
                   "block", "phrases", "whens", "at_end"):
            if key in ("condition", "expression", "sql", "block", "reasons", "kind", "mode", "operator", "phrases",
                       "whens", "at_end"):
                continue
        visit(value)
    return found - _NOISE


_STATEMENT_NAMES = {cls.__name__ for cls in typing.get_args(ir.Statement)} | {"SearchWhen", "InspectPhrase"}
_NOISE = {"ROUNDED", "SIZE", "BY", "REPLACING", "NUMERIC", "TO", "FROM", "UP", "DOWN", "INPUT", "OUTPUT", "I-O",
          "EXTEND", "DELIMITED", "ALL", "OF", "IN", "FUNCTION", "TRUE", "FALSE", "STDOUT", "NEXT"}


# --- mutation sensitivity -----------------------------------------------------------------------------------------

def test_flipping_one_classification_row_changes_the_access_the_tests_pin(monkeypatch):
    real = STATEMENT_RULES["AddStatement"]

    def mutated(statement):
        return [refs.Use(u.raw, "read" if u.access == "modify" else u.access, u.role, u.kind) for u in real(statement)]

    monkeypatch.setitem(STATEMENT_RULES, "AddStatement", mutated)
    assert _uses("ADD A TO B.") != [("A", "read", "source"), ("B", "modify", "target")]


def test_one_edit_moves_the_reference_span():
    plain = _table(_body("MOVE A TO B."))[1].references
    indented = _table(_body("MOVE  A TO B."))[1].references
    first = {r.name: r.span for r in plain}
    second = {r.name: r.span for r in indented}
    assert second["A"].column == first["A"].column + 1 and second["B"].column == first["B"].column + 1
    assert first["A"].exact and first["A"].basis == "token"


def test_without_the_source_text_no_token_position_is_claimed():
    source = _body("MOVE A TO B.")
    parser = CobolParser()
    program, trace = parser.parse_traced(source)
    spans = build_span_table(program, trace, file="T.cbl")
    table = build_reference_table(program, trace, spans, build_symbol_table(program, trace, spans))
    assert all(r.span is not None and not r.span.exact and r.span.note == "SPAN_OPERAND_NOT_LOCATED"
               for r in table.references)
    assert all(r.span.line == 16 for r in table.references)


def test_a_token_that_occurs_twice_on_its_line_is_not_claimed():
    first = {r.name: r.span for r in _table(_body("MOVE A TO A."))[1].references}
    assert not first["A"].exact and first["A"].note == "SPAN_OPERAND_NOT_LOCATED"


def test_write_record_direction_depends_on_from_and_a_continued_statement_claims_no_second_line_token():
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. F.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT OUT-F ASSIGN TO 'o.dat'.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD OUT-F.\n       01 OUT-REC PIC X(4).\n"
        "       WORKING-STORAGE SECTION.\n       01 W PIC X(4).\n       01 N PIC 9.\n       PROCEDURE DIVISION.\n"
        "       MAIN.\n           WRITE OUT-REC.\n           WRITE OUT-REC FROM W.\n"
        "           COMPUTE N =\n               N + 1.\n           STOP RUN.\n")
    _, table, _ = _table(source)
    records = [(r.owner_stmt.rsplit("/", 1)[1], r.access) for r in table.references if r.role == "record"]
    assert records == [("1", "read"), ("2", "write")]
    expression = next(r for r in table.references if r.role == "expression")
    assert not expression.span.exact, "N on the continuation line must not be placed on the first line"

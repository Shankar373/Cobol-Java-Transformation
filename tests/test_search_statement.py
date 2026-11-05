"""Hermetic tests for SEARCH and SET on indexes (roadmap unit 9); GnuCOBOL proof: test_search_oracle.py."""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import SearchStatement, SetIndexStatement
from engine.transformation.java_generator import JavaGenerator

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. S.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 T.
          05 E PIC X(2) OCCURS 4 TIMES INDEXED BY IDX JDX.
       01 V PIC 99 VALUE 0.
       01 N PIC 99 VALUE 0.
       01 BIG PIC S99 VALUE 0.
       PROCEDURE DIVISION.
"""


def _parse(body: str):
    return CobolParser().parse(HEAD + body + "           STOP RUN.\n")


def _java(body: str) -> str:
    return JavaGenerator().generate(_parse(body))[0].source_code


def _statements(program):
    return [s for p in program.paragraphs for s in p.statements] or list(program.statements)


def test_indexed_by_names_are_parsed_and_declared():
    program = _parse("           DISPLAY 'A'.\n")
    table = program.working_storage[0].children[0]
    assert table.indexed_by == ("IDX", "JDX")
    java = _java("           SET IDX TO 2.\n")
    assert "static int IDX" in java and "static int JDX" in java


def test_set_forms_parse():
    program = _parse("           SET IDX JDX TO 3.\n           SET IDX UP BY 1.\n           SET N TO IDX.\n")
    sets = [s for s in _statements(program) if isinstance(s, SetIndexStatement)]
    assert [(s.targets, s.mode, s.value) for s in sets] == [
        (("IDX", "JDX"), "TO", "3"), (("IDX",), "UP", "1"), (("N",), "TO", "IDX")]


def test_search_parses_arms_and_lowers_to_a_loop():
    body = ("           SEARCH E VARYING V\n               AT END DISPLAY 'NO'\n"
            "               WHEN E(IDX) = 'AB' DISPLAY 'YES'\n           END-SEARCH.\n")
    search = next(s for s in _statements(_parse(body)) if isinstance(s, SearchStatement))
    assert search.table == "E" and search.varying == "V" and search.has_at_end and len(search.whens) == 1
    java = _java(body)
    assert "while (" in java and "IDX <= 4" in java and "V = (IDX % 100)" in java


def _set_reasons(body: str) -> list[str]:
    from engine.transformation.search_lowering import set_reasons

    program = _parse(body)
    stmt = next(s for s in _statements(program) if isinstance(s, SetIndexStatement))
    return set_reasons(stmt, program)


def test_set_on_a_non_index_target_is_refused():
    assert _set_reasons("           SET N TO 2.\n") == ["TARGET"]
    assert _set_reasons("           SET N UP BY 1.\n") == ["TARGET"]


def test_set_of_an_index_and_of_an_integer_item_from_an_index_is_certified():
    assert _set_reasons("           SET IDX UP BY 2.\n") == []
    assert _set_reasons("           SET N TO IDX.\n") == []
    assert _set_reasons("           SET BIG TO IDX.\n") == ["TARGET"]  # signed target


def test_set_with_an_expression_is_not_parsed_as_an_index_form():
    program = _parse("           SET IDX TO N + 1.\n")
    assert not any(isinstance(s, SetIndexStatement) for s in _statements(program))


def _reasons(body: str) -> list[str]:
    from engine.transformation.search_lowering import search_reasons

    program = _parse(body)
    search = next(s for s in _statements(program) if isinstance(s, SearchStatement))
    return search_reasons(search, program)


def test_search_all_is_refused_by_name():
    assert "SEARCH_ALL" in _reasons("           SEARCH ALL E\n               WHEN E(IDX) = 'AB' DISPLAY 'X'\n"
                                   "           END-SEARCH.\n")


def test_varying_an_index_and_a_signed_item_are_refused():
    assert "VARYING_INDEX" in _reasons(
        "           SEARCH E VARYING JDX\n               WHEN E(IDX) = 'AB' DISPLAY 'X'\n           END-SEARCH.\n")
    assert "VARYING" in _reasons(
        "           SEARCH E VARYING BIG\n               WHEN E(IDX) = 'AB' DISPLAY 'X'\n           END-SEARCH.\n")


def test_search_without_when_is_refused():
    assert "NO_WHEN" in _reasons("           SEARCH E\n               AT END DISPLAY 'X'\n           END-SEARCH.\n")


def test_compound_conditions_over_subscripted_numeric_items_map_atom_by_atom():
    from engine.transformation.cobol_to_java_mapping import map_cobol_condition_to_java
    from engine.transformation.java_ir import JavaBinaryOp, JavaUnsupportedExpression

    program = _parse("           DISPLAY 'A'.\n")
    program = CobolParser().parse(HEAD.replace("PIC X(2) OCCURS", "PIC 9 OCCURS") + "           STOP RUN.\n")
    for text, operator in (("E(IDX) > 0 OR E(IDX) > 1", "||"), ("E(IDX) = 0 AND E(JDX) < 3", "&&")):
        mapped = map_cobol_condition_to_java(text, program=program)
        assert not isinstance(mapped, JavaUnsupportedExpression), text
        assert isinstance(mapped, JavaBinaryOp) and mapped.operator == operator

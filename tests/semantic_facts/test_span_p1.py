"""Layer 5 P1: source spans of parsed declarations and statements (docs/architecture/LAYER5_DESIGN.md, section 2).

Every exact span is re-read from the *file text* and must land on the token it claims; one-edit variants must move
the span; the wrong-origin-vector and wrong-copy-chain mutations must be caught; anything that cannot be placed is
named, never guessed.  The parser IR is the same object ``parse`` returns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.semantic_facts.span import (
    SPAN_CODES,
    SpannedDeclaration,
    CopyFrame,
    build_span_table,
    copybook_declaration_spans,
)
from engine.transformation import qualified_names
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.copybook_model import _parse_copybook_expanded
from engine.transformation.fd_copybooks import expand_fd_copybooks

REPO = Path(__file__).resolve().parents[2]
FIXTURES = sorted(p for p in (REPO / "fixtures").rglob("*") if p.is_file() and p.suffix.lower() in (".cob", ".cbl"))

#: The only reasons a fact may have no span today (shrink-only: a new reason or a new SPAN_UNAVAILABLE fails here).
ALLOWED_UNPLACED = {"SPAN_SYNTHETIC_DECLARATION"}

#: statement classes whose source verb is not spelt like the class (the EVALUATE statement is lowered to an IfStatement)
VERB_ALIASES = {"IF": ("EVALUATE",), "STOPRUN": ("STOP",), "GOTO": ("GO",)}

HEAD = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {name}.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)


def _spans(source: str, *, file: str = "T.cbl", origins=None):
    parser = CobolParser()
    program, trace = parser.parse_traced(source)
    return program, parser, build_span_table(program, trace, file=file, origins=origins)


def _statement_lines(table):
    return [(type(s.statement).__name__, s.span.line, s.span.column, s.span.exact) for s in table.statements if s.span]


def test_parse_traced_returns_the_ir_parse_returns():
    source = HEAD.format(name="P") + "       01 A PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n           MOVE 1 TO A.\n           STOP RUN.\n"
    assert CobolParser().parse_traced(source)[0] == CobolParser().parse(source)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_every_exact_span_of_every_repo_fixture_lands_on_its_token(path):
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.split("\n")
    program, parser, table = _spans(source, file=path.name)
    assert len(parser.last_line_map) == len(parser.last_code_lines), "the logical-line map must never be dropped"
    for fact in (*table.statements, *table.declarations):
        span = fact.span
        if span is None:
            assert fact.code in ALLOWED_UNPLACED, (path.name, fact.code, getattr(fact, "name", ""))
            continue
        assert span.file == path.name and span.line >= 1
        if not span.exact:
            assert span.note in SPAN_CODES and span.basis in ("line", "statement", "copy-site")
            continue
        text = lines[span.line - 1]
        assert span.column >= 1 and text[span.column - 1] != " ", (path.name, span)
        assert text[: span.column - 1].strip(" 0123456789") == "", (path.name, span)
        word = text[span.column - 1:].split()[0].rstrip(".").upper()
        if isinstance(fact, SpannedDeclaration):
            assert word.isdigit() and fact.name.upper() in text.upper(), (path.name, fact.name, span)
        else:
            kind = type(fact.statement).__name__.removesuffix("Statement").upper()
            assert word.startswith(kind[:3]) or word in VERB_ALIASES.get(kind, ()), (path.name, kind, word, span)
    for statement in table.statements:
        assert statement.code != "SPAN_UNAVAILABLE", (path.name, statement.paragraph, statement.ordinal)


def test_an_end_line_in_copy_expanded_text_is_in_file_coordinates(tmp_path):
    (tmp_path / "REC.cpy").write_text(
        "\n".join(["       01 IN-REC.", "          05 IN-F PIC X(5).", "       01 EXTRA.", "          05 EX-F PIC X.", ""]),
        encoding="utf-8")
    source = "\n".join([
        "       IDENTIFICATION DIVISION.", "       PROGRAM-ID. FD2.", "       ENVIRONMENT DIVISION.",
        "       INPUT-OUTPUT SECTION.", "       FILE-CONTROL.", "           SELECT IN-FILE ASSIGN TO 'IN.DAT'.",
        "       DATA DIVISION.", "       FILE SECTION.", "       FD IN-FILE.", "           COPY REC.",
        "       WORKING-STORAGE SECTION.", "       01 A", "           PIC 9.", "       PROCEDURE DIVISION.",
        "       MAIN.", "           STOP RUN.", ""])
    expansion = expand_fd_copybooks(source, (tmp_path,), source_file="FD2.cbl")
    _, _, table = _spans(expansion.source, file="FD2.cbl", origins=expansion.origins)
    span = next(d.span for d in table.declarations if d.name == "A")
    assert (span.line, span.end_line) == (12, 13), span


def test_a_declaration_span_names_the_level_number_and_its_end_line():
    source = (HEAD.format(name="D") + "       01 GRP.\n          05 F1 PIC 9.\n          05 F2\n              PIC 9.\n"
              "       PROCEDURE DIVISION.\n       MAIN.\n           STOP RUN.\n")
    _, _, table = _spans(source)
    by_name = {d.name: d.span for d in table.declarations}
    lines = source.split("\n")
    assert lines[by_name["F2"].line - 1][by_name["F2"].column - 1:].startswith("05 F2")
    assert (by_name["F2"].line, by_name["F2"].end_line) == (7, 8), "a two-line entry spans both lines"
    assert (by_name["F1"].line, by_name["F1"].end_line) == (6, 6)


# --- one-edit variants must move the span ------------------------------------------------------------------------

def _program_with_statements():
    return (HEAD.format(name="E") + "       01 A PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n"
            "           MOVE 1 TO A.\n           DISPLAY A.\n           STOP RUN.\n")


def test_inserting_a_line_moves_every_later_span_by_one_and_nothing_else():
    base = _statement_lines(_spans(_program_with_statements())[2])
    shifted = _statement_lines(_spans("      * a new comment line\n" + _program_with_statements())[2])
    assert [(n, line + 1, col, ex) for n, line, col, ex in base] == shifted


def test_indenting_one_statement_moves_only_its_column():
    original = _program_with_statements()
    edited = original.replace("           DISPLAY A.", "             DISPLAY A.")
    base = {n: (line, col) for n, line, col, _ in _statement_lines(_spans(original)[2])}
    after = {n: (line, col) for n, line, col, _ in _statement_lines(_spans(edited)[2])}
    assert after["DisplayStatement"] == (base["DisplayStatement"][0], base["DisplayStatement"][1] + 2)
    assert after["MoveStatement"] == base["MoveStatement"]


def test_a_free_format_file_reports_columns_from_column_one():
    source = ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\nPROGRAM-ID. F.\nDATA DIVISION.\nWORKING-STORAGE SECTION.\n01 A PIC 9.\n" \
             "PROCEDURE DIVISION.\nMAIN.\n    MOVE 1 TO A.\n    STOP RUN.\n"
    _, _, table = _spans(source)
    assert [(n, line, col) for n, line, col, _ in _statement_lines(table)] == [
        ("MoveStatement", 9, 5), ("StopRunStatement", 10, 5)]


def test_a_mixed_format_file_spans_each_segment_by_its_own_format():
    source = (HEAD.format(name="M") + "       01 A PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n"
              "           MOVE 1 TO A.\n>>SOURCE FORMAT FREE\n  DISPLAY A.\n  STOP RUN.\n")
    _, _, table = _spans(source)
    got = {n: (line, col) for n, line, col, _ in _statement_lines(table)}
    assert got["MoveStatement"] == (8, 12)
    assert got["DisplayStatement"] == (10, 3), "a free-format segment has no indicator area"


# --- the text-rewrite passes ------------------------------------------------------------------------------------

CORRESPONDING = (
    HEAD.format(name="C") + "       01 R1.\n          05 F1 PIC 9.\n          05 F2 PIC 9.\n"
    "       01 R2.\n          05 F1 PIC 9.\n          05 F2 PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n"
    "           MOVE CORRESPONDING R1 TO R2.\n           DISPLAY F1 OF R2.\n           STOP RUN.\n"
)


def test_the_line_map_survives_a_corresponding_expansion():
    program, parser, table = _spans(CORRESPONDING)
    assert len(parser.last_line_map) == len(parser.last_code_lines) > 0
    lines = {(n, line) for n, line, _c, _e in _statement_lines(table)}
    # the two MOVEs the CORRESPONDING expanded into both sit on its physical line; later statements keep their own
    assert [line for n, line in sorted(lines) if n == "MoveStatement"] == [13]
    assert ("DisplayStatement", 14) in lines and ("StopRunStatement", 15) in lines


def test_a_wrong_origin_vector_is_caught(monkeypatch):
    """Mutation: an origin vector that ignores the expansion (as if no pass changed the line count) mis-places what follows."""
    real = qualified_names.resolve_qualified_names_detailed

    def broken(lines):
        out, problems, _origin, renames = real(lines)
        return out, problems, [min(i, len(lines) - 1) for i in range(len(out))], renames

    monkeypatch.setattr("engine.transformation.cobol_parser.resolve_qualified_names_detailed", broken)
    _, _, table = _spans(CORRESPONDING)
    assert ("DisplayStatement", 14, 12, True) not in _statement_lines(table)


def test_a_split_qualifier_keeps_the_statement_on_its_first_line():
    source = (HEAD.format(name="S") + "       01 R1.\n          05 F1 PIC 9.\n       01 R2.\n          05 F1 PIC 9.\n"
              "       PROCEDURE DIVISION.\n       MAIN.\n           MOVE 1 TO F1\n               OF R1.\n"
              "           DISPLAY F1 OF R2.\n           STOP RUN.\n")
    program, parser, table = _spans(source)
    assert len(parser.last_line_map) == len(parser.last_code_lines)
    got = {n: (line, col, ex) for n, line, col, ex in _statement_lines(table)}
    assert got["MoveStatement"] == (11, 12, True)
    assert got["DisplayStatement"] == (13, 12, True), "the statement after the wrapped qualifier keeps its true line"


def test_a_replace_rewritten_line_has_its_line_but_no_claimed_column():
    source = (HEAD.format(name="R") + "       01 A PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n"
              "           REPLACE ==XX== BY ==A==.\n           MOVE 1 TO XX.\n           STOP RUN.\n")
    _, _, table = _spans(source)
    move = next(s for s in table.statements if type(s.statement).__name__ == "MoveStatement")
    assert (move.span.line, move.span.exact, move.span.basis, move.span.note) == (
        9, False, "line", "SPAN_REWRITTEN_REPLACE")
    stop = next(s for s in table.statements if type(s.statement).__name__ == "StopRunStatement")
    assert (stop.span.line, stop.span.column, stop.span.exact) == (10, 12, True), "only a line the REPLACE changed is inexact"


def test_a_tab_before_the_first_character_makes_the_column_inexact_not_wrong():
    source = (HEAD.format(name="T") + "       01 A PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n"
              "\tMOVE 1 TO A.\n           STOP RUN.\n")
    _, _, table = _spans(source)
    move = next(s for s in table.statements if type(s.statement).__name__ == "MoveStatement")
    assert move.span.line == 8 and move.span.exact is False and move.span.note == "SPAN_COLUMN_TAB"
    stop = next(s for s in table.statements if type(s.statement).__name__ == "StopRunStatement")
    assert (stop.span.line, stop.span.column, stop.span.exact) == (9, 12, True)


def test_a_continued_literal_keeps_later_statements_on_their_physical_lines():
    source = (HEAD.format(name="K") + "       PROCEDURE DIVISION.\n       MAIN.\n"
              "           DISPLAY 'ABCDEFGHIJ\n      -    'KLMNOP'.\n           STOP RUN.\n")
    _, _, table = _spans(source)
    got = {n: (line, col) for n, line, col, _ in _statement_lines(table)}
    assert got["DisplayStatement"] == (7, 12)
    assert got["StopRunStatement"] == (9, 12)


def test_an_evaluate_when_chain_names_its_parent_instead_of_inventing_a_line():
    source = (HEAD.format(name="V") + "       01 A PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n"
              "           EVALUATE A\n             WHEN 1 DISPLAY 'ONE'\n             WHEN OTHER DISPLAY 'OTHER'\n"
              "           END-EVALUATE.\n           STOP RUN.\n")
    _, _, table = _spans(source)
    evaluate = next(s for s in table.statements if s.paragraph == "MAIN" and s.ordinal == 0)
    assert evaluate.span.line == 8 and evaluate.span.exact
    for fact in table.statements:
        if fact.span is not None and not fact.span.exact:
            assert fact.span.note in {"SPAN_INLINE_FRAGMENT", "SPAN_LOWERED_FROM_PARENT"}
            assert fact.span.line >= 8, "an inexact span points inside the statement it lies in, never before it"


# --- COPY-origin chains -----------------------------------------------------------------------------------------

def test_fd_copy_expansion_maps_later_statements_back_to_the_program_lines(tmp_path):
    (tmp_path / "REC.cpy").write_text("       01 IN-REC.\n          05 IN-F PIC X(5).\n       01 EXTRA.\n          05 EX-F PIC X.\n",
                                      encoding="utf-8")
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. FD1.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT IN-FILE ASSIGN TO 'IN.DAT'.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD IN-FILE.\n           COPY REC.\n"
        "       WORKING-STORAGE SECTION.\n       01 A PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n"
        "           OPEN INPUT IN-FILE.\n           STOP RUN.\n"
    )
    expansion = expand_fd_copybooks(source, (tmp_path,), source_file="FD1.cbl")
    assert expansion.source != source and expansion.origins is not None
    _, _, table = _spans(expansion.source, file="FD1.cbl", origins=expansion.origins)
    program_lines = source.split("\n")
    for fact in table.statements:
        span = fact.span
        assert span is not None and span.file == "FD1.cbl" and span.exact
        assert program_lines[span.line - 1][span.column - 1:].lstrip().startswith(("OPEN", "STOP")), span


def test_a_copybook_declaration_carries_the_copy_chain_and_never_a_column(tmp_path):
    inner = tmp_path / "INNER.cpy"
    inner.write_text("       05 IN-F PIC X.\n", encoding="utf-8")
    outer = tmp_path / "OUTER.cpy"
    outer.write_text("       01 OUT-REC.\n           COPY INNER.\n       05 OUT-G PIC 9.\n", encoding="utf-8")
    model = _parse_copybook_expanded(outer, (tmp_path,), [])
    site = CopyFrame("PROG.cbl", 21, "OUTER")
    spans = {d.name: d.span for d in copybook_declaration_spans(model, copy_site=site)}
    assert spans["OUT-REC"].file.endswith("OUTER.cpy") and spans["OUT-REC"].line == 1
    assert spans["OUT-REC"].via_copy == (site,)
    inner_span = spans["IN-F"]
    assert inner_span.file.endswith("INNER.cpy") and inner_span.line == 1
    assert [(f.file.endswith("OUTER.cpy"), f.line, f.target) for f in inner_span.via_copy[1:]] == [(True, 2, "INNER")]
    assert inner_span.via_copy[0] == site, "the program's own COPY statement is the outermost frame"
    assert spans["OUT-G"].line == 3
    for span in spans.values():
        assert span.exact is False and span.column == 0 and span.note == "SPAN_COPY_COLUMN_UNPROVEN"


def test_a_replacing_text_that_splits_lines_is_attributed_to_the_copy_site_only(tmp_path):
    from engine.transformation.copybook_model import _apply_replacing  # noqa: F401 - the clause under test lives there

    cpy = tmp_path / "REP.cpy"
    cpy.write_text("       01 REC.\n          05 F1 PIC 9.\n", encoding="utf-8")
    model = _parse_copybook_expanded(cpy, (tmp_path,), [], replacing=(("F1", "F1 PIC 9.\n          05 F2"),))
    spans = [d.span for d in copybook_declaration_spans(model)]
    assert spans and all(s.basis == "copy-site" and s.note == "SPAN_COPY_SITE_ONLY" and s.exact is False for s in spans)


def test_the_parser_adds_items_itself_and_says_so():
    source = (HEAD.format(name="Q") + "       01 A PIC 9.\n       PROCEDURE DIVISION.\n       MAIN.\n"
              "           EXEC SQL INCLUDE SQLCA END-EXEC.\n           STOP RUN.\n")
    _, _, table = _spans(source)
    unplaced = {(kind, code) for kind, _subject, code in table.unplaced()}
    assert unplaced <= {("declaration", c) for c in ALLOWED_UNPLACED}

"""Layer 4 (criteria 2-4): the engine face reads every file at the same ``(line, column)`` as discovery.

Both faces are built on ``enterprise.discovery.cobol_text.read_source``.  These tests compare the token
streams they produce at every ``(line, column)`` over mixed-format, continuation, card, debug and
conditional fixtures, and prove each comparison can fail (a variant of the fixture must differ).
Cards and directives are asserted absent from the parser's input, IR and diagnostics, and present in
discovery's facts.
"""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.source_format import (
    compiler_visible_text,
    has_format_switch,
    positioned_lines,
    positioned_token_lines,
    source_formats,
)
from enterprise.discovery.cobol_text import read_source, tokenize
from enterprise.discovery.scan_cobol import scan_cobol

# ---------------------------------------------------------------------------------------------------------------
# Fixtures (physical text; every line below is exactly what the compiler would read)
# ---------------------------------------------------------------------------------------------------------------

FIXED_TO_FREE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MIXA.\n"
    "       PROCEDURE DIVISION.\n"
    '           DISPLAY "FIXED".\n'
    ">>SOURCE FORMAT FREE\n"
    '      DISPLAY "FREE" *> trailing comment\n'   # six blanks then D: column 7 is code in a free segment
    "STOP RUN.\n"
)

FREE_TO_FIXED = (
    "IDENTIFICATION DIVISION.\n"
    "PROGRAM-ID. MIXB.\n"
    ">>SOURCE FORMAT FIXED\n"
    "       PROCEDURE DIVISION.\n"
    "      * a fixed comment line\n"
    '      D    DISPLAY "DEBUG".\n'
    "           DISPLAY 'IT''S' \"X\".\n"
    "           STOP RUN.\n"
)

MICRO_FOCUS_SET = (
    '$SET SOURCEFORMAT"FREE"\n'
    "IDENTIFICATION DIVISION.\n"
    "PROGRAM-ID. MFS.\n"
    "PROCEDURE DIVISION.\n"
    '  DISPLAY "Z". *> note\n'
    "  STOP RUN.\n"
)

CONTINUATION = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CONT.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-AL\n"
    "      -   PHA PIC X(10).\n"
    '       01 WS-MSG PIC X(60) VALUE "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCDEFGH\n'
    '      -    "IJKLMNOP".\n'
    "       01 WS-B PIC 9.\n"
)

CARDS = (
    "CBL ARITH(EXTEND),DYNAM\n"
    "PROCESS NODISPLAY\n"
    "-INC COPYA\n"
    "++INCLUDE COPYB\n"
    "%INCLUDE COPYC\n"
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CARDS.\n"
    "       PROCEDURE DIVISION.\n"
    "           GOBACK.\n"
)

#: The same words indented to column 8: program text, not cards.
NOT_CARDS = (
    "       CBL ARITH(EXTEND),DYNAM\n"
    "       PROCESS NODISPLAY\n"
    "       -INC COPYA\n"
    "       ++INCLUDE COPYB\n"
    "       %INCLUDE COPYC\n"
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CARDS.\n"
    "       PROCEDURE DIVISION.\n"
    "           GOBACK.\n"
)

DEBUG_LINES = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. DBG.\n"
    "       PROCEDURE DIVISION.\n"
    '      D    DISPLAY "DEBUG-ONLY".\n'
    '           DISPLAY "LIVE".\n'
    "           GOBACK.\n"
)

CONDITIONAL = (
    "       >>DEFINE MODE AS 1\n"
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CDF.\n"
    "       PROCEDURE DIVISION.\n"
    "       >>IF MODE = 1\n"
    '           DISPLAY "LIVE-BRANCH".\n'
    "       >>ELSE\n"
    '           DISPLAY "DEAD-BRANCH".\n'
    "       >>END-IF\n"
    "           GOBACK.\n"
)


def _discovery_tokens(src: str) -> list[tuple[int, int, str, str]]:
    return [(t.line, t.column, t.kind, t.text) for t in tokenize(read_source(src).lines)]


def _engine_tokens(src: str) -> list[tuple[int, int, str, str]]:
    return [(t.line, t.column, t.kind, t.text) for t in tokenize(positioned_token_lines(src))]


def _parse(src: str) -> tuple[CobolParser, object]:
    parser = CobolParser()
    return parser, parser.parse(src)


def _display_parts(program) -> list[tuple[str, ...]]:
    return [tuple(statement.parts) for paragraph in program.paragraphs for statement in paragraph.statements
            if hasattr(statement, "parts")]


def _statement_texts(program) -> list[str]:
    return [repr(statement) for paragraph in program.paragraphs for statement in paragraph.statements]


# ---------------------------------------------------------------------------------------------------------------
# Token parity at every (line, column) — both faces, every fixture, with a mutation check each
# ---------------------------------------------------------------------------------------------------------------

PARITY_CASES = {
    "fixed-to-free": (FIXED_TO_FREE, FIXED_TO_FREE.replace('"FREE" *> trailing', '"FREE!" *> trailing')),
    "free-to-fixed": (FREE_TO_FIXED, FREE_TO_FIXED.replace("PROCEDURE DIVISION.", "PROCEDURE  DIVISION.")),
    "microfocus-set-free": (MICRO_FOCUS_SET, MICRO_FOCUS_SET.replace('"Z"', '"ZZ"')),
    "continuation": (CONTINUATION, CONTINUATION.replace("IJKLMNOP", "IJKLMNOPQ")),
    "cards": (CARDS, NOT_CARDS),
    "debug": (DEBUG_LINES, DEBUG_LINES.replace("      D    DISPLAY", "           DISPLAY")),
    "conditional": (CONDITIONAL, CONDITIONAL.replace("MODE = 1", "MODE = 2")),
}


@pytest.mark.parametrize("name", sorted(PARITY_CASES))
def test_engine_and_discovery_token_streams_agree_at_every_line_and_column(name: str):
    src, variant = PARITY_CASES[name]
    discovery, engine = _discovery_tokens(src), _engine_tokens(src)
    assert discovery, "the fixture must produce tokens"
    assert engine == discovery
    # Mutation check: a one-edit variant moves or changes tokens, so the equality above is not vacuous...
    assert _discovery_tokens(variant) != discovery
    # ...and it holds for the variant too (agreement is a property of the readers, not of one fixture).
    assert _engine_tokens(variant) == _discovery_tokens(variant)


def test_a_divergent_engine_stream_would_be_caught():
    """The comparison itself fails when one face moves a token by a single column."""
    discovery = _discovery_tokens(FIXED_TO_FREE)
    shifted = [(line, column + (1 if i == 5 else 0), kind, text) for i, (line, column, kind, text) in enumerate(discovery)]
    assert shifted != discovery


def test_mixed_format_tokens_cover_both_segments_at_their_own_columns():
    tokens = {(line, column): text for line, column, _kind, text in _engine_tokens(FIXED_TO_FREE)}
    assert tokens[(4, 12)] == "DISPLAY"          # fixed segment: code starts in column 8 + 4
    assert tokens[(6, 7)] == "DISPLAY"           # free segment: column 7 is code (no indicator area)
    assert tokens[(6, 15)] == "FREE"
    assert all(line != 5 for line, _c in tokens)  # the directive line yields no token
    assert not any(text == "trailing" for text in tokens.values())  # the *> comment is cut


def test_doubled_quote_literal_keeps_discovery_columns_after_canonicalisation():
    """``'IT''S'`` is re-delimited in the compiler-visible text (one character shorter); positions index the source."""
    engine = {(line, column): text for line, column, _k, text in _engine_tokens(FREE_TO_FIXED)}
    assert engine[(7, 20)] == "IT'S"
    assert engine[(7, 28)] == "X"    # the token after it is where the customer wrote it, not shifted left
    line = positioned_lines(FREE_TO_FIXED)[6]
    assert "IT'S" in line.text and "''" not in line.text           # canonicalised in the compiler-visible text
    assert line.source_text.index('"X"') == line.text.index('"X"') + 1   # which is one character shorter


# ---------------------------------------------------------------------------------------------------------------
# Positioned lines: shape, byte-identity with compiler_visible_text, continuation origins
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("src", [FIXED_TO_FREE, FREE_TO_FIXED, MICRO_FOCUS_SET, CONTINUATION, CARDS, NOT_CARDS,
                                 DEBUG_LINES, CONDITIONAL])
def test_positioned_lines_are_the_single_source_of_compiler_visible_text(src: str):
    lines = positioned_lines(src, "p.cbl")
    assert "\n".join(line.text for line in lines) == compiler_visible_text(src)
    assert [line.line for line in lines] == list(range(1, src.count("\n") + 2))  # one per physical line
    assert all(line.span.file == "p.cbl" and line.span.column == 1 for line in lines)


def test_line_kinds_say_why_a_line_carries_no_program_text():
    kinds = {line.line: line.kind for line in positioned_lines(CARDS)}
    assert [kinds[n] for n in (1, 2, 3, 4, 5)] == ["card"] * 5
    assert kinds[6] == "code"
    assert {line.line: line.kind for line in positioned_lines(DEBUG_LINES)}[4] == "debug"
    cond = {line.line: line.kind for line in positioned_lines(CONDITIONAL)}
    assert cond[1] == "directive" and cond[8] == "dead-branch" and cond[6] == "code"
    mixed = {line.line: line.kind for line in positioned_lines(FREE_TO_FIXED)}
    assert mixed[5] == "comment" and mixed[3] == "directive"


def test_continuation_tokens_resolve_to_their_true_physical_position():
    lines = {line.line: line for line in positioned_lines(CONTINUATION, "c.cbl")}
    anchor = lines[5]
    assert anchor.continuations and lines[6].kind == "continuation" and lines[6].text == ""
    assert anchor.text.strip().endswith("WS-ALPHA PIC X(10).")
    joined = anchor.source_text
    assert anchor.span_at(joined.index("WS-AL")).line == 5
    pha = anchor.span_at(joined.index("PHA"))
    assert (pha.file, pha.line, pha.column) == ("c.cbl", 6, 11)   # "      -   PHA": P is column 11
    literal = lines[7]
    tail = literal.span_at(literal.source_text.rindex("IJKLMNOP"))
    assert (tail.line, tail.column) == (8, 13)                      # after the resuming quote in column 12
    assert literal.span_at(0).line == 7


def test_continuation_origin_changes_when_the_continuation_moves():
    moved = CONTINUATION.replace("      -   PHA", "      -      PHA")
    anchor = {line.line: line for line in positioned_lines(moved)}[5]
    assert anchor.span_at(anchor.source_text.index("PHA")).column == 14


# ---------------------------------------------------------------------------------------------------------------
# Mixed-format truth: formats, per-line parser semantics, the line map
# ---------------------------------------------------------------------------------------------------------------

def test_source_formats_and_switch_are_truthful_where_detect_source_format_is_the_start_format():
    from engine.transformation.source_format import detect_source_format

    assert detect_source_format(FIXED_TO_FREE) == "fixed"          # start format, kept for oracle callers
    assert source_formats(FIXED_TO_FREE) == ("fixed", "free")
    assert source_formats(FREE_TO_FIXED) == ("free", "fixed")
    assert source_formats(MICRO_FOCUS_SET) == ("free",)
    assert has_format_switch(FIXED_TO_FREE) and has_format_switch(FREE_TO_FIXED)
    assert not has_format_switch(CONTINUATION) and not has_format_switch(MICRO_FOCUS_SET)


def test_a_free_segment_keeps_its_column_7_code_in_a_fixed_start_file():
    """Six blanks then ``DISPLAY`` in a free segment: column 7 is ``D`` — code, not a debugging indicator."""
    parser, program = _parse(FIXED_TO_FREE)
    statements = _statement_texts(program)
    assert any("FREE" in text for text in statements), statements
    assert any("FIXED" in text for text in statements)
    assert (6, 'DISPLAY "FREE"') in zip(parser.last_line_map, parser.last_code_lines)
    assert not [d for d in parser.diagnostics.all if "DISPLAY" in d.message]


def test_a_fixed_segment_in_a_free_start_file_gets_fixed_indicator_semantics():
    """After ``>>SOURCE FORMAT FIXED`` a ``D`` in column 7 is a debugging line and ``*`` a comment."""
    parser, program = _parse(FREE_TO_FIXED)
    statements = _statement_texts(program)
    assert not any("DEBUG" in text for text in statements), statements
    assert ("\"IT'S\"", '"X"') in _display_parts(program), statements
    assert not [d for d in parser.diagnostics.all if "DEBUG" in d.message or "comment" in d.message]
    # Mutation: the same text in a free segment is program text, not a debugging line.
    free_variant = FREE_TO_FIXED.replace(">>SOURCE FORMAT FIXED", ">>SOURCE FORMAT FREE")
    assert {pl.line: pl.kind for pl in positioned_lines(free_variant)}[6] == "code"
    assert {pl.line: pl.kind for pl in positioned_lines(FREE_TO_FIXED)}[6] == "debug"


def test_micro_focus_set_free_parses_like_the_directive_form():
    _parser, set_program = _parse(MICRO_FOCUS_SET)
    directive_form = MICRO_FOCUS_SET.replace('$SET SOURCEFORMAT"FREE"', ">>SOURCE FORMAT FREE")
    _parser2, directive_program = _parse(directive_form)
    assert _statement_texts(set_program) == _statement_texts(directive_program)
    assert _statement_texts(set_program), "the DISPLAY must survive"
    assert _engine_tokens(MICRO_FOCUS_SET)[:3] == [(2, 1, "word", "IDENTIFICATION"), (2, 16, "word", "DIVISION"),
                                                    (2, 24, "punct", ".")]


def test_variable_format_is_refused_by_name_never_read_as_fixed():
    src = '$SET SOURCEFORMAT"VARIABLE"\n       IDENTIFICATION DIVISION.\n       PROGRAM-ID. V.\n'
    parser, _program = _parse(src)
    codes = [d.code for d in parser.diagnostics.all]
    assert DiagnosticCode.REFERENCE_FORMAT_VARIABLE_UNSUPPORTED in codes
    assert parser.diagnostics.has_errors
    clean, _ = _parse(MICRO_FOCUS_SET)
    assert DiagnosticCode.REFERENCE_FORMAT_VARIABLE_UNSUPPORTED not in [d.code for d in clean.diagnostics.all]
    assert read_source(src).format == "variable"


def test_line_map_names_the_physical_line_of_every_parsed_code_line():
    parser, _program = _parse(CONTINUATION)
    pairs = dict(zip(parser.last_code_lines, parser.last_line_map))
    assert pairs["PROGRAM-ID. CONT."] == 2
    assert pairs["01 WS-ALPHA PIC X(10)."] == 5      # a folded continuation maps to the line it continues
    assert pairs["01 WS-B PIC 9."] == 9
    assert len(parser.last_line_map) == len(parser.last_code_lines)
    # Mutation: an extra comment line shifts every later physical line.
    shifted = CONTINUATION.replace("       DATA DIVISION.\n", "      * inserted\n       DATA DIVISION.\n")
    parser2, _ = _parse(shifted)
    assert dict(zip(parser2.last_code_lines, parser2.last_line_map))["01 WS-B PIC 9."] == 10


def test_line_map_survives_a_replace_directive_that_removes_lines():
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. REPL.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       REPLACE ==AAA== BY ==WS-X==.\n"
        "       01 AAA PIC 9.\n"
        "       REPLACE OFF.\n"
        "       01 WS-Y PIC 9.\n"
    )
    parser, _program = _parse(src)
    pairs = dict(zip(parser.last_code_lines, parser.last_line_map))
    assert pairs["01 WS-X PIC 9."] == 6
    assert pairs["01 WS-Y PIC 9."] == 8
    assert "REPLACE OFF." not in pairs


# ---------------------------------------------------------------------------------------------------------------
# Cards: dropped by the one reader, absent from the engine's input / IR / diagnostics, present in discovery facts
# ---------------------------------------------------------------------------------------------------------------

def test_column_1_cards_never_reach_the_engine_input_ir_or_diagnostics():
    text = compiler_visible_text(CARDS)
    first_lines = text.split("\n")[:5]
    assert first_lines == [""] * 5                      # five card lines dropped, line count kept
    for word in ("ARITH", "DYNAM", "NODISPLAY", "COPYA", "COPYB", "COPYC"):
        assert word not in text
    parser, program = _parse(CARDS)
    assert program.program_id == "CARDS"
    assert program.copybooks == ()                      # -INC/++INCLUDE/%INCLUDE are not COPY references of the IR
    assert [pair for pair in zip(parser.last_line_map, parser.last_code_lines)][0] == (6, "IDENTIFICATION DIVISION.")
    for diagnostic in parser.diagnostics.all:
        blob = f"{diagnostic.message} {diagnostic.location}"
        assert not any(word in blob for word in ("ARITH", "DYNAM", "NODISPLAY", "COPYA", "COPYB", "COPYC", "CBL")), blob


def test_cards_are_discovery_facts_from_the_reader_with_their_columns():
    read = read_source(CARDS)
    assert [(c.line, c.column, c.keyword, c.text) for c in read.cards] == [
        (1, 1, "CBL", "ARITH(EXTEND),DYNAM"), (2, 1, "PROCESS", "NODISPLAY"), (3, 1, "-INC", "COPYA"),
        (4, 1, "++INCLUDE", "COPYB"), (5, 1, "%INCLUDE", "COPYC")]
    scan = scan_cobol("cards.cbl", CARDS)
    options = sorted((f.line, f.column, f.name) for f in scan.facts if f.category == "compiler-option")
    assert options == [(1, 1, "ARITH(EXTEND)"), (1, 1, "DYNAM"), (2, 1, "NODISPLAY")]
    copies = sorted((r.line, r.column, r.target) for r in scan.refs if r.relation == "copies")
    assert copies == [(3, 6, "COPYA"), (4, 11, "COPYB"), (5, 10, "COPYC")]


def test_the_same_words_in_column_8_are_program_text_not_cards():
    read = read_source(NOT_CARDS)
    assert read.cards == ()
    assert not [kind for _line, kind in read.skipped if kind == "card"]
    lines = positioned_lines(NOT_CARDS)
    assert [line.kind for line in lines[:5]] == ["code"] * 5
    assert "CBL ARITH(EXTEND),DYNAM" in compiler_visible_text(NOT_CARDS)
    scan = scan_cobol("not_cards.cbl", NOT_CARDS)
    assert not [f for f in scan.facts if f.category == "compiler-option"]
    assert not [r for r in scan.refs if r.relation == "copies"]
    # The engine reads them as program text at (1, 8): the same positions as discovery.
    assert (1, 8, "word", "CBL") in _engine_tokens(NOT_CARDS)
    assert (1, 8, "word", "CBL") in _discovery_tokens(NOT_CARDS)
    assert (1, 8, "word", "CBL") not in _engine_tokens(CARDS)


def test_a_card_inside_a_dead_branch_is_not_a_fact():
    src = (">>DEFINE X AS 1\n>>IF X = 2\nCBL SQL\n>>END-IF\n       IDENTIFICATION DIVISION.\n"
           "       PROGRAM-ID. D.\n")
    assert read_source(src).cards == ()
    assert not [f for f in scan_cobol("d.cbl", src).facts if f.category == "compiler-option"]
    live = src.replace("X = 2", "X = 1")
    assert [c.keyword for c in read_source(live).cards] == ["CBL"]


# ---------------------------------------------------------------------------------------------------------------
# Debug lines and conditional dead branches
# ---------------------------------------------------------------------------------------------------------------

def test_debug_line_is_not_program_text_on_either_face():
    _parser, program = _parse(DEBUG_LINES)
    statements = _statement_texts(program)
    assert any("LIVE" in text for text in statements)
    assert not any("DEBUG-ONLY" in text for text in statements)
    assert not [t for t in _engine_tokens(DEBUG_LINES) if t[3] == "DEBUG-ONLY"]
    assert ("debug" in [kind for _line, kind in read_source(DEBUG_LINES).skipped])


def test_dead_conditional_branch_never_reaches_the_parser_and_flips_with_the_condition():
    _parser, program = _parse(CONDITIONAL)
    statements = _statement_texts(program)
    assert any("LIVE-BRANCH" in text for text in statements)
    assert not any("DEAD-BRANCH" in text for text in statements)
    flipped = CONDITIONAL.replace("MODE = 1", "MODE = 2")
    _p, flipped_program = _parse(flipped)
    flipped_statements = _statement_texts(flipped_program)
    assert any("DEAD-BRANCH" in text for text in flipped_statements)
    assert not any("LIVE-BRANCH" in text for text in flipped_statements)

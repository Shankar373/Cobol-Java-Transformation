"""Layer 4 residual audit: where the two faces of the single reader agree, and where they honestly do not.

Both faces read through ``enterprise.discovery.cobol_text.read_source``.  The cases below are the residuals the
closure record listed (tabs, ``\\n`` vs ``splitlines()``, ``*>`` on a continued line, CRLF/CR).  Agreeing cases are
ordinary tests with a mutation variant.  Divergences are pinned with ``xfail(strict=True)``: they state the agreed
behaviour, fail today, and turn the suite red the day a face is changed, so the limitation cannot silently move.
Nothing here changes what the engine generates (``tools/generation_hashes.py --check`` stays ``identical``).
"""

from __future__ import annotations

import pytest

from engine.transformation.producer import TransformationProducer
from engine.transformation.source_format import positioned_token_lines
from enterprise.discovery.cobol_text import read_source, tokenize
from enterprise.discovery.scan_cobol import scan_cobol

HEAD = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n"
TAIL = "       PROCEDURE DIVISION.\n           GOBACK.\n"


def _discovery(text: str) -> list[tuple[int, int, str, str]]:
    return [(t.line, t.column, t.kind, t.text) for t in tokenize(read_source(text).lines)]


def _engine(text: str) -> list[tuple[int, int, str, str]]:
    return [(t.line, t.column, t.kind, t.text) for t in tokenize(positioned_token_lines(text))]


# --- (d) CRLF agrees; (c) a `*>` comment after a continued literal agrees (fixed in this audit) -----------------------

def test_crlf_text_is_read_identically_by_both_faces() -> None:
    crlf = (HEAD + TAIL).replace("\n", "\r\n")
    assert _discovery(crlf) == _engine(crlf) != []
    assert _discovery(crlf) == _discovery(HEAD + TAIL)


LONG = "'" + "A" * 66
CONTINUED_THEN_COMMENT = (HEAD + "       PROCEDURE DIVISION.\n"
                          f"           DISPLAY {LONG}\n      -    'BBB'. *> CALL 'GHOST'\n           GOBACK.\n")


def test_a_star_gt_comment_after_a_continued_literal_is_a_comment_on_both_faces() -> None:
    assert _discovery(CONTINUED_THEN_COMMENT) == _engine(CONTINUED_THEN_COMMENT)
    assert not [t for t in _discovery(CONTINUED_THEN_COMMENT) if t[3] in ("*", ">", "CALL", "GHOST")]
    # The comment text must never become a fact (it used to yield a ``calls GHOST`` edge).
    refs = [(ref.relation, ref.target) for ref in scan_cobol("P.cbl", CONTINUED_THEN_COMMENT).refs]
    assert ("calls", "GHOST") not in refs
    # Mutation: the same words as program text on a fresh line are a real CALL, so the assertion above can fail.
    live = CONTINUED_THEN_COMMENT.replace("*> CALL 'GHOST'", "").replace("           GOBACK.", "           CALL 'GHOST'.")
    assert ("calls", "GHOST") in [(ref.relation, ref.target) for ref in scan_cobol("P.cbl", live).refs]


def test_a_star_gt_inside_a_continued_literal_stays_literal_text_on_both_faces() -> None:
    text = HEAD + f"       01 X PIC X(20) VALUE '{'A' * 30} *> CD\n      -    'EF'.\n" + TAIL
    assert _discovery(text) == _engine(text)
    assert any(kind == "literal" and "*> CD" in value for _l, _c, kind, value in _discovery(text))


# --- residual divergences, pinned ------------------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="RESIDUAL: discovery expandtabs(8)s each line, the engine keeps the tab as one "
                   "column, so token columns differ.  Fixing the engine would change compiler_visible_text; owner decision.")
def test_tab_indented_source_has_one_column_numbering() -> None:
    text = HEAD + "\tDISPLAY 'X'.\n" + TAIL
    assert _discovery(text) == _engine(text)


@pytest.mark.xfail(strict=True, reason="RESIDUAL: the engine splits physical lines on \\n, discovery on str.splitlines() "
                   "(also \\x0b \\x0c \\x1c-\\x1e \\x85 \\u2028 \\u2029 and a lone \\r), so line numbers drift after such a "
                   "character.  Owner decision (changing either face changes positions/output).")
@pytest.mark.parametrize("terminator", ["\x0c", "\x0b", "\x1c", "\x85", " "])
def test_a_unicode_line_separator_does_not_shift_later_line_numbers(terminator: str) -> None:
    text = HEAD + "           DISPLAY 'A'." + terminator + "\n           DISPLAY 'B'.\n" + TAIL
    assert _discovery(text) == _engine(text)


def test_form_feed_on_its_own_line_shifts_discovery_line_numbers_by_one_today() -> None:
    """Witness of the divergence (not an xfail, so the characterisation of *which* face is off is explicit): the
    physical line of PROCEDURE is 5 by ``\\n`` counting (the engine); discovery reports 6."""
    text = HEAD + "\x0c\n" + TAIL
    physical = text.split("\n").index(TAIL.split("\n")[0]) + 1
    procedure = next(t for t in _engine(text) if t[3] == "PROCEDURE")
    assert procedure[0] == physical
    assert next(t for t in _discovery(text) if t[3] == "PROCEDURE")[0] == physical + 1


@pytest.mark.xfail(strict=True, reason="RESIDUAL: a lone \\r (classic Mac line end) is a line break to discovery and "
                   "ordinary text to the engine, which then finds no program and refuses (fail closed, generic message).")
def test_cr_only_line_ends_are_read_identically() -> None:
    text = (HEAD + TAIL).replace("\n", "\r")
    assert _discovery(text) == _engine(text)


def test_cr_only_source_is_refused_not_silently_transformed() -> None:
    text = (HEAD + TAIL).replace("\n", "\r")
    result = TransformationProducer().transform(text, "P")
    assert result.success is False
    # Mutation: the same program with \n line ends transforms.
    assert TransformationProducer().transform(HEAD + TAIL, "P").success is True


@pytest.mark.xfail(strict=True, reason="RESIDUAL (contrived: a continuation line after a closed sentence): a `*>` comment on "
                   "the first line of a continued pair is cut at different points by the two faces.")
def test_a_star_gt_comment_on_the_line_before_a_continuation_is_cut_the_same_way() -> None:
    text = HEAD + "       01 X PIC X(20). *> note\n      -    'EF'.\n" + TAIL
    assert _discovery(text) == _engine(text)


# --- external_dependency_edges keeps its own comment mask: the column-6 star residual -----------------------------------

MQ_LINE = "EXEC MQI GET Q(COMMENTQ) END-EXEC."


def test_a_column_6_star_is_program_text_to_the_reader_but_a_comment_to_external_dependency_edges() -> None:
    """Columns 1-6 are the sequence area and column 7 is the indicator, so ``     *    EXEC MQI ...`` (star in column 6,
    blank column 7) is a code line to the single reader and to the engine parser; ``external_dependency_edges`` masks any
    line whose first non-blank is a star and so reads it as a comment.  The two disagree; the module's own fixture
    (``tests/test_external_dependency_edges.py::COMMENT_AND_LITERAL_TEXT``) relies on the masking, so migrating needs an
    owner decision (see docs/discovery/LAYER4_RESIDUAL_DISPOSITION.md)."""
    from engine.modernization.external_dependency_edges import extract_external_dependency_entries

    col6 = "       PROCEDURE DIVISION.\n     *    " + MQ_LINE + "\n           STOP RUN.\n"
    col7 = col6.replace("     *    ", "      *    ")
    assert any(MQ_LINE in line.text for line in read_source(col6).lines)          # program text to the reader
    assert not any(MQ_LINE in line.text for line in read_source(col7).lines)      # a true comment (column 7)
    assert extract_external_dependency_entries(col6) == ()                        # legacy mask: hidden
    assert extract_external_dependency_entries(col7) == ()                        # both agree on a real comment
    # Mutation: the same statement without any star is extracted, so the equalities above can fail.
    live = col6.replace("     *    ", "          ")
    assert extract_external_dependency_entries(live) != ()

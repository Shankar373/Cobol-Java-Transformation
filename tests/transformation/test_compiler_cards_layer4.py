"""Layer 4: column-1 compiler/library cards never reach the engine's parser input, IR, output or diagnostics.

The token-level parity and the negative (column 8) cases live in ``test_positions_parity_layer4.py``;
these tests prove the end-to-end effect through the producer.
"""

from __future__ import annotations

import pytest

from engine.transformation.producer import TransformationProducer
from engine.transformation.source_format import compiler_visible_text

PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. P.\n"
    "       PROCEDURE DIVISION.\n"
    "           GOBACK.\n"
)
CARD_LINES = {
    "CBL": "CBL ARITH(EXTEND),DYNAM\n",
    "PROCESS": "PROCESS NODISPLAY\n",
    "-INC": "-INC COPYLIB\n",
    "++INCLUDE": "++INCLUDE COPYLIB\n",
    "%INCLUDE": "%INCLUDE COPYLIB\n",
}
CARD_WORDS = ("ARITH", "DYNAM", "NODISPLAY", "COPYLIB")


@pytest.mark.parametrize("kind", sorted(CARD_LINES))
def test_a_column_1_card_changes_nothing_the_engine_reads_or_produces(kind: str):
    carded = CARD_LINES[kind] + PROGRAM
    visible = compiler_visible_text(carded).split("\n")
    assert visible[0] == ""                                  # the card line is dropped, the line count is kept
    assert visible[1:] == compiler_visible_text(PROGRAM).split("\n")
    with_card = TransformationProducer().transform(carded, "P")
    without = TransformationProducer().transform(PROGRAM, "P")
    assert with_card.success and without.success
    assert with_card.generated_files == without.generated_files
    assert with_card.diagnostics == without.diagnostics
    blob = " ".join(f"{d.message} {d.location}" for d in with_card.diagnostics) + " ".join(with_card.errors)
    assert not any(word in blob for word in CARD_WORDS)


@pytest.mark.parametrize("kind", sorted(CARD_LINES))
def test_the_same_text_in_column_8_is_program_text_and_stays_visible(kind: str):
    """Mutation: moving the card out of column 1 makes it text again, so the cards test above is not vacuous."""
    indented = "       " + CARD_LINES[kind]
    assert compiler_visible_text(indented + PROGRAM).split("\n")[0] == indented.rstrip("\n")


# --- free-format files: a column-1 card is still a card (regression found by the Phase 0 review) --------------------

FREE_PROGRAM = (
    ">>SOURCE FORMAT FREE\n"
    "IDENTIFICATION DIVISION.\n"
    "PROGRAM-ID. P.\n"
    "PROCEDURE DIVISION.\n"
    "    GOBACK.\n"
)


@pytest.mark.parametrize("kind", ["CBL", "PROCESS", "-INC", "++INCLUDE", "%INCLUDE"])
def test_a_free_format_column_1_card_is_a_discovery_fact_and_never_engine_text(kind: str):
    from enterprise.discovery.cobol_text import read_source
    from enterprise.discovery.scan_cobol import scan_cobol

    carded = ">>SOURCE FORMAT FREE\n" + CARD_LINES[kind] + FREE_PROGRAM.split("\n", 1)[1]
    read = read_source(carded)
    assert [(c.line, c.keyword) for c in read.cards] == [(2, kind)]          # the reader names the card
    assert all("COPYLIB" not in line.text and "ARITH" not in line.text for line in read.lines)
    scan = scan_cobol("p.cbl", carded)
    if kind in ("CBL", "PROCESS"):
        assert {f.category for f in scan.facts} >= {"compiler-option"}        # recorded as a fact, as in fixed format
    else:
        assert [(r.relation, r.target) for r in scan.refs if r.relation == "copies"] == [("copies", "COPYLIB")]
    visible = compiler_visible_text(carded).split("\n")
    assert visible[1] == ""                                                    # the engine drops it too (same reader)
    assert not read_source(FREE_PROGRAM).cards                                 # mutation: no card line, no card

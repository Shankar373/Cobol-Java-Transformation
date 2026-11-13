"""The data-description clauses that change storage size are recorded, not dropped (ADR-0009).

``SIGN ... SEPARATE`` adds a byte, ``SYNCHRONIZED`` adds alignment padding, ``JUSTIFIED``
changes how a value is placed.  The parser used to drop all three, so nothing downstream could
tell that a layout derived from the IR would be wrong.  They are now recorded on ``DataItem``;
lowering does not use them (defaults reproduce the previous IR exactly).
Dependency-free (pytest only).
"""
from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser


def item(entry: str):
    items = CobolParser().parse_data_description_lines([f"       01 {entry}"])
    assert len(items) == 1
    return items[0]


def test_an_item_with_none_of_the_clauses_keeps_the_defaults():
    it = item("PLAIN PIC S9(4).")
    assert (it.sign_position, it.sign_separate, it.synchronized, it.justified) == ("", False, False, False)


@pytest.mark.parametrize("clause,position,separate", [
    ("SIGN IS LEADING", "LEADING", False),
    ("SIGN LEADING", "LEADING", False),
    ("SIGN IS TRAILING", "TRAILING", False),
    ("SIGN TRAILING", "TRAILING", False),
    ("SIGN IS LEADING SEPARATE", "LEADING", True),
    ("SIGN IS LEADING SEPARATE CHARACTER", "LEADING", True),
    ("SIGN IS TRAILING SEPARATE CHARACTER", "TRAILING", True),
    ("LEADING SEPARATE", "LEADING", True),
    ("TRAILING SEPARATE CHARACTER", "TRAILING", True),
])
def test_sign_clause_forms_are_recorded(clause, position, separate):
    it = item(f"AMT PIC S9(5) {clause}.")
    assert it.sign_position == position and it.sign_separate is separate


@pytest.mark.parametrize("clause", ["SYNC", "SYNCHRONIZED", "SYNC LEFT", "SYNCHRONIZED RIGHT"])
def test_synchronized_forms_are_recorded(clause):
    assert item(f"CNT PIC S9(4) COMP {clause}.").synchronized is True


@pytest.mark.parametrize("clause", ["JUSTIFIED RIGHT", "JUST RIGHT", "JUSTIFIED"])
def test_justified_forms_are_recorded(clause):
    assert item(f"NAME PIC X(10) {clause}.").justified is True


def test_clause_words_inside_a_value_literal_are_not_clauses():
    it = item("TEXT PIC X(20) VALUE 'SIGN IS LEADING SEPARATE SYNC JUSTIFIED'.")
    assert (it.sign_position, it.sign_separate, it.synchronized, it.justified) == ("", False, False, False)


def test_clause_words_that_are_part_of_a_longer_name_are_not_clauses():
    it = item("RESYNC-FLAG PIC X.")
    assert it.synchronized is False and it.name == "RESYNC-FLAG"


def test_clauses_combine_with_usage_and_each_other():
    it = item("TOTAL PIC S9(7)V99 COMP-3 SYNC.")
    assert it.usage == "COMP-3" and it.synchronized is True
    both = item("AMT PIC S9(5) SIGN IS TRAILING SEPARATE CHARACTER JUSTIFIED RIGHT.")
    assert both.sign_position == "TRAILING" and both.sign_separate and both.justified


def test_group_children_carry_their_own_clauses():
    items = CobolParser().parse_data_description_lines([
        "       01 REC.",
        "          05 A PIC S9(3) SIGN IS LEADING SEPARATE.",
        "          05 B PIC S9(3).",
    ])
    a, b = items[0].children
    assert a.sign_separate is True and b.sign_separate is False

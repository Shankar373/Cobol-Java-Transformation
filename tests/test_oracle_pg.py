"""Roadmap unit 12: hermetic checks of the OCESQL + PostgreSQL reference runner's helpers.

The runs themselves need Docker and are in ``tests/integration/test_ocesql_pg_oracle.py``.
"""

from __future__ import annotations

import pytest

from engine.sql.oracle_pg import dump_command, state_hash, with_banner

BARE = (
    "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
    "       PROCEDURE DIVISION.\n           STOP RUN.\n"
)


def test_banner_is_inserted_before_procedure_division():
    assert with_banner(BARE) == (
        "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n      *\n"
        "       PROCEDURE DIVISION.\n           STOP RUN.\n")


def test_an_existing_comment_line_is_kept_and_nothing_is_added_twice():
    once = with_banner(BARE)
    assert with_banner(once) == once


def test_a_source_without_procedure_division_is_left_alone():
    assert with_banner("       DATA DIVISION.\n") == "       DATA DIVISION.\n"


def test_state_hash_is_stable_and_order_sensitive():
    state = ("--ACCT", "1|ALICE|1.00")
    assert state_hash(state) == state_hash(state)
    assert state_hash(state) != state_hash(tuple(reversed(state)))
    assert len(state_hash(state)) == 64


def test_dump_command_orders_rows_as_text_per_table():
    command = dump_command(("ACCT", "LOG"))
    assert "echo '--ACCT'" in command and "echo '--LOG'" in command
    assert "order by t::text" in command


@pytest.mark.parametrize("name", ["acct; drop table x", "1abc", "a-b", ""])
def test_table_names_that_are_not_plain_identifiers_are_refused(name):
    with pytest.raises(ValueError, match="plain identifier"):
        dump_command((name,))

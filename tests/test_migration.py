"""Roadmap unit 13: record layout, decoding, load SQL and reconciliation (hermetic).

The load into a real PostgreSQL and the read-back are in ``tests/integration/test_migration_postgres.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from engine.sql.migration import (
    FIELD_SEPARATOR,
    MigrationError,
    canonical,
    columns_from_record,
    create_table_sql,
    decode_records,
    dump_query,
    load_sql,
    parse_dump,
    reconcile,
    record_width,
)
from engine.transformation.cobol_parser import CobolParser

SOURCE = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n       01 ACCT-REC.\n"
    "          05 ACCT-ID   PIC 9(4).\n          05 ACCT-NAME PIC X(8).\n"
    "          05 ACCT-BAL  PIC 9(7)V99.\n"
    "       PROCEDURE DIVISION.\n       MAIN.\n           STOP RUN.\n"
)


def _columns():
    program = CobolParser().parse(SOURCE)
    return columns_from_record(program.working_storage[0])


COLUMNS = _columns()
TEXT = "0001ALICE   000012345\n0002BOB     000000100\n"


class TestLayout:
    def test_columns_offsets_and_types(self):
        assert [(c.name, c.offset, c.width, str(c.sql_type)) for c in COLUMNS] == [
            ("acct_id", 0, 4, "DECIMAL(4,0)"),
            ("acct_name", 4, 8, "CHAR(8)"),
            ("acct_bal", 12, 9, "DECIMAL(9,2)"),
        ]
        assert record_width(COLUMNS) == 21

    def test_create_table_for_postgresql(self):
        assert create_table_sql("acct", COLUMNS, ("acct_id",)) == (
            "CREATE TABLE acct (acct_id NUMERIC(4,0) NOT NULL, acct_name CHAR(8) NOT NULL, "
            "acct_bal NUMERIC(9,2) NOT NULL, PRIMARY KEY (acct_id));")

    def test_a_key_outside_the_layout_is_refused(self):
        with pytest.raises(MigrationError, match="key"):
            create_table_sql("acct", COLUMNS, ("nope",))

    @pytest.mark.parametrize("pic,fragment", [
        ("PIC S9(4)", "signed DISPLAY"),
        ("PIC 9(4) COMP-3", "USAGE COMP-3"),
        ("PIC 9(4) COMP", "USAGE COMP"),
    ])
    def test_encodings_without_a_certified_byte_layout_are_refused(self, pic, fragment):
        source = SOURCE.replace("PIC 9(4).", pic + ".")
        record = CobolParser().parse(source).working_storage[0]
        with pytest.raises(MigrationError, match=fragment):
            columns_from_record(record)

    def test_nested_groups_occurs_and_reserved_names_are_refused(self):
        grouped = SOURCE.replace("          05 ACCT-NAME PIC X(8).\n",
                                 "          05 SUB.\n             10 X1 PIC X(2).\n")
        with pytest.raises(MigrationError, match="nested group"):
            columns_from_record(CobolParser().parse(grouped).working_storage[0])
        reserved = SOURCE.replace("ACCT-NAME", "ORDER")
        with pytest.raises(MigrationError, match="reserved"):
            columns_from_record(CobolParser().parse(reserved).working_storage[0])


class TestDecodeAndLoad:
    def test_decode_keeps_padding_and_applies_the_implied_decimal(self):
        rows = decode_records(TEXT, COLUMNS)
        assert rows == [
            (Decimal("1"), "ALICE   ", Decimal("123.45")),
            (Decimal("2"), "BOB     ", Decimal("1.00")),
        ]

    def test_a_record_of_the_wrong_width_is_refused(self):
        with pytest.raises(MigrationError, match="record 1 is 5 characters"):
            decode_records("short\n", COLUMNS)

    def test_a_non_digit_in_a_numeric_field_is_refused(self):
        with pytest.raises(MigrationError, match="not unsigned digits"):
            decode_records("00X1ALICE   000012345\n", COLUMNS)

    def test_load_sql_is_exact_and_escapes_quotes(self):
        rows = [(Decimal("3"), "O'NEIL  ", Decimal("0.05"))]
        assert load_sql("acct", rows, COLUMNS) == (
            "INSERT INTO acct (acct_id, acct_name, acct_bal) VALUES (3, 'O''NEIL  ', 0.05);")

    def test_dump_query_restores_char_width_and_spells_out_nulls(self):
        query = dump_query("acct", COLUMNS, ("acct_id",))
        assert "rpad(acct_name::text, 8)" in query and "<NULL>" in query
        assert query.endswith("ORDER BY acct_id;")

    def test_parse_dump_round_trips_canonical_rows(self):
        rows = decode_records(TEXT, COLUMNS)
        lines = [canonical(COLUMNS, r) for r in rows]
        assert parse_dump(lines, COLUMNS) == rows

    def test_parse_dump_refuses_a_row_with_the_wrong_field_count(self):
        with pytest.raises(MigrationError, match="fields"):
            parse_dump(["1" + FIELD_SEPARATOR + "x"], COLUMNS)


class TestReconcile:
    def _source(self):
        return decode_records(TEXT, COLUMNS)

    def test_identical_data_reconciles(self):
        report = reconcile(self._source(), self._source(), COLUMNS, ("acct_id",))
        assert report.ok and report.source_count == report.target_count == 2
        assert report.source_totals == {"acct_id": Decimal("3"), "acct_bal": Decimal("124.45")}
        assert report.source_digest == report.target_digest

    def test_a_changed_value_is_named_down_to_the_column(self):
        target = self._source()
        target[0] = (Decimal("1"), "ALICE   ", Decimal("123.46"))
        report = reconcile(self._source(), target, COLUMNS, ("acct_id",))
        assert not report.ok
        assert [(m.key, m.column, m.source, m.target) for m in report.mismatches] == [
            ((Decimal("1"),), "acct_bal", "123.45", "123.46")]
        assert report.source_totals != report.target_totals

    def test_a_missing_and_an_extra_row_are_reported(self):
        target = self._source()[:1] + [(Decimal("9"), "ZED     ", Decimal("0.00"))]
        report = reconcile(self._source(), target, COLUMNS, ("acct_id",))
        assert not report.ok
        assert report.missing_in_target == ((Decimal("2"),),)
        assert report.extra_in_target == ((Decimal("9"),),)

    def test_padding_is_data_and_a_trimmed_value_is_a_mismatch(self):
        target = self._source()
        target[0] = (Decimal("1"), "ALICE", Decimal("123.45"))
        report = reconcile(self._source(), target, COLUMNS, ("acct_id",))
        assert not report.ok and report.mismatches[0].column == "acct_name"

    def test_a_duplicate_key_on_either_side_fails_the_report(self):
        doubled = self._source() + self._source()[:1]
        assert not reconcile(doubled, self._source(), COLUMNS, ("acct_id",)).ok
        assert reconcile(doubled, self._source(), COLUMNS, ("acct_id",)).duplicate_source_keys
        assert reconcile(self._source(), doubled, COLUMNS, ("acct_id",)).duplicate_target_keys

    def test_a_null_in_the_target_is_a_mismatch_not_a_zero(self):
        target = self._source()
        target[1] = (Decimal("2"), "BOB     ", None)
        report = reconcile(self._source(), target, COLUMNS, ("acct_id",))
        assert not report.ok and report.mismatches[0].target == "<NULL>"

    def test_the_digest_does_not_depend_on_row_order(self):
        reversed_rows = list(reversed(self._source()))
        assert reconcile(self._source(), reversed_rows, COLUMNS, ("acct_id",)).ok

    def test_reconciliation_needs_a_key(self):
        with pytest.raises(MigrationError, match="key"):
            reconcile([], [], COLUMNS, ())

"""Roadmap unit 11: DatabaseDialect (DB2 source, PostgreSQL target).

Table-driven checks of the type map, the SQL rewriter, host-variable binding, the SQLSTATE ->
SQLCODE mapper and the refusals.  These pin the dialect's documented rules; running the rewritten
SQL against a real PostgreSQL (and DB2) is roadmap unit 12 and is not claimed here.
"""

from __future__ import annotations

import pytest

from engine.sql.database_dialect import (
    BindVariable,
    DatabaseDialect,
    SqlType,
    available_dialects,
    cobol_to_sql_type,
    dialect_for,
    parse_db2_type,
    register_dialect,
)

PG = dialect_for("postgresql")
DB2 = dialect_for("db2")


class TestRegistry:
    def test_db2_and_postgresql_are_registered(self):
        assert available_dialects() == ("db2", "postgresql")

    def test_lookup_is_case_insensitive(self):
        assert dialect_for("PostgreSQL") is PG

    def test_unknown_dialect_fails_closed_naming_the_choices(self):
        with pytest.raises(ValueError, match="available: db2, postgresql"):
            dialect_for("oracle")

    def test_a_name_registers_once(self):
        with pytest.raises(ValueError, match="already registered"):
            register_dialect(PG)

    def test_a_new_dialect_plugs_in(self):
        class Fake(DatabaseDialect):
            name = "fakedb-unit-test"

            def column_type(self, sql_type):
                return "X"

            def java_type(self, sql_type):
                return "Object"

            def _translate(self, sql, issues, notes):
                return sql.replace("FETCH FIRST 1 ROW ONLY", "TOP 1")

            def map_status(self, sqlstate, message=""):
                return DB2.map_status(sqlstate, message)

        register_dialect(Fake())
        assert dialect_for("fakedb-unit-test").rewrite("SELECT A FETCH FIRST 1 ROW ONLY").sql.endswith("TOP 1")


class TestTypes:
    @pytest.mark.parametrize("text,expected", [
        ("DECIMAL(9,2)", SqlType("DECIMAL", precision=9, scale=2)),
        ("dec(7)", SqlType("DECIMAL", precision=7, scale=0)),
        ("NUMERIC(5,1)", SqlType("DECIMAL", precision=5, scale=1)),
        ("DECIMAL", SqlType("DECIMAL", precision=5, scale=0)),
        ("INT", SqlType("INTEGER")),
        ("CHARACTER(8)", SqlType("CHAR", length=8)),
        ("VARCHAR(40)", SqlType("VARCHAR", length=40)),
        ("TIMESTAMP", SqlType("TIMESTAMP")),
        ("DOUBLE PRECISION", SqlType("DOUBLE")),
    ])
    def test_parse(self, text, expected):
        assert parse_db2_type(text) == expected

    @pytest.mark.parametrize("text", ["XML", "GRAPHIC(4)", "DECIMAL(32,2)", "DECIMAL(5,6)", "VARCHAR", "INTEGER(4)", "??"])
    def test_types_outside_the_map_are_refused(self, text):
        with pytest.raises(ValueError):
            parse_db2_type(text)

    @pytest.mark.parametrize("text,ddl,java", [
        ("DECIMAL(9,2)", "NUMERIC(9,2)", "java.math.BigDecimal"),
        ("INTEGER", "INTEGER", "int"),
        ("SMALLINT", "SMALLINT", "short"),
        ("BIGINT", "BIGINT", "long"),
        ("CHAR(3)", "CHAR(3)", "String"),
        ("VARCHAR(20)", "VARCHAR(20)", "String"),
        ("DATE", "DATE", "java.time.LocalDate"),
        ("TIME", "TIME", "java.time.LocalTime"),
        ("TIMESTAMP", "TIMESTAMP(6)", "java.time.LocalDateTime"),
        ("DOUBLE", "DOUBLE PRECISION", "double"),
        ("CLOB", "TEXT", "String"),
        ("BLOB", "BYTEA", "byte[]"),
    ])
    def test_postgresql_column_and_java_types(self, text, ddl, java):
        sql_type = parse_db2_type(text)
        assert PG.column_type(sql_type) == ddl
        assert PG.java_type(sql_type) == java

    def test_decimal_is_never_a_floating_type(self):
        for dialect in (DB2, PG):
            assert dialect.java_type(parse_db2_type("DECIMAL(15,3)")) == "java.math.BigDecimal"

    def test_db2_keeps_its_own_spelling(self):
        assert DB2.column_type(parse_db2_type("DECIMAL(9,2)")) == "DECIMAL(9,2)"

    @pytest.mark.parametrize("kwargs,expected", [
        (dict(digits=4, usage="COMP"), "SMALLINT"),
        (dict(digits=9, usage="COMP"), "INTEGER"),
        (dict(digits=18, usage="BINARY"), "BIGINT"),
        (dict(digits=9, scale=2, usage="COMP-3"), "DECIMAL(9,2)"),
        (dict(digits=7), "DECIMAL(7,0)"),
        (dict(alphanumeric_length=30), "CHAR(30)"),
        (dict(alphanumeric_length=30, varying=True), "VARCHAR(30)"),
    ])
    def test_dclgen_style_mapping(self, kwargs, expected):
        assert str(cobol_to_sql_type(**kwargs)) == expected

    @pytest.mark.parametrize("kwargs", [dict(digits=19, usage="COMP"), dict(digits=32), dict()])
    def test_dclgen_refusals(self, kwargs):
        with pytest.raises(ValueError):
            cobol_to_sql_type(**kwargs)


class TestRewrite:
    def test_host_variables_become_positional_markers_in_source_order(self):
        result = PG.rewrite(
            "SELECT NAME, BAL INTO :WS-NAME, :WS-BAL:WS-IND FROM ACCT WHERE ID = :WS-ID AND T = :WS-T")
        assert result.sql == "SELECT NAME, BAL INTO ?, ? FROM ACCT WHERE ID = ? AND T = ?"
        assert result.binds == (
            BindVariable("WS-NAME"), BindVariable("WS-BAL", "WS-IND"),
            BindVariable("WS-ID"), BindVariable("WS-T"))
        assert result.ok

    def test_db2_dialect_keeps_the_text_and_binds(self):
        result = DB2.rewrite("SELECT A FROM T WHERE K = :K FETCH FIRST 5 ROWS ONLY;")
        assert result.sql == "SELECT A FROM T WHERE K = ? FETCH FIRST 5 ROWS ONLY"
        assert result.binds == (BindVariable("K"),)

    def test_a_colon_inside_a_literal_is_not_a_host_variable(self):
        result = PG.rewrite("SELECT A FROM T WHERE N = ':NOT-A-HOST' AND K = :K")
        assert result.sql == "SELECT A FROM T WHERE N = ':NOT-A-HOST' AND K = ?"
        assert [b.name for b in result.binds] == ["K"]

    @pytest.mark.parametrize("db2,pg", [
        ("SELECT A FROM T FETCH FIRST 10 ROWS ONLY", "SELECT A FROM T LIMIT 10"),
        ("SELECT A FROM T FETCH FIRST ROW ONLY", "SELECT A FROM T LIMIT 1"),
        ("SELECT A FROM T ORDER BY A FETCH FIRST 3 ROWS ONLY", "SELECT A FROM T ORDER BY A LIMIT 3"),
        ("SELECT NVL(A, 0) FROM T", "SELECT COALESCE(A, 0) FROM T"),
        ("SELECT VALUE(A, 0) FROM T", "SELECT COALESCE(A, 0) FROM T"),
        ("UPDATE T SET D = CURRENT DATE", "UPDATE T SET D = CURRENT_DATE"),
        ("UPDATE T SET D = CURRENT TIMESTAMP", "UPDATE T SET D = CURRENT_TIMESTAMP"),
        ("SELECT CURRENT TIME FROM T", "SELECT CURRENT_TIME FROM T"),
    ])
    def test_db2_constructs_are_translated(self, db2, pg):
        result = PG.rewrite(db2)
        assert result.sql == pg and result.ok

    def test_text_inside_a_literal_is_never_rewritten(self):
        result = PG.rewrite("SELECT 'CURRENT DATE NVL( FETCH FIRST 1 ROW ONLY' FROM T")
        assert result.sql == "SELECT 'CURRENT DATE NVL( FETCH FIRST 1 ROW ONLY' FROM T"

    def test_isolation_clause_is_dropped_with_a_note(self):
        result = PG.rewrite("SELECT A FROM T WITH UR")
        assert result.sql == "SELECT A FROM T"
        assert any("UR is strengthened" in n for n in result.notes) and result.ok

    def test_a_cte_called_cs_is_not_an_isolation_clause(self):
        assert PG.rewrite("WITH CS AS (SELECT 1 FROM T) SELECT * FROM CS").sql.startswith("WITH CS AS")

    def test_for_read_only_is_dropped_with_a_note(self):
        result = PG.rewrite("SELECT A FROM T FOR READ ONLY")
        assert result.sql == "SELECT A FROM T" and result.notes

    @pytest.mark.parametrize("sql,fragment", [
        ("SELECT A FROM T FETCH FIRST 3 ROWS ONLY WITH TIES", "WITH TIES"),
        ("SELECT DAYS(D) FROM T", "scalar function"),
        ("SELECT A FROM T FOR UPDATE OF A", "FOR UPDATE OF"),
        ("SELECT A FROM T USING CCSID 1208", "CCSID"),
    ])
    def test_untranslatable_constructs_are_blocking_issues(self, sql, fragment):
        result = PG.rewrite(sql)
        assert not result.ok and any(fragment in i for i in result.issues)

    def test_rewriting_is_deterministic(self):
        sql = "SELECT NVL(A,0) FROM T WHERE K = :K FETCH FIRST 2 ROWS ONLY WITH CS"
        assert PG.rewrite(sql) == PG.rewrite(sql)


class TestStatusMapping:
    @pytest.mark.parametrize("sqlstate,code,db2_state", [
        ("00000", 0, "00000"),
        ("02000", 100, "02000"),
        ("21000", -811, "21000"),
        ("23505", -803, "23505"),
        ("23503", -530, "23503"),
        ("23502", -407, "23502"),
        ("22001", -302, "22001"),
        ("22003", -413, "22003"),
        ("22012", -802, "22012"),
        ("42P01", -204, "42704"),
        ("42703", -206, "42703"),
        ("42601", -104, "42601"),
        ("40001", -911, "40001"),
        ("40P01", -911, "40001"),
        ("55P03", -913, "57033"),
    ])
    def test_documented_mappings(self, sqlstate, code, db2_state):
        status = PG.map_status(sqlstate)
        assert (status.sqlcode, status.sqlstate) == (code, db2_state)

    def test_an_unknown_sqlstate_is_an_explicit_unmapped_error_never_success(self):
        status = PG.map_status("XX000", "internal error")
        assert status.is_error and status.sqlcode == -1 and "internal error" in status.message

    def test_success_and_no_data_categories(self):
        assert PG.map_status("00000").is_success
        assert PG.map_status("02000").is_no_data

    def test_both_dialects_share_the_status_table(self):
        assert DB2.map_status("23505") == PG.map_status("23505")

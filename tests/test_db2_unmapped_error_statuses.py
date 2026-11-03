r"""BL-060: unmapped controlled-database failures must return a well-formed status.

The old error handlers built ``Db2SqlStatus(sqlstate="")``, which fails
``__post_init__`` (5-char requirement) — so every IntegrityError outside
the UNIQUE mapping and every OperationalError crashed the *handler*
itself with a ``ValueError`` instead of reporting the failure
(Phase 6 audit probes A2/B, ``%TEMP%\opencode\phase6\audit_probes.txt``).

The sentinel contract (documented in ``engine.sql.status``): SQLCODE -1
is a *lane* sentinel — not a DB2-documented code in this modeled subset —
marking "unclassified failure on the controlled database"; SQLSTATE
'56000' sits in DB2 class 56 (internal error processing) and is used as
the lane's unmapped placeholder. It does NOT claim the exact DB2 SQLSTATE
for the specific condition.
"""

from __future__ import annotations

from engine.sql.execution import Db2ControlledDatabase
from engine.sql.status import (
    SQLCODE_DUPLICATE_KEY,
    SQLCODE_UNMAPPED_ERROR,
    SQLSTATE_DUPLICATE_KEY,
    SQLSTATE_UNMAPPED_ERROR,
    Db2SqlStatus,
)
from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.transformation.sql_parser import SqlParser

_ANALYZER = Db2SemanticAnalyzer()
_PARSER = SqlParser()


def _exec(db: Db2ControlledDatabase, sql: str, bindings=None):
    stmt = _ANALYZER.analyze_statement(_PARSER.parse_embedded_sql(sql).statements[0])
    return db.execute(stmt, bindings=bindings)


class TestUnmappedIntegrityViolations:
    def test_not_null_violation_returns_unmapped_error_status_not_a_handler_crash(self):
        db = Db2ControlledDatabase(
            "CREATE TABLE ACCOUNT (ACCT INTEGER NOT NULL, BAL INTEGER)"
        )
        result = _exec(db, "INSERT INTO ACCOUNT (ACCT, BAL) VALUES (NULL, 5)")
        assert result.status.is_error
        assert result.status.sqlcode == SQLCODE_UNMAPPED_ERROR
        assert result.status.sqlstate == SQLSTATE_UNMAPPED_ERROR
        assert "NOT NULL" in result.status.message
        assert "outside the mapped subset" in result.note
        db.close()

    def test_unique_violation_still_maps_to_duplicate_key_control(self):
        db = Db2ControlledDatabase(
            "CREATE TABLE ACCOUNT (ACCT INTEGER PRIMARY KEY, BAL INTEGER)"
        )
        first = _exec(db, "INSERT INTO ACCOUNT (ACCT, BAL) VALUES (1, 10)")
        assert first.status.is_success
        second = _exec(db, "INSERT INTO ACCOUNT (ACCT, BAL) VALUES (1, 20)")
        assert second.status.sqlcode == SQLCODE_DUPLICATE_KEY
        assert second.status.sqlstate == SQLSTATE_DUPLICATE_KEY
        db.close()


class TestUnmappedOperationalErrors:
    def test_missing_table_returns_unmapped_error_status(self):
        db = Db2ControlledDatabase()
        result = _exec(db, "SELECT ACCT FROM NO_SUCH_TABLE")
        assert result.status.is_error
        assert result.status.sqlcode == SQLCODE_UNMAPPED_ERROR
        assert result.status.sqlstate == SQLSTATE_UNMAPPED_ERROR
        assert "NO_SUCH_TABLE" in result.status.message
        assert "operational error" in result.note
        db.close()


class TestSentinelValuesAreExplicitConstants:
    def test_sentinel_carries_the_documented_lane_values(self):
        status = Db2SqlStatus.unmapped_error("boom")
        assert status.sqlcode == -1
        assert status.sqlstate == "56000"
        assert status.category.value == "ERROR"
        assert status.is_error

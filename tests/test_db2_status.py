"""Tests for DB2 SQLCODE / SQLSTATE status semantics (engine/sql/status).

The constants are DB2-documented (syntax/semantic domain).  A controlled
test database reproducing them at the status boundary does NOT prove DB2
runtime equivalence.
"""

from __future__ import annotations

from engine.sql.status import (
    DELETE_STATUSES,
    DML_STATUSES,
    SINGLETON_SELECT_STATUSES,
    SQLCODE_DUPLICATE_KEY,
    SQLCODE_NO_DATA,
    SQLCODE_SUCCESS,
    SQLCODE_TOO_MANY_ROWS,
    SQLSTATE_DUPLICATE_KEY,
    SQLSTATE_NO_DATA,
    SQLSTATE_SUCCESS,
    SQLSTATE_TOO_MANY_ROWS,
    Db2SqlCodeCategory,
    Db2SqlStatus,
    classify_sqlcode,
)


class TestConstants:
    def test_documented_sqlcodes(self):
        assert SQLCODE_SUCCESS == 0
        assert SQLCODE_NO_DATA == 100
        assert SQLCODE_TOO_MANY_ROWS == -811
        assert SQLCODE_DUPLICATE_KEY == -803

    def test_documented_sqlstates(self):
        assert SQLSTATE_SUCCESS == "00000"
        assert SQLSTATE_NO_DATA == "02000"
        assert SQLSTATE_TOO_MANY_ROWS == "21000"
        assert SQLSTATE_DUPLICATE_KEY == "23505"


class TestClassification:
    def test_success(self):
        assert classify_sqlcode(0) is Db2SqlCodeCategory.SUCCESS

    def test_no_data(self):
        assert classify_sqlcode(100) is Db2SqlCodeCategory.NO_DATA

    def test_errors(self):
        assert classify_sqlcode(-811) is Db2SqlCodeCategory.ERROR
        assert classify_sqlcode(-803) is Db2SqlCodeCategory.ERROR

    def test_positive_warning_not_random_error(self):
        # DB2: positive codes are warnings/informational; only 100 is modeled.
        assert classify_sqlcode(162) is Db2SqlCodeCategory.SUCCESS


class TestStatusObject:
    def test_success_factory(self):
        status = Db2SqlStatus.success()
        assert (status.sqlcode, status.sqlstate) == (0, "00000")
        assert status.is_success and not status.is_error and not status.is_no_data

    def test_no_data_factory(self):
        status = Db2SqlStatus.no_data()
        assert (status.sqlcode, status.sqlstate) == (100, "02000")
        assert status.is_no_data and not status.is_success

    def test_too_many_rows_factory(self):
        status = Db2SqlStatus.too_many_rows()
        assert (status.sqlcode, status.sqlstate) == (-811, "21000")
        assert status.is_error

    def test_duplicate_key_factory(self):
        status = Db2SqlStatus.duplicate_key()
        assert (status.sqlcode, status.sqlstate) == (-803, "23505")
        assert status.is_error

    def test_validation_of_fields(self):
        import pytest

        with pytest.raises(TypeError):
            Db2SqlStatus(sqlcode="0")
        with pytest.raises(ValueError):
            Db2SqlStatus(sqlstate="0000")


class TestStatusSets:
    def test_singleton_select_set(self):
        assert sorted(s.sqlcode for s in SINGLETON_SELECT_STATUSES) == [-811, 0, 100]

    def test_dml_set_excludes_no_data(self):
        assert not any(s.sqlcode == 100 for s in DML_STATUSES)
        assert any(s.sqlcode == -803 for s in DML_STATUSES)

    def test_delete_set_has_no_duplicate_key(self):
        assert [s.sqlcode for s in DELETE_STATUSES] == [0]
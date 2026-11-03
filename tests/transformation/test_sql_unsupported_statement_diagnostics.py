"""BL-080: unsupported EXEC SQL statements are preserved and diagnosed.

The SQL lane's own doctrine (``db2_sqlite.py``): "It never silently drops
semantics." The old parser's dispatch loop had no else-branch, so whole
statements (``BEGIN DECLARE SECTION``, ``INCLUDE SQLCA``, ``WHENEVER …``,
``DECLARE … STATEMENT``) vanished with no record, and ``EXECUTE IMMEDIATE``
was classified as plain ``EXECUTE`` with its IR flag never set.
"""

from __future__ import annotations

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.transformation.ir import SqlStatementType
from engine.transformation.sql_parser import SqlParser

_PARSER = SqlParser()

UNSUPPORTED_BLOCK = """\
BEGIN DECLARE SECTION;
INCLUDE SQLCA;
WHENEVER NOT FOUND CONTINUE;
DECLARE STMT1 STATEMENT FOR SELECT ACCT FROM ACCOUNT;
SELECT ACCT FROM ACCOUNT;
"""


class TestUnsupportedStatementsArePreserved:
    def test_every_unsupported_statement_text_is_kept_on_the_block(self):
        block = _PARSER.parse_embedded_sql(UNSUPPORTED_BLOCK)
        preserved = [t.strip().splitlines()[0] for t in block.unsupported_statements]
        # Note (honesty): texts are delimiter-stripped exactly like
        # raw_sql for parsed statements (the shared splitter removes the
        # top-level ';'); the red capture in bl080_pre_fix.txt included
        # this test's own wrong ';' expectation before it was corrected.
        assert preserved == [
            "BEGIN DECLARE SECTION",
            "INCLUDE SQLCA",
            "WHENEVER NOT FOUND CONTINUE",
            "DECLARE STMT1 STATEMENT FOR SELECT ACCT FROM ACCOUNT",
        ]

    def test_supported_statements_alongside_unsupported_ones_still_parse(self):
        block = _PARSER.parse_embedded_sql(UNSUPPORTED_BLOCK)
        assert len(block.statements) == 1
        assert block.statements[0].statement_type == SqlStatementType.SELECT

    def test_fully_supported_block_has_no_unsupported_statements(self):
        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT; COMMIT;"
        )
        assert block.unsupported_statements == ()

    def test_recognized_statement_with_unparsable_text_is_not_dropped(self):
        # A SELECT without FROM cannot be modeled: the text must survive
        # in the unsupported channel instead of vanishing.
        block = _PARSER.parse_embedded_sql("SELECT :WS-COUNT")
        assert block.statements == ()
        assert len(block.unsupported_statements) == 1
        assert "SELECT :WS-COUNT" in block.unsupported_statements[0]


class TestUnsupportedStatementsReachAnalyzerDiagnostics:
    def test_analyzer_validation_reports_each_unsupported_statement(self):
        block = _PARSER.parse_embedded_sql(UNSUPPORTED_BLOCK)
        model = Db2SemanticAnalyzer().analyze_program("PROG1", (block,))
        messages = [v for v in model.validation if "unsupported SQL" in v]
        assert len(messages) == 4
        assert any("WHENEVER NOT FOUND CONTINUE" in m for m in messages)

    def test_clean_program_stays_free_of_unsupported_diagnostics(self):
        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT; INSERT INTO ACCOUNT (ACCT) VALUES (1);"
        )
        model = Db2SemanticAnalyzer().analyze_program("PROG1", (block,))
        assert model.validation == ()


class TestExecuteImmediateFlag:
    def test_execute_immediate_sets_the_ir_flag(self):
        block = _PARSER.parse_embedded_sql("EXECUTE IMMEDIATE :SQL-TEXT")
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.EXECUTE
        assert stmt.execute_immediate is True

    def test_plain_execute_keeps_the_flag_false(self):
        block = _PARSER.parse_embedded_sql("EXECUTE STMT1")
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.EXECUTE
        assert stmt.execute_immediate is False

"""BL-055: lowercase PERFORM UNTIL/VARYING must parse like uppercase.

`_parse_perform` guards with `" UNTIL " in upper` but splits the
original-case line (`line.split(" UNTIL ", 1)[1]`), so a lowercase
`perform … until …` raises `IndexError` out of the parser — an unhandled
crash on valid lowercase COBOL in an otherwise case-insensitive parser.

These tests prove the crash first (red), then pin the fix: the UNTIL
split is case-insensitive and lowercase inline forms parse to the same
statement shape as their uppercase twins. Uppercase behavior is pinned
as regression.
"""

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import PerformStatement


def _parse_inline(lines: list[str]) -> PerformStatement:
    stmt, _ = CobolParser()._parse_perform(lines, 0)
    assert isinstance(stmt, PerformStatement)
    return stmt


def test_lowercase_perform_until_inline_parses_without_crash():
    """`perform … until …` with a lowercase source line must not IndexError."""
    stmt = _parse_inline([
        "           perform until ws-x > 5",
        "               add 1 to ws-x",
        "           end-perform",
    ])

    assert stmt.until_condition == "ws-x > 5"
    assert stmt.structured_condition is not None
    assert len(stmt.body) == 1


def test_lowercase_perform_varying_inline_until_parses_without_crash():
    """The inline VARYING form must not IndexError on a lowercase line."""
    stmt = _parse_inline([
        "           perform varying ws-i from 1 by 1 until ws-i > 5",
        "               add 1 to ws-i",
        "           end-perform",
    ])

    assert stmt.until_condition.lower().startswith("varying")
    assert stmt.structured_condition is not None
    assert len(stmt.body) == 1


def test_lowercase_perform_condition_matches_uppercase_twin():
    """Lowercase and uppercase spellings produce the same condition text."""
    lower = _parse_inline([
        "           perform until ws-x > 5",
        "               add 1 to ws-x",
        "           end-perform",
    ])
    upper = _parse_inline([
        "           PERFORM UNTIL WS-X > 5",
        "               ADD 1 TO WS-X",
        "           END-PERFORM",
    ])

    assert lower.until_condition.upper() == upper.until_condition
    assert lower.structured_condition is not None
    assert upper.structured_condition is not None


def test_mixed_case_perform_until_parses_without_crash():
    """Mixed-case spellings are as legitimate as all-lowercase."""
    stmt = _parse_inline([
        "           Perform Until Ws-X > 5",
        "               Add 1 To Ws-X",
        "           End-Perform",
    ])

    assert stmt.until_condition == "Ws-X > 5"
    assert stmt.structured_condition is not None


def test_uppercase_perform_until_inline_regression():
    """The certified uppercase form keeps its exact behavior."""
    stmt = _parse_inline([
        "           PERFORM UNTIL WS-X > 5",
        "               ADD 1 TO WS-X",
        "           END-PERFORM",
    ])

    assert stmt.until_condition == "WS-X > 5"
    assert stmt.structured_condition is not None
    assert len(stmt.body) == 1


def test_lowercase_full_program_parses_end_to_end():
    """A fully lowercase program reaches a parsed PROCEDURE DIVISION."""
    source = (
        "       identification division.\n"
        "       program-id. lower-perform.\n"
        "       data division.\n"
        "       working-storage section.\n"
        "       01 ws-x pic 9(4) value 0.\n"
        "       procedure division.\n"
        "       main-logic.\n"
        "           perform until ws-x > 5\n"
        "               add 1 to ws-x\n"
        "           end-perform\n"
        "           stop run.\n"
    )

    program = CobolParser().parse(source)

    performs = [
        stmt
        for paragraph in program.paragraphs
        for stmt in paragraph.statements
        if isinstance(stmt, PerformStatement)
    ]
    assert len(performs) == 1
    assert performs[0].structured_condition is not None

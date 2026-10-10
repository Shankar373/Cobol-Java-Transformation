"""`NOT` in conditions must produce compiling, semantically correct Java.

BL-019: `map_cobol_condition_to_java` performed an unconditional
`condition.replace("NOT ", "!")`.  Because that ran *after* `NOT =` had already
become `!=`, `IF C NOT = SPACES` produced `C ! == SPACES` and `IF A NOT > 3`
produced `A !> 3` — non-compiling Java with no diagnostic, on a construct the
capability registry certifies as SUPPORTED.

Java has no prefix operator that negates a relational result: `!A > B` compares
a boolean, and `A !> B` does not compile at all.  COBOL's negated relational
must therefore be folded into the operator itself (`NOT >` becomes `<=`), which
is what `_fold_negated_relational` does.

Deterministic only: no model, no LLM.
"""

import re

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import (
    _fold_negated_relational,
    map_cobol_condition_to_java,
)
from engine.transformation.java_generator import JavaGenerator

WORKING_STORAGE = (
    "       01 WS-A PIC 9(4).\n"
    "       01 WS-C PIC X(10).\n"
)

#: Tokens that can never appear in generated Java. Their presence is the
#: BL-019 signature.
MALFORMED = ("! >", "!>", "!<", "!>=", "!<=", "! ==", "!==", '"" ""')


def _generate(body: str) -> str:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. NOTCOND.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{WORKING_STORAGE}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        + "".join(f"           {line}\n" for line in body)
        + "           STOP RUN.\n"
    )
    return JavaGenerator().generate(CobolParser().parse(source))[0].source_code


# ---------------------------------------------------------------------------
# Positive - the operator is folded, not prefixed
# ---------------------------------------------------------------------------

class TestNegatedRelationalFolding:
    @pytest.mark.parametrize(
        ("cobol", "expected"),
        [
            ("A NOT = 5", "!="), ("A NOT == 5", "!="),
            ("A NOT > 3", "<="), ("A NOT >= 3", "<"),
            ("A NOT < 3", ">="), ("A NOT <= 3", ">"),
            ("A NOT <> 3", "=="),
        ],
    )
    def test_operator_is_folded(self, cobol, expected):
        assert _fold_negated_relational(cobol) == f"A {expected} 3" or (
            _fold_negated_relational(cobol).split()[1] == expected
        ), _fold_negated_relational(cobol)

    def test_not_is_removed_entirely(self):
        assert "NOT" not in _fold_negated_relational("A NOT > 3").upper()

    def test_not_inside_a_literal_is_untouched(self):
        assert _fold_negated_relational('A = "NOT >"') == 'A = "NOT >"'

    def test_ordinary_conditions_are_unchanged(self):
        for condition in ("A = 5", "A > 5", "WS-N >= 5", "WS-N <> 5"):
            assert "!" not in _fold_negated_relational(condition), condition


class TestGeneratedJavaHasNoMalformedTokens:
    @pytest.mark.parametrize(
        "body",
        [
            ('IF WS-A NOT > 3', '    DISPLAY "OK"', "END-IF."),
            ('IF WS-A NOT < 3', '    DISPLAY "OK"', "END-IF."),
            ('IF WS-A NOT = 3', '    DISPLAY "OK"', "END-IF."),
            ('IF WS-A NOT >= 3', '    DISPLAY "OK"', "END-IF."),
            ('IF WS-A NOT <= 3', '    DISPLAY "OK"', "END-IF."),
            ('IF WS-C NOT = SPACES', '    DISPLAY "OK"', "END-IF."),
            ('IF WS-A NOT > 3 OR WS-C NOT = SPACES', '    DISPLAY "OK"', "END-IF."),
        ],
    )
    def test_no_malformed_operator(self, body):
        code = _generate(body)
        for token in MALFORMED:
            assert token not in code, (token, body)

    def test_semantics_are_correct_for_not_greater_than(self):
        code = _generate(('IF WS-A NOT > 3', '    DISPLAY "OK"', "END-IF."))
        assert "if (WS_A <= 3)" in code, code

    def test_semantics_are_correct_for_not_less_than(self):
        code = _generate(('IF WS-A NOT < 3', '    DISPLAY "OK"', "END-IF."))
        assert "if (WS_A >= 3)" in code, code

    def test_not_equals_spaces_is_a_whole_field_test(self):
        code = _generate(('IF WS-C NOT = SPACES', '    DISPLAY "OK"', "END-IF."))
        assert 'replace(" ", "").isEmpty()' in code, code
        assert "!" in code, code

    def test_multi_clause_not_equals_spaces_keeps_semantics(self):
        code = _generate((
            'IF WS-A NOT < 1 OR WS-C NOT = SPACES',
            '    DISPLAY "OK"',
            "END-IF.",
        ))
        assert 'replace(" ", "").isEmpty()' in code, code
        for token in MALFORMED:
            assert token not in code, token


class TestConditionMapperDoesNotRaise:
    @pytest.mark.parametrize(
        "condition",
        [
            'C NOT = "A"', "A NOT > 3", "A NOT < 3", "A NOT >= 3",
            "A NOT <= 3", 'C NOT = "A" AND A NOT = 0',
            'C NOT = "A" OR B = 1', "A = 5", 'C = "A"',
        ],
    )
    def test_maps_without_error(self, condition):
        assert map_cobol_condition_to_java(condition) is not None

    def test_not_is_never_rendered_as_a_bare_prefix(self):
        for condition in ("A NOT > 3", "A NOT < 3", "A NOT = 3"):
            rendered = str(map_cobol_condition_to_java(condition))
            assert "!>" not in rendered and "!<" not in rendered, condition
            assert "! =" not in rendered and "===" not in rendered, condition
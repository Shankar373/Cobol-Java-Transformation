"""INITIALIZE lowering — certified plain subset and fail-closed contract.

Pins the real, oracle-backed INITIALIZE lane (GnuCOBOL 3.1.2
differential proof in ``tests/integration/test_initialize_oracle_proof.py``)
at the parser and generation level:

* the parser records ``ALL TO VALUE`` / ``REPLACING`` clauses on the
  statement instead of treating their keyword tokens as bogus targets;
* elementary targets lower to their category default (spaces for
  alphanumeric, typed zero for numeric);
* group targets are expanded recursively to every elementary
  subordinate by category — FILLER and 88-level condition-names are
  skipped, nested groups recurse, COMP/COMP-3 children are zeroed
  (GnuCOBOL oracle-pinned); the phantom group field is never assigned;
* every form outside the certified subset (ALL TO VALUE, REPLACING,
  table targets or table children, unknown targets) fails closed with
  an unresolvable ``UNSUPPORTED_INITIALIZE$...`` symbol so ``javac``
  names the form instead of silently wrong field values shipping.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_statement
from engine.transformation.ir import InitializeStatement
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import JavaAssignment, JavaLiteral, JavaVariableRef

HEADER = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. INITT.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-ALPHA PIC X(4).
01 WS-NUM PIC 9(4).
01 WS-DEC PIC 9(4)V99.
01 WS-SIGNED PIC S9(4).
01 WS-COMP PIC 9(4) COMP.
01 WS-COMP3 PIC 9(4) COMP-3.
01 WS-TAB PIC X(4) OCCURS 5 TIMES.
01 WS-G.
05 WS-GA PIC X(4).
05 FILLER PIC X(3).
05 88 WS-GOK VALUE 5.
05 WS-GB PIC 9(2).
05 WS-GC PIC 9(2) COMP-3.
05 WS-GH.
10 WS-GHI PIC X(2).
01 WS-GT.
05 WS-GTA PIC X(2).
05 WS-GTT PIC X(2) OCCURS 2 TIMES.
PROCEDURE DIVISION.
MAIN.
"""


def _parse_initializes(body: str) -> tuple[object, list[InitializeStatement]]:
    program = CobolParser().parse(HEADER + body + "    STOP RUN.\n")
    stmts = [
        s
        for para in program.paragraphs
        for s in para.statements
        if isinstance(s, InitializeStatement)
    ]
    assert stmts, "no InitializeStatement parsed"
    return program, stmts


def _assignments(body: str, index: int = -1) -> list[JavaAssignment]:
    program, stmts = _parse_initializes(body)
    mapped = map_cobol_statement(stmts[index], program)
    assert mapped, "no statements mapped"
    assert all(isinstance(m, JavaAssignment) for m in mapped), mapped
    return list(mapped)


def _symbol(assignment: JavaAssignment) -> str:
    expr = assignment.expression
    assert isinstance(expr, JavaVariableRef), expr
    return expr.name


def _literal_value(assignment: JavaAssignment) -> str:
    expr = assignment.expression
    assert isinstance(expr, JavaLiteral), expr
    return expr.value


class TestParserContract:
    def test_plain_form_takes_all_tokens_as_targets(self) -> None:
        _, stmts = _parse_initializes("    INITIALIZE WS-ALPHA WS-NUM.\n")
        stmt = stmts[-1]
        assert stmt.targets == ("WS-ALPHA", "WS-NUM"), stmt.targets
        assert stmt.all_to_value is False
        assert stmt.replacing == ""

    def test_all_to_value_clause_is_recorded_not_targeted(self) -> None:
        _, stmts = _parse_initializes("    INITIALIZE WS-G ALL TO VALUE.\n")
        stmt = stmts[-1]
        assert stmt.all_to_value is True
        # ALL / TO / VALUE keywords are NOT targets.
        assert stmt.targets == ("WS-G",), stmt.targets

    def test_replacing_clause_is_recorded_not_targeted(self) -> None:
        _, stmts = _parse_initializes(
            "    INITIALIZE WS-G REPLACING NUMERIC BY 7.\n"
        )
        stmt = stmts[-1]
        assert stmt.replacing.startswith("REPLACING"), stmt.replacing
        # REPLACING / NUMERIC / BY / 7 keywords are NOT targets.
        assert stmt.targets == ("WS-G",), stmt.targets


class TestCertifiedElementaryTargets:
    def test_alnum_target_becomes_spaces_of_pic_width(self) -> None:
        out, = _assignments("    INITIALIZE WS-ALPHA.\n")
        assert out.target == "WS_ALPHA"
        assert _literal_value(out) == "    "

    def test_unsigned_numeric_target_becomes_int_zero(self) -> None:
        out, = _assignments("    INITIALIZE WS-NUM.\n")
        assert out.target == "WS_NUM"
        assert _literal_value(out) == "0"

    def test_signed_numeric_target_becomes_int_zero(self) -> None:
        # GnuCOBOL displays the signed zero as +0000 (DISPLAY lane
        # concern); the INITIALIZE lowering itself stores plain zero.
        out, = _assignments("    INITIALIZE WS-SIGNED.\n")
        assert out.target == "WS_SIGNED"
        assert _literal_value(out) == "0"

    def test_decimal_target_becomes_bigdecimal_zero(self) -> None:
        out, = _assignments("    INITIALIZE WS-DEC.\n")
        assert out.target == "WS_DEC"
        assert _literal_value(out) == "0"

    def test_comp_usage_elementary_target_is_zeroed(self) -> None:
        # Oracle-pinned: USAGE COMP/COMP-3 items ARE initialized.
        for target in ("WS-COMP", "WS-COMP3"):
            out, = _assignments(f"    INITIALIZE {target}.\n")
            assert out.target == target.replace("-", "_")
            assert _literal_value(out) == "0"


class TestCertifiedGroupExpansion:
    def test_group_expands_to_children_by_category(self) -> None:
        out = _assignments("    INITIALIZE WS-G.\n")
        targets = [a.target for a in out]
        # FILLER and the bogus '88' child are skipped; the nested group
        # is expanded recursively.
        assert targets == ["WS_GA", "WS_GB", "WS_GC", "WS_GHI"], targets
        assert _literal_value(out[0]) == "    "   # X(4) -> 4 spaces
        assert _literal_value(out[1]) == "0"      # 9(2) -> zero
        assert _literal_value(out[2]) == "0"      # COMP-3 -> zero
        assert _literal_value(out[3]) == "  "     # nested X(2) -> spaces

    def test_group_field_itself_is_never_assigned(self) -> None:
        # The fabricated lowering assigned the phantom group field
        # (WS_G = " ") and left the children untouched.
        program, stmts = _parse_initializes("    INITIALIZE WS-G.\n")
        source = JavaGenerator().generate(program)[0].source_code
        assert 'WS_G = " ";' not in source, source
        assert 'WS_GA = "    ";' in source, source

    def test_multi_target_group_and_elementary_mix(self) -> None:
        out = _assignments("    INITIALIZE WS-G WS-ALPHA.\n")
        targets = [a.target for a in out]
        assert targets == ["WS_GA", "WS_GB", "WS_GC", "WS_GHI", "WS_ALPHA"], targets


class TestFailClosedForms:
    def test_all_to_value_is_fail_closed(self) -> None:
        out, = _assignments("    INITIALIZE WS-G ALL TO VALUE.\n")
        assert _symbol(out) == "UNSUPPORTED_INITIALIZE$ALL_TO_VALUE"

    def test_replacing_is_fail_closed(self) -> None:
        out, = _assignments("    INITIALIZE WS-G REPLACING NUMERIC BY 7.\n")
        assert _symbol(out) == "UNSUPPORTED_INITIALIZE$REPLACING"

    def test_unknown_target_is_fail_closed(self) -> None:
        out, = _assignments("    INITIALIZE WS-NOPE.\n")
        assert _symbol(out) == "UNSUPPORTED_INITIALIZE$TARGET"

    def test_table_target_is_fail_closed(self) -> None:
        # GnuCOBOL itself rejects unsubscripted table targets
        # ("requires one subscript"); the Java lane must not emit a
        # silently wrong first-element/phantom assignment.
        out, = _assignments("    INITIALIZE WS-TAB.\n")
        assert _symbol(out) == "UNSUPPORTED_INITIALIZE$TABLE"

    def test_table_child_inside_group_is_fail_closed(self) -> None:
        # The whole group target fails closed when it contains an
        # OCCURS child (arrays are not certified for INITIALIZE).
        out, = _assignments("    INITIALIZE WS-GT.\n")
        assert _symbol(out) == "UNSUPPORTED_INITIALIZE$TABLE"

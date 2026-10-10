"""Scoped-construct statement loss: inline statements must never be dropped.

Master README Section 60 (no silent loss) and Section 53 (no silent semantic
loss may remain at phase closure) are the contracts under test here.

A COBOL statement may legally sit on the same line that opens a scope:

    EVALUATE A
        WHEN 1 DISPLAY "ONE"
    END-EVALUATE.

    IF A > 1 THEN DISPLAY "YES" END-IF.

The parser previously took every token after ``WHEN `` / ``IF `` as the
*condition*, so the inline statement became a comparison operand
(``A = 1 OR A = DISPLAY OR A = "ONE"``) or vanished entirely, and the mapper
emitted an empty branch.  No diagnostic was emitted and the capability
verdict stayed SUPPORTED, so an executable statement was silently deleted.

Also covered:

* BL-021 ``WHEN a ALSO b`` - ALSO is a keyword listing alternatives, not a value.
* BL-022 ``WHEN OTHER`` - must become the else branch (regression guard: the
  earlier inline defect made OTHER misparse as ``A = OTHER OR ...``).
* BL-023 ``2 ** 3`` - exponentiation, not two multiplications; fails closed.
* BL-024 ``FUNCTION MIN(1, 2)`` - an intrinsic, never a field reference.

Deterministic only: no model, no LLM, no heuristics.
"""

from pathlib import Path
import re

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.transformation import ir as irmod
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator

WORKING_STORAGE = (
    "       01 WS-A PIC 9(4).\n"
    "       01 WS-B PIC 9(4).\n"
)


def _program(*body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SCOPED.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{WORKING_STORAGE}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        + "".join(f"           {line}\n" for line in body)
        + "           STOP RUN.\n"
    )


def _first_statement(source: str):
    program = CobolParser().parse(source)
    return program.paragraphs[0].statements[0]


def _generate(source: str) -> str:
    return JavaGenerator().generate(CobolParser().parse(source))[0].source_code


def _classify_via_discovery(tmp_path: Path, name: str, body: str) -> str:
    """Classify through real discovery so parse diagnostics reach the analyzer."""
    cobol = tmp_path / "cobol"
    cobol.mkdir(exist_ok=True)
    (cobol / f"{name}.cob").write_text(
        "IDENTIFICATION DIVISION.\n"
        f"PROGRAM-ID. {name.upper()}.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 WS-A PIC 9(4).\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        f"    {body}\n"
        "    STOP RUN.\n",
        encoding="utf-8",
    )
    app = ApplicationDiscovery().discover(cobol)
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    programs = [c for c in report.components if c.component_type == "PROGRAM"]
    assert programs, "discovery produced no PROGRAM component"
    return programs[0].level.name


# ---------------------------------------------------------------------------
# Positive - the inline statement is preserved
# ---------------------------------------------------------------------------

class TestInlineWhenBodyIsPreserved:
    def test_inline_display_becomes_the_then_body(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            '    WHEN 1 DISPLAY "ONE"',
            "END-EVALUATE",
        ))
        assert isinstance(stmt, irmod.IfStatement)
        assert stmt.condition == "WS-A = 1", stmt.condition
        assert len(stmt.then_body) == 1
        assert isinstance(stmt.then_body[0], irmod.DisplayStatement)

    def test_inline_body_appears_in_generated_java(self):
        code = _generate(_program(
            "EVALUATE WS-A",
            '    WHEN 1 DISPLAY "ONE"',
            "END-EVALUATE",
        ))
        assert 'if (WS_A == 1)' in code
        assert 'println("ONE")' in code
        # The branch must not be empty: a `{` immediately closed by `}` with
        # nothing between them is the silent-loss signature (BL-020).
        assert not re.search(r"\{\s*\}", code), code

    def test_inline_when_with_range(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            '    WHEN 1 THRU 5 DISPLAY "IN-RANGE"',
            "END-EVALUATE",
        ))
        assert stmt.condition == "WS-A >= 1 AND WS-A <= 5", stmt.condition
        assert len(stmt.then_body) == 1

    def test_inline_statement_never_enters_the_condition(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            '    WHEN 1 DISPLAY "ONE"',
            "END-EVALUATE",
        ))
        for verb in ("DISPLAY", "MOVE", "END-IF", "THEN"):
            assert verb not in stmt.condition, (verb, stmt.condition)

    def test_inline_move_is_preserved(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            '    WHEN 1 MOVE 5 TO WS-B',
            "END-EVALUATE",
        ))
        assert len(stmt.then_body) == 1
        assert isinstance(stmt.then_body[0], irmod.MoveStatement)

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            # A scope terminator shares the line; it must never be read as an
            # operand (this produced `B = (B + END_IF)` before the fix).
            ("IF WS-A > 1 ADD 1 TO WS-B END-IF", "WS_B = (WS_B + 1)"),
            ("IF WS-A > 1 MOVE 9 TO WS-B END-IF", "WS_B = 9"),
            ("IF WS-A > 1 COMPUTE WS-B = 4 END-IF", "WS_B = 4"),
        ],
    )
    def test_scope_terminator_never_becomes_an_operand(self, line, expected):
        code = _generate(_program(line))
        assert expected in code, code
        assert "END_IF" not in code, code

    def test_inline_add_in_an_evaluate_arm(self):
        code = _generate(_program(
            "EVALUATE WS-A",
            "    WHEN 1 ADD 3 TO WS-B",
            "END-EVALUATE",
        ))
        assert "WS_B = (WS_B + 3)" in code, code

    def test_inline_and_multiline_arms_both_preserved(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            '    WHEN 1 DISPLAY "ONE"',
            "    WHEN 2",
            '        DISPLAY "TWO"',
            "END-EVALUATE",
        ))
        assert isinstance(stmt.then_body[0], irmod.DisplayStatement)
        nested = stmt.else_body[0]
        assert isinstance(nested, irmod.IfStatement)
        assert len(nested.then_body) == 1


class TestInlineIfBodyIsPreserved:
    def test_inline_then_statement_becomes_the_body(self):
        stmt = _first_statement(_program(
            'IF WS-A > 1 THEN DISPLAY "YES" END-IF',
        ))
        assert isinstance(stmt, irmod.IfStatement)
        assert stmt.condition == "WS-A > 1", stmt.condition
        assert len(stmt.then_body) == 1
        assert isinstance(stmt.then_body[0], irmod.DisplayStatement)

    def test_inline_if_generates_compiling_java(self):
        code = _generate(_program('IF WS-A > 1 THEN DISPLAY "YES" END-IF'))
        assert 'if (WS_A > 1) {' in code
        assert 'println("YES")' in code
        for broken in ("THEN DISPLAY", "END_IF.", "END-IF"):
            assert broken not in code, broken

    def test_inline_if_without_then_and_with_a_period_closes_on_that_line(self):
        # A period ends the statement. Without END-IF the scope must not run
        # past the line and swallow the following STOP RUN.
        stmt = _first_statement(_program('IF WS-A > 1 DISPLAY "YES".'))
        assert stmt.condition == "WS-A > 1", stmt.condition
        assert len(stmt.then_body) == 1
        assert isinstance(stmt.then_body[0], irmod.DisplayStatement)

    def test_inline_if_without_terminator_keeps_cobol_scope(self):
        # No period and no END-IF: COBOL scope extends to the next END-IF,
        # which this program does not have. The statement must still be kept.
        stmt = _first_statement(_program('IF WS-A > 1 DISPLAY "YES"'))
        assert stmt.condition == "WS-A > 1", stmt.condition
        assert any(isinstance(s, irmod.DisplayStatement) for s in stmt.then_body)

    def test_literal_named_like_a_verb_is_not_a_boundary(self):
        # "DISPLAY" inside a literal must not be read as a statement verb.
        stmt = _first_statement(_program(
            "01 WS-F PIC X(8).",
            'IF WS-F = "DISPLAY" DISPLAY "MATCH" END-IF',
        ))
        assert stmt.condition == 'WS-F = "DISPLAY"', stmt.condition
        assert len(stmt.then_body) == 1

    def test_field_name_containing_a_verb_prefix_is_preserved(self):
        stmt = _first_statement(_program(
            "01 WS-MOVE-COUNT PIC 9(2).",
            "IF WS-MOVE-COUNT > 0 DISPLAY \"POS\" END-IF",
        ))
        assert stmt.condition == "WS-MOVE-COUNT > 0", stmt.condition


# ---------------------------------------------------------------------------
# Positive - existing multi-line behaviour is unchanged (regression guard)
# ---------------------------------------------------------------------------

class TestMultilineBehaviourUnchanged:
    def test_multiline_when_body_still_preserved(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            "    WHEN 1 THRU 5",
            '        DISPLAY "IN-RANGE"',
            "END-EVALUATE",
        ))
        assert len(stmt.then_body) == 1

    def test_three_level_nesting_still_works(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            "    WHEN 1",
            '        DISPLAY "A"',
            "    WHEN 2",
            '        DISPLAY "B"',
            "    WHEN 3",
            '        DISPLAY "C"',
            "END-EVALUATE",
        ))
        depth = 0
        node = stmt
        while isinstance(node, irmod.IfStatement):
            depth += 1
            node = node.else_body[0] if node.else_body else None
        assert depth == 3


# ---------------------------------------------------------------------------
# BL-021 - ALSO lists alternatives
# ---------------------------------------------------------------------------

class TestWhenAlso:
    def test_two_values(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            "    WHEN 1 ALSO 2",
            '        DISPLAY "LOW"',
            "END-EVALUATE",
        ))
        assert stmt.condition == "WS-A = 1 OR WS-A = 2", stmt.condition

    def test_three_values(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            "    WHEN 1 ALSO 2 ALSO 3",
            '        DISPLAY "LOW"',
            "END-EVALUATE",
        ))
        assert stmt.condition == "WS-A = 1 OR WS-A = 2 OR WS-A = 3", stmt.condition

    def test_also_is_not_a_value(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            "    WHEN 1 ALSO 2",
            '        DISPLAY "LOW"',
            "END-EVALUATE",
        ))
        assert "ALSO" not in stmt.condition

    def test_also_generates_correct_java(self):
        code = _generate(_program(
            "EVALUATE WS-A",
            "    WHEN 1 ALSO 2",
            '        DISPLAY "LOW"',
            "END-EVALUATE",
        ))
        assert "if (WS_A == 1 || WS_A == 2)" in code

    def test_range_plus_also(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            "    WHEN 1 THRU 5 ALSO 7",
            '        DISPLAY "X"',
            "END-EVALUATE",
        ))
        assert stmt.condition == "WS-A >= 1 AND WS-A <= 5 OR WS-A = 7", stmt.condition


# ---------------------------------------------------------------------------
# BL-022 - WHEN OTHER becomes the else branch
# ---------------------------------------------------------------------------

class TestWhenOther:
    def test_other_becomes_else_branch(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            "    WHEN 1",
            '        DISPLAY "ONE"',
            "    WHEN OTHER",
            '        DISPLAY "OTHER"',
            "END-EVALUATE",
        ))
        assert isinstance(stmt, irmod.IfStatement)
        assert any(isinstance(s, irmod.DisplayStatement) for s in stmt.else_body)

    def test_other_alone_is_always_taken(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            "    WHEN OTHER",
            '        DISPLAY "OTHER"',
            "END-EVALUATE",
        ))
        assert stmt.condition == "OTHER"
        assert len(stmt.then_body) == 1

    def test_inline_other_generates_an_else_branch(self):
        code = _generate(_program(
            "EVALUATE WS-A",
            "    WHEN 1",
            '        DISPLAY "ONE"',
            '    WHEN OTHER DISPLAY "OTHER"',
            "END-EVALUATE",
        ))
        assert 'println("ONE")' in code
        assert 'println("OTHER")' in code

    def test_other_is_not_compared_as_a_value(self):
        stmt = _first_statement(_program(
            "EVALUATE WS-A",
            '    WHEN OTHER DISPLAY "OTHER"',
            "END-EVALUATE",
        ))
        assert "OTHER OR" not in stmt.condition


# ---------------------------------------------------------------------------
# BL-023 / BL-024 - unmapable forms must fail closed
# ---------------------------------------------------------------------------

class TestUnmappedFormsFailClosed:
    def test_exponentiation_is_an_intrinsic_call_not_arithmetic(self):
        stmt = _first_statement(_program("COMPUTE WS-A = 2 ** 3"))
        assert isinstance(stmt, irmod.ComputeStatement)
        assert isinstance(stmt.expression_expr, irmod.IntrinsicCall)
        assert stmt.expression_expr.name == "**"

    def test_exponentiation_emits_a_diagnostic(self):
        parser = CobolParser()
        parser.parse(_program("COMPUTE WS-A = 2 ** 3"))
        messages = " ".join(d.message for d in parser.diagnostics.all)
        assert "xponentiation" in messages

    def test_exponentiation_never_yields_an_empty_field_reference(self):
        stmt = _first_statement(_program("COMPUTE WS-A = 2 ** 3"))
        assert not isinstance(stmt.expression_expr, irmod.FieldReference)

    def test_intrinsic_is_an_intrinsic_call(self):
        stmt = _first_statement(_program("COMPUTE WS-A = FUNCTION MIN(1, 2)"))
        assert isinstance(stmt.expression_expr, irmod.IntrinsicCall)
        assert stmt.expression_expr.name == "MIN"

    def test_intrinsic_emits_a_diagnostic(self):
        parser = CobolParser()
        parser.parse(_program("COMPUTE WS-A = FUNCTION MIN(1, 2)"))
        messages = " ".join(d.message for d in parser.diagnostics.all)
        assert "ntrinsic" in messages

    def test_intrinsic_is_never_a_field_reference(self):
        stmt = _first_statement(_program("COMPUTE WS-A = FUNCTION MIN(1, 2)"))
        assert not isinstance(stmt.expression_expr, irmod.FieldReference)

    def test_field_named_function_is_still_a_field(self):
        # FUNCTION-CODE has no parentheses: it is a legal field name.
        stmt = _first_statement(_program("COMPUTE WS-A = FUNCTION-CODE"))
        assert isinstance(stmt.expression_expr, irmod.FieldReference)


# ---------------------------------------------------------------------------
# Capability truth - honest verdicts through real discovery
# ---------------------------------------------------------------------------

class TestCapabilityVerdicts:
    def test_supported_program_stays_supported(self, tmp_path):
        assert _classify_via_discovery(tmp_path, "ctrl", "COMPUTE WS-A = WS-A + 1.") == "SUPPORTED"

    def test_correctly_parsed_inline_evaluate_is_supported(self, tmp_path):
        assert _classify_via_discovery(
            tmp_path, "evl", 'EVALUATE WS-A\n        WHEN 1 DISPLAY "X"\n    END-EVALUATE.'
        ) == "SUPPORTED"

    def test_exponentiation_is_never_supported(self, tmp_path):
        assert _classify_via_discovery(tmp_path, "exp", "COMPUTE WS-A = 2 ** 3.") == "UNSUPPORTED"

    def test_intrinsic_is_never_supported(self, tmp_path):
        assert _classify_via_discovery(
            tmp_path, "intr", "COMPUTE WS-A = FUNCTION MIN(1, 2)."
        ) == "UNSUPPORTED"


# ---------------------------------------------------------------------------
# Real fixtures must be unaffected
# ---------------------------------------------------------------------------

class TestShippedFixturesUnaffected:
    """Shipped fixtures must not change verdict because of this fix.

    `workload_inventory` was ALREADY UNSUPPORTED before this work (its
    `PERFORM VARYING` continuation lines are diagnosed as unparsed), verified
    by running the baseline commit `c312eb9` in a detached worktree. Asserting
    SUPPORTED there would encode a claim the repository has never made.
    """

    @pytest.mark.parametrize(
        ("fixture", "expected"),
        [("workload-evaluate", "SUPPORTED"), ("workload_inventory", "UNSUPPORTED")],
    )
    def test_fixture_verdict_is_unchanged(self, fixture, expected):
        path = Path(__file__).resolve().parents[2] / "fixtures" / fixture / "cobol"
        app = ApplicationDiscovery().discover(path)
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert programs, fixture
        for component in programs:
            assert component.level.name == expected, (fixture, component.component_id)

    def test_evaluate_fixture_arms_still_carry_their_bodies(self):
        """The real multi-branch fixture must still keep its WHEN bodies."""
        path = (
            Path(__file__).resolve().parents[2]
            / "fixtures" / "workload-evaluate" / "cobol" / "MAIN.cob"
        )
        program = CobolParser().parse(path.read_text(encoding="utf-8"))
        evaluates = [
            s for para in program.paragraphs for s in para.statements
            if isinstance(s, irmod.IfStatement)
        ]
        assert evaluates, "fixture lost its EVALUATE lowering"
        # Every lowered branch must carry at least one statement; an empty
        # arm is the silent-loss signature this fix removes.
        def _arms(node):
            yield node
            for child in (*node.then_body, *node.else_body):
                if isinstance(child, irmod.IfStatement):
                    yield from _arms(child)
        for statement in evaluates:
            for node in _arms(statement):
                assert node.then_body or node.else_body, node.condition
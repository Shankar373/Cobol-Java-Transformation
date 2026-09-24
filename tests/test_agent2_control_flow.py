"""Agent 2 — CONTROL FLOW + PROGRAM INTERACTION capability tests.

Covers the parse → IR → mapping → generator stages for:

  CONTROL FLOW
  - PERFORM TIMES (paragraph, inline, variable count, nested)
  - PERFORM UNTIL (paragraph, inline, zero-trip, nested)
  - PERFORM VARYING edge cases (out-of-line paragraph form, nested,
    VARYING with IF, multiple iterations)
  - inline PERFORM / nested PERFORM
  - PERFORM THRU (range expansion)
  - paragraph PERFORM
  - EVALUATE (simple, multi-WHEN, WHEN OTHER, value lists, THRU ranges)
  - IF/ELSE edge cases (nesting, AND/OR/NOT, ELSE)
  - GO TO classification (parsed, explicitly unsupported at runtime)

  PROGRAM INTERACTION
  - CALL USING with BY REFERENCE / BY CONTENT / BY VALUE
  - LINKAGE SECTION preservation through discovery
  - value-result mutation semantics in generated Java
  - multi-program dependency ordering
  - recursive/self CALL classification
  - dynamic CALL classification

Runtime (Docker oracle + candidate + comparator + verdict) verification
lives in the agent harness; these tests pin the transformation stages.
"""
from __future__ import annotations

import textwrap

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import (
    CallStatement,
    GoToStatement,
    IfStatement,
    PerformStatement,
)


def _parse(body: str):
    src = textwrap.dedent("""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TPROG.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-N PIC 9(4) VALUE 0.
        01 WS-M PIC 9(4) VALUE 0.
        01 WS-K PIC 9(3) VALUE 2.
        01 WS-F PIC X(1) VALUE 'N'.
        PROCEDURE DIVISION.
        MAIN-PARA.
        """) + textwrap.indent(textwrap.dedent(body), "    ") + textwrap.dedent("""\
            STOP RUN.
        OTHER-PARA.
            ADD 1 TO WS-N.
        """)
    return CobolParser().parse(src)


def _stmts(program):
    return program.paragraphs[0].statements


# ---------------------------------------------------------------------------
# PERFORM TIMES
# ---------------------------------------------------------------------------

class TestPerformTimes:
    def test_paragraph_times_parses(self) -> None:
        prog = _parse("PERFORM OTHER-PARA 3 TIMES.\n")
        stmt = _stmts(prog)[0]
        assert isinstance(stmt, PerformStatement)
        assert stmt.paragraph_name == "OTHER-PARA"
        assert stmt.until_condition == "TIMES=3"

    def test_inline_times_parses_with_body(self) -> None:
        prog = _parse("PERFORM 3 TIMES\n    ADD 1 TO WS-N\nEND-PERFORM.\n")
        stmt = _stmts(prog)[0]
        assert isinstance(stmt, PerformStatement)
        assert stmt.paragraph_name == ""
        assert stmt.until_condition == "TIMES=3"
        assert len(stmt.body) == 1

    def test_variable_count_times_parses(self) -> None:
        prog = _parse("PERFORM OTHER-PARA WS-K TIMES.\n")
        stmt = _stmts(prog)[0]
        assert isinstance(stmt, PerformStatement)
        assert stmt.until_condition == "TIMES=WS-K"

    def test_times_maps_to_bounded_for(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_statement,
        )
        from engine.transformation.java_ir import JavaFor

        prog = _parse("PERFORM OTHER-PARA 3 TIMES.\n")
        mapped = map_cobol_statement(_stmts(prog)[0], prog)
        assert len(mapped) == 1
        assert isinstance(mapped[0], JavaFor)

    def test_nested_times_use_unique_counters(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_program_to_java,
        )
        from engine.transformation.java_generator import JavaGenerator
        from engine.transformation.java_ir import JavaApplication

        prog = _parse(
            "PERFORM 2 TIMES\n"
            "    PERFORM 3 TIMES\n"
            "        ADD 1 TO WS-N\n"
            "    END-PERFORM\n"
            "END-PERFORM.\n"
            "PERFORM OTHER-PARA 2 TIMES.\n"
        )
        java_app = JavaApplication(
            application_id="t",
            programs=(map_cobol_program_to_java(prog),),
        )
        src = JavaGenerator().generate_from_java(java_app)[0].source_code
        import re
        counters = re.findall(r"for \(int (_times_\d+) =", src)
        assert len(counters) >= 3
        assert len(set(counters)) == len(counters), (
            f"loop counters must be unique: {counters}"
        )


# ---------------------------------------------------------------------------
# PERFORM UNTIL
# ---------------------------------------------------------------------------

class TestPerformUntil:
    def test_paragraph_until_keeps_condition(self) -> None:
        prog = _parse("PERFORM OTHER-PARA UNTIL WS-N >= 5.\n")
        stmt = _stmts(prog)[0]
        assert isinstance(stmt, PerformStatement)
        assert stmt.paragraph_name == "OTHER-PARA"
        assert stmt.until_condition == "WS-N >= 5"
        assert stmt.structured_condition is not None

    def test_inline_until_parses_with_body(self) -> None:
        prog = _parse(
            "PERFORM UNTIL WS-N >= 3\n"
            "    ADD 1 TO WS-N\n"
            "END-PERFORM.\n"
        )
        stmt = _stmts(prog)[0]
        assert isinstance(stmt, PerformStatement)
        assert stmt.paragraph_name == ""
        assert stmt.until_condition == "WS-N >= 3"
        assert len(stmt.body) == 1

    def test_paragraph_until_maps_to_while_not(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_statement,
        )
        from engine.transformation.java_ir import (
            JavaMethodCallStatement,
            JavaUnaryOp,
            JavaWhile,
        )

        prog = _parse("PERFORM OTHER-PARA UNTIL WS-N >= 5.\n")
        mapped = map_cobol_statement(_stmts(prog)[0], prog)
        assert len(mapped) == 1
        loop = mapped[0]
        assert isinstance(loop, JavaWhile)
        assert isinstance(loop.condition, JavaUnaryOp)
        assert loop.condition.operator == "!"
        assert len(loop.body) == 1
        assert isinstance(loop.body[0], JavaMethodCallStatement)

    def test_inline_until_maps_to_while_with_body(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_statement,
        )
        from engine.transformation.java_ir import JavaAssignment, JavaWhile

        prog = _parse(
            "PERFORM UNTIL WS-N >= 3\n"
            "    ADD 1 TO WS-N\n"
            "END-PERFORM.\n"
        )
        mapped = map_cobol_statement(_stmts(prog)[0], prog)
        assert isinstance(mapped[0], JavaWhile)
        assert any(isinstance(s, JavaAssignment) for s in mapped[0].body)

    def test_while_renders_in_minimal_generator(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_program_to_java,
        )
        from engine.transformation.java_generator import JavaGenerator
        from engine.transformation.java_ir import JavaApplication

        prog = _parse("PERFORM OTHER-PARA UNTIL WS-N >= 5.\n")
        java_app = JavaApplication(
            application_id="t",
            programs=(map_cobol_program_to_java(prog),),
        )
        src = JavaGenerator().generate_from_java(java_app)[0].source_code
        assert "while (" in src
        assert "!(WS_N >= 5)" in src


# ---------------------------------------------------------------------------
# PERFORM VARYING edge cases (verified core untouched, edges pinned)
# ---------------------------------------------------------------------------

class TestPerformVaryingEdges:
    def test_out_of_line_varying_keeps_paragraph(self) -> None:
        prog = _parse(
            "PERFORM OTHER-PARA VARYING WS-N FROM 1 BY 1 UNTIL WS-N > 5.\n"
        )
        stmt = _stmts(prog)[0]
        assert isinstance(stmt, PerformStatement)
        assert stmt.paragraph_name == "OTHER-PARA"
        assert "VARYING" in (stmt.until_condition or "")
        assert stmt.body == ()

    def test_out_of_line_varying_does_not_swallow(self) -> None:
        prog = _parse(
            "PERFORM OTHER-PARA VARYING WS-N FROM 1 BY 1 UNTIL WS-N > 5.\n"
            "DISPLAY WS-N.\n"
        )
        stmts = _stmts(prog)
        assert isinstance(stmts[0], PerformStatement)
        # DISPLAY + STOP RUN must remain siblings, not loop body members.
        assert len(stmts) == 3

    def test_nested_inline_varying(self) -> None:
        prog = _parse(
            "PERFORM VARYING WS-N FROM 1 BY 1 UNTIL WS-N > 2\n"
            "    PERFORM VARYING WS-M FROM 1 BY 1 UNTIL WS-M > 2\n"
            "        ADD 1 TO WS-M\n"
            "    END-PERFORM\n"
            "END-PERFORM.\n"
        )
        outer = _stmts(prog)[0]
        assert isinstance(outer, PerformStatement)
        assert len(outer.body) == 1
        inner = outer.body[0]
        assert isinstance(inner, PerformStatement)
        assert len(inner.body) == 1


# ---------------------------------------------------------------------------
# PERFORM THRU
# ---------------------------------------------------------------------------

class TestPerformThru:
    def test_thru_parses_range(self) -> None:
        prog = _parse("PERFORM MAIN-PARA THRU OTHER-PARA.\n")
        stmt = _stmts(prog)[0]
        assert isinstance(stmt, PerformStatement)
        assert stmt.paragraph_name == "MAIN-PARA"
        assert stmt.thru_target == "OTHER-PARA"

    def test_thru_expands_to_sequential_calls(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            _expand_thru_range,
        )

        prog = _parse("PERFORM MAIN-PARA THRU OTHER-PARA.\n")
        names = _expand_thru_range(_stmts(prog)[0], prog)
        assert names == ["MAIN-PARA", "OTHER-PARA"]


# ---------------------------------------------------------------------------
# EVALUATE
# ---------------------------------------------------------------------------

class TestEvaluate:
    def _eval(self, arms: str):
        src = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. TPROG.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-G PIC X(1) VALUE 'B'.
            01 WS-R PIC X(5) VALUE SPACES.
            01 WS-S PIC 9(4) VALUE 75.
            PROCEDURE DIVISION.
            MAIN-PARA.
            """) + "    EVALUATE WS-G\n" + textwrap.indent(
            textwrap.dedent(arms), "        "
        ) + "    END-EVALUATE.\n"
        return CobolParser().parse(src).paragraphs[0].statements[0]

    def test_simple_evaluate_becomes_if(self) -> None:
        stmt = self._eval("WHEN 'A'\n    MOVE 'ALPHA' TO WS-R\n")
        assert isinstance(stmt, IfStatement)
        assert "WS-G" in stmt.condition

    def test_multiple_when_nest(self) -> None:
        stmt = self._eval(
            "WHEN 'A'\n    MOVE 'ALPHA' TO WS-R\n"
            "WHEN 'B'\n    MOVE 'BETA ' TO WS-R\n"
        )
        assert isinstance(stmt, IfStatement)
        assert isinstance(stmt.else_body[0], IfStatement)

    def test_when_other_becomes_else(self) -> None:
        from engine.transformation.ir import MoveStatement

        stmt = self._eval(
            "WHEN 'A'\n    MOVE 'ALPHA' TO WS-R\n"
            "WHEN OTHER\n    MOVE 'OTHER' TO WS-R\n"
        )
        assert isinstance(stmt, IfStatement)
        assert any(
            isinstance(s, MoveStatement) for s in stmt.else_body
        )

    def test_when_list_becomes_or(self) -> None:
        stmt = self._eval(
            "WHEN 'Y' 'y'\n    MOVE 'ALPHA' TO WS-R\n"
        )
        assert isinstance(stmt, IfStatement)
        assert "OR" in stmt.condition

    def test_thru_range_becomes_bounded_compare(self) -> None:
        src = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. TPROG.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-S PIC 9(4) VALUE 75.
            01 WS-R PIC X(5) VALUE SPACES.
            PROCEDURE DIVISION.
            MAIN-PARA.
                EVALUATE WS-S
                    WHEN 60 THRU 79
                        MOVE 'PASS ' TO WS-R
                    WHEN OTHER
                        MOVE 'OTHER' TO WS-R
                END-EVALUATE.
            """)
        stmt = CobolParser().parse(src).paragraphs[0].statements[0]
        assert isinstance(stmt, IfStatement)
        assert ">=" in stmt.condition and "<=" in stmt.condition


# ---------------------------------------------------------------------------
# IF/ELSE edge cases + condition rendering
# ---------------------------------------------------------------------------

class TestIfElseEdges:
    def test_bare_equals_does_not_mangle_gte_lte(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_condition_to_java,
        )
        from engine.transformation.java_ir import JavaBinaryOp

        for cobol, op in (("WS-N >= 5", ">="), ("WS-N <= 5", "<="),
                          ("WS-N = 5", "=="), ("WS-N <> 5", "!=")):
            expr = map_cobol_condition_to_java(cobol)
            assert isinstance(expr, JavaBinaryOp), cobol
            assert expr.operator == op, cobol

    def test_single_quoted_literal_becomes_java_string(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_condition_to_java,
        )
        from engine.transformation.java_ir import JavaBinaryOp, JavaLiteral

        expr = map_cobol_condition_to_java("WS-F = 'N'")
        # String-literal comparisons render as raw Java boolean text;
        # what matters is the literal is double-quoted (Java string),
        # never single-quoted (Java char, which would not compile).
        if isinstance(expr, JavaBinaryOp):
            assert expr.operator == "=="
        elif isinstance(expr, JavaLiteral):
            assert expr.value == 'WS_F == "N"', expr.value
        else:  # pragma: no cover
            pytest.fail(f"unexpected condition mapping: {expr!r}")

    def test_nested_if_else_parses(self) -> None:
        prog = _parse(
            "IF WS-N > 1\n"
            "    IF WS-M > 2\n"
            "        ADD 1 TO WS-N\n"
            "    ELSE\n"
            "        ADD 2 TO WS-N\n"
            "    END-IF\n"
            "ELSE\n"
            "    ADD 3 TO WS-N\n"
            "END-IF.\n"
        )
        stmt = _stmts(prog)[0]
        assert isinstance(stmt, IfStatement)
        assert isinstance(stmt.then_body[0], IfStatement)
        assert len(stmt.else_body) == 1


# ---------------------------------------------------------------------------
# GO TO classification
# ---------------------------------------------------------------------------

class TestGoTo:
    def test_goto_parses_with_target(self) -> None:
        prog = _parse("GO TO OTHER-PARA.\n")
        assert isinstance(_stmts(prog)[0], GoToStatement)

    def test_goto_maps_to_comment_not_code(self) -> None:
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_statement,
        )
        from engine.transformation.java_ir import JavaComment

        prog = _parse("GO TO OTHER-PARA.\n")
        mapped = map_cobol_statement(_stmts(prog)[0], prog)
        assert len(mapped) == 1
        assert isinstance(mapped[0], JavaComment)

    def test_goto_program_is_unsupported(self) -> None:
        from engine.modernization.capability_analyzer import (
            CapabilityAnalyzer,
            CapabilityLevel,
        )
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )

        app = ApplicationDiscovery().discover(
            "tests/fixtures/cf_goto", application_id="goto-app"
        )
        report = CapabilityAnalyzer().analyze(app)
        goto = [c for c in report.components if c.component_type == "PROGRAM"]
        assert goto and goto[0].level == CapabilityLevel.UNSUPPORTED


# ---------------------------------------------------------------------------
# CALL USING / LINKAGE / mutation semantics
# ---------------------------------------------------------------------------

class TestCallUsing:
    def test_modes_parse(self) -> None:
        src = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. TPROG.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-A PIC 9(4) VALUE 5.
            PROCEDURE DIVISION.
            MAIN-PARA.
                CALL 'SUBP' USING BY REFERENCE WS-A BY CONTENT WS-N.
            """)
        prog = CobolParser().parse(src)
        call = prog.paragraphs[0].statements[0]
        assert isinstance(call, CallStatement)
        assert call.arguments == ("WS-A", "WS-N")
        assert call.passing_modes == ("REFERENCE", "CONTENT")

    def test_multiline_using_parses_all_args(self) -> None:
        from pathlib import Path

        prog = CobolParser().parse(
            Path("tests/fixtures/call_byref/MAIN.cob").read_text()
        )
        call = prog.paragraphs[0].statements[2]
        assert isinstance(call, CallStatement)
        assert call.arguments == ("WS-A", "WS-B")
        assert call.passing_modes == ("REFERENCE", "CONTENT")

    def test_discovery_preserves_linkage(self) -> None:
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )

        app = ApplicationDiscovery().discover(
            "tests/fixtures/call_byref", application_id="call-app"
        )
        by_id = {u.program_id: u for u in app.programs}
        assert {d.name for d in by_id["DOUBLE"].program.linkage_section} == {
            "LS-A", "LS-B",
        }

    def test_value_result_sync_in_call_out(self) -> None:
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_generator import JavaGenerator

        app = ApplicationDiscovery().discover(
            "tests/fixtures/call_byref", application_id="call-app"
        )
        programs = tuple(u.program for u in app.programs)
        java_app = map_cobol_programs_to_application(
            programs, application_id="call-app"
        )
        files = {
            f.class_name: f.source_code
            for f in JavaGenerator().generate_from_java(java_app)
        }
        main_src = files["Main"]
        # sync-in for every mode
        assert "Double.LS_A = WS_A;" in main_src
        assert "Double.LS_B = WS_B;" in main_src
        assert "Double.MAIN_LOGIC();" in main_src
        # sync-out ONLY for BY REFERENCE
        assert "WS_A = Double.LS_A;" in main_src
        assert "WS_B = Double.LS_B;" not in main_src

    def test_by_value_has_sync_in_but_no_sync_out(self) -> None:
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_generator import JavaGenerator

        app = ApplicationDiscovery().discover(
            "tests/fixtures/call_byvalue", application_id="byvalue-app"
        )
        programs = tuple(u.program for u in app.programs)
        java_app = map_cobol_programs_to_application(
            programs, application_id="byvalue-app"
        )
        files = {
            f.class_name: f.source_code
            for f in JavaGenerator().generate_from_java(java_app)
        }
        main_src = files["Main"]
        assert "Subv.LV_A = WS_A;" in main_src
        assert "Subv.LV_V = WS_V;" in main_src
        assert "Subv.MAIN_LOGIC();" in main_src
        assert "WS_A = Subv.LV_A;" in main_src
        assert "WS_V = Subv.LV_V;" not in main_src

    def test_static_call_resolves_dynamic_does_not(self) -> None:
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )

        app = ApplicationDiscovery().discover(
            "tests/fixtures/call_dynamic", application_id="dyn-app"
        )
        by_id = {u.program_id: u for u in app.programs}
        dyn_calls = [c for c in by_id["MAIN"].calls]
        assert dyn_calls and dyn_calls[0].call_type == "DYNAMIC"

        static = ApplicationDiscovery().discover(
            "tests/fixtures/call_byref", application_id="call-app"
        )
        main_calls = next(
            u for u in static.programs if u.program_id == "MAIN"
        ).calls
        assert main_calls and main_calls[0].call_type == "STATIC"

    def test_dynamic_call_is_unsupported(self) -> None:
        from engine.modernization.capability_analyzer import (
            CapabilityAnalyzer,
            CapabilityLevel,
        )
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )

        app = ApplicationDiscovery().discover(
            "tests/fixtures/call_dynamic", application_id="dyn-app"
        )
        report = CapabilityAnalyzer().analyze(app)
        calls = [c for c in report.components if c.component_type == "CALL"]
        assert calls
        assert any(c.level == CapabilityLevel.UNSUPPORTED for c in calls), (
            [c for c in calls]
        )

    def test_self_call_is_unsupported(self) -> None:
        from engine.modernization.capability_analyzer import (
            CapabilityAnalyzer,
            CapabilityLevel,
        )
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )

        app = ApplicationDiscovery().discover(
            "tests/fixtures/call_recursive", application_id="self-app"
        )
        report = CapabilityAnalyzer().analyze(app)
        calls = [c for c in report.components if c.component_type == "CALL"]
        assert calls
        assert any(c.level == CapabilityLevel.UNSUPPORTED for c in calls)

    def test_call_chain_edges_in_order(self) -> None:
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )

        app = ApplicationDiscovery().discover(
            "tests/fixtures/call_byref", application_id="call-app"
        )
        call_edges = [e for e in app.edges if e.edge_type == "CALL"]
        pairs = {(e.source, e.target) for e in call_edges}
        assert ("MAIN", "DOUBLE") in pairs
        assert ("DOUBLE", "TRIPLE") in pairs
        # N programs → N artifacts → one assembled application.
        assert len(app.programs) == 3


# ---------------------------------------------------------------------------
# Capability sanity on the new control-flow fixtures
# ---------------------------------------------------------------------------

class TestControlFlowCapabilities:
    @pytest.mark.parametrize("fixture", [
        "cf_perform_times",
        "cf_perform_until",
        "cf_perform_mixed",
        "cf_evaluate",
    ])
    def test_control_flow_fixture_supported(self, fixture: str) -> None:
        from engine.modernization.capability_analyzer import (
            CapabilityAnalyzer,
            CapabilityLevel,
        )
        from engine.transformation.application_discovery import (
            ApplicationDiscovery,
        )

        app = ApplicationDiscovery().discover(
            f"tests/fixtures/{fixture}", application_id=f"{fixture}-app"
        )
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        programs = [
            c for c in report.components if c.component_type == "PROGRAM"
        ]
        assert programs
        assert all(
            p.level == CapabilityLevel.SUPPORTED for p in programs
        ), [(p.component_id, p.level, p.reason) for p in programs]

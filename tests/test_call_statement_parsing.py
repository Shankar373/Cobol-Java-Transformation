"""BL-036 + BL-037 focused gate: one extraction truth for CALL statements.

BL-036: a multi-line CALL (line breaks between the verb, the target and
the USING clause) parses to the same IR and verdict as its single-line
spelling — never three "skipped statement" diagnostics while the
discovery lane records the edge.

BL-037: the ``ON EXCEPTION`` / ``ON OVERFLOW`` phrase ends the USING
argument list — correct arity, an explicit diagnostic naming the phrase
(recognised but not transformed), never a false arity claim; a *real*
caller/callee LINKAGE mismatch maps to its own ``ARITY_MISMATCH`` blocking
reason instead of ``UNKNOWN_CONSTRUCT``.

Acceptance (docs/BACKLOG.md BL-036/BL-037):
1. multi-line CALL parses to the same IR/verdict as the single-line form;
2. diagnostics never split one CALL statement into three messages;
3. CALL with ON EXCEPTION yields the correct arity and a diagnostic naming
   the phrase — never a false arity;
4. focused tests join the gate; no existing CALL contract weakened.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
    _iter_call_statements,
)
from engine.modernization.modernization_planner import (
    BlockingReason,
    ModernizationPlanner,
    ModernizationStatus,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)
CALL_LINE = "           CALL 'LINETARGET' USING WS-B.\n"


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (src / name).write_text(text, encoding="utf-8")
    return src


def _parse(source: str) -> tuple:
    parser = CobolParser()
    return parser, parser.parse(source)


# ---------------------------------------------------------------------------
# BL-036: multi-line CALL parity
# ---------------------------------------------------------------------------


class TestMultiLineCall:
    def test_multi_line_call_parses_to_same_ir_as_single_line(self, tmp_path):
        multi = (
            HEADER.format(pid="MLMAIN")
            + "       PROCEDURE DIVISION.\n"
            + "           CALL\n"
            + "             'LINETARGET'\n"
            + "             USING WS-B.\n"
            + "           STOP RUN.\n"
        )
        single = (
            HEADER.format(pid="SLMAIN")
            + "       PROCEDURE DIVISION.\n"
            + CALL_LINE
            + "           STOP RUN.\n"
        )
        _, p_multi = _parse(multi)
        _, p_single = _parse(single)
        calls_multi = _iter_call_statements(p_multi)
        calls_single = _iter_call_statements(p_single)
        assert len(calls_multi) == 1, calls_multi
        m, s = calls_multi[0], calls_single[0]
        assert (m.program_name, m.arguments, m.is_dynamic) == (
            s.program_name, s.arguments, s.is_dynamic,
        )
        assert m.program_name == "LINETARGET"
        assert m.arguments == ("WS-B",)
        assert m.is_dynamic is False

    def test_multi_line_call_produces_no_split_diagnostics(self, tmp_path):
        multi = (
            HEADER.format(pid="MLMAIN")
            + "       PROCEDURE DIVISION.\n"
            + "           CALL\n"
            + "             'LINETARGET'\n"
            + "             USING WS-B.\n"
            + "           STOP RUN.\n"
        )
        parser, program = _parse(multi)
        skipped = [
            d for d in parser.diagnostics.all
            if "Skipped unsupported statement" in d.message
            and "CALL" in d.message
        ]
        assert skipped == [], [d.message for d in skipped]
        # And the program is not blamed for an unparsed statement.
        unit = ApplicationDiscovery().discover(
            _write(tmp_path, {"MLMAIN.cob": multi}),
            application_id="bl036",
        ).programs[0]
        call_noise = [
            d for d in unit.parse_diagnostics if "CALL" in d
            and "Skipped" in d
        ]
        assert call_noise == [], call_noise

    def test_multi_line_call_edge_matches_parser_ir_cross_lane(self, tmp_path):
        """Discovery's edge and the parser's IR agree about the same CALL."""
        src = _write(tmp_path, {
            "MLMAIN.cob": (
                HEADER.format(pid="MLMAIN")
                + "       PROCEDURE DIVISION.\n"
                + "           CALL\n"
                + "             'LINETARGET'\n"
                + "             USING WS-B.\n"
                + "           STOP RUN.\n"
            ),
            "LINETARGET.cob": (
                HEADER.format(pid="LINETARGET")
                + "       PROCEDURE DIVISION.\n"
                + "           STOP RUN.\n"
            ),
        })
        app = ApplicationDiscovery().discover(src, application_id="bl036")
        edges = [e for e in app.edges if e.edge_type == "CALL"]
        assert [(e.source, e.target) for e in edges] == [
            ("MLMAIN", "LINETARGET")
        ]
        unit = next(u for u in app.programs if u.program_id == "MLMAIN")
        calls = _iter_call_statements(unit.program)
        assert [c.program_name for c in calls] == ["LINETARGET"]
        # BL-038 composes: the IR record and the edge agree.
        assert unit.calls[0].resolution == "RESOLVED"
        assert "resolution=RESOLVED" in edges[0].metadata

    def test_multi_line_call_without_using_parses(self, tmp_path):
        parser, program = _parse(
            HEADER.format(pid="ML2")
            + "       PROCEDURE DIVISION.\n"
            + "           CALL\n"
            + "             'LINETARGET'.\n"
            + "           STOP RUN.\n"
        )
        calls = _iter_call_statements(program)
        assert [(c.program_name, c.arguments) for c in calls] == [
            ("LINETARGET", ())
        ]


# ---------------------------------------------------------------------------
# BL-037: ON EXCEPTION / ON OVERFLOW honesty
# ---------------------------------------------------------------------------


class TestOnExceptionPhrase:
    def test_on_exception_yields_correct_arity_and_names_the_phrase(self):
        parser, program = _parse(
            HEADER.format(pid="OEMAIN")
            + "       PROCEDURE DIVISION.\n"
            + "           CALL 'NOSUCHX' USING WS-A ON EXCEPTION "
            'DISPLAY "EXC".\n'
            + "           STOP RUN.\n"
        )
        calls = _iter_call_statements(program)
        assert len(calls) == 1
        assert calls[0].arguments == ("WS-A",)
        named = [
            d for d in parser.diagnostics.all
            if "ON EXCEPTION" in d.message
        ]
        assert len(named) == 1, [d.message for d in parser.diagnostics.all]
        assert named[0].code.name == "UNSUPPORTED_CONSTRUCT"

    def test_on_overflow_variant_also_ends_the_argument_list(self):
        parser, program = _parse(
            HEADER.format(pid="OFMAIN")
            + "       PROCEDURE DIVISION.\n"
            + "           CALL 'NOSUCHX' USING WS-A ON OVERFLOW "
            'DISPLAY "OVF".\n'
            + "           STOP RUN.\n"
        )
        calls = _iter_call_statements(program)
        assert calls[0].arguments == ("WS-A",)
        assert any("ON OVERFLOW" in d.message for d in parser.diagnostics.all)

    def test_never_produces_a_false_arity_claim(self, tmp_path):
        """The filed defect: 5 swallowed tokens vs 1 declared = false claim."""
        src = _write(tmp_path, {"OEMAIN.cob": (
            HEADER.format(pid="OEMAIN")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "       01  WS-A PIC X(4).\n"
            + "       PROCEDURE DIVISION.\n"
            + "           CALL 'NOSUCHX' USING WS-A ON EXCEPTION "
            'DISPLAY "EXC".\n'
            + "           STOP RUN.\n"
        )})
        app = ApplicationDiscovery().discover(src, application_id="bl037")
        report = CapabilityAnalyzer(docker_available=True).analyze(
            app, source_root=src
        )
        call_components = [
            c for c in report.components if c.component_type == "CALL"
        ]
        for comp in call_components:
            assert "argument(s) but" not in comp.reason, comp.reason

    def test_program_with_phrase_is_blocked_naming_the_phrase(self, tmp_path):
        src = _write(tmp_path, {"OEMAIN.cob": (
            HEADER.format(pid="OEMAIN")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "       01  WS-A PIC X(4).\n"
            + "       PROCEDURE DIVISION.\n"
            + "           CALL 'NOSUCHX' USING WS-A ON EXCEPTION "
            'DISPLAY "EXC".\n'
            + "           STOP RUN.\n"
        )})
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="bl037", entrypoint="OEMAIN"
        )
        assert plan.overall_status is not ModernizationStatus.READY
        assert any(
            "ON EXCEPTION" in line for line in plan.blocking_summary
        ), list(plan.blocking_summary)

    def test_form_without_phrase_keeps_full_arguments(self):
        _, program = _parse(
            HEADER.format(pid="SLA")
            + "       PROCEDURE DIVISION.\n"
            + "           CALL 'X' USING WS-A WS-B.\n"
            + "           STOP RUN.\n"
        )
        calls = _iter_call_statements(program)
        assert calls[0].arguments == ("WS-A", "WS-B")


# ---------------------------------------------------------------------------
# Real arity mismatch gets its own blocking reason (BL-037 remediation)
# ---------------------------------------------------------------------------


class TestArityReasonMapping:
    def test_linkage_mismatch_maps_to_arity_mismatch_not_unknown(self, tmp_path):
        src = _write(tmp_path, {
            "CALLER.cob": (
                HEADER.format(pid="CALLER")
                + "       DATA DIVISION.\n"
                + "       WORKING-STORAGE SECTION.\n"
                + "       01  WS-A PIC X(4).\n"
                + "       PROCEDURE DIVISION.\n"
                + "           CALL 'CALLEE' USING WS-A.\n"
                + "           STOP RUN.\n"
            ),
            "CALLEE.cob": (
                HEADER.format(pid="CALLEE")
                + "       DATA DIVISION.\n"
                + "       WORKING-STORAGE SECTION.\n"
                + "       01  WS-X PIC X(2).\n"
                + "       LINKAGE SECTION.\n"
                + "       01  LK-A PIC X(4).\n"
                + "       01  LK-B PIC X(4).\n"
                + "       PROCEDURE DIVISION.\n"
                + "           DISPLAY WS-X.\n"
                + "           EXIT PROGRAM.\n"
            ),
        })
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="bl037", entrypoint="CALLER"
        )
        assert any(
            "ARITY_MISMATCH" in line for line in plan.blocking_summary
        ), list(plan.blocking_summary)
        assert not any(
            "UNKNOWN_CONSTRUCT" in line and "ARITY" in line
            for line in plan.blocking_summary
        ), list(plan.blocking_summary)

    def test_matching_arity_produces_no_arity_component(self, tmp_path):
        src = _write(tmp_path, {
            "CALLER.cob": (
                HEADER.format(pid="CALLER")
                + "       DATA DIVISION.\n"
                + "       WORKING-STORAGE SECTION.\n"
                + "       01  WS-A PIC X(4).\n"
                + "       PROCEDURE DIVISION.\n"
                + "           CALL 'CALLEE' USING WS-A.\n"
                + "           STOP RUN.\n"
            ),
            "CALLEE.cob": (
                HEADER.format(pid="CALLEE")
                + "       DATA DIVISION.\n"
                + "       WORKING-STORAGE SECTION.\n"
                + "       01  WS-X PIC X(2).\n"
                + "       LINKAGE SECTION.\n"
                + "       01  LK-A PIC X(4).\n"
                + "       PROCEDURE DIVISION.\n"
                + "           DISPLAY WS-X.\n"
                + "           EXIT PROGRAM.\n"
            ),
        })
        app = ApplicationDiscovery().discover(src, application_id="bl037")
        report = CapabilityAnalyzer(docker_available=True).analyze(
            app, source_root=src
        )
        arity = [
            c for c in report.components
            if "linkage arity mismatch" in c.reason
        ]
        assert arity == []

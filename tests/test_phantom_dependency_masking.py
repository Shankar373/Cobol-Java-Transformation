"""BL-034 focused gate: comment/string-literal text never creates CALL/COPY dependencies.

Phantom dependency masking (deterministic, no LLM): discovery's CALL/COPY
extraction is literal-aware — comment lines, ``*>`` inline comments and
string literals are data, never statements — while every *real* statement
(single/double-quoted targets included) is still extracted and still fails
closed when unresolved.

Acceptance (docs/BACKLOG.md BL-034):
1. comment/string-only CALL/COPY text produces no edge, no component and no
   generation error;
2. real CALL/COPY statements are still extracted and still fail closed when
   unresolved;
3. positive and negative focused tests join the gate;
4. no existing dependency contract weakened.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.modernization.modernization_planner import (
    BlockingReason,
    ModernizationPlanner,
    ModernizationStatus,
)
from engine.modernization.pipeline import (
    ModernizationConfig,
    UniversalModernizationPipeline,
)
from engine.transformation.application_discovery import ApplicationDiscovery

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (src / name).write_text(text, encoding="utf-8")
    return src


def _discover(tmp_path: Path, files: dict[str, str]):
    src = _write(tmp_path, files)
    return src, ApplicationDiscovery().discover(src, application_id="bl034")


def _pipeline(tmp_path: Path, files: dict[str, str], entrypoint: str):
    src = _write(tmp_path, files)
    return UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(src),
            output_dir=str(tmp_path / "out"),
            application_id="bl034",
            entrypoint=entrypoint,
            docker_available=True,
        )
    ).execute()


# ---------------------------------------------------------------------------
# Acceptance 1: phantom text produces nothing
# ---------------------------------------------------------------------------


class TestPhantomTextProducesNoDependencies:
    def test_comment_only_call_produces_no_edge(self, tmp_path):
        _, app = _discover(tmp_path, {"PC.cob": (
            HEADER.format(pid="PC")
            + "       PROCEDURE DIVISION.\n"
            + "      *    CALL 'X'.\n"
            + "           STOP RUN.\n"
        )})
        assert [e for e in app.edges if e.edge_type == "CALL"] == []
        assert app.programs[0].calls == ()

    def test_string_literal_call_produces_no_edge(self, tmp_path):
        _, app = _discover(tmp_path, {"PL.cob": (
            HEADER.format(pid="PL")
            + "       PROCEDURE DIVISION.\n"
            + '           DISPLAY "CALL \'Y\' STARTED".\n'
            + "           STOP RUN.\n"
        )})
        assert [e for e in app.edges if e.edge_type == "CALL"] == []
        assert app.programs[0].calls == ()

    def test_inline_comment_call_and_copy_produce_nothing(self, tmp_path):
        _, app = _discover(tmp_path, {"IC.cob": (
            HEADER.format(pid="IC")
            + "       PROCEDURE DIVISION.\n"
            + "           DISPLAY 1 *> CALL 'X'.\n"
            + "           DISPLAY 2 *> COPY NOT-A-BOOK.\n"
            + "           STOP RUN.\n"
        )})
        assert [e for e in app.edges if e.edge_type == "CALL"] == []
        assert app.programs[0].calls == ()
        assert app.programs[0].copybooks == ()

    def test_comment_only_copy_produces_no_reference(self, tmp_path):
        _, app = _discover(tmp_path, {"CM.cob": (
            HEADER.format(pid="CM")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "      *    COPY NOT-A-REAL-BOOK.\n"
            + "       PROCEDURE DIVISION.\n"
            + '           DISPLAY "CM OK".\n'
            + "           STOP RUN.\n"
        )})
        assert app.programs[0].copybooks == ()

    def test_string_literal_copy_produces_no_reference(self, tmp_path):
        _, app = _discover(tmp_path, {"CL.cob": (
            HEADER.format(pid="CL")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + '           DISPLAY "COPY FAKE-BOOK DONE".\n'
            + "       PROCEDURE DIVISION.\n"
            + "           STOP RUN.\n"
        )})
        assert app.programs[0].copybooks == ()

    def test_identifier_suffix_call_is_not_an_edge(self, tmp_path):
        """Word guard: MYCALL / X-COPY suffixes are not statements."""
        _, app = _discover(tmp_path, {"SFX.cob": (
            HEADER.format(pid="SFX")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "       01  WS-A PIC X(4).\n"
            + "       PROCEDURE DIVISION.\n"
            + '           MOVE "MYCALL" TO WS-A.\n'
            + '           DISPLAY "X-COPY DONE".\n'
            + "           STOP RUN.\n"
        )})
        assert [e for e in app.edges if e.edge_type == "CALL"] == []
        assert app.programs[0].copybooks == ()

    def test_program_with_only_commented_dependencies_plans_ready_and_generates(
        self, tmp_path,
    ):
        """The filed scenario: a valid program must not be blocked/killed."""
        files = {"CM.cob": (
            HEADER.format(pid="CM")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "      *    COPY NOT-A-REAL-BOOK.\n"
            + "       PROCEDURE DIVISION.\n"
            + '           DISPLAY "CM OK".\n'
            + "           STOP RUN.\n"
        )}
        plan = ModernizationPlanner(docker_available=True).plan(
            _write(tmp_path, files), application_id="bl034", entrypoint="CM")
        assert plan.overall_status is ModernizationStatus.READY
        report = _pipeline(tmp_path, files, "CM")
        assert report.generation_success is True, report.generation_errors


# ---------------------------------------------------------------------------
# Acceptance 2: real statements are still extracted and still fail closed
# ---------------------------------------------------------------------------


class TestRealStatementsPreserved:
    def test_real_single_quoted_call_still_extracted(self, tmp_path):
        _, app = _discover(tmp_path, {"RC.cob": (
            HEADER.format(pid="RC")
            + "       PROCEDURE DIVISION.\n"
            + "           CALL 'NOSUCHPROG'.\n"
            + "           STOP RUN.\n"
        )})
        calls = app.programs[0].calls
        assert [(c.target, c.call_type, c.resolution) for c in calls] == [
            ("NOSUCHPROG", "STATIC", "UNRESOLVED")
        ]
        edges = [e for e in app.edges if e.edge_type == "CALL"]
        assert [(e.source, e.target) for e in edges] == [("RC", "NOSUCHPROG")]

    def test_real_double_quoted_call_still_extracted(self, tmp_path):
        _, app = _discover(tmp_path, {"RD.cob": (
            HEADER.format(pid="RD")
            + "       PROCEDURE DIVISION.\n"
            + '           CALL "NOSUCHPROG".\n'
            + "           STOP RUN.\n"
        )})
        assert [c.target for c in app.programs[0].calls] == ["NOSUCHPROG"]

    def test_real_bare_call_is_dynamic_and_fails_closed(self, tmp_path):
        _, app = _discover(tmp_path, {"RB.cob": (
            HEADER.format(pid="RB")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "       01  WS-P PIC X(8) VALUE 'NOSUCHPR'.\n"
            + "       PROCEDURE DIVISION.\n"
            + "           CALL WS-P.\n"
            + "           STOP RUN.\n"
        )})
        calls = app.programs[0].calls
        assert [(c.target, c.call_type) for c in calls] == [("WS-P", "DYNAMIC")]

    def test_unresolved_call_still_blocks_the_plan(self, tmp_path):
        src = _write(tmp_path, {"RC.cob": (
            HEADER.format(pid="RC")
            + "       PROCEDURE DIVISION.\n"
            + "           CALL 'NOSUCHPROG'.\n"
            + "           STOP RUN.\n"
        )})
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="bl034", entrypoint="RC")
        assert plan.overall_status is not ModernizationStatus.READY
        assert any(
            "UNRESOLVED_CALL" in line for line in plan.blocking_summary
        ), list(plan.blocking_summary)

    def test_real_copy_still_extracted_and_resolved(self, tmp_path):
        _, app = _discover(tmp_path, {
            "RX.cob": (
                HEADER.format(pid="RX")
                + "       DATA DIVISION.\n"
                + "       WORKING-STORAGE SECTION.\n"
                + "           COPY REALREC.\n"
                + "       PROCEDURE DIVISION.\n"
                + "           STOP RUN.\n"
            ),
            "REALREC.cpy": "       01  WS-REAL PIC X(4).\n",
        })
        refs = app.programs[0].copybooks
        assert [(r.copybook_name, r.resolution) for r in refs] == [
            ("REALREC", "RESOLVED")
        ]

    def test_unresolved_real_copy_still_fails_generation(self, tmp_path):
        report = _pipeline(tmp_path, {"RX.cob": (
            HEADER.format(pid="RX")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "           COPY MISSING-BOOK.\n"
            + "       PROCEDURE DIVISION.\n"
            + "           STOP RUN.\n"
        )}, "RX")
        assert report.generation_success is False
        assert any(
            "Missing COPY target" in e for e in report.generation_errors
        ), report.generation_errors

    def test_mixed_real_and_phantom_keeps_only_the_real_edge(self, tmp_path):
        _, app = _discover(tmp_path, {"MX.cob": (
            HEADER.format(pid="MX")
            + "       PROCEDURE DIVISION.\n"
            + "      *    CALL 'PHANTOM'.\n"
            + '           DISPLAY "CALL \'ALSO-PHANTOM\'".\n'
            + "           CALL 'REALPROG'.\n"
            + "           STOP RUN.\n"
        )})
        edges = [e for e in app.edges if e.edge_type == "CALL"]
        assert [(e.source, e.target) for e in edges] == [("MX", "REALPROG")]

    def test_real_unresolved_copybook_component_still_unsupported(self, tmp_path):
        """BL-033 negative contract stays: real unresolved COPY blocks."""
        src = _write(tmp_path, {"RX.cob": (
            HEADER.format(pid="RX")
            + "       DATA DIVISION.\n"
            + "       WORKING-STORAGE SECTION.\n"
            + "           COPY MISSING-BOOK.\n"
            + "       PROCEDURE DIVISION.\n"
            + "           STOP RUN.\n"
        )})
        app = ApplicationDiscovery().discover(src, application_id="bl034")
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        comp = next(
            c for c in report.components if c.component_type == "COPYBOOK")
        assert comp.level is CapabilityLevel.UNSUPPORTED
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="bl034", entrypoint="RX")
        assert plan.overall_status is ModernizationStatus.BLOCKED
        assert any(
            "MISSING_COPYBOOK" in line for line in plan.blocking_summary
        ), list(plan.blocking_summary)
        assert not any(
            "UNRESOLVED_CALL" in line for line in plan.blocking_summary
        ), list(plan.blocking_summary)  # BL-033 residual: "call" substring

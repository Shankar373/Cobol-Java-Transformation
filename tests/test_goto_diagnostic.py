"""BL-026 focused gate: `GO TO` produces an explicit diagnostic (§16).

The parser names GO TO through the same `UNSUPPORTED_CONSTRUCT`
channel SORT/INSPECT use.  The verdict is unchanged (the registry already
classifies GO TO UNSUPPORTED), the planner still blocks, and generation
now fails closed instead of manufacturing a Java candidate.

Acceptance (docs/BACKLOG.md BL-026):
1. a program containing GO TO produces an explicit diagnostic naming GO TO;
2. its capability verdict remains UNSUPPORTED and the planner still blocks;
3. generation now fails closed (no manufactured Java candidate / comment);
4. focused positive/negative tests join the gate;
5. no existing test weakened or skipped.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.modernization.modernization_planner import (
    ModernizationPlanner,
    ModernizationStatus,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.copybook_model import prepare_application_copybooks

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)
GOTO_MAIN = (
    HEADER.format(pid="GT")
    + "       PROCEDURE DIVISION.\n"
    + "       MAIN-PARA.\n"
    + "           DISPLAY \"A\".\n"
    + "           GO TO MAIN-PARA.\n"
)


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (src / name).write_text(text, encoding="utf-8")
    return src


class TestGoToDiagnostic:
    def test_go_to_produces_an_explicit_diagnostic_naming_it(self):
        parser = CobolParser()
        parser.parse(GOTO_MAIN)
        named = [
            d for d in parser.diagnostics.all
            if "GO TO" in d.message
            and d.code.name == "UNSUPPORTED_CONSTRUCT"
        ]
        assert len(named) == 1, [d.message for d in parser.diagnostics.all]

    def test_discovery_carries_the_diagnostic_on_the_unit(self, tmp_path):
        src = _write(tmp_path, {"GT.cob": GOTO_MAIN})
        app = ApplicationDiscovery().discover(src, application_id="bl026")
        unit = app.programs[0]
        named = [d for d in unit.parse_diagnostics if "GO TO" in d]
        assert len(named) == 1, unit.parse_diagnostics

    def test_verdict_stays_unsupported_and_plan_still_blocks(self, tmp_path):
        src = _write(tmp_path, {"GT.cob": GOTO_MAIN})
        app = ApplicationDiscovery().discover(src, application_id="bl026")
        report = CapabilityAnalyzer(docker_available=True).analyze(
            app, source_root=src
        )
        program = next(
            c for c in report.components
            if c.component_type == "PROGRAM" and c.component_id == "GT"
        )
        assert program.level is CapabilityLevel.UNSUPPORTED
        assert "GO TO" in program.reason
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="bl026", entrypoint="GT"
        )
        assert plan.overall_status is ModernizationStatus.BLOCKED

    def test_generated_comment_no_longer_emitted_fail_closed(self, tmp_path):
        # GO TO is UNSUPPORTED: generation must fail closed rather than
        # silently manufacturing a successful Java candidate carrying a
        # "// GO TO ..." comment (BL-026 / D-9).
        src = _write(tmp_path, {"GT.cob": GOTO_MAIN})
        app = ApplicationDiscovery().discover(src, application_id="bl026")
        prep = prepare_application_copybooks(app, source_root=src)
        gen = ApplicationGenerator().generate(
            prep.application, entrypoint="GT", source_root=src
        )
        assert gen.success is False, gen.errors
        emitted = "".join(str(getattr(g, "source_code", ""))
                          for g in gen.generated_files)
        assert "// GO TO MAIN-PARA" not in emitted

    def test_commented_go_to_produces_no_diagnostic(self):
        parser = CobolParser()
        parser.parse(
            HEADER.format(pid="GC")
            + "       PROCEDURE DIVISION.\n"
            + "           DISPLAY \"A\".\n"
            + "     *    GO TO MAIN-PARA.\n"
            + '           DISPLAY "GO TO SPOTTED".\n'
        )
        named = [d for d in parser.diagnostics.all if "GO TO" in d.message]
        assert named == [], [d.message for d in named]

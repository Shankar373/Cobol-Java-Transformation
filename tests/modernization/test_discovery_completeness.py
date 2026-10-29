"""P0 discovery completeness regression tests.

These tests prove that a failed source unit remains authoritative in the
application inventory and prevents transformation planning from treating a
partial inventory as a complete application.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.modernization.transformation_plan import TransformationPlanGenerator
from engine.transformation.application_discovery import ApplicationDiscovery


VALID = """
IDENTIFICATION DIVISION.
PROGRAM-ID. VALID-ONE.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-X PIC 9(3) VALUE 1.
PROCEDURE DIVISION.
MAIN.
    DISPLAY WS-X.
    STOP RUN.
"""

INVALID = "THIS IS NOT A COBOL PROGRAM"


def _workspace(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "valid.cob").write_text(VALID, encoding="utf-8")
    (tmp_path / "invalid.cob").write_text(INVALID, encoding="utf-8")
    return tmp_path


def test_failed_source_unit_remains_in_discovery_inventory(tmp_path: Path) -> None:
    app = ApplicationDiscovery().discover(_workspace(tmp_path), application_id="mixed-app")

    assert len(app.programs) == 2
    valid = app.get_program("VALID-ONE")
    invalid = app.get_program("INVALID")
    assert valid is not None and valid.status == "PARSED" and valid.program is not None
    assert invalid is not None
    assert invalid.status == "PARSE_FAILED"
    assert invalid.program is None
    assert invalid.source_path == "invalid.cob"
    assert invalid.diagnostic
    assert not app.discovery_complete
    assert len(app.discovery_issues) == 1
    assert app.discovery_issues[0].source_path == "invalid.cob"
    assert app.discovery_issues[0].source_hash


def test_incomplete_inventory_cannot_be_planned_as_transformable(tmp_path: Path) -> None:
    app = ApplicationDiscovery().discover(_workspace(tmp_path), application_id="mixed-app")
    capabilities = CapabilityAnalyzer(docker_available=False).analyze(app)
    plan = TransformationPlanGenerator().generate(app, capabilities)

    assert plan.total_programs == 2
    assert plan.transformable_programs == 0
    assert plan.skipped_programs == 2
    assert all(
        component.action.value == "SKIP"
        for component in plan.components
        if component.component_type == "PROGRAM"
    )
    assert any("Discovery incomplete" in component.reason for component in plan.components)


def test_modernization_pipeline_blocks_incomplete_discovery(tmp_path: Path) -> None:
    source_dir = _workspace(tmp_path / "source")
    output_dir = tmp_path / "out"
    report = UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(source_dir),
            output_dir=str(output_dir),
            application_id="mixed-app",
        )
    ).execute()

    assert report.discovery_complete is False
    assert report.discovery_issues
    assert report.transformation_plan is None
    assert report.generation_success is False
    assert any("Discovery incomplete" in limitation for limitation in report.limitations)
    assert any("invalid.cob" in limitation for limitation in report.limitations)

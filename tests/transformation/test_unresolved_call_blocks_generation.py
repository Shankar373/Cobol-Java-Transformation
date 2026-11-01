"""A CALL the plan cannot dispatch blocks generation (Docker-free).

``CALL WS-PROG-NAME`` dispatches on a runtime value, so the plan marks the
CALL component SKIP.  Generation used to continue because only PROGRAM
components were checked: the Spring Boot project built and the run failed
at execution time.  Generation now stops before emitting any Java.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.pipeline import (
    ModernizationConfig,
    UniversalModernizationPipeline,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _report(app: str, entry: str, tmp_path: Path):
    return UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(FIXTURES / app / "cobol"),
            output_dir=str(tmp_path / "out"),
            application_id=app,
            entrypoint=entry,
            docker_available=True,
        )
    ).execute()


def test_dynamic_call_blocks_generation(tmp_path: Path) -> None:
    report = _report("workload-dynamic-call-valid", "MAIN", tmp_path)
    assert report.generation_success is False
    assert any(
        "non-transformable CALLs: MAIN->WS-PROG-NAME" in error
        for error in report.generation_errors
    ), report.generation_errors
    assert not list((tmp_path / "out").rglob("*.java"))


def test_static_call_still_generates(tmp_path: Path) -> None:
    report = _report("workload-call-linkage-valid", "MAIN", tmp_path)
    assert report.generation_success is True, report.generation_errors

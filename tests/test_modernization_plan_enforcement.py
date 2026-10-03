"""Regression tests for plan-enforced modernization orchestration."""

from types import SimpleNamespace

from engine.modernization.capability_analyzer import CapabilityLevel, CapabilityReport
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.modernization.transformation_plan import (
    AssemblyPlan,
    ComponentPlan,
    OraclePlan,
    TransformationAction,
    TransformationPlan,
    TransformerType,
)


def test_pipeline_blocks_transformation_when_plan_skips_program(tmp_path):
    app = SimpleNamespace(
        application_id="demo",
        programs=(SimpleNamespace(program_id="BLOCKED"),),
        copybooks=(),
        edges=(),
    )

    capability = CapabilityReport(
        application_id="demo",
        components=(),
        overall_level=CapabilityLevel.SUPPORTED,
    )
    plan = TransformationPlan(
        application_id="demo",
        components=(
            ComponentPlan(
                component_id="BLOCKED",
                component_type="PROGRAM",
                action=TransformationAction.SKIP,
                transformer=TransformerType.SKIP,
                reason="Unsupported: EXEC CICS",
            ),
        ),
        assembly=AssemblyPlan(
            output_type="SPRING_BOOT",
            base_package="com.modernized.app",
            application_name="demo",
            include_service_registry=False,
        ),
        oracle=OraclePlan(source_format="free", entry_program="BLOCKED"),
        total_programs=1,
        transformable_programs=0,
        skipped_programs=1,
    )

    pipeline = UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(tmp_path),
            output_dir=str(tmp_path / "out"),
            docker_available=True,
        )
    )
    pipeline._discovery.discover = lambda *args, **kwargs: app
    pipeline._capability_analyzer.analyze = lambda application: capability
    pipeline._plan_generator.generate = lambda *args, **kwargs: plan

    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("ApplicationGenerator must not run for a skipped plan")

    pipeline._generator.generate = fail_if_called

    report = pipeline.execute()

    assert called is False
    assert report.generation_success is False
    assert report.skipped_count == 1
    assert report.generation_errors
    assert "BLOCKED" in report.generation_errors[0]
    assert report.limitations[0] == "Transformation blocked by capability plan"

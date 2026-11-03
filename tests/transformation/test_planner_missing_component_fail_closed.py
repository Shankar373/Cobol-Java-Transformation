"""BL-043: planner must fail closed when a capability component is missing.

`_build_program_plan` fails closed for `cap is None` (level UNKNOWN,
blocking ``UNKNOWN_CONSTRUCT``), but `_build_copybook_plan` and
`_build_file_plan` used to default missing components to ``SUPPORTED``
with an optimistic reason and no blocking reasons — a fail-open path
that silently turns absent analyzer output into a green plan.

These tests prove the fail-open default first (red), then pin the fix:
a missing copybook/file capability component must yield a non-SUPPORTED
level with a blocking reason and SKIP strategies, mirroring the program
path. Present components must pass through unchanged.
"""

from engine.modernization.capability_analyzer import CapabilityLevel, ComponentCapability
from engine.modernization.modernization_planner import (
    BlockingReason,
    ModernizationPlanner,
    TransformationStrategy,
    ValidationStrategy,
)
from engine.transformation.ir import CopybookReference, FileDependency

planner = ModernizationPlanner(docker_available=True)


def _copybook_ref() -> CopybookReference:
    return CopybookReference(source_program="MAIN", copybook_name="MYCOPY")


def _file_dep() -> FileDependency:
    return FileDependency(program_id="MAIN", file_name="INPUT-FILE", operation="READ")


def test_missing_copybook_capability_component_fails_closed():
    """cap=None for a copybook must not become SUPPORTED."""
    plan = planner._build_copybook_plan(_copybook_ref(), None)

    assert plan.capability_level != CapabilityLevel.SUPPORTED
    assert plan.may_proceed is False
    assert BlockingReason.UNKNOWN_CONSTRUCT in plan.blocking_reasons


def test_missing_file_capability_component_fails_closed():
    """cap=None for a file dependency must not become SUPPORTED."""
    plan = planner._build_file_plan(_file_dep(), None)

    assert plan.capability_level != CapabilityLevel.SUPPORTED
    assert plan.may_proceed is False
    assert BlockingReason.UNKNOWN_CONSTRUCT in plan.blocking_reasons


def test_missing_copybook_component_reason_names_the_missing_analysis():
    """The reason must describe the missing analysis, not a green default."""
    plan = planner._build_copybook_plan(_copybook_ref(), None)

    assert "capability analysis" in plan.capability_reason
    assert plan.capability_reason != "Copybook resolution supported"


def test_missing_file_component_reason_names_the_missing_analysis():
    """The file reason must describe the missing analysis, not a green default."""
    plan = planner._build_file_plan(_file_dep(), None)

    assert "capability analysis" in plan.capability_reason
    assert "supported" not in plan.capability_reason.lower()


def test_missing_components_get_skip_strategies():
    """A missing component must not receive transformation/validation strategies."""
    cb_plan = planner._build_copybook_plan(_copybook_ref(), None)
    fd_plan = planner._build_file_plan(_file_dep(), None)

    for component_plan in (cb_plan, fd_plan):
        assert component_plan.transformation_strategy == TransformationStrategy.SKIP
        assert component_plan.validation_strategy == ValidationStrategy.SKIP


def test_present_copybook_component_passes_through_unchanged_regression():
    """A present SUPPORTED component keeps its level and strategies (regression)."""
    cap = ComponentCapability(
        component_id="MYCOPY",
        component_type="COPYBOOK",
        level=CapabilityLevel.SUPPORTED,
        reason="Copybook resolution supported",
    )

    plan = planner._build_copybook_plan(_copybook_ref(), cap)

    assert plan.capability_level == CapabilityLevel.SUPPORTED
    assert plan.may_proceed is True
    assert plan.transformation_strategy == TransformationStrategy.INTERNAL_NATIVE
    assert plan.validation_strategy == ValidationStrategy.DOCKER_ORACLE


def test_present_unsupported_file_component_passes_through_unchanged_regression():
    """A present UNSUPPORTED component keeps its level (regression)."""
    cap = ComponentCapability(
        component_id="MAIN:INPUT-FILE",
        component_type="FILE",
        level=CapabilityLevel.UNSUPPORTED,
        reason="Unsupported file construct",
    )

    plan = planner._build_file_plan(_file_dep(), cap)

    assert plan.capability_level == CapabilityLevel.UNSUPPORTED
    assert plan.may_proceed is False

"""Fail-closed CALL capability for a callee with no analysis (BL-139).

Before this fix ``CapabilityAnalyzer._analyze_call`` classified a
``resolution=RESOLVED`` edge as ``SUPPORTED`` whenever the callee was
*absent* from ``program_levels``::

    if callee is None or callee is CapabilityLevel.SUPPORTED:
        level = CapabilityLevel.SUPPORTED

Unknown support must fail closed (``UNKNOWN``), never present an
undetermined callee as fully transformable.  These tests pin:

* a RESOLVED edge whose target has no capability analysis is UNKNOWN,
* the reason names the missing callee (triageable),
* a known-SUPPORTED callee still classifies SUPPORTED (no over-block),
* callee PARTIAL/UNSUPPORTED/UNAVAILABLE still propagate, and
* an application-level report containing such a CALL never aggregates
  to SUPPORTED.
"""

from __future__ import annotations

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
    CapabilityReport,
    ComponentCapability,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import (
    CobolApplication,
    CobolProgramUnit,
    DependencyEdge,
    normalize_cobol_name,
)

_MAIN = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. MAIN.
PROCEDURE DIVISION.
MAIN-LOGIC.
    CALL 'GONE' USING BY CONTENT LNK-AREA.
    STOP RUN.
LINKAGE SECTION.
01  LNK-AREA    PIC X(10).
"""


def _analyzer() -> CapabilityAnalyzer:
    return CapabilityAnalyzer(docker_available=True)


def _resolved_edge(source: str = "MAIN", target: str = "GONE") -> DependencyEdge:
    return DependencyEdge(
        source=source,
        target=target,
        edge_type="CALL",
        metadata="resolution=RESOLVED;call_type=STATIC",
    )


class TestResolvedCallMissingCallee:
    def test_resolved_missing_callee_fails_closed(self):
        comp = _analyzer()._analyze_call(
            _resolved_edge(), program_levels={}
        )
        assert comp.level is CapabilityLevel.UNKNOWN, (
            f"missing callee must fail closed as UNKNOWN, got {comp.level}"
        )
        assert "GONE" in comp.reason

    def test_resolved_known_supported_callee_stays_supported(self):
        comp = _analyzer()._analyze_call(
            _resolved_edge(),
            program_levels={"GONE": CapabilityLevel.SUPPORTED},
        )
        assert comp.level is CapabilityLevel.SUPPORTED

    def test_resolved_callee_levels_propagate(self):
        for callee, expected in (
            (CapabilityLevel.PARTIAL, CapabilityLevel.PARTIAL),
            (CapabilityLevel.UNSUPPORTED, CapabilityLevel.UNSUPPORTED),
            (CapabilityLevel.UNAVAILABLE, CapabilityLevel.PARTIAL),
            (CapabilityLevel.UNKNOWN, CapabilityLevel.UNKNOWN),
        ):
            comp = _analyzer()._analyze_call(
                _resolved_edge(), program_levels={"GONE": callee}
            )
            assert comp.level is expected, (
                f"callee {callee} -> {comp.level}, expected {expected}"
            )

    def test_unresolved_static_call_stays_partial(self):
        edge = DependencyEdge(
            source="MAIN",
            target="NOWHERE",
            edge_type="CALL",
            metadata="resolution=UNRESOLVED;call_type=STATIC",
        )
        comp = _analyzer()._analyze_call(edge, program_levels={})
        assert comp.level is CapabilityLevel.PARTIAL


class TestApplicationLevelFailClosed:
    def test_report_with_missing_callee_call_never_aggregates_supported(self):
        """End-to-end: MAIN parsed, CALL edge RESOLVED to an absent target."""
        program = CobolParser().parse(_MAIN)
        unit = CobolProgramUnit(
            program_id="MAIN",
            source_path="MAIN.cob",
            program=program,
            source_text=_MAIN,
        )
        edge = DependencyEdge(
            source="MAIN",
            target="GONE",
            edge_type="CALL",
            metadata="resolution=RESOLVED;call_type=STATIC",
        )
        app = CobolApplication(
            application_id="APP", programs=(unit,), edges=(edge,)
        )
        report = _analyzer().analyze(app)
        call_comps = [
            c for c in report.components
            if c.component_type == "CALL" and "MAIN->GONE" in c.component_id
        ]
        assert call_comps, "the crafted CALL edge must be analyzed"
        assert all(
            c.level is not CapabilityLevel.SUPPORTED for c in call_comps
        ), "a CALL to an unanalyzed callee must never be SUPPORTED"
        # The application as a whole must not be able to claim full
        # support while an undetermined callee exists.
        assert report.overall_level is not CapabilityLevel.SUPPORTED

    def test_derive_overall_level_unknown_call_dominates(self):
        analyzer = _analyzer()
        comps = [
            ComponentCapability(
                component_id="MAIN", component_type="PROGRAM",
                level=CapabilityLevel.SUPPORTED, reason="ok",
            ),
            ComponentCapability(
                component_id="MAIN->GONE", component_type="CALL",
                level=CapabilityLevel.UNKNOWN, reason="no analysis",
            ),
        ]
        assert analyzer._derive_overall_level(comps) is CapabilityLevel.UNKNOWN
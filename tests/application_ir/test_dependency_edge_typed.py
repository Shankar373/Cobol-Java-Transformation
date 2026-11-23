"""Layer 6 R4: ``DependencyEdge`` is typed; its legacy ``metadata`` text is a derived view (docs/architecture/LAYER6_DESIGN.md 4)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine.transformation.ir import DependencyEdge

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("legacy,typed", [
    ("resolution=RESOLVED;call_type=STATIC", dict(resolution="RESOLVED", call_type="STATIC")),
    ("resolution=UNRESOLVED;call_type=DYNAMIC", dict(resolution="UNRESOLVED", call_type="DYNAMIC")),
    ("mode=INPUT", dict(mode="INPUT")),
    ("", {}),
])
def test_legacy_text_and_typed_construction_are_the_same_edge(legacy, typed):
    from_text = DependencyEdge("A", "B", "CALL", legacy)
    from_typed = DependencyEdge("A", "B", "CALL", **typed)
    assert from_text == from_typed and from_text.metadata == legacy == from_typed.metadata
    for name, value in typed.items():
        assert getattr(from_text, name) == value


def test_unknown_legacy_keys_are_kept_not_dropped_and_rendering_is_canonical():
    edge = DependencyEdge("A", "B", "CALL", "zeta=1;call_type=STATIC;alpha=2;resolution=RESOLVED")
    assert edge.attributes == (("alpha", "2"), ("zeta", "1"))
    assert edge.metadata == "resolution=RESOLVED;call_type=STATIC;alpha=2;zeta=1"
    assert DependencyEdge("A", "B", "CALL", edge.metadata) == edge


def test_a_typed_field_wins_over_conflicting_legacy_text():
    edge = DependencyEdge("A", "B", "CALL", "resolution=UNRESOLVED", resolution="RESOLVED")
    assert edge.resolution == "RESOLVED" and edge.metadata == "resolution=RESOLVED"


def test_the_edge_stays_immutable_and_hashable():
    edge = DependencyEdge("A", "B", "CALL", resolution="RESOLVED")
    with pytest.raises(Exception):
        edge.resolution = "UNRESOLVED"  # type: ignore[misc]
    assert hash(edge) == hash(DependencyEdge("A", "B", "CALL", resolution="RESOLVED"))


_READ = re.compile(r"\b(?:edge|e|dep|call_edge)\.metadata\b")


def test_no_engine_or_api_consumer_reads_the_free_text():
    offenders = []
    for root in ("engine", "api"):
        for path in sorted((REPO / root).rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _READ.search(line):
                    offenders.append(f"{path.relative_to(REPO).as_posix()}:{number}")
    assert not offenders, offenders


def test_the_capability_and_planner_verdicts_follow_the_typed_fields():
    from engine.modernization.capability_analyzer import CapabilityAnalyzer
    from engine.transformation.ir import CobolApplication

    analyzer = CapabilityAnalyzer()
    resolved = DependencyEdge("A", "B", "CALL", resolution="RESOLVED", call_type="STATIC")
    unresolved = DependencyEdge("A", "B", "CALL", resolution="UNRESOLVED", call_type="STATIC")
    dynamic = DependencyEdge("A", "X", "CALL", resolution="UNRESOLVED", call_type="DYNAMIC")
    levels = {e.resolution + e.call_type: analyzer._analyze_call(e, {}).level.value for e in (resolved, unresolved, dynamic)}
    assert levels["UNRESOLVEDDYNAMIC"] != levels["UNRESOLVEDSTATIC"] or levels["RESOLVEDSTATIC"] != levels["UNRESOLVEDSTATIC"]
    assert CobolApplication("x").edges == ()

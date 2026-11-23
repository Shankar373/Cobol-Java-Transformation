"""Layer 6 consumer migration: differential proof that the Application IR can replace ``ApplicationDiscovery``'s CALL edges.

Over every fixture application, the legacy CALL edges derived from the IR equal the ones ``ApplicationDiscovery`` builds, and
the capability report computed from either edge source is identical.  Switching a consumer is only allowed while this holds.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path

import pytest

from engine.application_ir.legacy import call_edges
from engine.application_ir.project import project
from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.semantic_facts.build import build_semantic_facts
from engine.transformation.application_discovery import ApplicationDiscovery

REPO = Path(__file__).resolve().parents[2]
APP_DIRS = sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())


def _sources(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(directory.rglob("*")) if p.suffix.lower() in (".cob", ".cbl")}


def _key(edge):
    return (edge.source.upper(), edge.target.upper(), edge.resolution, edge.call_type)


@pytest.fixture(scope="module")
def applications():
    out = {}
    for directory in APP_DIRS:
        try:
            app = ApplicationDiscovery().discover(directory)
        except Exception:                       # noqa: BLE001 - an application discovery refuses has no legacy edges
            continue
        out[directory.parent.name] = (directory, app, project(build_semantic_facts(_sources(directory)).as_dict()))
    return out


def test_the_corpus_has_applications_with_calls(applications):
    assert len(applications) > 30
    assert sum(1 for _d, app, _ir in applications.values() if any(e.edge_type == "CALL" for e in app.edges)) >= 5


def test_ir_call_edges_equal_the_discovery_call_edges_on_every_application(applications):
    for name, (_directory, app, ir) in applications.items():
        old = Counter(_key(e) for e in app.edges if e.edge_type == "CALL")
        new = Counter(_key(e) for e in call_edges(ir))
        assert old == new, (name, dict(old - new), dict(new - old))


def test_the_capability_report_is_identical_from_either_edge_source(applications):
    analyzer = CapabilityAnalyzer()
    checked = 0
    for name, (directory, app, ir) in applications.items():
        migrated = dataclasses.replace(
            app, edges=tuple(e for e in app.edges if e.edge_type != "CALL") + call_edges(ir))
        assert analyzer.analyze(migrated, directory).to_dict() == analyzer.analyze(app, directory).to_dict(), name
        checked += 1
    assert checked == len(applications)


def test_a_wrong_ir_edge_changes_the_capability_report_so_the_differential_is_live(applications):
    analyzer = CapabilityAnalyzer()
    name, (directory, app, ir) = next((n, v) for n, v in applications.items()
                                      if any(e.edge_type == "CALL" and e.resolution == "RESOLVED" for e in v[1].edges))
    forged = tuple(dataclasses.replace(e, resolution="UNRESOLVED") if e.edge_type == "CALL" else e for e in app.edges)
    assert analyzer.analyze(dataclasses.replace(app, edges=forged), directory).to_dict() != \
        analyzer.analyze(app, directory).to_dict(), name


def test_every_ir_call_edge_names_its_layer5_fact(applications):
    for _name, (_d, _app, ir) in applications.items():
        assert all(e.provenance.startswith("fact:") for e in ir.edges if e.kind == "call")

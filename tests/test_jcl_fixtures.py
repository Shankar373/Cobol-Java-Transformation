"""JCL fixture workload tests — end-to-end discovery + modernization.

Exercises the real ``fixtures/workload-jcl`` directory through discovery,
semantic modeling, and Spring Batch representation generation.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.jcl_discovery import JclDiscovery
from engine.transformation.jcl_to_spring_batch import JclProfileStatus, modernize_jcl

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workload-jcl"

EXPECTED_JOBS = {"SIMPLEB", "PAYORDER", "CONDJOB", "UNSUPP"}


def load_sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(FIXTURES.glob("*.jcl"))
    }


class TestFixtureDiscovery:
    """Discovery of the JCL fixture workload."""

    def test_fixtures_are_discovered(self) -> None:
        discovery = JclDiscovery()
        app = discovery.discover(FIXTURES)
        assert {job.name for job in app.jobs} == EXPECTED_JOBS

    def test_every_fixture_job_has_steps(self) -> None:
        discovery = JclDiscovery()
        app = discovery.discover(FIXTURES)
        for job in app.jobs:
            assert job.steps, f"{job.name} must have at least one step"


class TestFixtureModernization:
    """End-to-end modernization of the fixture workload."""

    def test_supported_fixtures_full(self) -> None:
        sources = load_sources()
        discovery = JclDiscovery()
        app = discovery.discover(FIXTURES)
        profile = modernize_jcl(app, sources, application_id="workload-jcl")
        assert profile.status in (JclProfileStatus.FULL, JclProfileStatus.PARTIAL)
        assert len(profile.application.jobs) == len(EXPECTED_JOBS)
        assert profile.application.validate() == []

    def test_unsupported_fixture_is_partial(self) -> None:
        sources = {"unsupported.jcl": load_sources()["unsupported.jcl"]}
        from engine.transformation.jcl_parser import JclParser

        parser_app = JclParser().parse_application(sources)
        profile = modernize_jcl(parser_app, sources, application_id="workload-jcl")
        assert profile.status == JclProfileStatus.PARTIAL
        assert "IF/THEN/ELSE/ENDIF control blocks" in profile.unsupported_constructs

    def test_fixture_dataset_inventory(self) -> None:
        sources = load_sources()
        discovery = JclDiscovery()
        app = discovery.discover(FIXTURES)
        profile = modernize_jcl(app, sources, application_id="workload-jcl")
        dsn_set = {r.dsn for r in profile.application.resources}
        assert {"ORDER.INPUT", "&&WORK1", "ORDER.OUTPUT"} <= dsn_set
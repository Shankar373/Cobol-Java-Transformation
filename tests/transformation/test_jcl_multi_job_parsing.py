"""BL-072: multiple JOB statements in one source must not be silently merged.

Phase 5 §76 audit probes 7/13 (`%TEMP%\\opencode\\phase5\\probe_p5_r1.py`)
proved that a source containing two JOB statements collapses into a single
``JclJob`` named after the **second** JOB: the first job's name is lost,
its steps are misattributed to the surviving job, and the profile reports
status FULL with zero diagnostics — contradicting the profile spec's
explicit rule that statements are "never silently dropped"
(`docs/specs/JCL_MODERNIZATION_PROFILE.md` L84-85).

Expected behavior: one ``JclJob`` per JOB statement, job identity and
step attribution preserved, dependencies staying within their own job.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.jcl_consumer import modernize_jcl_from_sources
from engine.transformation.jcl_discovery import JclDiscovery
from engine.transformation.jcl_parser import JclParser

TWO_JOB_SOURCE = """\
//JOBONE JOB CLASS=A
//S1 EXEC PGM=ONE
//S1OUT DD DSN=ONE.OUTPUT,DISP=(NEW,CATLG)
//S2 EXEC PGM=ONEB
//JOBTWO JOB CLASS=A
//T1 EXEC PGM=TWO
//T1IN DD DSN=TWO.INPUT,DISP=SHR
//T2 EXEC PGM=TWOB
"""

SINGLE_JOB_SOURCE = """\
//ALONE JOB CLASS=A
//S1 EXEC PGM=ALONE-MAIN
//S2 EXEC PGM=ALONE-REPORT
"""


class TestTwoJobSourceYieldsOneJobPerJobStatement:
    """A second JOB statement starts a new job instead of extending the first."""

    def test_parse_application_yields_one_job_per_job_statement(self) -> None:
        app = JclParser().parse_application({"stream.jcl": TWO_JOB_SOURCE})
        assert len(app.jobs) == 2

    def test_both_job_names_are_preserved_in_source_order(self) -> None:
        app = JclParser().parse_application({"stream.jcl": TWO_JOB_SOURCE})
        assert [job.name for job in app.jobs] == ["JOBONE", "JOBTWO"]

    def test_first_job_only_holds_its_own_steps(self) -> None:
        app = JclParser().parse_application({"stream.jcl": TWO_JOB_SOURCE})
        first = app.jobs[0]
        assert [step.name for step in first.steps] == ["S1", "S2"]
        assert [step.exec_.program for step in first.steps] == ["ONE", "ONEB"]

    def test_second_job_only_holds_its_own_steps(self) -> None:
        app = JclParser().parse_application({"stream.jcl": TWO_JOB_SOURCE})
        second = app.jobs[1]
        assert [step.name for step in second.steps] == ["T1", "T2"]
        assert [step.exec_.program for step in second.steps] == ["TWO", "TWOB"]

    def test_dd_statement_stays_with_the_step_of_its_own_job(self) -> None:
        app = JclParser().parse_application({"stream.jcl": TWO_JOB_SOURCE})
        first, second = app.jobs
        assert [dd.name for dd in first.steps[0].dd_statements] == ["S1OUT"]
        assert first.steps[1].dd_statements == ()
        assert [dd.name for dd in second.steps[0].dd_statements] == ["T1IN"]
        assert first.steps[0].dd_statements[0].dataset == "ONE.OUTPUT"
        assert second.steps[0].dd_statements[0].dataset == "TWO.INPUT"

    def test_source_path_is_shared_across_the_jobs_of_one_file(self) -> None:
        app = JclParser().parse_application({"stream.jcl": TWO_JOB_SOURCE})
        assert [job.source_path for job in app.jobs] == ["stream.jcl", "stream.jcl"]


class TestParseJobsApiExposesEveryJob:
    """``parse_jobs`` is the multi-job entry point; ``parse`` keeps one job."""

    def test_parse_jobs_returns_both_jobs_in_source_order(self) -> None:
        jobs = JclParser().parse_jobs(TWO_JOB_SOURCE)
        assert [job.name for job in jobs] == ["JOBONE", "JOBTWO"]

    def test_parse_jobs_single_job_source_returns_exactly_one(self) -> None:
        jobs = JclParser().parse_jobs(SINGLE_JOB_SOURCE)
        assert len(jobs) == 1
        assert jobs[0].name == "ALONE"

    def test_parse_keeps_its_single_job_contract_and_returns_the_first_job(
        self,
    ) -> None:
        job = JclParser().parse(TWO_JOB_SOURCE)
        assert job.name == "JOBONE"
        assert [step.name for step in job.steps] == ["S1", "S2"]


class TestStepOrderDependenciesStayWithinTheirJob:
    def test_step_order_edges_cover_each_job_without_cross_job_edges(self) -> None:
        app = JclParser().parse_application({"stream.jcl": TWO_JOB_SOURCE})
        order_edges = {
            (dep.source, dep.target)
            for dep in app.dependencies
            if dep.dependency_type == "JCL_STEP_ORDER"
        }
        assert order_edges == {("S1", "S2"), ("T1", "T2")}

    def test_step_count_and_dd_references_are_reported_per_job(self) -> None:
        app = JclParser().parse_application({"stream.jcl": TWO_JOB_SOURCE})
        assert [len(job.steps) for job in app.jobs] == [2, 2]


class TestDiscoveryAndConsumerSplitMultiJobFiles:
    def test_discovery_separates_two_jobs_from_one_file(self, tmp_path: Path) -> None:
        (tmp_path / "stream.jcl").write_text(TWO_JOB_SOURCE, encoding="utf-8")
        app = JclDiscovery().discover(tmp_path)
        assert [job.name for job in app.jobs] == ["JOBONE", "JOBTWO"]

    def test_consumer_reports_both_jobs_with_all_steps(self) -> None:
        result = modernize_jcl_from_sources(
            {"stream.jcl": TWO_JOB_SOURCE}, application_id="bl072"
        )
        assert result.job_count == 2
        assert result.step_count == 4

    def test_splitting_a_clean_two_job_source_keeps_status_full(self) -> None:
        result = modernize_jcl_from_sources(
            {"stream.jcl": TWO_JOB_SOURCE}, application_id="bl072"
        )
        assert result.status == "FULL"
        assert result.has_errors is False

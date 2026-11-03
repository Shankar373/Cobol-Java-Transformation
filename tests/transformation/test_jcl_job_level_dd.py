"""BL-073: job-level DD statements must not be silently dropped.

Phase 5 §76 audit probes 8/15 (`%TEMP%\\opencode\\phase5\\probe_p5_r1.py`,
`probe_p5_r2.py`) proved that a DD statement written before the first EXEC
of its job (the normal place for ``JOBLIB``, job-message datasets, etc.)
vanishes: the parser's DD branch skips it when no step exists, the raw
scan classifies any ``DD`` line as recognized, the dataset never reaches
the dependency graph or inventory, and the profile reports status FULL
with zero diagnostics — contradicting the profile spec's rule that
statements are "never silently dropped"
(`docs/specs/JCL_MODERNIZATION_PROFILE.md` L84-85) and §22's dependency
representation requirement.

Expected behavior: the parser preserves job-level DDs on the ``JclJob``
IR, the dependency graph carries them as ``JCL_DD`` edges, and the
semantic builder diagnoses them as outside the supported subset (status
PARTIAL — never a silent FULL).
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.jcl_consumer import modernize_jcl_from_sources
from engine.transformation.jcl_discovery import JclDiscovery
from engine.transformation.jcl_parser import JclParser

JOB_LEVEL_DD_SOURCE = """\
//LIBJOB JOB CLASS=A
//JOBLIB DD DSN=USER.LOADLIB,DISP=SHR
//MSGO DD SYSOUT=*
//STEP01 EXEC PGM=MAIN-PROGRAM
//INPUT DD DSN=INPUT.DATA,DISP=SHR
"""

STEP_LEVEL_ONLY_SOURCE = """\
//STEPS JOB CLASS=A
//STEP01 EXEC PGM=MAIN-PROGRAM
//INPUT DD DSN=INPUT.DATA,DISP=SHR
"""


class TestJobLevelDDIsPreservedOnTheJobIR:
    def test_job_level_dd_statements_are_attached_to_the_job(self) -> None:
        job = JclParser().parse(JOB_LEVEL_DD_SOURCE)
        names = [dd.name for dd in job.job_dd_statements]
        assert names == ["JOBLIB", "MSGO"]

    def test_job_level_dd_keeps_its_dataset_and_disposition(self) -> None:
        job = JclParser().parse(JOB_LEVEL_DD_SOURCE)
        joblib = job.job_dd_statements[0]
        assert joblib.dataset == "USER.LOADLIB"
        assert joblib.disposition == "SHR"

    def test_job_level_dd_is_not_duplicated_onto_the_first_step(self) -> None:
        job = JclParser().parse(JOB_LEVEL_DD_SOURCE)
        step_names = [dd.name for dd in job.steps[0].dd_statements]
        assert "JOBLIB" not in step_names
        assert step_names == ["INPUT"]

    def test_step_level_dd_still_belong_to_their_step(self) -> None:
        job = JclParser().parse(STEP_LEVEL_ONLY_SOURCE)
        assert job.job_dd_statements == ()
        assert [dd.name for dd in job.steps[0].dd_statements] == ["INPUT"]

    def test_discovery_preserves_job_level_dd_from_disk(self, tmp_path: Path) -> None:
        (tmp_path / "lib.jcl").write_text(JOB_LEVEL_DD_SOURCE, encoding="utf-8")
        app = JclDiscovery().discover(tmp_path)
        assert app.jobs[0].job_dd_statements[0].name == "JOBLIB"


class TestJobLevelDDReachesTheDependencyGraph:
    def test_job_level_dd_dataset_is_a_jcl_dd_edge(self) -> None:
        app = JclParser().parse_application({"lib.jcl": JOB_LEVEL_DD_SOURCE})
        dd_edges = {
            (dep.source, dep.target)
            for dep in app.dependencies
            if dep.dependency_type == "JCL_DD"
        }
        assert ("LIBJOB.JOBLIB", "USER.LOADLIB") in dd_edges

    def test_job_level_dd_edge_carries_the_disposition_metadata(self) -> None:
        app = JclParser().parse_application({"lib.jcl": JOB_LEVEL_DD_SOURCE})
        edge = next(
            dep
            for dep in app.dependencies
            if dep.dependency_type == "JCL_DD" and dep.target == "USER.LOADLIB"
        )
        assert edge.metadata == "disp=SHR"

    def test_step_level_dd_edges_are_unchanged(self) -> None:
        app = JclParser().parse_application({"s.jcl": STEP_LEVEL_ONLY_SOURCE})
        dd_edges = [
            (dep.source, dep.target)
            for dep in app.dependencies
            if dep.dependency_type == "JCL_DD"
        ]
        assert dd_edges == [("STEPS.STEP01.INPUT", "INPUT.DATA")]


class TestJobLevelDDIsDiagnosedInsteadOfSilentlyAccepted:
    def test_job_level_dd_produces_an_error_diagnostic(self) -> None:
        result = modernize_jcl_from_sources(
            {"lib.jcl": JOB_LEVEL_DD_SOURCE}, application_id="bl073"
        )
        joblib_diags = [
            d for d in result.diagnostics if "JOBLIB" in (d.message or "")
        ]
        assert joblib_diags, "job-level JOBLIB must be diagnosed, not dropped"
        assert any(d.level.value == "ERROR" for d in joblib_diags)

    def test_job_level_dd_never_reports_status_full(self) -> None:
        result = modernize_jcl_from_sources(
            {"lib.jcl": JOB_LEVEL_DD_SOURCE}, application_id="bl073"
        )
        assert result.status == "PARTIAL"
        assert result.has_errors is True

    def test_status_contract_lists_job_level_dd_as_unsupported(self) -> None:
        result = modernize_jcl_from_sources(
            {"lib.jcl": JOB_LEVEL_DD_SOURCE}, application_id="bl073"
        )
        assert "job-level DD statements" in result.unsupported_constructs

    def test_step_level_only_source_stays_full_without_job_level_diagnostic(
        self,
    ) -> None:
        result = modernize_jcl_from_sources(
            {"s.jcl": STEP_LEVEL_ONLY_SOURCE}, application_id="bl073"
        )
        assert result.status == "FULL"
        assert not any(
            d.code.value == "JOB_LEVEL_DD" for d in result.diagnostics
        )

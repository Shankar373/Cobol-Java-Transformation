"""JCL consumer integration tests — end-to-end proof.

Proves the full consumer integration path:

    JCL source files
    → JclDiscovery (ingestion)
    → modernize_jcl (representation)
    → JclConsumerResult (control-plane boundary)

Uses fixtures/workload-jcl/ as the starting point.

Covers:
- JCL file discovered from workspace
- Profile invoked
- Status propagated
- Diagnostics propagated
- Unsupported constructs preserved
- Spring Batch IR reaches the consumer
- No regression to existing COBOL pipeline (baseline test)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.jcl.diagnostics import JclDiagnosticCode
from engine.transformation.jcl_consumer import (
    modernize_jcl_from_sources,
    modernize_jcl_workload,
)
from engine.transformation.jcl_spring_batch_ir import (
    EXIT_STATUS_ANY,
    EXIT_STATUS_FAILED,
    EXIT_STATUS_SUCCESS,
    SpringBatchResourceType,
)
from engine.transformation.jcl_to_spring_batch import JclProfileStatus

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workload-jcl"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. JCL file discovered from workspace
# ---------------------------------------------------------------------------

class TestJclDiscoveryIntegration:
    """Prove JCL files are discovered from the real fixture directory."""

    def test_discover_fixture_directory(self) -> None:
        result = modernize_jcl_workload(FIXTURES, application_id="test-discover")
        assert result.application_id == "test-discover"
        assert result.source_path == str(FIXTURES.resolve())
        assert result.job_count == 4  # SIMPLEB, PAYORDER, CONDJOB, UNSUPP

    def test_discover_returns_profile(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert result.profile is not None
        assert len(result.profile.application.jobs) == 4

    def test_discover_step_count(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert result.step_count >= 10  # 2+3+4+5 steps across 4 jobs


# ---------------------------------------------------------------------------
# 2. Profile invoked
# ---------------------------------------------------------------------------

class TestProfileInvocation:
    """Prove modernize_jcl is called through the consumer boundary."""

    def test_profile_has_application(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        app = result.profile.application
        assert app.application_id == "jcl-modernization"
        assert app.profile_version == "1.0"
        assert len(app.jobs) > 0

    def test_profile_has_resources(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert len(result.profile.application.resources) > 0

    def test_profile_has_dataset_edges(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert len(result.profile.application.dataset_edges) > 0

    def test_application_id_propagated(self) -> None:
        result = modernize_jcl_workload(FIXTURES, application_id="my-app-id")
        assert result.profile.application.application_id == "my-app-id"


# ---------------------------------------------------------------------------
# 3. Status propagated
# ---------------------------------------------------------------------------

class TestStatusPropagation:
    """Prove status (FULL/PARTIAL/EMPTY) is correctly propagated."""

    def test_fixture_status_partial(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert result.status == JclProfileStatus.PARTIAL

    def test_full_status_for_clean_jcl(self) -> None:
        jcl = (
            "//CLEAN JOB CLASS=A\n"
            "//STEP01 EXEC PGM=HELLO\n"
            "//SYSOUT DD SYSOUT=*\n"
        )
        result = modernize_jcl_from_sources({"clean.jcl": jcl}, application_id="clean")
        assert result.status == JclProfileStatus.FULL

    def test_empty_status_for_no_jobs(self) -> None:
        result = modernize_jcl_from_sources({}, application_id="empty")
        assert result.status == JclProfileStatus.EMPTY

    def test_status_matches_profile(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert result.status == result.profile.status


# ---------------------------------------------------------------------------
# 4. Diagnostics propagated
# ---------------------------------------------------------------------------

class TestDiagnosticsPropagation:
    """Prove diagnostics reach the consumer boundary."""

    def test_diagnostics_not_empty(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert len(result.diagnostics) > 0

    def test_has_errors_matches_diagnostics(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        error_count = sum(1 for d in result.diagnostics if d.level.value == "ERROR")
        assert result.has_errors == (error_count > 0)

    def test_has_warnings_matches_diagnostics(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        warn_count = sum(1 for d in result.diagnostics if d.level.value == "WARNING")
        assert result.has_warnings == (warn_count > 0)

    def test_diagnostics_include_profile_noted(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        codes = {d.code for d in result.diagnostics}
        assert JclDiagnosticCode.PROFILE_NOTED in codes

    def test_diagnostics_traceable_to_jobs(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        job_names = {d.job for d in result.diagnostics if d.job}
        assert len(job_names) > 0


# ---------------------------------------------------------------------------
# 5. Unsupported constructs preserved
# ---------------------------------------------------------------------------

class TestUnsupportedPreserved:
    """Prove unsupported constructs are never silently discarded."""

    def test_unsupported_constructs_not_empty(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert len(result.unsupported_constructs) > 0

    def test_proc_procedure_flagged(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert "PROC steps / procedure definitions" in result.unsupported_constructs

    def test_if_then_else_flagged(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert "IF/THEN/ELSE/ENDIF control blocks" in result.unsupported_constructs

    def test_statements_outside_subset_flagged(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert "statements outside the supported subset" in result.unsupported_constructs

    def test_unsupported_not_lost(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        # All 4 fixture jobs preserved, even UNSUPP
        job_names = {j.name for j in result.profile.application.jobs}
        assert "UNSUPP" in job_names

    def test_unsupported_job_steps_preserved(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        unsupp = next(j for j in result.profile.application.jobs if j.name == "UNSUPP")
        assert len(unsupp.steps) == 5  # all 5 steps, nothing dropped


# ---------------------------------------------------------------------------
# 6. Spring Batch IR reaches the consumer
# ---------------------------------------------------------------------------

class TestSpringBatchIRConsumer:
    """Prove the Spring Batch representation is accessible at the consumer boundary."""

    def test_job_bean_naming(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        job = result.profile.application.get_job("SIMPLEB")
        assert job.job_bean == "SimplebJob"
        assert job.start_step == "Step01"

    def test_step_tasklet_bean(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        job = result.profile.application.get_job("SIMPLEB")
        step = job.steps[0]
        assert step.tasklet_bean == "Step01Tasklet"
        assert step.program == "SIMPLE-CALC"

    def test_resource_mapping(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        job = result.profile.application.get_job("PAYORDER")
        input_res = job.steps[0].resources[0]
        assert input_res.name == "INPUT"
        assert input_res.resource_type == SpringBatchResourceType.INPUT
        assert input_res.dsn == "ORDER.INPUT"

    def test_flow_edges(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        job = result.profile.application.get_job("SIMPLEB")
        assert len(job.flows) == 1
        assert job.flows[0].source == "Step01"
        assert job.flows[0].target == "Step02"
        assert job.flows[0].on_status == EXIT_STATUS_SUCCESS

    def test_conditional_flow_edges(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        job = result.profile.application.get_job("CONDJOB")
        flow_only = next(f for f in job.flows if f.target == "Step02")
        assert flow_only.on_status == EXIT_STATUS_FAILED
        flow_even = next(f for f in job.flows if f.target == "Step03")
        assert flow_even.on_status == EXIT_STATUS_ANY

    def test_dataset_edges(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        edges = {(e.dataset, e.producer, e.consumer) for e in result.profile.application.dataset_edges}
        assert ("ORDER.INPUT", "", "Step01") in edges
        assert ("ORDER.OUTPUT", "Step03", "") in edges

    def test_validate_clean(self) -> None:
        result = modernize_jcl_workload(FIXTURES)
        assert result.profile.application.validate() == []


# ---------------------------------------------------------------------------
# 7. In-memory source path
# ---------------------------------------------------------------------------

class TestInMemorySources:
    """Prove the in-memory entry point works identically."""

    def test_in_memory_discovery(self) -> None:
        sources = {
            "batch1.jcl": load_fixture("simple_batch.jcl"),
            "batch2.jcl": load_fixture("order_flow.jcl"),
        }
        result = modernize_jcl_from_sources(sources, application_id="in-mem")
        assert result.application_id == "in-mem"
        assert result.job_count == 2
        assert result.status in (JclProfileStatus.FULL, JclProfileStatus.PARTIAL)

    def test_in_memory_supported_constructs(self) -> None:
        jcl = (
            "//JOB JOB CLASS=A\n"
            "//STEP01 EXEC PGM=TEST\n"
            "//IN DD DSN=INPUT,DISP=SHR\n"
        )
        result = modernize_jcl_from_sources({"test.jcl": jcl})
        assert result.status == JclProfileStatus.FULL
        assert len(result.unsupported_constructs) == 0
        assert result.profile.application.validate() == []


# ---------------------------------------------------------------------------
# 8. No regression to existing COBOL pipeline
# ---------------------------------------------------------------------------

class TestNoRegression:
    """Verify existing JCL tests still pass (baseline preserved)."""

    def test_parser_regression(self) -> None:
        from engine.transformation.jcl_parser import JclParser

        jcl = (
            "//TESTJOB JOB CLASS=A\n"
            "//STEP01 EXEC PGM=CALC\n"
            "//INPUT DD DSN=MY.DATA,DISP=SHR\n"
        )
        app = JclParser().parse_application({"test.jcl": jcl})
        assert len(app.jobs) == 1
        assert app.jobs[0].name == "TESTJOB"
        assert app.jobs[0].steps[0].exec_.program == "CALC"

    def test_discovery_still_works(self) -> None:
        from engine.transformation.jcl_discovery import JclDiscovery

        discovery = JclDiscovery()
        jcl_app = discovery.discover(FIXTURES)
        assert len(jcl_app.jobs) == 4
        names = {j.name for j in jcl_app.jobs}
        assert names == {"SIMPLEB", "PAYORDER", "CONDJOB", "UNSUPP"}


# ---------------------------------------------------------------------------
# 9. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Consumer must not silently swallow errors."""

    def test_nonexistent_path(self) -> None:
        with pytest.raises(FileNotFoundError):
            modernize_jcl_workload("/nonexistent/path/xyz")

    def test_file_not_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "not_a_dir.jcl"
        f.write_text("//JOB JOB\n")
        with pytest.raises(ValueError, match="not a directory"):
            modernize_jcl_workload(f)


# ---------------------------------------------------------------------------
# 10. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Consumer results must be deterministic."""

    def test_two_calls_identical(self) -> None:
        a = modernize_jcl_workload(FIXTURES, application_id="det-a")
        b = modernize_jcl_workload(FIXTURES, application_id="det-b")
        assert a.status == b.status
        assert a.job_count == b.job_count
        assert a.step_count == b.step_count
        assert a.unsupported_constructs == b.unsupported_constructs
        assert len(a.diagnostics) == len(b.diagnostics)

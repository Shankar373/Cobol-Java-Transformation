"""JCL → Java/Spring Batch representation tests — generated representation.

Covers:
- generated Spring Batch representation (jobs, steps, tasklets, flows)
- dependency semantics in flow edges
- dataset relationships in batch edges
- determinism of generated names
- unsupported construct handling (PARTIAL, explicit diagnostics)
- profile status derivation
"""

from __future__ import annotations

from pathlib import Path

from engine.jcl.diagnostics import JclDiagnosticCode, JclDiagnosticLevel
from engine.transformation.jcl_parser import JclParser
from engine.transformation.jcl_spring_batch_ir import (
    EXIT_STATUS_ANY,
    EXIT_STATUS_CONDITIONAL,
    EXIT_STATUS_FAILED,
    EXIT_STATUS_SUCCESS,
    SpringBatchResourceType,
)
from engine.transformation.jcl_to_spring_batch import (
    JclProfileStatus,
    modernize_jcl,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workload-jcl"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def modernize(source: str, path: str = "test.jcl"):
    app = JclParser().parse_application({path: source})
    return modernize_jcl(app, {path: source})


class TestGeneratedRepresentation:
    """The Spring Batch representation produced from JCL."""

    def test_job_bean_and_steps(self) -> None:
        profile = modernize(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        job = profile.application.get_job("SIMPLEB")
        assert job is not None
        assert job.job_bean == "SimplebJob"
        assert job.start_step == "Step01"
        assert [s.name for s in job.steps] == ["Step01", "Step02"]
        assert job.steps[0].tasklet_bean == "Step01Tasklet"
        assert job.steps[0].program == "SIMPLE-CALC"

    def test_default_sequential_flows(self) -> None:
        profile = modernize(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        job = profile.application.get_job("SIMPLEB")
        assert len(job.flows) == 1
        assert job.flows[0].source == "Step01"
        assert job.flows[0].target == "Step02"
        assert job.flows[0].on_status == EXIT_STATUS_SUCCESS

    def test_resource_mapping(self) -> None:
        profile = modernize(load_fixture("order_flow.jcl"), "order_flow.jcl")
        job = profile.application.get_job("PAYORDER")
        input_res = job.steps[0].resources[0]
        assert input_res.name == "INPUT"
        assert input_res.resource_type == SpringBatchResourceType.INPUT
        assert input_res.dsn == "ORDER.INPUT"
        assert input_res.step_ref == "Step01"

        sysout_res = next(
            r for r in job.steps[2].resources if r.name == "SYSPRINT"
        )
        assert sysout_res.resource_type == SpringBatchResourceType.SYSOUT_LOG

    def test_generated_dataset_edges(self) -> None:
        profile = modernize(load_fixture("order_flow.jcl"), "order_flow.jcl")
        edges = profile.application.dataset_edges
        expected = {
            ("ORDER.INPUT", "", "Step01"),
            ("&&WORK1", "Step01", "Step02"),
            ("ORDER.OUTPUT", "Step03", ""),
        }
        got = {(e.dataset, e.producer, e.consumer) for e in edges}
        assert expected <= got

    def test_resource_inventory(self) -> None:
        profile = modernize(load_fixture("order_flow.jcl"), "order_flow.jcl")
        dsn_set = {r.dsn for r in profile.application.resources}
        assert {"ORDER.INPUT", "&&WORK1", "ORDER.OUTPUT"} <= dsn_set

    def test_application_validate_clean(self) -> None:
        profile = modernize(load_fixture("order_flow.jcl"), "order_flow.jcl")
        assert profile.application.validate() == []

    def test_job_parameters_propagated(self) -> None:
        profile = modernize(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        job = profile.application.get_job("SIMPLEB")
        assert ("CLASS", "A") in job.parameters


class TestConditionalFlowSemantics:
    """COND handling in generated flow edges."""

    def test_cond_only_maps_to_failed(self) -> None:
        profile = modernize(load_fixture("conditional.jcl"), "conditional.jcl")
        job = profile.application.get_job("CONDJOB")
        flow = next(f for f in job.flows if f.target == "Step02")
        assert flow.on_status == EXIT_STATUS_FAILED

    def test_cond_even_maps_to_any(self) -> None:
        profile = modernize(load_fixture("conditional.jcl"), "conditional.jcl")
        job = profile.application.get_job("CONDJOB")
        flow = next(f for f in job.flows if f.target == "Step03")
        assert flow.on_status == EXIT_STATUS_ANY

    def test_cond_rc_maps_to_conditional(self) -> None:
        profile = modernize(load_fixture("conditional.jcl"), "conditional.jcl")
        job = profile.application.get_job("CONDJOB")
        flow = next(f for f in job.flows if f.target == "Step04")
        assert flow.on_status == EXIT_STATUS_CONDITIONAL
        target_step = next(s for s in job.steps if s.name == "Step04")
        assert target_step.raw_condition == "(0,NE)"

    def test_step_activation_descriptors(self) -> None:
        profile = modernize(load_fixture("conditional.jcl"), "conditional.jcl")
        job = profile.application.get_job("CONDJOB")
        activations = {s.name: s.activation for s in job.steps}
        assert activations["Step01"] == EXIT_STATUS_SUCCESS
        assert activations["Step02"] == EXIT_STATUS_FAILED
        assert activations["Step03"] == EXIT_STATUS_ANY
        assert activations["Step04"] == EXIT_STATUS_CONDITIONAL


class TestUnsupportedHandling:
    """Unsupported constructs must be explicit, never silent."""

    def test_unsupported_profile_status(self) -> None:
        profile = modernize(load_fixture("unsupported.jcl"), "unsupported.jcl")
        assert profile.status == JclProfileStatus.PARTIAL
        assert profile.has_errors is True

    def test_unsupported_constructs_listed(self) -> None:
        profile = modernize(load_fixture("unsupported.jcl"), "unsupported.jcl")
        unsupported = set(profile.unsupported_constructs)
        assert "PROC steps / procedure definitions" in unsupported
        assert "IF/THEN/ELSE/ENDIF control blocks" in unsupported
        assert "statements outside the supported subset" in unsupported
        assert "DD continuations" in unsupported

    def test_proc_step_not_dropped(self) -> None:
        profile = modernize(load_fixture("unsupported.jcl"), "unsupported.jcl")
        job = profile.application.get_job("UNSUPP")
        proc_step = next(s for s in job.steps if s.source_step == "STEP04")
        assert proc_step.program == ""
        assert proc_step.tasklet_bean == "Step04Tasklet"

    def test_conditional_warning_present(self) -> None:
        profile = modernize(load_fixture("conditional.jcl"), "conditional.jcl")
        warnings = [d for d in profile.diagnostics if d.level == JclDiagnosticLevel.WARNING]
        assert any(d.code == JclDiagnosticCode.PARTIAL_COND_SEMANTICS for d in warnings)

    def test_no_jes_equivalence_note(self) -> None:
        profile = modernize(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        notes = [
            d for d in profile.diagnostics
            if d.code == JclDiagnosticCode.PROFILE_NOTED and "no JES/z/OS" in d.message
        ]
        assert len(notes) == 1


class TestProfileStatus:
    """Status derivation."""

    def test_full_status(self) -> None:
        profile = modernize(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        assert profile.status == JclProfileStatus.FULL
        assert profile.has_errors is False

    def test_empty_status(self) -> None:
        from engine.transformation.ir import JclApplication

        app = JclApplication()
        profile = modernize_jcl(app, {})
        assert profile.status == JclProfileStatus.EMPTY

    def test_supported_constructs_contract(self) -> None:
        profile = modernize(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        supported = set(profile.supported_constructs)
        assert "JOB" in supported
        assert "EXEC-PGM" in supported
        assert "DD-DATASET" in supported
        assert "STEP-ORDER" in supported


class TestDeterminism:
    """Generated representation must be deterministic."""

    def test_two_profiles_identical(self) -> None:
        source = load_fixture("order_flow.jcl")
        left = modernize(source, "order_flow.jcl")
        right = modernize(source, "order_flow.jcl")
        left_job = left.application.get_job("PAYORDER")
        right_job = right.application.get_job("PAYORDER")
        assert [s.tasklet_bean for s in left_job.steps] == [s.tasklet_bean for s in right_job.steps]
        assert [(f.source, f.on_status, f.target) for f in left_job.flows] == [
            (f.source, f.on_status, f.target) for f in right_job.flows
        ]
        assert [e.dsn for e in left.application.resources] == [
            e.dsn for e in right.application.resources
        ]

    def test_bean_naming(self) -> None:
        profile = modernize(load_fixture("order_flow.jcl"), "order_flow.jcl")
        job = profile.application.get_job("PAYORDER")
        assert job.job_bean == "PayorderJob"
        assert job.steps[0].tasklet_bean == "Step01Tasklet"
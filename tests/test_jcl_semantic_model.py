"""JCL semantic model tests — the JCL modernization lane.

Covers:
- parser → semantic model regression
- step ordering
- dataset relationships (producer/consumer)
- dependency semantics (COND)
- unsupported construct handling (explicit diagnostics)
- determinism
"""

from __future__ import annotations

from pathlib import Path

from engine.jcl.builder import JclSemanticBuilder
from engine.jcl.diagnostics import JclDiagnosticCode, JclDiagnosticLevel
from engine.jcl.model import (
    JclControlKind,
    JclDatasetUse,
    JclResourceKind,
)
from engine.transformation.jcl_parser import JclParser

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workload-jcl"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def build(source: str, path: str = "test.jcl"):
    app = JclParser().parse_application({path: source})
    builder = JclSemanticBuilder()
    model = builder.build(app, {path: source})
    return model, builder.diagnostics


class TestParserModelRegression:
    """Parser output must flow into the semantic model unchanged."""

    def test_simple_job(self) -> None:
        model, _ = build(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        job = model.get_job("SIMPLEB")
        assert job is not None
        assert model.step_order("SIMPLEB") == ["STEP01", "STEP02"]
        assert job.steps[0].exec_.program == "SIMPLE-CALC"
        assert job.steps[1].exec_.program == "SIMPLE-REPORT"

    def test_job_parameters_preserved(self) -> None:
        model, _ = build(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        job = model.get_job("SIMPLEB")
        assert job.parameters is not None
        assert job.parameters.get("CLASS") == "A"

    def test_dd_resources_preserved(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        step1 = model.get_step("PAYORDER", "STEP01")
        assert len(step1.resources) == 2
        input_dd = step1.resources[0]
        assert input_dd.dataset == "ORDER.INPUT"
        assert input_dd.kind == JclResourceKind.DATASET
        assert input_dd.dataset_use == JclDatasetUse.INPUT
        assert input_dd.is_temporary is False

    def test_temporary_dataset_kind(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        step1 = model.get_step("PAYORDER", "STEP01")
        work = step1.resources[1]
        assert work.dataset == "&&WORK1"
        assert work.kind == JclResourceKind.TEMPORARY
        assert work.is_temporary is True

    def test_sysout_resource_kind(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        step3 = model.get_step("PAYORDER", "STEP03")
        sysout = step3.resources[1]
        assert sysout.name == "SYSPRINT"
        assert sysout.kind == JclResourceKind.SYSOUT

    def test_model_validate_clean(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        assert model.validate() == []


class TestStepOrder:
    """Step ordering semantics."""

    def test_order_flow_step_order(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        assert model.step_order("PAYORDER") == ["STEP01", "STEP02", "STEP03"]

    def test_conditional_step_order(self) -> None:
        model, _ = build(load_fixture("conditional.jcl"), "conditional.jcl")
        assert model.step_order("CONDJOB") == ["STEP01", "STEP02", "STEP03", "STEP04"]

    def test_order_index_assignment(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        job = model.get_job("PAYORDER")
        indexes = [s.order_index for s in job.steps]
        assert indexes == [0, 1, 2]


class TestDatasetRelationships:
    """Producer/consumer dataset relationships."""

    def test_external_input_flow(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        job = model.get_job("PAYORDER")
        flow = next(f for f in job.dataset_flows if f.dataset == "ORDER.INPUT")
        assert flow.producer == ""
        assert flow.consumers == ("STEP01",)

    def test_temporary_dataset_flow(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        job = model.get_job("PAYORDER")
        flow = next(f for f in job.dataset_flows if f.dataset == "&&WORK1")
        assert flow.producer == "STEP01"
        assert flow.consumers == ("STEP02",)

    def test_output_dataset_flow_no_consumer(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        job = model.get_job("PAYORDER")
        flow = next(f for f in job.dataset_flows if f.dataset == "ORDER.OUTPUT")
        assert flow.producer == "STEP03"
        assert flow.consumers == ()

    def test_dataset_inventory(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        names = {inv.name for inv in model.dataset_inventory}
        assert {"ORDER.INPUT", "&&WORK1", "ORDER.OUTPUT"} <= names

    def test_dataset_references(self) -> None:
        model, _ = build(load_fixture("order_flow.jcl"), "order_flow.jcl")
        refs = model.dataset_references("PAYORDER")
        assert ("STEP01", "INPUT", "ORDER.INPUT") in refs
        assert ("STEP02", "WORK1", "&&WORK1") in refs


class TestDependencySemantics:
    """Step activation dependency semantics."""

    def test_sequential_dependencies(self) -> None:
        model, _ = build(load_fixture("simple_batch.jcl"), "simple_batch.jcl")
        job = model.get_job("SIMPLEB")
        by_target = {dep.target: dep for dep in job.dependencies}
        assert by_target["STEP01"].source == ""
        assert by_target["STEP01"].control_kind == JclControlKind.SEQUENTIAL
        assert by_target["STEP02"].source == "STEP01"
        assert by_target["STEP02"].control_kind == JclControlKind.SEQUENTIAL
        assert by_target["STEP02"].exit_status == "SUCCESS"

    def test_only_and_even_and_rc(self) -> None:
        model, _ = build(load_fixture("conditional.jcl"), "conditional.jcl")
        job = model.get_job("CONDJOB")
        by_target = {dep.target: dep for dep in job.dependencies}
        assert by_target["STEP02"].control_kind == JclControlKind.ONLY
        assert by_target["STEP02"].exit_status == "FAILED"
        assert by_target["STEP03"].control_kind == JclControlKind.EVEN
        assert by_target["STEP03"].exit_status == "ANY"
        assert by_target["STEP04"].control_kind == JclControlKind.RETURN_CODE
        assert by_target["STEP04"].exit_status == "CONDITIONAL"
        assert by_target["STEP04"].raw_condition == "(0,NE)"


class TestUnsupportedConstructs:
    """Unsupported constructs must produce explicit diagnostics."""

    def test_unsupported_construct_scan(self) -> None:
        _, diagnostics = build(load_fixture("unsupported.jcl"), "unsupported.jcl")
        errors = diagnostics.errors
        codes = {d.code for d in errors}
        assert JclDiagnosticCode.UNSUPPORTED_STATEMENT in codes  # JCLLIB
        assert JclDiagnosticCode.UNSUPPORTED_CONTROL_BLOCK in codes  # IF / ENDIF
        assert JclDiagnosticCode.UNSUPPORTED_CONTINUATION in codes  # split line
        assert JclDiagnosticCode.UNSUPPORTED_PROCEDURE in codes  # EXEC PROC=

    def test_unsupported_never_silently_skipped(self) -> None:
        _, diagnostics = build(load_fixture("unsupported.jcl"), "unsupported.jcl")
        assert len(diagnostics.errors) >= 4
        for error in diagnostics.errors:
            assert error.level == JclDiagnosticLevel.ERROR

    def test_proc_step_flagged(self) -> None:
        model, diagnostics = build(load_fixture("unsupported.jcl"), "unsupported.jcl")
        step4 = model.get_step("UNSUPP", "STEP04")
        assert step4.exec_.mode.value == "PROCEDURE"
        proc_diags = [d for d in diagnostics.all if d.code == JclDiagnosticCode.UNSUPPORTED_PROCEDURE]
        assert any(d.step == "STEP04" for d in proc_diags)

    def test_symbolic_reference_warning(self) -> None:
        _, diagnostics = build(load_fixture("unsupported.jcl"), "unsupported.jcl")
        symbol_diags = [d for d in diagnostics.all if d.code == JclDiagnosticCode.UNRESOLVED_SYMBOL]
        assert any(d.level == JclDiagnosticLevel.WARNING for d in symbol_diags)

    def test_dummy_dd_warning(self) -> None:
        model, diagnostics = build(load_fixture("unsupported.jcl"), "unsupported.jcl")
        say = model.get_step("UNSUPP", "STEP05")
        dummy = next(r for r in say.resources if r.name == "SAY")
        assert dummy.kind == JclResourceKind.UNKNOWN
        dummy_diags = [d for d in diagnostics.all if d.code == JclDiagnosticCode.DUMMY_RESOURCE]
        assert len(dummy_diags) == 1
        assert dummy_diags[0].step == "STEP05"

    def test_conditional_warning(self) -> None:
        _, diagnostics = build(load_fixture("conditional.jcl"), "conditional.jcl")
        cond_diags = [d for d in diagnostics.all if d.code == JclDiagnosticCode.PARTIAL_COND_SEMANTICS]
        assert len(cond_diags) == 1  # only the return-code condition


class TestDeterminism:
    """Semantic modeling must be deterministic."""

    def test_two_builds_identical(self) -> None:
        source = load_fixture("order_flow.jcl")
        model_a, diag_a = build(source, "order_flow.jcl")
        model_b, diag_b = build(source, "order_flow.jcl")
        assert model_a.step_order("PAYORDER") == model_b.step_order("PAYORDER")
        assert [f.dataset for f in model_a.get_job("PAYORDER").dataset_flows] == [
            f.dataset for f in model_b.get_job("PAYORDER").dataset_flows
        ]
        assert [d.code for d in diag_a.all] == [d.code for d in diag_b.all]


class TestValidation:
    """Semantic model validation."""

    def test_validate_proc_hidden(self) -> None:
        model, _ = build(load_fixture("unsupported.jcl"), "unsupported.jcl")
        errors = model.validate()
        assert errors == []  # model consistency, not construct support

    def test_duplicate_step_detected(self) -> None:
        jcl = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=A\n//STEP01 EXEC PGM=B"
        model, _ = build(jcl, "dup.jcl")
        assert model.validate() != []
        assert any("Duplicate step" in e for e in model.validate())

    def test_empty_source(self) -> None:
        model, diagnostics = build("", "x.jcl")
        assert all(not j.steps for j in model.jobs)
        assert diagnostics.all == ()
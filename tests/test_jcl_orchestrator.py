"""Roadmap unit 6: a JCL job becomes a Java launcher that runs its steps in order.

Planning, COND parsing, refusals and rendering are hermetic; the run-time behaviour
(real generated programs, dataset hand-over, return codes, bypass rules) is proven in
``tests/integration/test_jcl_orchestrator_oracle.py``.
"""

from __future__ import annotations

import pytest

from engine.jcl.orchestrator import (
    CondTest,
    dataset_path,
    orchestrate,
    parse_cond,
    plan_job,
    render_runner,
)
from engine.transformation.jcl_parser import JclParser

CLASSES = {"PRODUCER": "Producer", "CONSUMER": "Consumer"}

JOB = """\
//SEQJOB   JOB CLASS=A
//STEP1    EXEC PGM=PRODUCER
//OUTDD    DD DSN=HR.DATA,DISP=(NEW,CATLG)
//SYSOUT   DD SYSOUT=*
//TMP      DD DSN=&&WORK,DISP=(NEW,PASS)
//STEP2    EXEC PGM=CONSUMER,COND=(4,LT)
//INDD     DD DSN=HR.DATA,DISP=SHR
"""


def _plan(jcl: str, classes: dict[str, str] | None = None):
    return plan_job(JclParser().parse_jobs(jcl)[0], CLASSES if classes is None else classes)


class TestPlanning:
    def test_steps_programs_and_dd_paths(self):
        plan = _plan(JOB)
        assert plan.runnable, plan.refusals
        first, second = plan.steps
        assert (first.name, first.program, first.main_class) == ("STEP1", "PRODUCER", "Producer")
        # SYSOUT is not bound; DISP defaults follow JCL (NEW is deleted unless catalogued/kept/passed)
        assert [(d.name, d.path, d.status, d.normal) for d in first.dds] == [
            ("OUTDD", "HR.DATA", "NEW", "CATLG"), ("TMP", "_tmp/WORK", "NEW", "PASS")]
        assert [(d.name, d.path, d.status, d.normal) for d in second.dds] == [
            ("INDD", "HR.DATA", "SHR", "KEEP")]
        assert second.conds == (CondTest(4, "LT"),)

    def test_dataset_paths(self):
        assert dataset_path("HR.MASTER") == "HR.MASTER"
        assert dataset_path("&&WORK") == "_tmp/WORK"


class TestCond:
    @pytest.mark.parametrize("text,expected", [
        ("(4,LT)", (CondTest(4, "LT"),)),
        ("(0,NE,STEP1)", (CondTest(0, "NE", "STEP1"),)),
        ("((4,LT),(8,EQ,S2))", (CondTest(4, "LT"), CondTest(8, "EQ", "S2"))),
    ])
    def test_supported_forms(self, text, expected):
        assert parse_cond(text) == expected

    @pytest.mark.parametrize("text", ["EVEN", "ONLY", "(4,XX)", "(4)", "(4,LT),EVEN", "", "(a,LT)"])
    def test_other_forms_are_not_parsed(self, text):
        assert parse_cond(text) is None


class TestRefusals:
    def _reasons(self, jcl: str, classes=None) -> str:
        plan = _plan(jcl, classes)
        assert not plan.runnable
        return "; ".join(plan.refusals)

    def test_a_program_that_is_not_in_the_application(self):
        assert "SORT" in self._reasons("//J JOB\n//S EXEC PGM=SORT\n")

    def test_dummy_dd_on_a_program_step(self):
        assert "DUMMY" in self._reasons(
            "//J JOB\n//S EXEC PGM=PRODUCER\n//OUTDD DD DUMMY\n")

    def test_later_generations_and_pds_members(self):
        assert "(+2)" in self._reasons(
            "//J JOB\n//S EXEC PGM=PRODUCER\n//OUTDD DD DSN=HR.G(+2),DISP=NEW\n")
        assert "PDS member" in self._reasons(
            "//J JOB\n//S EXEC PGM=PRODUCER\n//OUTDD DD DSN=HR.PDS(MEM),DISP=NEW\n")

    def test_even_and_only(self):
        assert "COND=EVEN" in self._reasons("//J JOB\n//S EXEC PGM=PRODUCER,COND=EVEN\n")

    def test_if_blocks(self):
        assert "IF/THEN" in self._reasons(
            "//J JOB\n// IF (A.RC = 0) THEN\n//S EXEC PGM=PRODUCER\n// ENDIF\n")

    def test_unexpanded_procedure(self):
        assert "PGM=" in self._reasons("//J JOB\n//S EXEC NOSUCHPROC\n")

    def test_job_level_dd(self):
        assert "job-level" in self._reasons(
            "//J JOB\n//JOBLIB DD DSN=A.B,DISP=SHR\n//S EXEC PGM=PRODUCER\n")

    def test_dd_name_the_lowering_does_not_certify(self):
        assert "plain ddname" in self._reasons(
            "//J JOB\n//S EXEC PGM=PRODUCER\n//OUT#1 DD DSN=A.B,DISP=NEW\n")

    def test_empty_job(self):
        assert "no steps" in self._reasons("//J JOB CLASS=A\n")

    def test_render_refuses_a_refused_plan(self):
        with pytest.raises(ValueError, match="not runnable"):
            render_runner(_plan("//J JOB\n//S EXEC PGM=NOPE\n"))


class TestRendering:
    def test_runner_source_carries_the_plan(self):
        source = render_runner(_plan(JOB), "JobSeqRunner")
        assert "public class JobSeqRunner" in source
        assert 'new Step("STEP1", "Producer"' in source
        assert 'new Dd("OUTDD", "HR.DATA", "", 0, "NEW", "CATLG", null, false)' in source
        assert 'new Cond(4, "LT", "")' in source
        assert "gnucobol" not in source.lower()

    def test_rendering_is_deterministic(self):
        assert render_runner(_plan(JOB)) == render_runner(_plan(JOB))

    def test_orchestrate_renders_only_runnable_jobs(self):
        app = JclParser().parse_application({
            "a.jcl": JOB, "b.jcl": "//BADJOB JOB\n//S EXEC PGM=NOPE\n"})
        result = orchestrate(app, CLASSES)
        assert list(result.files) == ["JobSeqjobRunner"]
        assert [p.runnable for p in result.plans] == [True, False]


def test_program_name_stops_at_the_next_exec_parameter():
    # Regression: PGM=CONSUMER,COND=(4,LT) used to yield the program "CONSUMER,COND=(4,LT)".
    jcl = "//J JOB CLASS=A\n//S EXEC PGM=CONSUMER,COND=(4,LT),REGION=0M\n"
    step = JclParser().parse_jobs(jcl)[0].steps[0]
    assert step.exec_.program == "CONSUMER"
    assert step.condition.code == "(4,LT)"

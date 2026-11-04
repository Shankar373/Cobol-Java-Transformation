"""Roadmap unit 8: inline data, DUMMY, dispositions, GDG references and utility steps.

Hermetic checks of parsing, planning and refusals. The behaviour of the generated launcher
(IEFBR14, IEBGENER, IDCAMS, GDG roll-off, JCL errors) is run in
``tests/integration/test_jcl_utilities_runtime.py``.
"""

from __future__ import annotations

import pytest

from engine.jcl.orchestrator import parse_disposition, parse_idcams, plan_job, render_runner
from engine.transformation.jcl_parser import JclParser

CLASSES = {"PRODUCER": "Producer"}


def _plan(jcl: str):
    return plan_job(JclParser().parse_jobs(jcl)[0], CLASSES)


class TestParserCapturesInlineDataAndDummy:
    JCL = (
        "//J JOB CLASS=A\n//S EXEC PGM=IEBGENER\n//SYSIN DD DUMMY\n//SYSUT1 DD *\n"
        "AAA\n  BBB\n/*\n//SYSUT2 DD DSN=A.B,DISP=(NEW,CATLG)\n"
    )

    def test_inline_records_are_kept_verbatim(self):
        dds = {d.name: d for d in JclParser().parse_jobs(self.JCL)[0].steps[0].dd_statements}
        assert dds["SYSUT1"].inline_data == ("AAA", "  BBB")
        assert dds["SYSUT1"].is_inline

    def test_dummy_and_the_dd_after_the_stream(self):
        dds = {d.name: d for d in JclParser().parse_jobs(self.JCL)[0].steps[0].dd_statements}
        assert dds["SYSIN"].is_dummy
        assert dds["SYSUT2"].dataset == "A.B"

    def test_a_stream_ends_at_the_next_statement_without_a_delimiter(self):
        jcl = "//J JOB CLASS=A\n//S EXEC PGM=P\n//SYSIN DD *\nX\nY\n//T EXEC PGM=Q\n"
        job = JclParser().parse_jobs(jcl)[0]
        assert job.steps[0].dd_statements[0].inline_data == ("X", "Y")
        assert [s.name for s in job.steps] == ["S", "T"]


class TestDisposition:
    @pytest.mark.parametrize("text,expected", [
        ("SHR", ("SHR", "KEEP")),
        ("OLD", ("OLD", "KEEP")),
        ("NEW", ("NEW", "DELETE")),  # JCL: a NEW dataset with no normal disposition is deleted
        ("(NEW,CATLG,DELETE)", ("NEW", "CATLG")),
        ("(OLD,DELETE)", ("OLD", "DELETE")),
        ("(MOD,PASS)", ("MOD", "PASS")),
        ("(,CATLG)", ("NEW", "CATLG")),
        ("", ("NEW", "DELETE")),
    ])
    def test_status_and_normal(self, text, expected):
        assert parse_disposition(text) == expected


class TestIdcams:
    def test_supported_commands(self):
        commands, problems = parse_idcams((
            "  DELETE HR.OLD PURGE",
            "  DELETE (HR.OTHER) NONVSAM",
            "  DEFINE GDG (NAME(HR.GDG) -",
            "     LIMIT(3) NOEMPTY SCRATCH)",
            "  REPRO INFILE(IN) OUTFILE(OUT)",
            "  SET MAXCC = 0",
            "  /* a comment */",
        ))
        assert not problems, problems
        assert commands == (
            ("DELETE", "HR.OLD"), ("DELETE", "HR.OTHER"), ("DEFINE_GDG", "HR.GDG", "3"),
            ("REPRO", "IN", "OUT"), ("SET_MAXCC", "0"),
        )

    @pytest.mark.parametrize("record,fragment", [
        ("  LISTCAT ENTRIES(HR.A)", "LISTCAT"),
        ("  DEFINE CLUSTER (NAME(HR.K) KEYS(4 0))", "DEFINE CLUSTER"),
        ("  DEFINE GDG (NAME(HR.G) LIMIT(0))", "outside 1..255"),
        ("  DEFINE GDG (NAME(HR.G) LIMIT(5) EMPTY)", "EMPTY"),
        ("  DELETE HR.A CATALOG(X)", "DELETE"),
        ("  IF LASTCC = 0 THEN SET MAXCC = 4", "IF LASTCC"),
    ])
    def test_everything_else_is_refused(self, record, fragment):
        commands, problems = parse_idcams((record,))
        assert any(fragment in p for p in problems), problems

    def test_empty_sysin_is_refused(self):
        assert parse_idcams(()) == ((), ["IDCAMS SYSIN carries no command"])


class TestUtilityPlanning:
    def test_the_three_utilities_are_planned(self):
        plan = _plan(
            "//J JOB CLASS=A\n//A EXEC PGM=IEFBR14\n//D DD DSN=A.B,DISP=(NEW,CATLG)\n"
            "//B EXEC PGM=IEBGENER\n//SYSIN DD DUMMY\n//SYSUT1 DD DSN=A.B,DISP=SHR\n"
            "//SYSUT2 DD DSN=A.C,DISP=(NEW,CATLG)\n"
            "//C EXEC PGM=IDCAMS\n//SYSIN DD *\n  DELETE A.C\n/*\n"
        )
        assert plan.runnable, plan.refusals
        assert [s.utility for s in plan.steps] == ["IEFBR14", "IEBGENER", "IDCAMS"]
        assert plan.steps[2].commands == (("DELETE", "A.C"),)

    def test_a_utility_is_not_a_program_class(self):
        step = _plan("//J JOB CLASS=A\n//A EXEC PGM=IEFBR14\n").steps[0]
        assert (step.main_class, step.utility) == ("", "IEFBR14")

    def test_iebgener_needs_both_datasets(self):
        plan = _plan("//J JOB CLASS=A\n//B EXEC PGM=IEBGENER\n//SYSUT1 DD DSN=A.B,DISP=SHR\n")
        assert any("SYSUT2" in r for r in plan.refusals)

    def test_idcams_needs_an_inline_sysin(self):
        plan = _plan("//J JOB CLASS=A\n//C EXEC PGM=IDCAMS\n")
        assert any("inline SYSIN" in r for r in plan.refusals)

    def test_idcams_repro_must_name_dds_of_the_step(self):
        plan = _plan(
            "//J JOB CLASS=A\n//C EXEC PGM=IDCAMS\n//SYSIN DD *\n  REPRO INFILE(A) OUTFILE(B)\n/*\n")
        assert any("REPRO names DD A" in r for r in plan.refusals)

    def test_unsupported_idcams_command_refuses_the_job(self):
        plan = _plan("//J JOB CLASS=A\n//C EXEC PGM=IDCAMS\n//SYSIN DD *\n  LISTCAT\n/*\n")
        assert not plan.runnable


class TestGenerations:
    JCL = (
        "//G JOB CLASS=A\n//S EXEC PGM=PRODUCER\n"
        "//OUTDD DD DSN=HR.GDG(+1),DISP=(NEW,CATLG)\n//INDD DD DSN=HR.GDG(-1),DISP=SHR\n"
        "//PREV DD DSN=HR.GDG(0),DISP=SHR\n"
    )

    def test_relative_generations_are_planned_per_dd(self):
        plan = _plan(self.JCL)
        assert plan.runnable, plan.refusals
        got = [(d.name, d.gdg_base, d.gdg_rel) for d in plan.steps[0].dds]
        assert got == [("OUTDD", "HR.GDG", 1), ("INDD", "HR.GDG", -1), ("PREV", "HR.GDG", 0)]
        assert plan.gdg_bases == ("HR.GDG",)

    def test_runner_declares_the_base_and_resolves_at_runtime(self):
        source = render_runner(_plan(self.JCL))
        assert 'GDG_BASES = new String[] {"HR.GDG"}' in source
        assert 'new Dd("OUTDD", "", "HR.GDG", 1, "NEW", "CATLG", null, false)' in source
        assert "gnucobol" not in source.lower()

"""Roadmap unit 5: JCL procedures, symbolic parameters and SET are expanded before parsing.

Before this unit ``//S1 EXEC PAYPROC`` parsed as a step with no program and ``&SYM``
references were never substituted, so the DD names, datasets and programs inside
procedures were invisible to discovery. Expansion is textual and deterministic; what it
cannot expand faithfully (missing or nested procedures, ``PARM.step`` overrides,
unresolved symbols) is reported and refused, never approximated. IF/THEN/ELSE/ENDIF is
recorded on the enclosed steps but not evaluated, and the builder still refuses it.
"""

from __future__ import annotations

from pathlib import Path

from api.ingestion import discover_application
from engine.jcl.builder import JclSemanticBuilder
from engine.jcl.diagnostics import JclDiagnosticCode
from engine.jcl.preprocess import expand, procedure_members
from engine.transformation.jcl_parser import JclParser

INSTREAM = """\
//PAYJOB   JOB CLASS=A
// SET HLQ=HR
//PAYPROC  PROC DSN=DEFAULT.DS,PGMN=PAYROLL
//RUN      EXEC PGM=&PGMN
//EMPIN    DD DSN=&HLQ..&DSN,DISP=SHR
//WORK     DD DSN=&&TMP,DISP=(NEW,PASS)
//SYSOUT   DD SYSOUT=*
//         PEND
//STEP1    EXEC PAYPROC,DSN=EMPLOYEES
//STEP2    EXEC PGM=REPORTER
//PAYIN    DD DSN=&HLQ..PAYMENTS,DISP=SHR
"""


def _steps(text: str, library: dict[str, str] | None = None):
    return {s.name: s for s in JclParser().parse_jobs(text, library)[0].steps}


def _dds(step):
    return {dd.name: dd for dd in step.dd_statements}


class TestExpansion:
    def test_instream_proc_expands_with_defaults_overrides_and_set(self):
        steps = _steps(INSTREAM)
        run = steps["STEP1.RUN"]
        assert run.exec_.program == "PAYROLL"  # default PGMN
        assert _dds(run)["EMPIN"].dataset == "HR.EMPLOYEES"  # SET HLQ + EXEC override DSN
        assert _dds(steps["STEP2"])["PAYIN"].dataset == "HR.PAYMENTS"  # SET at job level

    def test_temporary_dataset_marker_is_not_a_symbol(self):
        assert _dds(_steps(INSTREAM)["STEP1.RUN"])["WORK"].dataset == "&&TMP"

    def test_the_proc_definition_itself_is_not_a_step(self):
        assert list(_steps(INSTREAM)) == ["STEP1.RUN", "STEP2"]

    def test_exec_override_beats_default_and_symbol_with_period_terminator(self):
        text = INSTREAM.replace("DSN=EMPLOYEES", "DSN=OTHER,PGMN=ALTPGM")
        steps = _steps(text)
        assert steps["STEP1.RUN"].exec_.program == "ALTPGM"
        assert _dds(steps["STEP1.RUN"])["EMPIN"].dataset == "HR.OTHER"

    def test_expansion_is_deterministic(self):
        assert expand(INSTREAM).text == expand(INSTREAM).text

    def test_source_without_jcl_is_returned_unchanged(self):
        assert expand("just text").text == "just text"


class TestDdOverrides:
    def test_override_replaces_only_the_coded_parameters(self):
        text = INSTREAM.replace(
            "//STEP2    EXEC", "//RUN.EMPIN DD DSN=HR.OVERRIDE\n//STEP2    EXEC")
        dd = _dds(_steps(text)["STEP1.RUN"])["EMPIN"]
        assert (dd.dataset, dd.disposition) == ("HR.OVERRIDE", "SHR")  # DISP kept

    def test_override_of_an_absent_dd_adds_it(self):
        text = INSTREAM.replace(
            "//STEP2    EXEC", "//RUN.EXTRA DD DSN=HR.EXTRA,DISP=SHR\n//STEP2    EXEC")
        assert "EXTRA" in _dds(_steps(text)["STEP1.RUN"])

    def test_override_of_a_missing_step_is_reported(self):
        text = INSTREAM.replace(
            "//STEP2    EXEC", "//NOSTEP.EMPIN DD DSN=X\n//STEP2    EXEC")
        assert any("NOSTEP" in i.message for i in expand(text).issues)

    def test_unqualified_dd_after_proc_exec_is_reported(self):
        text = INSTREAM.replace(
            "//STEP2    EXEC", "//EMPIN DD DSN=X\n//STEP2    EXEC")
        assert any("names no procedure step" in i.message for i in expand(text).issues)


class TestLibraryProcedures:
    PROC_MEMBER = "//RUN EXEC PGM=&PGMN\n//EMPIN DD DSN=&DSN,DISP=SHR\n"
    JOB = "//LIBJOB JOB CLASS=A\n// SET PGMN=PAYROLL,DSN=HR.EMP\n//S1 EXEC MYPROC\n"

    def test_member_named_by_stem_supplies_the_procedure(self):
        steps = _steps(self.JOB, {"MYPROC.jcl": self.PROC_MEMBER})
        assert steps["S1.RUN"].exec_.program == "PAYROLL"
        assert _dds(steps["S1.RUN"])["EMPIN"].dataset == "HR.EMP"

    def test_member_with_proc_statement_is_registered_by_that_name(self):
        member = "//OTHER PROC PGMN=X\n" + self.PROC_MEMBER.replace("&DSN", "A.B")
        steps = _steps("//J JOB\n//S1 EXEC OTHER\n", {"anything.jcl": member})
        assert steps["S1.RUN"].exec_.program == "X"

    def test_procedure_member_is_not_a_job_stream(self):
        sources = {"MYPROC.jcl": self.PROC_MEMBER, "LIBJOB.jcl": self.JOB}
        assert procedure_members(sources) == {"MYPROC.jcl"}
        app = JclParser().parse_application(sources)
        assert [job.name for job in app.jobs] == ["LIBJOB"]
        assert app.jobs[0].steps[0].exec_.program == "PAYROLL"


class TestFailClosed:
    def _build(self, text: str, library: dict[str, str] | None = None):
        sources = {"JOB.jcl": text, **(library or {})}
        builder = JclSemanticBuilder()
        builder.build(JclParser().parse_application(sources), sources)
        return builder.diagnostics

    def test_expanded_job_builds_without_errors(self):
        diagnostics = self._build(INSTREAM)
        assert not diagnostics.errors, [d.message for d in diagnostics.errors]
        assert any(d.code is JclDiagnosticCode.PROCEDURE_EXPANDED for d in diagnostics.all)

    def test_unresolved_symbol_is_an_error(self):
        diagnostics = self._build("//J JOB\n//S EXEC PGM=&NOSUCH\n")
        assert any(d.code is JclDiagnosticCode.UNRESOLVED_SYMBOL for d in diagnostics.errors)

    def test_missing_procedure_is_an_error(self):
        diagnostics = self._build("//J JOB\n//S EXEC NOPROC\n")
        assert any(d.code is JclDiagnosticCode.UNSUPPORTED_PROCEDURE for d in diagnostics.errors)

    def test_nested_procedure_call_is_an_error(self):
        inner = "//INNER PROC\n//A EXEC PGM=P\n//   PEND\n"
        outer = "//OUTER PROC\n//B EXEC INNER\n//   PEND\n"
        diagnostics = self._build(
            "//J JOB\n" + inner + outer + "//S EXEC OUTER\n")
        assert any("nested" in d.message for d in diagnostics.errors)

    def test_parm_step_override_is_an_error(self):
        text = INSTREAM.replace("DSN=EMPLOYEES", "DSN=EMPLOYEES,PARM.RUN=X")
        assert any("PARM.RUN" in d.message for d in self._build(text).errors)


class TestExecKeywords:
    def test_caller_parm_applies_to_the_expanded_step(self):
        text = INSTREAM.replace("DSN=EMPLOYEES", "DSN=EMPLOYEES,PARM=FAST")
        step = _steps(text)["STEP1.RUN"]
        assert (step.exec_.parameters or {}).get("PARM") == "FAST"


class TestIfBlocks:
    JCL = (
        "//J JOB\n//S1 EXEC PGM=A\n// IF (S1.RC = 0) THEN\n//S2 EXEC PGM=B\n"
        "// ELSE\n//S3 EXEC PGM=C\n// ENDIF\n//S4 EXEC PGM=D\n"
    )

    def test_conditions_are_recorded_on_enclosed_steps(self):
        steps = _steps(self.JCL)
        assert steps["S1"].condition is None and steps["S4"].condition is None
        then, other = steps["S2"].condition, steps["S3"].condition
        assert then.condition_type == "IF" and then.if_expression == "(S1.RC = 0)"
        assert then.then_steps == ("S2",)
        assert other.if_expression == "NOT (S1.RC = 0)" and other.else_steps == ("S3",)

    def test_nested_if_combines_expressions(self):
        jcl = (
            "//J JOB\n// IF (A.RC = 0) THEN\n// IF (B.RC = 0) THEN\n//S EXEC PGM=X\n"
            "// ENDIF\n// ENDIF\n"
        )
        assert _steps(jcl)["S"].condition.if_expression == "(A.RC = 0) AND (B.RC = 0)"

    def test_the_builder_still_refuses_if_blocks(self):
        builder = JclSemanticBuilder()
        sources = {"J.jcl": self.JCL}
        builder.build(JclParser().parse_application(sources), sources)
        assert any(
            d.code is JclDiagnosticCode.UNSUPPORTED_CONTROL_BLOCK for d in builder.diagnostics.errors
        )


def test_discovery_sees_programs_and_bindings_through_a_procedure(tmp_path: Path):
    """A step that calls a procedure binds its COBOL ddnames (roadmap unit 4 + 5)."""
    (tmp_path / "PAYROLL.cob").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAYROLL.\n"
        "       ENVIRONMENT DIVISION.\n       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        "           SELECT EMP-FILE ASSIGN TO EMPIN\n               ORGANIZATION IS LINE SEQUENTIAL.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD EMP-FILE.\n"
        "       01 EMP-REC PIC X(20).\n       PROCEDURE DIVISION.\n           STOP RUN.\n",
        encoding="utf-8",
    )
    (tmp_path / "PAYJOB.jcl").write_text(INSTREAM, encoding="utf-8")
    result = discover_application(tmp_path, "proc").to_dict()
    row = next(b for b in result["dd_bindings"] if b["ddname"] == "EMPIN")
    assert (row["step"], row["status"], row["dataset"]) == ("STEP1.RUN", "BOUND", "HR.EMPLOYEES")

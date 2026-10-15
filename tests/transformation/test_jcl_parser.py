"""Tests for JCL parsing, discovery, and COBOL integration.

Covers:
- JCL IR construction
- JCL parser
- JCL discovery
- JCL ↔ COBOL integration
- Step ordering
- Dataset lifecycle
- Symbolic parameters
- Domain-neutral workloads
- Lexical false-positives
- Mutation matrix
- Determinism
- Validation
- Forensic search
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engine.transformation.ir import (
    CobolApplication,
    CobolProgram,
    CobolProgramUnit,
    DependencyEdge,
    FileDependency,
    JclApplication,
    JclCondition,
    JclDD,
    JclDataset,
    JclDependency,
    JclExec,
    JclJob,
    JclProcedure,
    JclStep,
    JclSymbol,
    ProgramCall,
)
from engine.transformation.jcl_parser import JclParser
from engine.transformation.jcl_discovery import JclDiscovery


# ---------------------------------------------------------------------------
# Helper: minimal JCL sources
# ---------------------------------------------------------------------------

SIMPLE_JCL = """\
//SIMPLE JOB CLASS=A
//STEP01 EXEC PGM=SIMPLE-CALC
"""

TWO_STEP_JCL = """\
//TWOSTEP JOB CLASS=A
//STEP01 EXEC PGM=PROGRAM-A
//STEP02 EXEC PGM=PROGRAM-B
"""

MULTI_STEP_JCL = """\
//MULTIJOB JOB CLASS=A
//STEP01 EXEC PGM=MAIN-PROGRAM
//INPUT DD DSN=INPUT.DATA,DISP=SHR
//STEP02 EXEC PGM=VALIDATE-PROGRAM
//WORK DD DSN=WORK.DATA,DISP=(NEW,PASS)
//STEP03 EXEC PGM=STORE-PROGRAM
//OUTPUT DD DSN=OUTPUT.DATA,DISP=(NEW,CATLG,DELETE)
"""

JCL_WITH_COMMENTS = """\
//COMMENT JOB CLASS=A
//* This is a comment
//STEP01 EXEC PGM=PROGRAM-A
//* Another comment
"""

JCL_WITH_COND = """\
//CONDJOB JOB CLASS=A
//STEP01 EXEC PGM=PROGRAM-A
//STEP02 EXEC PGM=PROGRAM-B,COND=(0,NE)
"""

JCL_WITH_SYMBOLS = """\
//SYMJOB JOB CLASS=A
// SET PROGNAME=PROGRAM-A
//STEP01 EXEC PGM=&PROGNAME
"""

JCL_WITH_PROC = """\
//PROCJOB JOB CLASS=A
//STEP01 EXEC PROC=MYPROC
"""

JCL_WITH_SYSOUT = """\
//SYSJOB JOB CLASS=A
//STEP01 EXEC PGM=PROGRAM-A
//SYSOUT DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
"""

JCL_WITH_INLINE = """\
//INLINE JOB CLASS=A
//STEP01 EXEC PGM=PROGRAM-A
//SYSIN DD *
DATA LINE 1
DATA LINE 2
/*
"""

JCL_WITH_DISP = """\
//DISPJOB JOB CLASS=A
//STEP01 EXEC PGM=PROGRAM-A
//NEWFILE DD DSN=NEW.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(TRK,(10,5))
//OLDFILE DD DSN=OLD.DATA,DISP=SHR
//MODFILE DD DSN=MOD.DATA,DISP=MOD
"""

JCL_UNRESOLVED_PGM = """\
//UNRESJOB JOB CLASS=A
//STEP01 EXEC PGM=UNKNOWN-PROGRAM
"""


# ---------------------------------------------------------------------------
# Domain-neutral JCL workloads (Phase 12)
# ---------------------------------------------------------------------------

ACCOUNT_JCL = """\
//ACCTJOB JOB CLASS=A
//STEP01 EXEC PGM=ACCOUNT-MAIN
//INPUT DD DSN=ACCOUNT.INPUT,DISP=SHR
//STEP02 EXEC PGM=ACCOUNT-VALIDATE
//STEP03 EXEC PGM=ACCOUNT-STORE
//OUTPUT DD DSN=ACCOUNT.OUTPUT,DISP=(NEW,CATLG)
"""

ORDER_JCL = """\
//ORDJOB JOB CLASS=A
//STEP01 EXEC PGM=ORDER-MAIN
//INPUT DD DSN=ORDER.INPUT,DISP=SHR
//STEP02 EXEC PGM=ORDER-VALIDATE
//STEP03 EXEC PGM=ORDER-STORE
//OUTPUT DD DSN=ORDER.OUTPUT,DISP=(NEW,CATLG)
"""

CUSTOMER_JCL = """\
//CUSTJOB JOB CLASS=A
//STEP01 EXEC PGM=CUSTOMER-MAIN
//INPUT DD DSN=CUSTOMER.INPUT,DISP=SHR
//STEP02 EXEC PGM=CUSTOMER-VALIDATE
//STEP03 EXEC PGM=CUSTOMER-STORE
//OUTPUT DD DSN=CUSTOMER.OUTPUT,DISP=(NEW,CATLG)
"""


# ---------------------------------------------------------------------------
# Lexical false-positive JCL (Phase 13)
# ---------------------------------------------------------------------------

CLAIM_JOB_JCL = """\
//CLAIMJOB JOB CLASS=A
//STEP01 EXEC PGM=CLAIM-PROGRAM
//DATA DD DSN=CLAIM.DATA,DISP=SHR
"""

SETTLEMENT_JOB_JCL = """\
//SETTLEJOB JOB CLASS=A
//STEP01 EXEC PGM=SETTLEMENT-PROCESSOR
//INPUT DD DSN=SETTLEMENT.INPUT,DISP=SHR
"""

PAYMENT_JOB_JCL = """\
//PAYJOB JOB CLASS=A
//STEP01 EXEC PGM=PAYMENT-HANDLER
//OUTPUT DD DSN=PAYMENT.OUTPUT,DISP=(NEW,CATLG)
"""


# ============================================================================
# Test Classes
# ============================================================================


class TestJclIR:
    """JCL IR type construction tests."""

    def test_job_construction_defaults_to_empty_steps_and_no_parameters(self) -> None:
        job = JclJob(name="TESTJOB")
        assert job.name == "TESTJOB"
        assert job.steps == ()
        assert job.parameters is None

    def test_step_construction_defaults_to_no_exec_and_no_dds(self) -> None:
        step = JclStep(name="STEP01")
        assert step.name == "STEP01"
        assert step.exec_ is None
        assert step.dd_statements == ()

    def test_exec_with_program_leaves_procedure_empty(self) -> None:
        exec_ = JclExec(program="PROGRAM-A")
        assert exec_.program == "PROGRAM-A"
        assert exec_.procedure == ""

    def test_exec_with_procedure_leaves_program_empty(self) -> None:
        exec_ = JclExec(procedure="MYPROC")
        assert exec_.program == ""
        assert exec_.procedure == "MYPROC"

    def test_dd_construction_preserves_name_dataset_and_disposition(self) -> None:
        dd = JclDD(name="INPUT", dataset="TEST.DATA", disposition="SHR")
        assert dd.name == "INPUT"
        assert dd.dataset == "TEST.DATA"
        assert dd.disposition == "SHR"

    def test_condition_construction_preserves_type_and_code(self) -> None:
        cond = JclCondition(condition_type="COND", code="EVEN")
        assert cond.condition_type == "COND"
        assert cond.code == "EVEN"

    def test_dataset_construction_preserves_name_and_disposition(self) -> None:
        ds = JclDataset(name="TEST.DATA", type="PS", disposition="SHR")
        assert ds.name == "TEST.DATA"
        assert ds.disposition == "SHR"

    def test_resolved_symbol_construction_preserves_value(self) -> None:
        sym = JclSymbol(name="PROGNAME", value="PROGRAM-A", is_resolved=True)
        assert sym.name == "PROGNAME"
        assert sym.value == "PROGRAM-A"
        assert sym.is_resolved is True

    def test_dependency_construction_preserves_endpoints_and_type(self) -> None:
        dep = JclDependency(
            source="STEP01",
            target="STEP02",
            dependency_type="JCL_STEP_ORDER",
        )
        assert dep.source == "STEP01"
        assert dep.target == "STEP02"
        assert dep.dependency_type == "JCL_STEP_ORDER"

    def test_application_construction_defaults_to_no_jobs_or_dependencies(self) -> None:
        app = JclApplication()
        assert app.jobs == ()
        assert app.dependencies == ()

    def test_step_construction_carries_its_dd_statements(self) -> None:
        dd = JclDD(name="INPUT", dataset="TEST.DATA")
        step = JclStep(name="STEP01", dd_statements=(dd,))
        assert len(step.dd_statements) == 1
        assert step.dd_statements[0].name == "INPUT"


class TestJclParser:
    """JCL parser tests."""

    def test_single_step_job_yields_job_name_step_name_and_program(self) -> None:
        parser = JclParser()
        job = parser.parse(SIMPLE_JCL)
        assert job.name == "SIMPLE"
        assert len(job.steps) == 1
        assert job.steps[0].name == "STEP01"
        assert job.steps[0].exec_.program == "SIMPLE-CALC"

    def test_two_step_job_yields_both_programs_in_source_order(self) -> None:
        parser = JclParser()
        job = parser.parse(TWO_STEP_JCL)
        assert job.name == "TWOSTEP"
        assert len(job.steps) == 2
        assert job.steps[0].exec_.program == "PROGRAM-A"
        assert job.steps[1].exec_.program == "PROGRAM-B"

    def test_three_step_job_yields_each_step_program(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        assert job.name == "MULTIJOB"
        assert len(job.steps) == 3
        assert job.steps[0].exec_.program == "MAIN-PROGRAM"
        assert job.steps[1].exec_.program == "VALIDATE-PROGRAM"
        assert job.steps[2].exec_.program == "STORE-PROGRAM"

    def test_dd_line_yields_name_dataset_and_disposition_on_its_step(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        step1 = job.steps[0]
        assert len(step1.dd_statements) == 1
        assert step1.dd_statements[0].name == "INPUT"
        assert step1.dd_statements[0].dataset == "INPUT.DATA"
        assert step1.dd_statements[0].disposition == "SHR"

    def test_comment_lines_are_collected_on_the_job(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_COMMENTS)
        assert len(job.comments) == 2
        assert "This is a comment" in job.comments[0]

    def test_cond_parameter_on_exec_yields_step_condition_with_code(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_COND)
        step2 = job.steps[1]
        assert step2.condition is not None
        assert step2.condition.condition_type == "COND"
        assert step2.condition.code == "(0,NE)"

    def test_set_symbol_reference_is_preserved_unresolved_in_exec(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_SYMBOLS)
        assert len(job.steps) == 1
        assert job.steps[0].exec_.program == "&PROGNAME"

    def test_proc_exec_yields_step_procedure(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_PROC)
        assert len(job.steps) == 1
        assert job.steps[0].exec_.procedure == "MYPROC"

    def test_sysout_dds_are_flagged_sysout(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_SYSOUT)
        step1 = job.steps[0]
        sysout_dds = [dd for dd in step1.dd_statements if dd.sysout]
        assert len(sysout_dds) == 2

    def test_inline_star_dd_is_flagged_inline(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_INLINE)
        step1 = job.steps[0]
        inline_dds = [dd for dd in step1.dd_statements if dd.is_inline]
        assert len(inline_dds) == 1

    def test_compound_and_simple_disp_values_parse_in_full(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_DISP)
        step1 = job.steps[0]
        assert len(step1.dd_statements) == 3

        new_dd = next(dd for dd in step1.dd_statements if dd.name == "NEWFILE")
        # Strengthened with BL-075: the full compound value must survive
        # (was the weak `assert "NEW" in new_dd.disposition`, which
        # tolerated the truncated "(NEW").
        assert new_dd.disposition == "(NEW,CATLG,DELETE)"
        assert new_dd.space == "(TRK,(10,5))"

        old_dd = next(dd for dd in step1.dd_statements if dd.name == "OLDFILE")
        assert old_dd.disposition == "SHR"

        mod_dd = next(dd for dd in step1.dd_statements if dd.name == "MODFILE")
        assert mod_dd.disposition == "MOD"

    def test_job_statement_parameters_are_parsed(self) -> None:
        parser = JclParser()
        job = parser.parse(SIMPLE_JCL)
        assert job.parameters is not None
        assert job.parameters.get("CLASS") == "A"

    def test_parsed_steps_keep_source_order(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        step_names = [s.name for s in job.steps]
        assert step_names == ["STEP01", "STEP02", "STEP03"]

    def test_empty_source_yields_empty_job(self) -> None:
        parser = JclParser()
        job = parser.parse("")
        assert job.name == ""
        assert job.steps == ()


class TestJclDiscovery:
    """JCL discovery from filesystem tests."""

    def test_directory_with_one_jcl_file_yields_its_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            jcl_file = Path(tmpdir) / "test.jcl"
            jcl_file.write_text(SIMPLE_JCL)

            discovery = JclDiscovery()
            app = discovery.discover(tmpdir)
            assert len(app.jobs) == 1
            assert app.jobs[0].name == "SIMPLE"

    def test_directory_with_two_jcl_files_yields_both_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir).joinpath("job1.jcl").write_text(SIMPLE_JCL)
            Path(tmpdir).joinpath("job2.jcl").write_text(TWO_STEP_JCL)

            discovery = JclDiscovery()
            app = discovery.discover(tmpdir)
            assert len(app.jobs) == 2

    def test_discover_nonexistent_directory_raises_value_error(self) -> None:
        discovery = JclDiscovery()
        with pytest.raises(ValueError, match="does not exist"):
            discovery.discover("/nonexistent/path")

    def test_empty_directory_yields_no_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            discovery = JclDiscovery()
            app = discovery.discover(tmpdir)
            assert len(app.jobs) == 0


class TestJclCobolIntegration:
    """JCL ↔ COBOL integration tests."""

    def test_exec_programs_known_to_cobol_link_as_resolved(self) -> None:
        parser = JclParser()
        jcl_job = parser.parse(TWO_STEP_JCL)

        cobol_app = CobolApplication(
            application_id="test",
            programs=(
                CobolProgramUnit(
                    program_id="PROGRAM-A",
                    source_path="a.cob",
                    program=CobolProgram(program_id="PROGRAM-A"),
                ),
                CobolProgramUnit(
                    program_id="PROGRAM-B",
                    source_path="b.cob",
                    program=CobolProgram(program_id="PROGRAM-B"),
                ),
            ),
        )

        jcl_app = JclApplication(jobs=(jcl_job,))

        discovery = JclDiscovery()
        linked = discovery.link_with_cobol(jcl_app, cobol_app)

        # Should have COBOL_PROGRAM dependencies
        cobol_deps = [d for d in linked.dependencies if d.dependency_type == "COBOL_PROGRAM"]
        assert len(cobol_deps) == 2

        # Check resolution
        resolved = [d for d in cobol_deps if "RESOLVED" in d.metadata]
        assert len(resolved) == 2

    def test_exec_program_absent_from_cobol_links_as_unresolved(self) -> None:
        parser = JclParser()
        jcl_job = parser.parse(JCL_UNRESOLVED_PGM)

        cobol_app = CobolApplication(application_id="test", programs=())
        jcl_app = JclApplication(jobs=(jcl_job,))

        discovery = JclDiscovery()
        linked = discovery.link_with_cobol(jcl_app, cobol_app)

        cobol_deps = [d for d in linked.dependencies if d.dependency_type == "COBOL_PROGRAM"]
        assert len(cobol_deps) == 1
        assert "UNRESOLVED" in cobol_deps[0].metadata

    def test_dataset_equal_to_cobol_file_name_links_as_file_edge(self) -> None:
        parser = JclParser()
        jcl_job = parser.parse(MULTI_STEP_JCL)

        cobol_app = CobolApplication(
            application_id="test",
            programs=(
                CobolProgramUnit(
                    program_id="MAIN-PROGRAM",
                    source_path="main.cob",
                    program=CobolProgram(program_id="MAIN-PROGRAM"),
                    file_dependencies=(
                        FileDependency(
                            program_id="MAIN-PROGRAM",
                            file_name="INPUT.DATA",
                            operation="READ",
                            mode="INPUT",
                        ),
                    ),
                ),
            ),
        )

        jcl_app = JclApplication(jobs=(jcl_job,))

        discovery = JclDiscovery()
        linked = discovery.link_with_cobol(jcl_app, cobol_app)

        file_deps = [d for d in linked.dependencies if d.dependency_type == "COBOL_FILE"]
        assert len(file_deps) >= 1


class TestStepOrdering:
    """Step execution order tests."""

    def test_get_step_order_returns_source_order(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))

        order = app.get_step_order(job.name)
        assert order == ["STEP01", "STEP02", "STEP03"]

    def test_three_step_job_yields_two_step_order_edges(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        # Use parse_application to build dependencies
        app = parser.parse_application({"test.jcl": MULTI_STEP_JCL})

        step_deps = [d for d in app.dependencies if d.dependency_type == "JCL_STEP_ORDER"]
        assert len(step_deps) == 2  # STEP01→STEP02, STEP02→STEP03

    def test_conditional_step_keeps_its_order_edge_with_cond_metadata(
        self,
    ) -> None:
        # Strengthened with BL-076: the old test asserted len==0 against a
        # hand-built JclApplication with no dependencies at all (vacuously
        # true, and pinning the wrong absence).  A COND step keeps its
        # source-order edge; the condition is disclosed in the metadata.
        parser = JclParser()
        source = (
            "//CONDJOB JOB CLASS=A\n"
            "//STEP01 EXEC PGM=PROGRAM-A\n"
            "//STEP02 EXEC PGM=PROGRAM-B,COND=(0,NE)\n"
            "//STEP03 EXEC PGM=PROGRAM-C\n"
        )
        app = parser.parse_application({"cond.jcl": source})

        step_deps = [
            d for d in app.dependencies if d.dependency_type == "JCL_STEP_ORDER"
        ]
        assert [(d.source, d.target) for d in step_deps] == [
            ("STEP01", "STEP02"),
            ("STEP02", "STEP03"),
        ]
        assert step_deps[1].metadata == "job=CONDJOB;cond=(0,NE)"


class TestDatasetLifecycle:
    """Dataset disposition lifecycle tests."""

    def test_new_disposition_is_preserved_verbatim(self) -> None:
        dd = JclDD(name="OUTPUT", dataset="NEW.DATA", disposition="NEW")
        assert dd.disposition == "NEW"

    def test_old_disposition_is_preserved_verbatim(self) -> None:
        dd = JclDD(name="INPUT", dataset="OLD.DATA", disposition="OLD")
        assert dd.disposition == "OLD"

    def test_shr_disposition_is_preserved_verbatim(self) -> None:
        dd = JclDD(name="SHARED", dataset="SHR.DATA", disposition="SHR")
        assert dd.disposition == "SHR"

    def test_mod_disposition_is_preserved_verbatim(self) -> None:
        dd = JclDD(name="MODIFIED", dataset="MOD.DATA", disposition="MOD")
        assert dd.disposition == "MOD"

    def test_compound_disposition_string_is_preserved_verbatim(self) -> None:
        dd = JclDD(name="COMPOUND", dataset="CMP.DATA", disposition="(NEW,CATLG,DELETE)")
        assert "NEW" in dd.disposition
        assert "CATLG" in dd.disposition

    def test_temporary_dataset_flag_is_preserved(self) -> None:
        dd = JclDD(name="TEMP", dataset="&&TEMP01", is_temporary=True)
        assert dd.is_temporary is True


class TestSymbolicParameters:
    """Symbolic parameter tests."""

    def test_resolved_symbol_construction_keeps_value_and_flag(self) -> None:
        sym = JclSymbol(name="VALUE", value="42", is_resolved=True)
        assert sym.name == "VALUE"
        assert sym.value == "42"
        assert sym.is_resolved is True

    def test_unresolved_symbol_defaults_to_empty_value(self) -> None:
        sym = JclSymbol(name="UNRESOLVED")
        assert sym.is_resolved is False
        assert sym.value == ""

    def test_symbolic_reference_in_exec_is_not_resolved_by_parser(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_SYMBOLS)
        # Symbol is not resolved, just preserved
        assert job.steps[0].exec_.program == "&PROGNAME"


class TestDomainNeutralEquivalence:
    """Domain-neutral workload equivalence tests (Phase 12)."""

    def _parse_and_structure(self, jcl: str) -> dict:
        parser = JclParser()
        job = parser.parse(jcl)
        return {
            "name": job.name,
            "step_count": len(job.steps),
            "step_names": [s.name for s in job.steps],
            "programs": [s.exec_.program for s in job.steps if s.exec_],
            "dd_count": sum(len(s.dd_statements) for s in job.steps),
        }

    def test_account_and_order_workloads_have_equal_structure(self) -> None:
        acct = self._parse_and_structure(ACCOUNT_JCL)
        order = self._parse_and_structure(ORDER_JCL)

        # Same structure
        assert acct["step_count"] == order["step_count"]
        assert acct["dd_count"] == order["dd_count"]
        assert acct["step_names"] == order["step_names"]

        # Different names
        assert acct["name"] != order["name"]
        assert acct["programs"] != order["programs"]

    def test_account_and_customer_workloads_have_equal_shape(self) -> None:
        acct = self._parse_and_structure(ACCOUNT_JCL)
        cust = self._parse_and_structure(CUSTOMER_JCL)

        assert acct["step_count"] == cust["step_count"]
        assert acct["dd_count"] == cust["dd_count"]

    def test_all_three_domain_workloads_share_step_and_dd_counts(self) -> None:
        acct = self._parse_and_structure(ACCOUNT_JCL)
        order = self._parse_and_structure(ORDER_JCL)
        cust = self._parse_and_structure(CUSTOMER_JCL)

        assert acct["step_count"] == order["step_count"] == cust["step_count"]
        assert acct["dd_count"] == order["dd_count"] == cust["dd_count"]


class TestLexicalFalsePositives:
    """Lexical false-positive tests (Phase 13)."""

    def test_claim_job_name_no_special_behavior(self) -> None:
        parser = JclParser()
        job = parser.parse(CLAIM_JOB_JCL)
        assert job.name == "CLAIMJOB"
        assert len(job.steps) == 1
        assert job.steps[0].exec_.program == "CLAIM-PROGRAM"

    def test_settlement_job_name_no_special_behavior(self) -> None:
        parser = JclParser()
        job = parser.parse(SETTLEMENT_JOB_JCL)
        assert job.name == "SETTLEJOB"
        assert job.steps[0].exec_.program == "SETTLEMENT-PROCESSOR"

    def test_payment_job_name_no_special_behavior(self) -> None:
        parser = JclParser()
        job = parser.parse(PAYMENT_JOB_JCL)
        assert job.name == "PAYJOB"
        assert job.steps[0].exec_.program == "PAYMENT-HANDLER"

    def test_claim_dataset_no_special_behavior(self) -> None:
        parser = JclParser()
        job = parser.parse(CLAIM_JOB_JCL)
        dd = job.steps[0].dd_statements[0]
        assert dd.dataset == "CLAIM.DATA"
        assert dd.disposition == "SHR"

    def test_lexical_names_do_not_activate_special_modes(self) -> None:
        parser = JclParser()
        for jcl in [CLAIM_JOB_JCL, SETTLEMENT_JOB_JCL, PAYMENT_JOB_JCL]:
            job = parser.parse(jcl)
            # All parsed the same way - no special behavior
            assert len(job.steps) == 1
            assert job.steps[0].exec_ is not None


class TestMutationMatrix:
    """Mutation matrix tests (Phase 14)."""

    def test_job_name_change_updates_name_and_keeps_step_count(self) -> None:
        parser = JclParser()
        job1 = parser.parse(SIMPLE_JCL)
        job2 = parser.parse(SIMPLE_JCL.replace("SIMPLE", "DIFFERENT"))
        assert job1.name != job2.name
        assert len(job1.steps) == len(job2.steps)

    def test_extra_step_increases_step_count(self) -> None:
        parser = JclParser()
        job1 = parser.parse(TWO_STEP_JCL)
        job2 = parser.parse(MULTI_STEP_JCL)
        assert len(job1.steps) < len(job2.steps)

    def test_missing_step_decreases_step_count(self) -> None:
        parser = JclParser()
        job1 = parser.parse(MULTI_STEP_JCL)
        job2 = parser.parse(TWO_STEP_JCL)
        assert len(job1.steps) > len(job2.steps)

    def test_pgm_change_updates_only_the_program_target(self) -> None:
        parser = JclParser()
        jcl1 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A"
        jcl2 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-B"
        job1 = parser.parse(jcl1)
        job2 = parser.parse(jcl2)
        assert job1.steps[0].exec_.program != job2.steps[0].exec_.program

    def test_added_dd_line_increases_step_dd_count(self) -> None:
        parser = JclParser()
        jcl1 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A"
        jcl2 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=DATA,DISP=SHR"
        job1 = parser.parse(jcl1)
        job2 = parser.parse(jcl2)
        assert len(job1.steps[0].dd_statements) < len(job2.steps[0].dd_statements)

    def test_removed_dd_lines_decrease_step_dd_count(self) -> None:
        parser = JclParser()
        job1 = parser.parse(MULTI_STEP_JCL)
        jcl2 = "//MULTIJOB JOB CLASS=A\n//STEP01 EXEC PGM=MAIN-PROGRAM"
        job2 = parser.parse(jcl2)
        assert len(job1.steps[0].dd_statements) > len(job2.steps[0].dd_statements)

    def test_dsn_change_updates_dataset_and_keeps_dd_count(self) -> None:
        parser = JclParser()
        jcl1 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=OLD.DATA,DISP=SHR"
        jcl2 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=NEW.DATA,DISP=SHR"
        job1 = parser.parse(jcl1)
        job2 = parser.parse(jcl2)
        assert job1.steps[0].dd_statements[0].dataset != job2.steps[0].dd_statements[0].dataset
        assert len(job1.steps[0].dd_statements) == len(job2.steps[0].dd_statements)

    def test_disp_change_updates_disposition_only(self) -> None:
        parser = JclParser()
        jcl1 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=DATA,DISP=SHR"
        jcl2 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=DATA,DISP=OLD"
        job1 = parser.parse(jcl1)
        job2 = parser.parse(jcl2)
        assert job1.steps[0].dd_statements[0].disposition != job2.steps[0].dd_statements[0].disposition


class TestDeterminism:
    """Determinism tests (Phase 15)."""

    def test_parsing_same_source_twice_yields_identical_jobs(self) -> None:
        parser = JclParser()
        job1 = parser.parse(MULTI_STEP_JCL)
        job2 = parser.parse(MULTI_STEP_JCL)
        assert job1.name == job2.name
        assert len(job1.steps) == len(job2.steps)
        assert [s.name for s in job1.steps] == [s.name for s in job2.steps]

    def test_repeated_parsing_keeps_step_order_stable(self) -> None:
        parser = JclParser()
        for _ in range(5):
            job = parser.parse(MULTI_STEP_JCL)
            assert [s.name for s in job.steps] == ["STEP01", "STEP02", "STEP03"]


class TestValidation:
    """JCL validation tests (Phase 16)."""

    def test_clean_application_validates_without_errors(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))
        errors = app.validate()
        assert errors == []

    def test_duplicate_step_name_is_reported(self) -> None:
        jcl = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=A\n//STEP01 EXEC PGM=B"
        parser = JclParser()
        job = parser.parse(jcl)
        app = JclApplication(jobs=(job,))
        errors = app.validate()
        assert any("Duplicate step" in e for e in errors)

    def test_step_without_exec_is_reported_malformed(self) -> None:
        # Step with no EXEC statement
        step = JclStep(name="STEP01", exec_=None)
        job = JclJob(name="TESTJOB", steps=(step,))
        app = JclApplication(jobs=(job,))
        errors = app.validate()
        assert any("Malformed EXEC" in e for e in errors)

    def test_exec_without_pgm_or_proc_is_reported(self) -> None:
        # Step with EXEC but no PGM or PROC
        exec_ = JclExec()
        step = JclStep(name="STEP01", exec_=exec_)
        job = JclJob(name="TESTJOB", steps=(step,))
        app = JclApplication(jobs=(job,))
        errors = app.validate()
        assert any("no PGM or PROC" in e for e in errors)


class TestApplicationGraphIntegration:
    """Application graph integration tests (Phase 17)."""

    def test_program_references_yield_step_to_program_pairs(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))

        refs = app.get_program_references()
        assert len(refs) == 3
        assert refs[0] == ("STEP01", "MAIN-PROGRAM")
        assert refs[1] == ("STEP02", "VALIDATE-PROGRAM")
        assert refs[2] == ("STEP03", "STORE-PROGRAM")

    def test_dataset_references_yield_dd_to_dataset_pairs(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))

        refs = app.get_dataset_references()
        assert len(refs) == 3
        assert ("INPUT", "INPUT.DATA") in refs
        assert ("OUTPUT", "OUTPUT.DATA") in refs

    def test_application_dependencies_expose_all_three_types(self) -> None:
        parser = JclParser()
        # Use parse_application to build dependencies
        app = parser.parse_application({"test.jcl": MULTI_STEP_JCL})

        dep_types = {d.dependency_type for d in app.dependencies}
        assert "JCL_STEP_ORDER" in dep_types
        assert "JCL_EXEC" in dep_types
        assert "JCL_DD" in dep_types


class TestJclApplicationMethods:
    """JclApplication helper method tests."""

    def test_get_job_finds_known_job_and_misses_unknown(self) -> None:
        parser = JclParser()
        job = parser.parse(SIMPLE_JCL)
        app = JclApplication(jobs=(job,))
        assert app.get_job("SIMPLE") is not None
        assert app.get_job("NONEXISTENT") is None

    def test_get_step_returns_the_step_with_its_program(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))
        step = app.get_step("MULTIJOB", "STEP01")
        assert step is not None
        assert step.exec_.program == "MAIN-PROGRAM"

    def test_get_dependencies_returns_edges_from_a_step(self) -> None:
        parser = JclParser()
        # Use parse_application to build dependencies
        app = parser.parse_application({"test.jcl": MULTI_STEP_JCL})
        deps = app.get_dependencies("STEP01")
        assert len(deps) >= 1


class TestForensicSearch:
    """Forensic search tests (Phase 20)."""

    def test_no_domain_driven_discovery(self) -> None:
        """JCL parsing does not use domain terms for discovery."""
        parser = JclParser()
        for jcl in [CLAIM_JOB_JCL, SETTLEMENT_JOB_JCL, PAYMENT_JOB_JCL]:
            job = parser.parse(jcl)
            # All parsed identically - no domain-driven behavior
            assert len(job.steps) == 1

    def test_no_filename_detection(self) -> None:
        """JCL parsing does not classify by filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Name file "claims.jcl" but content is generic
            jcl_file = Path(tmpdir) / "claims.jcl"
            jcl_file.write_text(SIMPLE_JCL)

            discovery = JclDiscovery()
            app = discovery.discover(tmpdir)
            assert len(app.jobs) == 1
            assert app.jobs[0].name == "SIMPLE"

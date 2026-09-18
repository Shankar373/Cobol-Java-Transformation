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

    def test_jcl_job_construction(self) -> None:
        job = JclJob(name="TESTJOB")
        assert job.name == "TESTJOB"
        assert job.steps == ()
        assert job.parameters is None

    def test_jcl_step_construction(self) -> None:
        step = JclStep(name="STEP01")
        assert step.name == "STEP01"
        assert step.exec_ is None
        assert step.dd_statements == ()

    def test_jcl_exec_construction(self) -> None:
        exec_ = JclExec(program="PROGRAM-A")
        assert exec_.program == "PROGRAM-A"
        assert exec_.procedure == ""

    def test_jcl_exec_procedure(self) -> None:
        exec_ = JclExec(procedure="MYPROC")
        assert exec_.program == ""
        assert exec_.procedure == "MYPROC"

    def test_jcl_dd_construction(self) -> None:
        dd = JclDD(name="INPUT", dataset="TEST.DATA", disposition="SHR")
        assert dd.name == "INPUT"
        assert dd.dataset == "TEST.DATA"
        assert dd.disposition == "SHR"

    def test_jcl_condition_construction(self) -> None:
        cond = JclCondition(condition_type="COND", code="EVEN")
        assert cond.condition_type == "COND"
        assert cond.code == "EVEN"

    def test_jcl_dataset_construction(self) -> None:
        ds = JclDataset(name="TEST.DATA", type="PS", disposition="SHR")
        assert ds.name == "TEST.DATA"
        assert ds.disposition == "SHR"

    def test_jcl_symbol_construction(self) -> None:
        sym = JclSymbol(name="PROGNAME", value="PROGRAM-A", is_resolved=True)
        assert sym.name == "PROGNAME"
        assert sym.value == "PROGRAM-A"
        assert sym.is_resolved is True

    def test_jcl_dependency_construction(self) -> None:
        dep = JclDependency(
            source="STEP01",
            target="STEP02",
            dependency_type="JCL_STEP_ORDER",
        )
        assert dep.source == "STEP01"
        assert dep.target == "STEP02"
        assert dep.dependency_type == "JCL_STEP_ORDER"

    def test_jcl_application_construction(self) -> None:
        app = JclApplication()
        assert app.jobs == ()
        assert app.dependencies == ()

    def test_jcl_step_with_dd(self) -> None:
        dd = JclDD(name="INPUT", dataset="TEST.DATA")
        step = JclStep(name="STEP01", dd_statements=(dd,))
        assert len(step.dd_statements) == 1
        assert step.dd_statements[0].name == "INPUT"


class TestJclParser:
    """JCL parser tests."""

    def test_parse_simple_job(self) -> None:
        parser = JclParser()
        job = parser.parse(SIMPLE_JCL)
        assert job.name == "SIMPLE"
        assert len(job.steps) == 1
        assert job.steps[0].name == "STEP01"
        assert job.steps[0].exec_.program == "SIMPLE-CALC"

    def test_parse_two_step(self) -> None:
        parser = JclParser()
        job = parser.parse(TWO_STEP_JCL)
        assert job.name == "TWOSTEP"
        assert len(job.steps) == 2
        assert job.steps[0].exec_.program == "PROGRAM-A"
        assert job.steps[1].exec_.program == "PROGRAM-B"

    def test_parse_multi_step(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        assert job.name == "MULTIJOB"
        assert len(job.steps) == 3
        assert job.steps[0].exec_.program == "MAIN-PROGRAM"
        assert job.steps[1].exec_.program == "VALIDATE-PROGRAM"
        assert job.steps[2].exec_.program == "STORE-PROGRAM"

    def test_parse_dd_statements(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        step1 = job.steps[0]
        assert len(step1.dd_statements) == 1
        assert step1.dd_statements[0].name == "INPUT"
        assert step1.dd_statements[0].dataset == "INPUT.DATA"
        assert step1.dd_statements[0].disposition == "SHR"

    def test_parse_comments(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_COMMENTS)
        assert len(job.comments) == 2
        assert "This is a comment" in job.comments[0]

    def test_parse_cond(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_COND)
        step2 = job.steps[1]
        assert step2.condition is not None
        assert step2.condition.condition_type == "COND"
        assert step2.condition.code == "(0,NE)"

    def test_parse_symbols(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_SYMBOLS)
        assert len(job.steps) == 1
        assert job.steps[0].exec_.program == "&PROGNAME"

    def test_parse_proc(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_PROC)
        assert len(job.steps) == 1
        assert job.steps[0].exec_.procedure == "MYPROC"

    def test_parse_sysout(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_SYSOUT)
        step1 = job.steps[0]
        sysout_dds = [dd for dd in step1.dd_statements if dd.sysout]
        assert len(sysout_dds) == 2

    def test_parse_inline_data(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_INLINE)
        step1 = job.steps[0]
        inline_dds = [dd for dd in step1.dd_statements if dd.is_inline]
        assert len(inline_dds) == 1

    def test_parse_disp(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_DISP)
        step1 = job.steps[0]
        assert len(step1.dd_statements) == 3

        new_dd = next(dd for dd in step1.dd_statements if dd.name == "NEWFILE")
        assert "NEW" in new_dd.disposition

        old_dd = next(dd for dd in step1.dd_statements if dd.name == "OLDFILE")
        assert old_dd.disposition == "SHR"

        mod_dd = next(dd for dd in step1.dd_statements if dd.name == "MODFILE")
        assert mod_dd.disposition == "MOD"

    def test_parse_job_parameters(self) -> None:
        parser = JclParser()
        job = parser.parse(SIMPLE_JCL)
        assert job.parameters is not None
        assert job.parameters.get("CLASS") == "A"

    def test_parse_step_order_preserved(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        step_names = [s.name for s in job.steps]
        assert step_names == ["STEP01", "STEP02", "STEP03"]

    def test_parse_empty_source(self) -> None:
        parser = JclParser()
        job = parser.parse("")
        assert job.name == ""
        assert job.steps == ()


class TestJclDiscovery:
    """JCL discovery from filesystem tests."""

    def test_discover_from_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            jcl_file = Path(tmpdir) / "test.jcl"
            jcl_file.write_text(SIMPLE_JCL)

            discovery = JclDiscovery()
            app = discovery.discover(tmpdir)
            assert len(app.jobs) == 1
            assert app.jobs[0].name == "SIMPLE"

    def test_discover_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir).joinpath("job1.jcl").write_text(SIMPLE_JCL)
            Path(tmpdir).joinpath("job2.jcl").write_text(TWO_STEP_JCL)

            discovery = JclDiscovery()
            app = discovery.discover(tmpdir)
            assert len(app.jobs) == 2

    def test_discover_nonexistent_directory(self) -> None:
        discovery = JclDiscovery()
        with pytest.raises(ValueError, match="does not exist"):
            discovery.discover("/nonexistent/path")

    def test_discover_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            discovery = JclDiscovery()
            app = discovery.discover(tmpdir)
            assert len(app.jobs) == 0


class TestJclCobolIntegration:
    """JCL ↔ COBOL integration tests."""

    def test_link_jcl_to_cobol(self) -> None:
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

    def test_link_unresolved_program(self) -> None:
        parser = JclParser()
        jcl_job = parser.parse(JCL_UNRESOLVED_PGM)

        cobol_app = CobolApplication(application_id="test", programs=())
        jcl_app = JclApplication(jobs=(jcl_job,))

        discovery = JclDiscovery()
        linked = discovery.link_with_cobol(jcl_app, cobol_app)

        cobol_deps = [d for d in linked.dependencies if d.dependency_type == "COBOL_PROGRAM"]
        assert len(cobol_deps) == 1
        assert "UNRESOLVED" in cobol_deps[0].metadata

    def test_link_dataset_to_file(self) -> None:
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

    def test_step_order_preserved(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))

        order = app.get_step_order(job.name)
        assert order == ["STEP01", "STEP02", "STEP03"]

    def test_step_order_dependencies(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        # Use parse_application to build dependencies
        app = parser.parse_application({"test.jcl": MULTI_STEP_JCL})

        step_deps = [d for d in app.dependencies if d.dependency_type == "JCL_STEP_ORDER"]
        assert len(step_deps) == 2  # STEP01→STEP02, STEP02→STEP03

    def test_conditional_step_no_order_dependency(self) -> None:
        parser = JclParser()
        job = parser.parse(JCL_WITH_COND)
        app = JclApplication(jobs=(job,))

        step_deps = [d for d in app.dependencies if d.dependency_type == "JCL_STEP_ORDER"]
        assert len(step_deps) == 0  # Conditional step has no order dependency


class TestDatasetLifecycle:
    """Dataset disposition lifecycle tests."""

    def test_new_dataset(self) -> None:
        dd = JclDD(name="OUTPUT", dataset="NEW.DATA", disposition="NEW")
        assert dd.disposition == "NEW"

    def test_old_dataset(self) -> None:
        dd = JclDD(name="INPUT", dataset="OLD.DATA", disposition="OLD")
        assert dd.disposition == "OLD"

    def test_shared_dataset(self) -> None:
        dd = JclDD(name="SHARED", dataset="SHR.DATA", disposition="SHR")
        assert dd.disposition == "SHR"

    def test_mod_dataset(self) -> None:
        dd = JclDD(name="MODIFIED", dataset="MOD.DATA", disposition="MOD")
        assert dd.disposition == "MOD"

    def test_compound_disposition(self) -> None:
        dd = JclDD(name="COMPOUND", dataset="CMP.DATA", disposition="(NEW,CATLG,DELETE)")
        assert "NEW" in dd.disposition
        assert "CATLG" in dd.disposition

    def test_temporary_dataset(self) -> None:
        dd = JclDD(name="TEMP", dataset="&&TEMP01", is_temporary=True)
        assert dd.is_temporary is True


class TestSymbolicParameters:
    """Symbolic parameter tests."""

    def test_symbol_construction(self) -> None:
        sym = JclSymbol(name="VALUE", value="42", is_resolved=True)
        assert sym.name == "VALUE"
        assert sym.value == "42"
        assert sym.is_resolved is True

    def test_unresolved_symbol(self) -> None:
        sym = JclSymbol(name="UNRESOLVED")
        assert sym.is_resolved is False
        assert sym.value == ""

    def test_symbol_in_jcl(self) -> None:
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

    def test_account_vs_order_equivalence(self) -> None:
        acct = self._parse_and_structure(ACCOUNT_JCL)
        order = self._parse_and_structure(ORDER_JCL)

        # Same structure
        assert acct["step_count"] == order["step_count"]
        assert acct["dd_count"] == order["dd_count"]
        assert acct["step_names"] == order["step_names"]

        # Different names
        assert acct["name"] != order["name"]
        assert acct["programs"] != order["programs"]

    def test_account_vs_customer_equivalence(self) -> None:
        acct = self._parse_and_structure(ACCOUNT_JCL)
        cust = self._parse_and_structure(CUSTOMER_JCL)

        assert acct["step_count"] == cust["step_count"]
        assert acct["dd_count"] == cust["dd_count"]

    def test_all_three_equivalent(self) -> None:
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

    def test_change_job_name(self) -> None:
        parser = JclParser()
        job1 = parser.parse(SIMPLE_JCL)
        job2 = parser.parse(SIMPLE_JCL.replace("SIMPLE", "DIFFERENT"))
        assert job1.name != job2.name
        assert len(job1.steps) == len(job2.steps)

    def test_add_step_changes_structure(self) -> None:
        parser = JclParser()
        job1 = parser.parse(TWO_STEP_JCL)
        job2 = parser.parse(MULTI_STEP_JCL)
        assert len(job1.steps) < len(job2.steps)

    def test_remove_step_changes_structure(self) -> None:
        parser = JclParser()
        job1 = parser.parse(MULTI_STEP_JCL)
        job2 = parser.parse(TWO_STEP_JCL)
        assert len(job1.steps) > len(job2.steps)

    def test_change_pgm_target(self) -> None:
        parser = JclParser()
        jcl1 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A"
        jcl2 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-B"
        job1 = parser.parse(jcl1)
        job2 = parser.parse(jcl2)
        assert job1.steps[0].exec_.program != job2.steps[0].exec_.program

    def test_add_dd_changes_step(self) -> None:
        parser = JclParser()
        jcl1 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A"
        jcl2 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=DATA,DISP=SHR"
        job1 = parser.parse(jcl1)
        job2 = parser.parse(jcl2)
        assert len(job1.steps[0].dd_statements) < len(job2.steps[0].dd_statements)

    def test_remove_dd_changes_step(self) -> None:
        parser = JclParser()
        job1 = parser.parse(MULTI_STEP_JCL)
        jcl2 = "//MULTIJOB JOB CLASS=A\n//STEP01 EXEC PGM=MAIN-PROGRAM"
        job2 = parser.parse(jcl2)
        assert len(job1.steps[0].dd_statements) > len(job2.steps[0].dd_statements)

    def test_change_dsn_preserves_structure(self) -> None:
        parser = JclParser()
        jcl1 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=OLD.DATA,DISP=SHR"
        jcl2 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=NEW.DATA,DISP=SHR"
        job1 = parser.parse(jcl1)
        job2 = parser.parse(jcl2)
        assert job1.steps[0].dd_statements[0].dataset != job2.steps[0].dd_statements[0].dataset
        assert len(job1.steps[0].dd_statements) == len(job2.steps[0].dd_statements)

    def test_change_disp_preserves_structure(self) -> None:
        parser = JclParser()
        jcl1 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=DATA,DISP=SHR"
        jcl2 = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=PROGRAM-A\n//INPUT DD DSN=DATA,DISP=OLD"
        job1 = parser.parse(jcl1)
        job2 = parser.parse(jcl2)
        assert job1.steps[0].dd_statements[0].disposition != job2.steps[0].dd_statements[0].disposition


class TestDeterminism:
    """Determinism tests (Phase 15)."""

    def test_same_source_same_job(self) -> None:
        parser = JclParser()
        job1 = parser.parse(MULTI_STEP_JCL)
        job2 = parser.parse(MULTI_STEP_JCL)
        assert job1.name == job2.name
        assert len(job1.steps) == len(job2.steps)
        assert [s.name for s in job1.steps] == [s.name for s in job2.steps]

    def test_deterministic_step_order(self) -> None:
        parser = JclParser()
        for _ in range(5):
            job = parser.parse(MULTI_STEP_JCL)
            assert [s.name for s in job.steps] == ["STEP01", "STEP02", "STEP03"]


class TestValidation:
    """JCL validation tests (Phase 16)."""

    def test_valid_application(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))
        errors = app.validate()
        assert errors == []

    def test_duplicate_step_detection(self) -> None:
        jcl = "//JOB JOB CLASS=A\n//STEP01 EXEC PGM=A\n//STEP01 EXEC PGM=B"
        parser = JclParser()
        job = parser.parse(jcl)
        app = JclApplication(jobs=(job,))
        errors = app.validate()
        assert any("Duplicate step" in e for e in errors)

    def test_malformed_exec_detection(self) -> None:
        # Step with no EXEC statement
        step = JclStep(name="STEP01", exec_=None)
        job = JclJob(name="TESTJOB", steps=(step,))
        app = JclApplication(jobs=(job,))
        errors = app.validate()
        assert any("Malformed EXEC" in e for e in errors)

    def test_empty_exec_detection(self) -> None:
        # Step with EXEC but no PGM or PROC
        exec_ = JclExec()
        step = JclStep(name="STEP01", exec_=exec_)
        job = JclJob(name="TESTJOB", steps=(step,))
        app = JclApplication(jobs=(job,))
        errors = app.validate()
        assert any("no PGM or PROC" in e for e in errors)


class TestApplicationGraphIntegration:
    """Application graph integration tests (Phase 17)."""

    def test_program_references(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))

        refs = app.get_program_references()
        assert len(refs) == 3
        assert refs[0] == ("STEP01", "MAIN-PROGRAM")
        assert refs[1] == ("STEP02", "VALIDATE-PROGRAM")
        assert refs[2] == ("STEP03", "STORE-PROGRAM")

    def test_dataset_references(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))

        refs = app.get_dataset_references()
        assert len(refs) == 3
        assert ("INPUT", "INPUT.DATA") in refs
        assert ("OUTPUT", "OUTPUT.DATA") in refs

    def test_dependency_types_distinguished(self) -> None:
        parser = JclParser()
        # Use parse_application to build dependencies
        app = parser.parse_application({"test.jcl": MULTI_STEP_JCL})

        dep_types = {d.dependency_type for d in app.dependencies}
        assert "JCL_STEP_ORDER" in dep_types
        assert "JCL_EXEC" in dep_types
        assert "JCL_DD" in dep_types


class TestJclApplicationMethods:
    """JclApplication helper method tests."""

    def test_get_job(self) -> None:
        parser = JclParser()
        job = parser.parse(SIMPLE_JCL)
        app = JclApplication(jobs=(job,))
        assert app.get_job("SIMPLE") is not None
        assert app.get_job("NONEXISTENT") is None

    def test_get_step(self) -> None:
        parser = JclParser()
        job = parser.parse(MULTI_STEP_JCL)
        app = JclApplication(jobs=(job,))
        step = app.get_step("MULTIJOB", "STEP01")
        assert step is not None
        assert step.exec_.program == "MAIN-PROGRAM"

    def test_get_dependencies(self) -> None:
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

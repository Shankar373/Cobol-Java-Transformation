"""JCL scanner: statements, continuation, symbols, DD semantics, in-stream utilities, build steps."""

from __future__ import annotations

from enterprise.discovery.jcl_syntax import read_statements, split_top, substitute
from enterprise.discovery.scan_jcl import scan_control_text, scan_jcl


def refs(scan, relation=None, kind=None):
    return [r for r in scan.refs if (relation is None or r.relation == relation) and (kind is None or r.target_kind == kind)]


def facts(scan, category):
    return [f for f in scan.facts if f.category == category]


def test_statement_reader_folds_continuations_and_skips_comments() -> None:
    text = "//J  JOB (A),'X',\n//        CLASS=A\n//* comment\n//S1 EXEC PGM=P1,PARM='A,B'\n"
    statements, comments, problems = read_statements(text)
    assert [(s.name, s.op) for s in statements] == [("J", "JOB"), ("S1", "EXEC")]
    assert "CLASS=A" in statements[0].operands and comments == 1 and not problems


def test_parm_inside_quotes_keeps_commas_and_blanks() -> None:
    statements, _, _ = read_statements("//S1 EXEC PGM=P1,PARM='ONE,TWO THREE'   trailing comment\n")
    assert split_top(statements[0].operands) == ["PGM=P1", "PARM='ONE,TWO THREE'"]


def test_sequence_numbers_in_columns_73_to_80_are_not_statement_text() -> None:
    line = "//STEP1   EXEC PGM=PAYROLL".ljust(72) + "00000100"
    scan = scan_jcl("j.jcl", "//J JOB\n" + line + "\n")
    assert [r.target for r in refs(scan, "executes")] == ["PAYROLL"]


def test_symbol_substitution_rules() -> None:
    assert substitute("&HLQ..EMP.DATA", {"HLQ": "PROD"}) == ("PROD.EMP.DATA", [])
    assert substitute("&&TEMP", {"TEMP": "X"}) == ("&&TEMP", [])
    assert substitute("&A.&B", {"A": "1"}) == ("1&B", ["B"])


def test_set_proc_defaults_and_step_parameters_resolve_dataset_names() -> None:
    text = ("//MYPROC PROC HLQ=TEST\n//S1 EXEC PGM=PAYROLL\n//EMPFILE DD DSN=&HLQ..EMP,DISP=SHR\n//  PEND\n"
            "//J JOB\n//  SET HLQ=PROD\n//S2 EXEC PGM=PAYROLL\n//EMPFILE DD DSN=&HLQ..EMP,DISP=SHR\n"
            "//S3 EXEC PGM=PAYROLL\n//EMPFILE DD DSN=&UNKNOWN..EMP,DISP=SHR\n")
    scan = scan_jcl("j.jcl", text)
    datasets = {(r.owner, r.target, r.dynamic) for r in refs(scan, "uses-dataset", "dataset")}
    assert ("proc:MYPROC/S1", "TEST.EMP", False) in datasets
    assert ("job:J/S2", "PROD.EMP", False) in datasets
    assert ("job:J/S3", "", True) in datasets


def test_dd_semantics_dummy_sysout_instream_temp_referback_gdg_and_members() -> None:
    text = ("//J JOB\n//S1 EXEC PGM=P\n//A DD DUMMY\n//B DD SYSOUT=*\n//C DD *\ndata\n/*\n//D DD DSN=&&TMP,DISP=(NEW,PASS)\n"
            "//E DD DSN=*.S0.OUT\n//F DD DSN=PROD.GDG(+1),DISP=(NEW,CATLG)\n//G DD DSN=PROD.LIB(MEMBR),DISP=SHR\n"
            "//H DD PATH='/u/app/in.txt'\n")
    scan = scan_jcl("j.jcl", text)
    kinds = {dict(r.detail).get("dd"): r.target_kind for r in refs(scan, "uses-dataset") + refs(scan, "creates-dataset")}
    assert kinds["A"] == "dummy" and kinds["B"] == "sysout" and kinds["C"] == "instream" and kinds["H"] == "uss-path"
    assert facts(scan, "temporary-dataset") and facts(scan, "dd-referback")
    created = refs(scan, "creates-dataset")[0]
    assert created.target == "PROD.GDG(+1)".split("(")[0] and dict(created.detail)["generation"] == "gdg"
    member = next(r for r in scan.refs if dict(r.detail).get("dd") == "G")
    assert dict(member.detail)["member"] == "MEMBR"


def test_proc_include_and_jcllib() -> None:
    text = "//J JOB\n//  JCLLIB ORDER=(PROD.PROCLIB,TEST.PROCLIB)\n//  INCLUDE MEMBER=COMMON\n//S1 EXEC PROC=MYPROC\n//S2 EXEC OTHERPROC\n"
    scan = scan_jcl("j.jcl", text)
    assert sorted(r.target for r in refs(scan, "executes", "proc")) == ["MYPROC", "OTHERPROC"]
    assert [r.target for r in refs(scan, "includes")] == ["COMMON"]
    assert sorted(r.target for r in refs(scan, "uses-library")) == ["PROD.PROCLIB", "TEST.PROCLIB"]


def test_step_dd_override_records_the_procedure_step_it_targets() -> None:
    scan = scan_jcl("j.jcl", "//J JOB\n//S1 EXEC PROC=P\n//STEP1.SYSIN DD DSN=MY.INPUT,DISP=SHR\n")
    ref = next(r for r in scan.refs if dict(r.detail).get("dd") == "SYSIN")
    assert dict(ref.detail)["override"] == "STEP1"


def test_idcams_define_cluster_aix_gdg_repro_delete() -> None:
    text = ("//J JOB\n//S1 EXEC PGM=IDCAMS\n//SYSIN DD *\n"
            "  DEFINE CLUSTER (NAME(PROD.KSDS.A) INDEXED KEYS(8 0) RECORDSIZE(100 200) -\n    SHAREOPTIONS(2 3)) -\n"
            "    DATA (NAME(PROD.KSDS.A.DATA)) INDEX (NAME(PROD.KSDS.A.INDEX))\n"
            "  DEFINE CLUSTER (NAME(PROD.ESDS.B) NONINDEXED)\n  DEFINE CLUSTER (NAME(PROD.RRDS.C) NUMBERED)\n"
            "  DEFINE AIX (NAME(PROD.KSDS.A.AIX) RELATE(PROD.KSDS.A) KEYS(4 20))\n"
            "  DEFINE GDG (NAME(PROD.GDG1) LIMIT(5))\n  REPRO INFILE(IN1) OUTDATASET(PROD.KSDS.A)\n"
            "  DELETE PROD.OLD CLUSTER PURGE\n/*\n")
    scan = scan_jcl("j.jcl", text)
    clusters = {f.name: dict(f.detail) for f in facts(scan, "vsam-cluster")}
    assert clusters["PROD.KSDS.A"]["organization"] == "KSDS" and clusters["PROD.KSDS.A"]["keys"] == "8 0"
    assert clusters["PROD.KSDS.A"]["record_size"] == "100 200"
    assert clusters["PROD.ESDS.B"]["organization"] == "ESDS" and clusters["PROD.RRDS.C"]["organization"] == "RRDS"
    assert {f.name for f in facts(scan, "vsam-component")} == {"PROD.KSDS.A.DATA", "PROD.KSDS.A.INDEX"}
    assert [f.name for f in facts(scan, "vsam-aix")] == ["PROD.KSDS.A.AIX"]
    assert [f.name for f in facts(scan, "gdg-base")] == ["PROD.GDG1"]
    assert {(r.target_kind, r.target) for r in refs(scan, "binds-ddname")} == {("dd", "IN1")}
    assert "PROD.KSDS.A" in {r.target for r in refs(scan, "uses-dataset")}
    assert any(f.name == "DELETE" for f in facts(scan, "idcams-command"))


def test_sort_control_statements_and_icetool_ddnames() -> None:
    text = ("//J JOB\n//S1 EXEC PGM=SORT\n//SYSIN DD *\n  SORT FIELDS=(1,6,CH,A)\n  INCLUDE COND=(8,2,CH,EQ,C'AB')\n"
            "  OUTREC FIELDS=(1,20)\n/*\n//S2 EXEC PGM=ICETOOL\n//TOOLIN DD *\n  COPY FROM(IN1) TO(OUT1)\n/*\n")
    scan = scan_jcl("j.jcl", text)
    assert {f.name for f in facts(scan, "sort-control")} >= {"SORT", "INCLUDE", "OUTREC"}
    assert {r.target for r in refs(scan, "binds-ddname")} == {"IN1", "OUT1"}  # ICETOOL TOOLIN is read like SYSIN


def test_tso_db2_run_program_and_bind() -> None:
    text = ("//J JOB\n//S1 EXEC PGM=IKJEFT01\n//SYSTSIN DD *\n  DSN SYSTEM(DB2P)\n  RUN PROGRAM(PAYSQL) PLAN(PAYPLAN) LIB('PROD.LOAD')\n"
            "  BIND PLAN(NEWPLAN) MEMBER(DBRM1,DBRM2)\n  END\n/*\n")
    scan = scan_jcl("j.jcl", text)
    assert {(r.target_kind, r.target) for r in refs(scan, "uses-db2")} >= {
        ("db2-subsystem", "DB2P"), ("db2-plan", "PAYPLAN"), ("db2-plan", "NEWPLAN")}
    run = next(r for r in refs(scan, "executes") if r.target == "PAYSQL")
    assert dict(run.detail)["plan"] == "PAYPLAN" and dict(run.detail)["library"] == "PROD.LOAD"
    assert {r.target for r in refs(scan, "binds")} == {"DBRM1", "DBRM2"}


def test_ims_region_controller_program_and_psb() -> None:
    scan = scan_jcl("j.jcl", "//J JOB\n//S1 EXEC PGM=DFSRRC00,PARM='BMP,IMSPGM,IMSPSB'\n")
    assert {(r.target_kind, r.target) for r in scan.refs} >= {("program", "IMSPGM"), ("ims-psb", "IMSPSB")}
    assert dict(facts(scan, "ims-region")[0].detail)["region"] == "BMP"


def test_cics_csd_and_mq_utility_definitions() -> None:
    text = ("//J JOB\n//S1 EXEC PGM=DFHCSDUP\n//SYSIN DD *\n  DEFINE PROGRAM(PAYPGM) GROUP(PAY)\n"
            "  DEFINE TRANSACTION(PAY1) GROUP(PAY) PROGRAM(PAYPGM)\n  DEFINE FILE(PAYFILE) GROUP(PAY)\n/*\n"
            "//S2 EXEC PGM=CSQUTIL\n//SYSIN DD *\n  DEFINE QLOCAL('PAY.REQ') REPLACE\n/*\n")
    scan = scan_jcl("j.jcl", text)
    defined = {(r.target_kind, r.target) for r in refs(scan, "defines-resource") + refs(scan, "defines-queue")}
    assert {("program", "PAYPGM"), ("transaction", "PAY1"), ("cics-file", "PAYFILE"), ("mq-queue", "PAY.REQ")} <= defined


def test_cobol_compile_and_link_steps_are_build_configuration() -> None:
    text = ("//J JOB\n//COB EXEC PGM=IGYCRCTL,PARM='LIB,OBJECT,SQL'\n//SYSIN DD DSN=PROD.SRC(PAYROLL),DISP=SHR\n"
            "//SYSLIB DD DSN=PROD.COPYLIB,DISP=SHR\n//LKED EXEC PGM=IEWL\n//SYSLMOD DD DSN=PROD.LOAD(PAYROLL),DISP=SHR\n"
            "//SYSLIN DD *\n  NAME PAYROLL(R)\n/*\n")
    scan = scan_jcl("j.jcl", text)
    assert dict(facts(scan, "compile-step")[0].detail)["compiler"] == "IGYCRCTL"
    assert facts(scan, "link-step")
    assert [r.target for r in refs(scan, "builds")] == ["PAYROLL"]
    assert {f.name for f in facts(scan, "load-module")} == {"PAYROLL"}
    assert any(r.target == "PROD.COPYLIB" and dict(r.detail)["purpose"] == "syslib" for r in refs(scan, "uses-library"))


def test_compile_procedure_names_are_recognised() -> None:
    scan = scan_jcl("j.jcl", "//J JOB\n//S1 EXEC PROC=IGYWCL\n")
    assert facts(scan, "compile-step")


def test_unknown_statement_and_empty_file_are_reported() -> None:
    assert "JCL_UNKNOWN_STATEMENT" in {p.code for p in scan_jcl("j.jcl", "//J JOB\n//X FROBNICATE A=B\n").problems}
    assert [p.code for p in scan_jcl("j.jcl", "no jcl here\n").problems] == ["JCL_NO_STATEMENTS"]


def test_standalone_idcams_control_file() -> None:
    scan = scan_control_text("define.idcams", "idcams", "  DEFINE CLUSTER (NAME(A.B) INDEXED KEYS(4 0))\n")
    assert [f.name for f in facts(scan, "vsam-cluster")] == ["A.B"]


def test_scan_is_deterministic() -> None:
    text = "//J JOB\n//S1 EXEC PGM=B\n//D1 DD DSN=Z.Z,DISP=SHR\n//S2 EXEC PGM=A\n"
    assert scan_jcl("j.jcl", text).refs == scan_jcl("j.jcl", text).refs

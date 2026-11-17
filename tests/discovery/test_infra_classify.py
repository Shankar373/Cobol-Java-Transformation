"""BMS, SQL DDL, build/runtime configuration, other legacy languages, classification and EBCDIC decoding."""

from __future__ import annotations

import pytest

from enterprise.discovery.classify import classify
from enterprise.discovery.scan_infra import scan_bms, scan_build, scan_other_language, scan_sql
from enterprise.discovery.textio import decode_source
from tests.discovery.helpers import COBOL_ESTATE


def facts(scan, category):
    return [f for f in scan.facts if f.category == category]


def refs(scan, relation=None):
    return [r for r in scan.refs if relation is None or r.relation == relation]


# --- BMS --------------------------------------------------------------------------------------------------------------


def test_bms_mapset_maps_and_fields() -> None:
    scan = scan_bms("m.bms", COBOL_ESTATE["bms/ORDSET.bms"])
    assert [f.name for f in facts(scan, "bms-mapset")] == ["ORDSET"]
    assert [f.name for f in facts(scan, "bms-map")] == ["ORDSET.ORDMAP"]
    assert [f.name for f in facts(scan, "bms-field")] == ["ORDNO"]
    assert {(r.target_kind, r.target) for r in scan.refs} == {("bms-map", "ORDMAP"), ("bms-mapset", "ORDSET")}


def test_bms_file_without_a_mapset_is_a_problem() -> None:
    assert [p.code for p in scan_bms("m.bms", "* nothing\n").problems] == ["BMS_NO_MAPSET"]


# --- SQL DDL ----------------------------------------------------------------------------------------------------------


def test_ddl_tables_indexes_views_foreign_keys_and_alter() -> None:
    text = ("-- a comment CREATE TABLE HIDDEN (A INT);\n"
            "CREATE TABLE HR.EMP (ID INT, DEPT INT REFERENCES HR.DEPT (ID));\n"
            "/* CREATE TABLE ALSO_HIDDEN (A INT) */\n"
            "CREATE INDEX HR.EMPIX ON HR.EMP (ID);\n"
            "CREATE VIEW HR.V AS SELECT * FROM HR.EMP JOIN HR.DEPT ON 1=1;\n"
            "ALTER TABLE HR.EMP ADD COLUMN X INT;\n")
    scan = scan_sql("s.sql", text)
    assert sorted(r.target for r in refs(scan, "defines-table")) == ["HR.EMP"]
    accessed = sorted({(dict(r.detail)["operation"], r.target) for r in refs(scan, "accesses-table")})
    assert ("REFERENCES", "HR.DEPT") in accessed and ("INDEX", "HR.EMP") in accessed
    assert ("VIEW", "HR.EMP") in accessed and ("ALTER", "HR.EMP") in accessed
    assert "HIDDEN" not in {r.target for r in scan.refs}


def test_ddl_positions_are_exact() -> None:
    scan = scan_sql("s.sql", "\n\n   CREATE TABLE T1 (A INT);\n")
    ref = refs(scan, "defines-table")[0]
    assert (ref.line, ref.column) == (3, 4)


# --- build and runtime configuration --------------------------------------------------------------------------------


def test_makefile_targets_and_cobc_invocation() -> None:
    scan = scan_build("build/Makefile", COBOL_ESTATE["build/Makefile"])
    invocation = facts(scan, "build-invocation")[0]
    info = dict(invocation.detail)
    assert invocation.name == "cobc" and info["format"] == "free" and info["output"] == "payroll"
    assert {r.target for r in refs(scan, "builds")} == {"src/cobol/PAYROLL.cbl"}
    assert [(r.target, dict(r.detail)["purpose"]) for r in refs(scan, "uses-library")] == [("cpy", "copybook-path")]
    assert {f.name for f in facts(scan, "build-target")} == {"all", "payroll"}


def test_shell_script_environment_settings_and_dd_bindings() -> None:
    text = "#!/bin/sh\nexport COBCPY=/app/cpy:/shared/cpy\nexport DD_EMPFILE=/data/emp.dat\nexport DB2INSTANCE=db2inst1\ncobc -x -std=ibm prog.cob -o prog\n"
    scan = scan_build("run.sh", text)
    assert {f.name for f in facts(scan, "runtime-setting")} == {"COBCPY", "DD_EMPFILE", "DB2INSTANCE"}
    assert {r.target for r in refs(scan, "uses-library")} == {"/app/cpy", "/shared/cpy"}
    assert [r.target for r in refs(scan, "binds-ddname")] == ["EMPFILE"]
    assert dict(facts(scan, "build-invocation")[0].detail)["standard"] == "-std=ibm"


def test_maven_and_gradle_dependencies() -> None:
    pom = ("<project><dependencies><dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId>"
           "<version>42.7.0</version></dependency></dependencies></project>")
    assert [f.name for f in facts(scan_build("pom.xml", pom), "java-dependency")] == ["org.postgresql:postgresql:42.7.0"]
    gradle = "dependencies {\n    implementation 'com.ibm.mq:com.ibm.mq.allclient:9.3.0.0'\n}\n"
    assert [f.name for f in facts(scan_build("build.gradle", gradle), "java-dependency")] == ["com.ibm.mq:com.ibm.mq.allclient:9.3.0.0"]


def test_comment_lines_in_scripts_do_not_produce_invocations() -> None:
    assert not facts(scan_build("run.sh", "# cobc -x hidden.cob\nREM cobc hidden2.cob\n"), "build-invocation")


def test_a_make_variable_in_a_source_name_is_a_dynamic_target() -> None:
    scan = scan_build("Makefile", "all:\n\tcobc -x $(SRC)/main.cob\n")
    assert refs(scan, "builds")[0].target == "$(SRC)/main.cob"


# --- other legacy languages -----------------------------------------------------------------------------------------


def test_assembler_csect_and_pli_main_procedure_become_callable_programs() -> None:
    asm = scan_other_language("asm/ASMUTIL.asm", "ASMUTIL  CSECT\nALTENT   CSECT\n", "assembler")
    assert {f.name for f in facts(asm, "program-id")} == {"ALTENT", "ASMUTIL"}
    pli = scan_other_language("pli/CALC.pli", "CALC: PROC OPTIONS(MAIN);\n CALL SUBX;\n END CALC;\n", "pli")
    assert [f.name for f in facts(pli, "program-id")] == ["CALC"] and [r.target for r in refs(pli, "calls")] == ["SUBX"]


# --- classification -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path, text, expected", [
    ("PAYROLL", "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAYROLL.\n", "cobol"),
    ("PAYROLL.cbl", "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAYROLL.\n", "cobol"),
    ("EMPREC", "       01  EMP-REC.\n           05  EMP-ID PIC 9(6).\n           05  EMP-NAME PIC X(30).\n", "copybook"),
    ("EMPREC.cpy", "       01  EMP-REC.\n           05  EMP-ID PIC 9(6).\n", "copybook"),
    ("NIGHTLY", "//NIGHTLY JOB (A),'X'\n//S1 EXEC PGM=IEFBR14\n", "jcl-job"),
    ("MYPROC", "//S1 EXEC PGM=SORT\n//SYSIN DD *\n", "jcl-proc"),
    ("ORDSET", "ORDSET DFHMSD TYPE=MAP\n", "bms"),
    ("schema", "CREATE TABLE T (A INT);\n", "sql"),
    ("DEFVSAM", "  DEFINE CLUSTER (NAME(A.B) INDEXED)\n", "idcams"),
    ("SORTCTL", "  SORT FIELDS=(1,4,CH,A)\n", "sort-control"),
    ("notes.txt", "hello\n", "doc"),
    ("Makefile", "all:\n", "build-config"),
    ("run.sh", "#!/bin/sh\n", "script"),
    (".github/workflows/ci.yml", "name: x\n", "ci-config"),
    ("data.dat", "abc\n", "data"),
    ("MYSTERY", "just some words\n", "unknown"),
    ("EMPTY", "", "unknown"),
])
def test_classification_by_name_and_content(path: str, text: str, expected: str) -> None:
    assert classify(path, text).cls == expected


def test_content_beats_a_misleading_extension_and_says_so() -> None:
    result = classify("EMPREC.cbl", "       01  EMP-REC.\n           05  A PIC X.\n           05  B PIC X.\n")
    assert result.cls == "copybook" and any("extension" in e for e in result.evidence)


def test_binary_and_archive_classes() -> None:
    assert classify("a.bin", None, binary=True).cls == "binary"
    assert classify("nested.zip", None, binary=True).cls == "archive"
    assert classify("prog.exe", None, binary=True).cls == "binary"


# --- decoding ---------------------------------------------------------------------------------------------------------


def test_utf8_bom_cp1252_and_ascii_decoding() -> None:
    assert decode_source(b"\xef\xbb\xbfPROGRAM-ID. A.").text == "PROGRAM-ID. A."
    cp = decode_source("CAFÉ".encode("cp1252"))
    assert cp.text == "CAFÉ" and cp.confidence == "low"
    assert decode_source(b"PLAIN").confidence == "high"


def test_ebcdic_source_with_line_breaks_is_decoded_and_flagged() -> None:
    text = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. EBC.\n"
    data = text.replace("\n", "\x25").encode("cp037")
    decoded = decode_source(data)
    assert decoded.encoding == "ebcdic-cp037" and decoded.confidence == "medium" and "PROGRAM-ID. EBC." in decoded.text


def test_ebcdic_fixed_80_byte_records_without_line_breaks() -> None:
    records = ["       IDENTIFICATION DIVISION.".ljust(80), "       PROGRAM-ID. REC80.".ljust(80)]
    decoded = decode_source("".join(records).encode("cp037"))
    assert decoded.note and decoded.text.splitlines()[1].strip() == "PROGRAM-ID. REC80."


def test_binary_content_is_not_decoded() -> None:
    assert decode_source(b"\x00\x01\x02\xff" * 100).binary


def test_random_bytes_are_never_misread_as_ebcdic_source() -> None:
    assert not decode_source(bytes(range(1, 256)) * 4).text.strip().startswith("IDENTIFICATION")

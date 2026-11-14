"""Per-FD VSAM migration assessment: what the product can say about a file before anything is converted.

The assessment reads the parsed FD (after COPY expansion), derives the record layout with the IBM width
model (source side) and states, per file, whether the migration library can take it: MIGRATABLE,
REQUIRES_PLATFORMS (binary fields: explicit source/target platforms are needed), REFUSED (layout not
derivable; reasons named), BLOCKED (RRDS) or NOT_APPLICABLE (sort work file).  Nothing is guessed.
Dependency-free (pytest only).
"""
from __future__ import annotations

import json

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.assess import assess_file_definition, assess_program


def program(fd_lines: str, select: str = 'SELECT F ASSIGN TO "F.DAT"') -> str:
    return ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
            f"       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           {select}.\n"
            "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n" + fd_lines +
            "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n")


def assess(fd_lines: str, select: str = 'SELECT F ASSIGN TO "F.DAT"'):
    return assess_program(CobolParser().parse(program(fd_lines, select)))


DISPLAY_ONLY = "       01 REC.\n          05 K PIC X(4).\n          05 V PIC 9(3).\n"
PACKED = "       01 REC.\n          05 K PIC X(4).\n          05 A PIC S9(5) COMP-3.\n"
BINARY = "       01 REC.\n          05 K PIC X(4).\n          05 N PIC S9(4) COMP.\n"


def test_a_display_and_packed_file_is_migratable_with_its_layout_summarised():
    (a,) = assess(PACKED)
    assert a["file"] == "F" and a["organization"] == "SEQUENTIAL"
    assert a["migration"]["status"] == "MIGRATABLE" and a["migration"]["reasons"] == []
    assert a["record_layouts"][0]["record_name"] == "REC"
    assert (a["record_layouts"][0]["record_length"], a["record_layouts"][0]["supported"]) == (7, True)
    assert a["record_layouts"][0]["has_binary"] is False


def test_a_binary_field_requires_explicit_platforms():
    (a,) = assess(BINARY)
    assert a["migration"]["status"] == "REQUIRES_PLATFORMS"
    assert any("source_platform" in r and "target_platform" in r for r in a["migration"]["reasons"])
    assert a["record_layouts"][0]["has_binary"] is True


def test_an_indexed_file_reports_its_keys_and_alternate_index_limit():
    select = "\n".join(['SELECT F ASSIGN TO "F.DAT"', "           ORGANIZATION IS INDEXED",
                        "           ACCESS MODE IS DYNAMIC", "           RECORD KEY IS K",
                        "           ALTERNATE RECORD KEY IS V WITH DUPLICATES"])
    (a,) = assess(DISPLAY_ONLY, select)
    assert a["organization"] == "INDEXED" and a["access_mode"] == "DYNAMIC"
    assert a["record_key"] == "K" and a["alternate_keys"] == [{"field": "V", "duplicates": True}]
    assert a["migration"]["status"] == "MIGRATABLE"
    assert any("alternate index" in n for n in a["migration"]["notes"])


def test_a_relative_file_is_blocked_by_name():
    (a,) = assess(DISPLAY_ONLY, 'SELECT F ASSIGN TO "F.DAT" ORGANIZATION IS RELATIVE RELATIVE KEY IS V')
    assert a["migration"]["status"] == "BLOCKED" and any("RRDS" in r for r in a["migration"]["reasons"])


def test_an_unsupported_layout_is_refused_with_the_diagnostic_named():
    (a,) = assess("       01 REC.\n          05 K PIC X(4).\n          05 F1 COMP-1.\n")
    assert a["migration"]["status"] == "REFUSED"
    assert a["record_layouts"][0]["supported"] is False
    assert any("COMP-1" in r or "FLOAT" in r.upper() or "USAGE" in r.upper() for r in a["migration"]["reasons"])


def test_several_records_in_one_fd_are_refused_until_one_is_chosen_and_each_is_summarised():
    (a,) = assess("       01 HDR.\n          05 H PIC X(4).\n       01 DET.\n          05 D PIC X(8).\n")
    assert a["migration"]["status"] == "REFUSED"
    assert any("several records" in r for r in a["migration"]["reasons"])
    assert [l["record_name"] for l in a["record_layouts"]] == ["HDR", "DET"]
    assert [l["record_length"] for l in a["record_layouts"]] == [4, 8]


def test_a_copy_inside_the_fd_is_assessed_like_an_inline_record(tmp_path):
    from engine.transformation.fd_copybooks import expand_fd_copybooks

    (tmp_path / "REC.cpy").write_text(DISPLAY_ONLY, encoding="utf-8")
    source = program("           COPY REC.\n")
    expanded = expand_fd_copybooks(source, (tmp_path,))
    (a,) = assess_program(CobolParser().parse(expanded.source))
    assert a["migration"]["status"] == "MIGRATABLE" and a["record_layouts"][0]["record_length"] == 7


def test_the_assessment_is_deterministic_and_json_serialisable():
    first, second = assess(PACKED), assess(PACKED)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_assessment_states_its_evidence_class_and_never_claims_ibm_equivalence():
    (a,) = assess(PACKED)
    assert a["evidence"]["layout_widths"] == "IBM 2/4/8 byte binary widths, documented; verified against GnuCOBOL only"
    assert "IBM" in a["evidence"]["not_claimed"] and "equivalence" in a["evidence"]["not_claimed"]


def test_a_sort_work_file_is_not_applicable():
    source = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
              "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT S ASSIGN TO \"S.TMP\".\n"
              "       DATA DIVISION.\n       FILE SECTION.\n       SD S.\n       01 SREC.\n          05 K PIC X(4).\n"
              "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           STOP RUN.\n")
    (a,) = assess_program(CobolParser().parse(source))
    assert a["migration"]["status"] == "NOT_APPLICABLE"


def test_assess_file_definition_matches_assess_program():
    parsed = CobolParser().parse(program(PACKED))
    assert assess_program(parsed) == [assess_file_definition(fd) for fd in parsed.file_definitions]

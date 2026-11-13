"""G-26: a ``COPY`` inside an FD reaches the same IR, layout and generated Java as the inline FD.

Copybooks used to be merged into WORKING-STORAGE only, so an FD whose record came from a ``COPY``
had no record: WRITE/REWRITE of it were refused (G-14) and ``derive_file_layout`` said
``FD_NO_RECORD``.  Discovery now expands the COPY statements that sit inside the FILE SECTION
before parsing.  Unresolvable members (missing, ambiguous, cyclic, unreadable) fail closed: the
unit carries an ERROR diagnostic and no record is invented.  Dependency-free (pytest only).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.ir import ReadStatement, RewriteStatement, WriteStatement
from engine.vsam.layout import BinaryWidthModel, derive_file_layout

IBM = BinaryWidthModel.IBM_2_4_8

RECORD = ("       01 CUST-REC.\n"
          "          05 CUST-ID    PIC 9(5).\n"
          "          05 CUST-NAME  PIC X(10).\n"
          "          05 CUST-BAL   PIC S9(7)V99 COMP-3.\n")


def program(fd_body: str, procedure: str | None = None) -> str:
    procedure = procedure or ("           OPEN OUTPUT F.\n"
                              "           MOVE 1 TO CUST-ID.\n"
                              "           WRITE CUST-REC.\n"
                              "           REWRITE CUST-REC.\n"
                              "           CLOSE F.\n")
    return (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        '           SELECT F ASSIGN TO "F.DAT" ORGANIZATION IS INDEXED\n'
        "               RECORD KEY IS CUST-ID.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n" + fd_body +
        "       WORKING-STORAGE SECTION.\n       01 WS-X PIC X.\n"
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n" + procedure + "           STOP RUN.\n"
    )


def discover(tmp_path: Path, source: str, copybooks: dict[str, str] | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name, text in (copybooks or {}).items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (tmp_path / "main.cob").write_text(source, encoding="utf-8")
    return ApplicationDiscovery().discover(tmp_path)


def unit_of(app):
    return next(u for u in app.programs if u.program_id == "MAIN")


def statements(unit, kind):
    return [s for p in unit.program.paragraphs for s in p.statements if isinstance(s, kind)]


def errors(unit) -> list[str]:
    return [d for d in unit.parse_diagnostics if d.startswith(("COPYBOOK_", "UNDEFINED_FILE", "SEMANTIC_ERROR", "PARSE_ERROR"))]


# --- equivalence with the inline FD -----------------------------------------------------------------------------

def test_an_fd_copy_gives_the_same_record_and_layout_as_the_inline_fd(tmp_path):
    inline = unit_of(discover(tmp_path / "inline", program(RECORD)))
    copied = unit_of(discover(tmp_path / "copy", program("       COPY CUSTREC.\n"), {"CUSTREC.cpy": RECORD}))
    assert errors(copied) == [] and errors(inline) == []
    fd_in, fd_cp = inline.program.file_definitions[0], copied.program.file_definitions[0]
    assert fd_cp.record_name == fd_in.record_name == "CUST-REC"
    assert [g.name for g in fd_cp.record_groups] == [g.name for g in fd_in.record_groups]
    layout_in = derive_file_layout(fd_in, binary_width_model=IBM)
    layout_cp = derive_file_layout(fd_cp, binary_width_model=IBM)
    assert layout_cp.supported and layout_cp.identity == layout_in.identity
    assert layout_cp.record_length == layout_in.record_length == 5 + 10 + 5


def test_write_and_rewrite_against_the_copied_record_are_bound_not_refused(tmp_path):
    unit = unit_of(discover(tmp_path, program("       COPY CUSTREC.\n"), {"CUSTREC.cpy": RECORD}))
    assert errors(unit) == []
    assert [s.file_name for s in statements(unit, WriteStatement)] == ["F"]
    assert [s.file_name for s in statements(unit, RewriteStatement)] == ["F"]


def test_the_generated_program_equals_the_one_from_the_inline_fd(tmp_path):
    inline = ApplicationGenerator().generate(discover(tmp_path / "i", program(RECORD)), entrypoint="MAIN",
                                             source_root=tmp_path / "i")
    copied_app = discover(tmp_path / "c", program("       COPY CUSTREC.\n"), {"CUSTREC.cpy": RECORD})
    copied = ApplicationGenerator().generate(copied_app, entrypoint="MAIN", source_root=tmp_path / "c")
    assert inline.success, inline.errors
    assert copied.success, copied.errors
    main_inline = next(f for f in inline.generated_files if f.class_name == "Main")
    main_copied = next(f for f in copied.generated_files if f.class_name == "Main")
    assert main_copied.source_code == main_inline.source_code


def test_the_copybook_record_is_not_also_defined_in_working_storage(tmp_path):
    unit = unit_of(discover(tmp_path, program("       COPY CUSTREC.\n"), {"CUSTREC.cpy": RECORD}))
    assert "CUST-REC" not in {i.name for i in unit.program.working_storage}
    assert "CUSTREC" not in {c.upper() for c in unit.program.copybooks}


def test_the_dependency_on_the_copybook_is_still_recorded(tmp_path):
    unit = unit_of(discover(tmp_path, program("       COPY CUSTREC.\n"), {"CUSTREC.cpy": RECORD}))
    refs = [(c.copybook_name.upper(), c.resolution) for c in unit.copybooks]
    assert ("CUSTREC", "RESOLVED") in refs


# --- shapes ----------------------------------------------------------------------------------------------------------

def test_a_copybook_with_several_01_records_gives_every_record_to_the_fd(tmp_path):
    two = ("       01 HEADER-REC.\n          05 H PIC X(4).\n"
           "       01 DETAIL-REC.\n          05 CUST-ID PIC 9(5).\n")
    body = "       COPY TWO.\n"
    src = program(body, "           WRITE DETAIL-REC.\n           WRITE HEADER-REC.\n").replace(
        "RECORD KEY IS CUST-ID", "RECORD KEY IS CUST-ID")
    unit = unit_of(discover(tmp_path, src, {"TWO.cpy": two}))
    fd = unit.program.file_definitions[0]
    assert [g.name for g in fd.record_groups] == ["HEADER-REC", "DETAIL-REC"]
    assert [s.file_name for s in statements(unit, WriteStatement)] == ["F", "F"]


def test_nested_copy_inside_the_copybook_is_expanded_in_place(tmp_path):
    outer = "       01 CUST-REC.\n          COPY NAMEPART.\n          05 CUST-ID PIC 9(5).\n"
    inner = "          05 CUST-NAME PIC X(10).\n"
    unit = unit_of(discover(tmp_path, program("       COPY OUTER.\n"), {"OUTER.cpy": outer, "NAMEPART.cpy": inner}))
    assert errors(unit) == []
    group = unit.program.file_definitions[0].record_groups[0]
    assert [c.name for c in group.children] == ["CUST-NAME", "CUST-ID"]     # declaration order preserved


def test_replacing_is_applied_to_the_fd_copybook(tmp_path):
    # pseudo-text replaces whole words: CUST-REC and CUST-ID are separate words, so both are named
    body = "       COPY CUSTREC REPLACING ==CUST-REC== BY ==ACCT-REC== ==CUST-ID== BY ==ACCT-ID==.\n"
    src = program(body, "           WRITE ACCT-REC.\n").replace("CUST-ID", "ACCT-ID")
    unit = unit_of(discover(tmp_path, src, {"CUSTREC.cpy": RECORD}))
    assert errors(unit) == []
    assert unit.program.file_definitions[0].record_name == "ACCT-REC"
    assert [g.name for g in unit.program.file_definitions[0].record_groups] == ["ACCT-REC"]


def test_two_fds_each_with_a_copy_each_own_their_record(tmp_path):
    other = "       01 LOG-REC.\n          05 LOG-TEXT PIC X(20).\n"
    src = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        '           SELECT F ASSIGN TO "F.DAT".\n           SELECT G ASSIGN TO "G.DAT".\n'
        "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n       COPY CUSTREC.\n"
        "       FD G.\n       COPY LOGREC.\n"
        "       WORKING-STORAGE SECTION.\n       01 WS-X PIC X.\n"
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           WRITE LOG-REC.\n           WRITE CUST-REC.\n"
        "           STOP RUN.\n")
    unit = unit_of(discover(tmp_path, src, {"CUSTREC.cpy": RECORD, "LOGREC.cpy": other}))
    assert errors(unit) == []
    assert [s.file_name for s in statements(unit, WriteStatement)] == ["G", "F"]


def test_a_working_storage_copy_still_goes_to_working_storage(tmp_path):
    ws = "       01 WS-COPIED PIC X(4).\n"
    src = program(RECORD).replace("       01 WS-X PIC X.\n", "       COPY WSPART.\n")
    app = discover(tmp_path, src, {"WSPART.cpy": ws})
    unit = unit_of(app)
    assert "WSPART" in {c.upper() for c in unit.program.copybooks}       # still merged later, as before
    assert unit.program.file_definitions[0].record_name == "CUST-REC"      # and untouched by the FD expansion


# --- fail closed ---------------------------------------------------------------------------------------------------------

def test_a_missing_copybook_is_refused_and_no_record_is_invented(tmp_path):
    unit = unit_of(discover(tmp_path, program("       COPY NOSUCH.\n")))
    assert any(d.startswith("COPYBOOK_UNRESOLVED") and "NOSUCH" in d for d in unit.parse_diagnostics)
    assert unit.program.file_definitions[0].record_groups == () and unit.program.file_definitions[0].record_name == ""


def test_a_cyclic_copy_is_refused_by_name(tmp_path):
    unit = unit_of(discover(tmp_path, program("       COPY A.\n"),
                            {"A.cpy": "       COPY B.\n", "B.cpy": "       COPY A.\n"}))
    assert any(d.startswith("COPYBOOK_CYCLE") for d in unit.parse_diagnostics)


def test_a_copybook_that_copies_itself_is_a_cycle(tmp_path):
    unit = unit_of(discover(tmp_path, program("       COPY SELF.\n"), {"SELF.cpy": "       COPY SELF.\n"}))
    assert any(d.startswith("COPYBOOK_CYCLE") for d in unit.parse_diagnostics)


def test_an_ambiguous_copybook_name_is_refused_not_picked(tmp_path):
    unit = unit_of(discover(tmp_path, program("       COPY CUSTREC.\n"),
                            {"a/CUSTREC.cpy": RECORD, "b/CUSTREC.cpy": RECORD.replace("PIC 9(5)", "PIC 9(6)")}))
    assert any(d.startswith("COPYBOOK_AMBIGUOUS") for d in unit.parse_diagnostics)
    assert unit.program.file_definitions[0].record_groups == ()


def test_a_missing_nested_copybook_is_refused(tmp_path):
    unit = unit_of(discover(tmp_path, program("       COPY OUTER.\n"),
                            {"OUTER.cpy": "       01 R.\n          COPY GONE.\n"}))
    assert any(d.startswith("COPYBOOK_UNRESOLVED") and "GONE" in d for d in unit.parse_diagnostics)


def test_the_same_record_declared_inline_and_by_copy_is_refused_not_resolved(tmp_path):
    body = RECORD + "       COPY CUSTREC.\n"
    unit = unit_of(discover(tmp_path, program(body), {"CUSTREC.cpy": RECORD}))
    assert any(d.startswith(("UNDEFINED_FILE", "SEMANTIC_ERROR")) and "CUST-REC" in d for d in unit.parse_diagnostics)


def test_a_copy_word_in_a_comment_or_literal_inside_the_fd_is_not_a_copy_statement(tmp_path):
    body = "      * COPY NOSUCH.\n" + RECORD
    unit = unit_of(discover(tmp_path, program(body)))
    assert not any(d.startswith("COPYBOOK_") for d in unit.parse_diagnostics)
    assert unit.program.file_definitions[0].record_name == "CUST-REC"


def test_a_copybook_that_is_not_utf8_is_refused(tmp_path):
    (tmp_path / "BAD.cpy").write_bytes(b"       01 R.\n          05 X PIC X(\xff\xfe).\n")
    unit = unit_of(discover(tmp_path, program("       COPY BAD.\n")))
    assert any(d.startswith("COPYBOOK_UNREADABLE") for d in unit.parse_diagnostics)


def test_existing_inline_fd_behaviour_is_unchanged(tmp_path):
    unit = unit_of(discover(tmp_path, program(RECORD)))
    assert errors(unit) == [] and unit.program.file_definitions[0].record_name == "CUST-REC"
    assert [c.copybook_name for c in unit.copybooks] == []

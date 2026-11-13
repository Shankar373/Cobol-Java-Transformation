"""G-23: discovery resolves record -> file from every FILE SECTION record, with no last-wins.

``ApplicationDiscovery._extract_file_dependencies`` built ``{fd.record_name: fd.name}``:
only the last 01 of an FD, and the last FD wins when two FDs declare the same record
name.  A WRITE of a record that belongs to the first 01 of an FD then produced a
dependency on a file name that does not exist, and a record shared by two FDs silently
bound to one of them.  The contract locked here: every declared 01 of every FD is an
owner key; a record declared under several FDs is *ambiguous* and says so; nothing is
inferred from names; discovery and the parser agree.  Dependency-free (pytest only).
"""
from __future__ import annotations

from pathlib import Path

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import WriteStatement

SELECTS = '''           SELECT {n} ASSIGN TO "{n}.DAT".\n'''


def program(fds: dict[str, list[str]], procedure: str) -> str:
    """fds: FD name -> its 01 record names."""
    text = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TST.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        + "".join(SELECTS.format(n=n) for n in fds)
        + "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
    )
    for fd, records in fds.items():
        text += f"       FD {fd}.\n" + "".join(f"       01 {r} PIC X(10).\n" for r in records)
    text += (
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-BUF PIC X(10).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n" + procedure + "           STOP RUN.\n"
    )
    return text


def deps(tmp_path: Path, fds: dict[str, list[str]], procedure: str):
    (tmp_path / "tst.cob").write_text(program(fds, procedure), encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    unit = app.programs[0]
    return [(d.operation, d.file_name, getattr(d, "ownership_note", "")) for d in unit.file_dependencies]


def writes(result):
    return [(name, note) for op, name, note in result if op == "WRITE"]


def test_one_fd_one_record_resolves_to_the_file(tmp_path):
    result = deps(tmp_path, {"MASTER": ["MASTER-REC"]}, "           WRITE MASTER-REC FROM WS-BUF.\n")
    assert writes(result) == [("MASTER", "")]


def test_every_01_of_a_multi_record_fd_resolves_to_that_fd(tmp_path):
    fds = {"MASTER": ["HEADER-LINE", "DETAIL-LINE", "TRAILER-LINE"]}
    result = deps(tmp_path, fds,
                  "           WRITE HEADER-LINE FROM WS-BUF.\n"
                  "           WRITE DETAIL-LINE FROM WS-BUF.\n"
                  "           WRITE TRAILER-LINE FROM WS-BUF.\n")
    assert writes(result) == [("MASTER", ""), ("MASTER", ""), ("MASTER", "")]


def test_two_fds_with_distinct_records_each_resolve_to_their_own_file(tmp_path):
    fds = {"IN-FILE": ["IN-REC"], "OUT-FILE": ["OUT-REC"]}
    result = deps(tmp_path, fds, "           WRITE OUT-REC FROM WS-BUF.\n           WRITE IN-REC FROM WS-BUF.\n")
    assert [w[0] for w in writes(result)] == ["OUT-FILE", "IN-FILE"]


def test_unconventional_names_resolve_by_declaration_not_by_naming(tmp_path):
    fds = {"CUSTOMERS": ["ZZ-PAYLOAD"], "ORDERS": ["QQ-ROW"]}
    result = deps(tmp_path, fds, "           WRITE QQ-ROW FROM WS-BUF.\n")
    assert writes(result) == [("ORDERS", "")]


def test_a_record_declared_under_two_fds_is_ambiguous_not_last_wins(tmp_path):
    fds = {"A-FILE": ["SHARED-REC"], "B-FILE": ["SHARED-REC"]}
    result = deps(tmp_path, fds, "           WRITE SHARED-REC FROM WS-BUF.\n")
    name, note = writes(result)[0]
    assert name not in ("A-FILE", "B-FILE")          # neither FD is picked
    assert "ambiguous" in note and "A-FILE" in note and "B-FILE" in note


def test_the_same_record_under_three_fds_names_all_three(tmp_path):
    fds = {"A": ["REC"], "B": ["REC"], "C": ["REC"]}
    name, note = writes(deps(tmp_path, fds, "           WRITE REC FROM WS-BUF.\n"))[0]
    assert name not in ("A", "B", "C") and all(f in note for f in ("A", "B", "C"))


def test_a_record_that_no_fd_declares_stays_verbatim_and_unresolved(tmp_path):
    result = deps(tmp_path, {"MASTER": ["MASTER-REC"]}, "           WRITE GHOST-REC FROM WS-BUF.\n")
    assert writes(result) == [("GHOST-REC", "")]


def test_read_and_write_dependencies_resolve_independently(tmp_path):
    fds = {"MASTER": ["HEADER-LINE", "DETAIL-LINE"], "AUDIT": ["AUDIT-ROW"]}
    result = deps(tmp_path, fds,
                  "           READ MASTER.\n"
                  "           WRITE DETAIL-LINE FROM WS-BUF.\n"
                  "           WRITE AUDIT-ROW FROM WS-BUF.\n")
    assert [d[1] for d in result if d[0] == "READ"] == ["MASTER"]
    assert [d[1] for d in result if d[0] == "WRITE"] == ["MASTER", "AUDIT"]


def test_discovery_and_the_parser_agree_on_every_ownership_decision(tmp_path):
    fds = {"MASTER": ["HEADER-LINE", "DETAIL-LINE"], "A-FILE": ["SHARED-REC"], "B-FILE": ["SHARED-REC"]}
    body = ("           WRITE HEADER-LINE FROM WS-BUF.\n"
            "           WRITE DETAIL-LINE FROM WS-BUF.\n"
            "           WRITE SHARED-REC FROM WS-BUF.\n")
    parser = CobolParser()
    parsed = parser.parse(program(fds, body))
    parser_view = [s.file_name for p in parsed.paragraphs for s in p.statements if isinstance(s, WriteStatement)]
    discovery_view = [w[0] for w in writes(deps(tmp_path, fds, body))]
    assert parser_view[:2] == discovery_view[:2] == ["MASTER", "MASTER"]
    assert parser_view[2] == ""                                   # parser refuses the ambiguous record
    assert discovery_view[2] not in ("A-FILE", "B-FILE")           # and discovery does not pick one either
    assert any("ambiguous" in e.message for e in parser.diagnostics.errors)


def test_no_naming_convention_is_used_for_resolution(tmp_path):
    # FD "REPORT-FILE" does not own "REPORT-REC" unless it declares it
    fds = {"REPORT-FILE": ["REPORT-LINE"], "OTHER": ["OTHER-REC"]}
    result = deps(tmp_path, fds, "           WRITE REPORT-REC FROM WS-BUF.\n")
    assert writes(result) == [("REPORT-REC", "")]

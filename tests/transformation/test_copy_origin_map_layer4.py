"""Layer 4: every expanded COPY line can be traced to its copybook file and line (and to the COPY statement)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.copy_origins import CopyOriginMap, OriginBuilder, OriginSpan
from engine.transformation.copybook_model import (
    CopybookDiagnostic,
    _expand_copybook_text,
    _expand_copybook_traced,
    _parse_copybook_expanded,
)
from engine.transformation.fd_copybooks import expand_fd_copybooks

OUTER = (
    "       01 OUTER-REC.\n"
    "          05 O-A PIC X(5).\n"
    "          COPY INNER REPLACING ==TAG== BY ==ALPHA==.\n"
    "          05 O-Z PIC X(2).\n"
)
INNER = (
    "          05 TAG PIC 9(4).\n"
    "          COPY DEEP.\n"
    "          05 TAG2 PIC X.\n"
)
DEEP = (
    "          05 D-ONE PIC 9.\n"
    "          05 D-TWO PIC 9.\n"
)


def _write(tmp_path: Path, **members: str) -> Path:
    for name, text in members.items():
        (tmp_path / f"{name}.cpy").write_text(text, encoding="utf-8", newline="\n")
    return tmp_path


def _line_of(text: str, needle: str) -> int:
    return next(i for i, line in enumerate(text.split("\n"), start=1) if needle in line)


def _posix(tmp_path: Path, name: str) -> str:
    return (tmp_path / f"{name}.cpy").as_posix()


def test_expansion_text_is_unchanged_and_every_line_has_exactly_one_origin(tmp_path: Path):
    _write(tmp_path, OUTER=OUTER, INNER=INNER, DEEP=DEEP)
    text, origins = _expand_copybook_traced(tmp_path / "OUTER.cpy", (tmp_path,), (), [])
    assert text == _expand_copybook_text(tmp_path / "OUTER.cpy", (tmp_path,), (), [])
    assert len(origins.lines) == text.count("\n") + 1
    assert "D-ONE" in text and "D-TWO" in text   # the nested expansion really spliced the text in


def test_nested_copy_and_replacing_lines_name_their_exact_copybook_line(tmp_path: Path):
    _write(tmp_path, OUTER=OUTER, INNER=INNER, DEEP=DEEP)
    diagnostics: list[CopybookDiagnostic] = []
    model = _parse_copybook_expanded(tmp_path / "OUTER.cpy", (tmp_path,), diagnostics)
    assert not diagnostics
    assert model.origins is not None
    outer, inner, deep = (_posix(tmp_path, n) for n in ("OUTER", "INNER", "DEEP"))
    expanded = _expand_copybook_traced(tmp_path / "OUTER.cpy", (tmp_path,), (), [])[0]
    where = {needle: model.origins.origin_of(_line_of(expanded, needle)) for needle in
             ("OUTER-REC", "O-A", "ALPHA PIC 9(4)", "D-ONE", "D-TWO", "TAG2", "O-Z")}
    assert (where["OUTER-REC"].file, where["OUTER-REC"].line, where["OUTER-REC"].via) == (outer, 1, ())
    assert (where["O-A"].file, where["O-A"].line) == (outer, 2)
    first = where["ALPHA PIC 9(4)"]
    assert (first.file, first.line) == (inner, 1)
    assert [(hop.file, hop.line, hop.target) for hop in first.via] == [(outer, 3, "INNER")]
    d1, d2 = where["D-ONE"], where["D-TWO"]
    assert [(d1.file, d1.line), (d2.file, d2.line)] == [(deep, 1), (deep, 2)]
    assert [(hop.file, hop.line, hop.target) for hop in d1.via] == [(outer, 3, "INNER"), (inner, 2, "DEEP")]
    assert d1.chain == (f"{outer}:3", f"{inner}:2", f"{deep}:1")
    assert (where["TAG2"].file, where["TAG2"].line) == (inner, 3)
    assert (where["O-Z"].file, where["O-Z"].line) == (outer, 4)
    assert all(origin.exact for origin in model.origins.lines)


def test_replacing_is_applied_to_the_model_text_and_keeps_the_map_aligned(tmp_path: Path):
    _write(tmp_path, OUTER=OUTER, INNER=INNER, DEEP=DEEP)
    model = _parse_copybook_expanded(tmp_path / "OUTER.cpy", (tmp_path,), [])
    names = [child.name for record in model.records for child in record.children]
    assert "ALPHA" in names and "TAG" not in names     # REPLACING ran on the nested expansion
    assert model.origins is not None
    assert model.origins.origin_of(_line_of(_expand_copybook_traced(
        tmp_path / "OUTER.cpy", (tmp_path,), (), [])[0], "ALPHA PIC 9(4)")).line == 1


def test_changing_a_copybooks_line_count_changes_the_map(tmp_path: Path):
    _write(tmp_path, OUTER=OUTER, INNER=INNER, DEEP=DEEP)
    before = _parse_copybook_expanded(tmp_path / "OUTER.cpy", (tmp_path,), []).origins
    _write(tmp_path, INNER="      * a new first line\n" + INNER)
    after = _parse_copybook_expanded(tmp_path / "OUTER.cpy", (tmp_path,), []).origins
    assert before != after
    inner = _posix(tmp_path, "INNER")
    tag2_before = [o.line for o in before.lines if o.file == inner and o.line == 3]
    tag2_after = [o.line for o in after.lines if o.file == inner and o.line == 4]
    assert tag2_before == [3] and tag2_after == [4]    # the line that was INNER:3 is now INNER:4
    # The model compares equal where the text is equal: the map is provenance, not identity.
    assert _parse_copybook_expanded(tmp_path / "OUTER.cpy", (tmp_path,), []) == \
        _parse_copybook_expanded(tmp_path / "OUTER.cpy", (tmp_path,), [])


def test_a_replacement_with_a_newline_is_attributed_to_the_copy_statement_never_a_guessed_line(tmp_path: Path):
    outer = OUTER.replace("==ALPHA==", "==ALPHA\n          BETA==")
    _write(tmp_path, OUTER=outer, INNER=INNER, DEEP=DEEP)
    origins = _parse_copybook_expanded(tmp_path / "OUTER.cpy", (tmp_path,), []).origins
    assert origins is not None
    inexact = [o for o in origins.lines if not o.exact]
    assert inexact
    assert all((o.file, o.line) == (_posix(tmp_path, "OUTER"), 3) for o in inexact)


def test_cycle_and_missing_expansions_keep_one_origin_per_line(tmp_path: Path):
    _write(tmp_path, A="       01 A-REC.\n          COPY B.\n", B="          COPY A.\n          COPY NOPE.\n")
    diagnostics: list[CopybookDiagnostic] = []
    text, origins = _expand_copybook_traced(tmp_path / "A.cpy", (tmp_path,), (), diagnostics)
    assert {d.code for d in diagnostics} == {"COPYBOOK_CYCLE", "COPYBOOK_UNRESOLVED"}
    assert len(origins.lines) == text.count("\n") + 1
    assert (origins.origin_of(1).file, origins.origin_of(1).line) == (_posix(tmp_path, "A"), 1)


def test_origin_of_fails_outside_the_text():
    with pytest.raises(IndexError):
        CopyOriginMap().origin_of(1)
    builder = OriginBuilder()
    builder.add("x\ny", lambda k: OriginSpan("f", k + 1))
    built = builder.build()
    assert [o.line for o in built.lines] == [1, 2]
    with pytest.raises(IndexError):
        built.origin_of(3)


PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. FDP.\n"
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    "           SELECT IN-FILE ASSIGN TO 'IN.DAT'.\n"
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD  IN-FILE.\n"
    "           COPY INREC.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 X PIC 9.\n"
    "       PROCEDURE DIVISION.\n"
    "           GOBACK.\n"
)
INREC = "       01 IN-REC.\n          COPY SUBREC.\n"
SUBREC = "          05 F1 PIC X.\n          05 F2 PIC X.\n"


def test_fd_copy_expansion_maps_program_and_copybook_lines(tmp_path: Path):
    _write(tmp_path, INREC=INREC, SUBREC=SUBREC)
    expansion = expand_fd_copybooks(PROGRAM, (tmp_path,), source_file="prog.cbl")
    assert expansion.source != PROGRAM and not expansion.errors
    assert expansion.source == expand_fd_copybooks(PROGRAM, (tmp_path,)).source  # the label never changes the text
    text = expansion.source
    inrec, subrec = _posix(tmp_path, "INREC"), _posix(tmp_path, "SUBREC")
    rec = expansion.origin_of(_line_of(text, "IN-REC"))
    assert (rec.file, rec.line) == (inrec, 1) and [(h.file, h.line) for h in rec.via] == [("prog.cbl", 10)]
    f2 = expansion.origin_of(_line_of(text, "F2"))
    assert (f2.file, f2.line) == (subrec, 2)
    assert [(h.file, h.line, h.target) for h in f2.via] == [("prog.cbl", 10, "INREC"), (inrec, 2, "SUBREC")]
    for needle, line in (("PROGRAM-ID", 2), ("FD  IN-FILE", 9), ("WORKING-STORAGE", 11), ("GOBACK", 14)):
        origin = expansion.origin_of(_line_of(text, needle))
        assert (origin.file, origin.line, origin.via) == ("prog.cbl", line, ()), needle
    assert expansion.origins is not None and len(expansion.origins.lines) == text.count("\n") + 1


def test_fd_origin_map_moves_when_the_program_gains_a_line(tmp_path: Path):
    _write(tmp_path, INREC=INREC, SUBREC=SUBREC)
    longer = PROGRAM.replace("       DATA DIVISION.\n", "       DATA DIVISION.\n      * extra\n")
    expansion = expand_fd_copybooks(longer, (tmp_path,), source_file="prog.cbl")
    rec = expansion.origin_of(_line_of(expansion.source, "IN-REC"))
    assert [(h.file, h.line) for h in rec.via] == [("prog.cbl", 11)]


def test_without_an_fd_copy_every_line_is_its_own_origin():
    expansion = expand_fd_copybooks("       IDENTIFICATION DIVISION.\n", (), source_file="p.cbl")
    assert expansion.origins is None
    assert expansion.origin_of(1) == OriginSpan("p.cbl", 1)


def test_copybook_reference_location_is_file_and_line_of_the_copy_statement(tmp_path: Path):
    (tmp_path / "REC.cpy").write_text("       01 REC.\n          05 F PIC X.\n", encoding="utf-8")
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. LOC.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "      * COPY IGNORED.\n"
        "       COPY REC.\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
    )
    (tmp_path / "loc.cbl").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    refs = [c for unit in app.programs for c in unit.copybooks]
    assert [(c.copybook_name, c.location) for c in refs] == [("REC", "loc.cbl:6")]
    (tmp_path / "loc.cbl").write_text(source.replace("      * COPY IGNORED.\n", ""), encoding="utf-8")
    moved = [c for unit in ApplicationDiscovery().discover(tmp_path).programs for c in unit.copybooks]
    assert [c.location for c in moved] == ["loc.cbl:5"]

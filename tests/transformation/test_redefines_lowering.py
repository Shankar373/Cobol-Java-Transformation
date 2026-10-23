"""REDEFINES overlay lowering.

Pinned contract (previously the parser dropped a second sibling after a nested
subgroup, aliases became independent Java fields — so writes through one view
were invisible through the other — and the shipped fixture emitted an
undeclared ``WS_CHAR``):

* certified subset: elementary alphanumeric DISPLAY views over an elementary
  alphanumeric base, written only by an unsubscripted MOVE;
* each certified chain gets one canonical byte string; a write through any view
  splices its bytes at offset 0 and refreshes every sibling view;
* initial values of every view are derived from the base's initial bytes;
* numeric views, groups, OCCURS, chained REDEFINES, non-DISPLAY USAGE, wider
  aliases and non-MOVE writers are reported with ``UNSUPPORTED_CONSTRUCT`` and
  the affected fields are not declared (fail closed by javac).
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.redefines import build_redefines_plan

CERTIFIED = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. REDEFX.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-RECORD.
    05  WS-FULL   PIC X(10) VALUE 'ABCDEFGHIJ'.
    05  WS-HEAD   REDEFINES WS-FULL PIC X(4).
    05  WS-TAIL   REDEFINES WS-FULL PIC X(6).
    05  WS-ONE    REDEFINES WS-FULL PIC X(1).
PROCEDURE DIVISION.
MAIN-LOGIC.
    DISPLAY "FULL=" WS-FULL "|".
    MOVE "XYZ" TO WS-HEAD.
    MOVE "123456" TO WS-TAIL.
    DISPLAY "FULL=" WS-FULL "|".
    STOP RUN.
"""

NUMERIC = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. REDEFN.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-RECORD.
    05  WS-NUM   PIC 9(6) VALUE 123456.
    05  WS-CHAR  REDEFINES WS-NUM PIC X(6).
PROCEDURE DIVISION.
MAIN-LOGIC.
    MOVE "ABCDEF" TO WS-CHAR.
    DISPLAY "N=" WS-NUM.
    STOP RUN.
"""

GROUP_ALIAS = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. REDEFG.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-RECORD.
    05  WS-FULL  PIC X(10) VALUE 'ABCDEFGHIJ'.
    05  WS-PARTS REDEFINES WS-FULL.
        10  WS-P1 PIC X(5).
        10  WS-P2 PIC X(5).
PROCEDURE DIVISION.
MAIN-LOGIC.
    DISPLAY "P1=" WS-P1.
    STOP RUN.
"""

NON_MOVE_WRITER = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. REDEFS.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-RECORD.
    05  WS-FULL  PIC X(10) VALUE 'ABCDEFGHIJ'.
    05  WS-HEAD  REDEFINES WS-FULL PIC X(4).
PROCEDURE DIVISION.
MAIN-LOGIC.
    STRING "ABCD" INTO WS-HEAD.
    DISPLAY "H=" WS-HEAD.
    STOP RUN.
"""


def _parse(source: str):
    parser = CobolParser()
    return parser, parser.parse(source)


def _source(source: str) -> str:
    _, program = _parse(source)
    return JavaGenerator().generate(program)[0].source_code


def _unsupported(parser) -> list[str]:
    return [
        d.message
        for d in parser.diagnostics.all
        if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
    ]


class TestCertifiedOverlay:
    def test_views_are_derived_from_base_initial_bytes(self) -> None:
        source = _source(CERTIFIED)
        assert 'static String WS_FULL = "ABCDEFGHIJ";' in source, source
        assert 'static String WS_HEAD = "ABCD";' in source, source
        assert 'static String WS_TAIL = "ABCDEF";' in source, source
        assert 'static String WS_ONE = "A";' in source, source
        assert 'static String WS_FULL$BYTES = "ABCDEFGHIJ";' in source, source

    def test_write_to_short_view_keeps_untouched_tail(self) -> None:
        source = _source(CERTIFIED)
        assert "WS_FULL$BYTES = (WS_HEAD + WS_FULL$BYTES.substring(4));" in source
        assert "WS_FULL = WS_FULL$BYTES.substring(0, 10);" in source
        assert "WS_TAIL = WS_FULL$BYTES.substring(0, 6);" in source

    def test_write_to_base_refreshes_every_alias(self) -> None:
        src = CERTIFIED.replace(
            'MOVE "XYZ" TO WS-HEAD.',
            'MOVE "0123456789" TO WS-FULL.',
        )
        source = _source(src)
        assert "WS_FULL$BYTES = (WS_FULL + WS_FULL$BYTES.substring(10));" in source
        assert "WS_HEAD = WS_FULL$BYTES.substring(0, 4);" in source
        assert "WS_ONE = WS_FULL$BYTES.substring(0, 1);" in source

    def test_plan_is_all_or_nothing_per_chain(self) -> None:
        _, program = _parse(CERTIFIED)
        plan = build_redefines_plan(program.working_storage)
        assert not plan.problems
        assert set(plan.views) == {"WS-FULL", "WS-HEAD", "WS-TAIL", "WS-ONE"}


class TestUncertifiedOverlaysFailClosed:
    def test_numeric_view_reported_and_not_declared(self) -> None:
        parser, program = _parse(NUMERIC)
        messages = _unsupported(parser)
        assert any("REDEFINES" in m and "numeric" in m for m in messages), messages
        source = JavaGenerator().generate(program)[0].source_code
        assert "static String WS_CHAR =" not in source, source
        # The base is part of the uncertified chain: no silently wrong store.
        assert "static int WS_NUM =" not in source, source

    def test_group_alias_reported_and_children_not_declared(self) -> None:
        parser, program = _parse(GROUP_ALIAS)
        messages = _unsupported(parser)
        assert any("group" in m for m in messages), messages
        source = JavaGenerator().generate(program)[0].source_code
        for name in ("WS_PARTS", "WS_P1", "WS_P2", "WS_FULL"):
            assert f"static String {name} " not in source, (name, source)
        # The references remain, so javac fails closed by name.
        assert "WS_P1" in source, source

    def test_non_move_writer_reported(self) -> None:
        parser, _ = _parse(NON_MOVE_WRITER)
        messages = _unsupported(parser)
        assert any("STRING" in m and "overlay sync" in m for m in messages), messages

    def test_chained_redefines_reported(self) -> None:
        src = CERTIFIED.replace(
            "    05  WS-ONE    REDEFINES WS-FULL PIC X(1).",
            "    05  WS-ONE    REDEFINES WS-HEAD PIC X(1).",
        )
        parser, _ = _parse(src)
        assert any("chained" in m for m in _unsupported(parser)), _unsupported(parser)

    def test_wide_alias_reported(self) -> None:
        src = CERTIFIED.replace("PIC X(4).", "PIC X(14).")
        parser, _ = _parse(src)
        assert any("wider" in m for m in _unsupported(parser)), _unsupported(parser)


class TestSiblingHierarchyRegression:
    def test_second_sibling_after_nested_subgroup_is_kept(self) -> None:
        src = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. SIBLING.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-RECORD.
    05  WS-A PIC X(4).
    05  WS-B REDEFINES WS-A.
        10  WS-B1 PIC X(2).
        10  WS-B2 PIC X(2).
    05  WS-C PIC X(3).
PROCEDURE DIVISION.
MAIN-LOGIC.
    DISPLAY WS-C.
    STOP RUN.
"""
        _, program = _parse(src)
        assert "WS-C" in [item.name for item in program.working_storage], (
            [item.name for item in program.working_storage]
        )

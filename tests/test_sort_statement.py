"""Roadmap unit 9: SORT -- parsing, SD handling, layout, lowering and refusals.

The behaviour against GnuCOBOL 3.1.2 is in ``tests/integration/test_sort_oracle.py``.
"""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import SortStatement
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY
from engine.transformation.sort_lowering import layout, unsupported_reasons
from engine.transformation.sort_statement import parse_sort


def _source(sort: str, *, sd_body: str | None = None, in_org: str = "LINE SEQUENTIAL",
            out_org: str = "LINE SEQUENTIAL", out_len: int = 10) -> str:
    sd_body = sd_body if sd_body is not None else (
        "          05 S-KEY PIC X(3).\n          05 S-NUM PIC 9(2).\n          05 S-REST PIC X(5).\n")
    return (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        f"           SELECT IN-FILE ASSIGN TO 'in.dat'\n               ORGANIZATION IS {in_org}.\n"
        f"           SELECT OUT-FILE ASSIGN TO 'out.dat'\n               ORGANIZATION IS {out_org}.\n"
        "           SELECT SORT-FILE ASSIGN TO 'sort.tmp'.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n"
        "       FD IN-FILE.\n       01 IN-REC PIC X(10).\n"
        f"       FD OUT-FILE.\n       01 OUT-REC PIC X({out_len}).\n"
        f"       SD SORT-FILE.\n       01 SORT-REC.\n{sd_body}"
        "       PROCEDURE DIVISION.\n       MAIN.\n" + sort + "           STOP RUN.\n")


GOOD = (
    "           SORT SORT-FILE\n               ON ASCENDING KEY S-KEY\n               ON DESCENDING KEY S-NUM\n"
    "               USING IN-FILE GIVING OUT-FILE.\n")


def _program(sort: str = GOOD, **kw):
    return CobolParser().parse(_source(sort, **kw))


def _sort(program) -> SortStatement:
    return next(s for p in program.paragraphs for s in p.statements if isinstance(s, SortStatement))


class TestParse:
    def test_keys_directions_files(self):
        file, keys, using, giving, reasons = parse_sort(
            "SORT SORT-FILE ON ASCENDING KEY A B ON DESCENDING KEY C USING IN-F GIVING OUT-F.")
        assert (file, keys, using, giving, reasons) == (
            "SORT-FILE", (("A", "ASCENDING"), ("B", "ASCENDING"), ("C", "DESCENDING")),
            ("IN-F",), ("OUT-F",), ())

    def test_on_and_key_are_optional_and_duplicates_in_order_is_accepted(self):
        _, keys, _, _, reasons = parse_sort(
            "SORT S ASCENDING A DESCENDING KEY B WITH DUPLICATES IN ORDER USING I GIVING O")
        assert keys == (("A", "ASCENDING"), ("B", "DESCENDING")) and reasons == ()

    @pytest.mark.parametrize("text,reason", [
        ("SORT S ON ASCENDING KEY A INPUT PROCEDURE IS P1 GIVING O", "INPUT_PROCEDURE"),
        ("SORT S ON ASCENDING KEY A USING I OUTPUT PROCEDURE IS P2", "OUTPUT_PROCEDURE"),
        ("SORT S ON ASCENDING KEY A USING I J GIVING O", "USING_COUNT"),
        ("SORT S ON ASCENDING KEY A USING I GIVING O P", "GIVING_COUNT"),
        ("SORT S USING I GIVING O", "NO_KEYS"),
        ("SORT S ON ASCENDING KEY A COLLATING SEQUENCE IS X USING I GIVING O", "COLLATING"),
        ("SORT S ON ASCENDING KEY A THRU B USING I GIVING O", "CLAUSE_THRU"),
    ])
    def test_everything_else_is_named(self, text, reason):
        assert reason in parse_sort(text)[4]


class TestStatementAndFiles:
    def test_the_statement_and_the_sd_reach_the_ir(self):
        program = _program()
        stmt = _sort(program)
        assert stmt.keys == (("S-KEY", "ASCENDING"), ("S-NUM", "DESCENDING")) and stmt.reasons == ()
        files = {f.name: f for f in program.file_definitions}
        assert files["SORT-FILE"].is_sort_file and not files["IN-FILE"].is_sort_file
        # the SD record no longer leaks into the preceding FD
        assert [i.name for i in files["OUT-FILE"].record_items] == ["OUT-REC"]
        assert [i.name for i in files["SORT-FILE"].record_items] == ["S-KEY", "S-NUM", "S-REST"]

    def test_the_layout_is_offsets_and_total_length(self):
        sd = {f.name: f for f in _program().file_definitions}["SORT-FILE"]
        leaves, total = layout(sd)
        assert total == 10 and {k: v[:2] for k, v in leaves.items()} == {
            "S-KEY": (0, 3), "S-NUM": (3, 2), "S-REST": (5, 5)}

    def test_keys_inside_groups_have_their_offsets(self):
        body = ("          05 GRP-A.\n             10 PRE PIC X(2).\n             10 S-KEY PIC X(3).\n"
                "          05 GRP-B.\n             10 S-NUM PIC 9(2).\n             10 S-REST PIC X(3).\n")
        sd = {f.name: f for f in _program(sd_body=body).file_definitions}["SORT-FILE"]
        leaves, total = layout(sd)
        assert total == 10 and leaves["S-KEY"][:2] == (2, 3) and leaves["S-NUM"][:2] == (5, 2)


class TestLowering:
    def test_it_renders_the_run_call_with_key_specs(self):
        source = JavaGenerator().generate(_program())[0].source_code
        assert 'CobolSort.run("in.dat", "out.dat", 10, "A:0:3", "D:3:2")' in source
        assert "final class CobolSort" in source and "final class CobolFileIo" in source
        assert "gnucobol" not in source.lower()

    def test_no_support_class_without_a_sort(self):
        source = JavaGenerator().generate(CobolParser().parse(
            _source("           DISPLAY 'X'.\n")))[0].source_code
        assert "CobolSort" not in source

    @pytest.mark.parametrize("kwargs,sort,reason", [
        ({}, GOOD.replace("ON DESCENDING KEY S-NUM", "ON DESCENDING KEY S-MISSING"), "KEY_NOT_ELEMENTARY"),
        ({"in_org": "SEQUENTIAL"}, GOOD, "USING_RECORD_SEQUENTIAL"),
        ({"out_org": "SEQUENTIAL"}, GOOD, "GIVING_RECORD_SEQUENTIAL"),
        ({"out_len": 12}, GOOD, "RECORD_LENGTHS"),
        ({"sd_body": "          05 S-KEY PIC X(3).\n          05 S-NUM PIC S9(2).\n          05 S-REST PIC X(5).\n"},
         GOOD, "KEY_SIGNED"),
        ({"sd_body": "          05 S-KEY PIC X(3).\n          05 S-NUM PIC 9(2) COMP.\n          05 S-REST PIC X(5).\n"},
         GOOD, "RECORD_LAYOUT"),
        ({}, GOOD.replace("GIVING OUT-FILE", "GIVING IN-FILE"), "SAME_FILE"),
        ({}, GOOD.replace("SORT SORT-FILE", "SORT IN-FILE"), "SD"),
        ({}, GOOD.replace("USING IN-FILE", "USING NOFILE"), "FILES"),
    ])
    def test_outside_the_subset_fails_closed_by_name(self, kwargs, sort, reason):
        program = _program(sort, **kwargs)
        assert reason in unsupported_reasons(_sort(program), program)
        source = JavaGenerator().generate(program)[0].source_code
        assert "UNSUPPORTED_SORT$" in source and "CobolSort.run(" not in source

    def test_input_and_output_procedures_fail_closed(self):
        program = _program("           SORT SORT-FILE ON ASCENDING KEY S-KEY\n"
                           "               INPUT PROCEDURE IS P1 GIVING OUT-FILE.\n")
        assert "INPUT_PROCEDURE" in _sort(program).reasons
        assert "UNSUPPORTED_SORT$INPUT_PROCEDURE" in JavaGenerator().generate(program)[0].source_code


def test_registry_marks_sort_supported_with_the_subset_named_and_merge_still_refused():
    assert CONSTRUCT_REGISTRY["SORT"].level.name == "SUPPORTED"
    assert "GnuCOBOL" in CONSTRUCT_REGISTRY["SORT"].evidence
    assert CONSTRUCT_REGISTRY["MERGE"].level.name == "UNSUPPORTED"

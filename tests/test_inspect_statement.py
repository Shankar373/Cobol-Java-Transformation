"""Roadmap unit 9: INSPECT parsing, refusals and capability classification.

The run-time behaviour (every form against GnuCOBOL 3.1.2, plus a seeded fuzz) is proven in
``tests/integration/test_inspect_oracle.py``.
"""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_statement
from engine.transformation.inspect_statement import InspectPhrase, parse_inspect
from engine.transformation.ir import InspectStatement
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY

HEADER = (
    "IDENTIFICATION DIVISION.\nPROGRAM-ID. T.\nDATA DIVISION.\nWORKING-STORAGE SECTION.\n"
    "01 F PIC X(8).\n01 N PIC 9(3).\n01 NUM PIC 9(4).\n01 G.\n   05 G1 PIC X(2).\n"
    "PROCEDURE DIVISION.\nMAIN.\n"
)


def _statement(body: str) -> InspectStatement:
    program = CobolParser().parse(HEADER + body + "    STOP RUN.\n")
    found = [s for p in program.paragraphs for s in p.statements if isinstance(s, InspectStatement)]
    assert len(found) == 1
    return found[0]


def _java(body: str) -> str:
    program = CobolParser().parse(HEADER + body + "    STOP RUN.\n")
    return JavaGenerator().generate(program)[0].source_code


class TestParsing:
    def test_tallying_with_bounds(self):
        target, mode, phrases, reasons = parse_inspect(
            'INSPECT F TALLYING N FOR ALL "AB" BEFORE INITIAL "X" LEADING "A" CHARACTERS.')
        assert (target, mode, reasons) == ("F", "TALLYING", ())
        assert phrases == (
            InspectPhrase("ALL", "AB", "", "B", "", "X", "N"),
            InspectPhrase("LEADING", "A", "", "", "", "", "N"),
            InspectPhrase("CHARACTERS", "", "", "", "", "", "N"),
        )

    def test_a_kind_carries_over_to_the_next_literal(self):
        phrases = parse_inspect('INSPECT F TALLYING N FOR ALL "A" "B"')[2]
        assert [(p.kind, p.pattern) for p in phrases] == [("ALL", "A"), ("ALL", "B")]

    def test_replacing_and_figuratives(self):
        phrases = parse_inspect('INSPECT F REPLACING ALL SPACES BY ZEROS AFTER INITIAL "Q" BEFORE "R"')[2]
        assert phrases == (InspectPhrase("ALL", " ", "0", "AB", "Q", "R"),)

    def test_doubled_quotes_decode(self):
        assert parse_inspect("INSPECT F CONVERTING 'A' TO 'It''s'")[3] == ("CONVERTING_LENGTHS",)
        assert parse_inspect("INSPECT F REPLACING ALL 'A' BY 'B'")[2][0].pattern == "A"

    def test_converting(self):
        target, mode, phrases, reasons = parse_inspect('INSPECT F CONVERTING "ab" TO "XY"')
        assert (mode, reasons) == ("CONVERTING", ())
        assert (phrases[0].pattern, phrases[0].replacement) == ("ab", "XY")

    @pytest.mark.parametrize("text,reason", [
        ("INSPECT F TALLYING N FOR ALL W", "ALL_OPERAND"),
        ("INSPECT F TALLYING N FOR TRAILING \"A\"", "CLAUSE_TRAILING"),
        ("INSPECT F TALLYING N FOR ALL \"A\" REPLACING ALL \"A\" BY \"B\"", "COMBINED"),
        ("INSPECT F TALLYING N FOR ALL HIGH-VALUES", "ALL_OPERAND"),
        ("INSPECT F REPLACING ALL \"AB\" BY \"C\"", "REPLACING_LENGTHS"),
        ("INSPECT F REPLACING CHARACTERS BY \"CD\"", "REPLACING_LENGTHS"),
        ("INSPECT F CONVERTING \"AB\" TO \"C\"", "CONVERTING_LENGTHS"),
        ("INSPECT F TALLYING N FOR ALL \"A\" M FOR ALL \"B\"", "MULTIPLE_COUNTERS"),
        ("INSPECT F REPLACING ALL \"A\" BY \"B\" BEFORE \"X\" BEFORE \"Y\"", "DUPLICATE_BEFORE"),
        ("INSPECT F SOMETHING", "FORM"),
    ])
    def test_everything_else_is_named(self, text, reason):
        assert reason in parse_inspect(text)[3]


class TestStatementAndLowering:
    def test_the_statement_reaches_the_ir(self):
        stmt = _statement('    INSPECT F TALLYING N FOR ALL "A".\n')
        assert (stmt.target, stmt.mode, stmt.counter) == ("F", "TALLYING", "N")

    def test_a_statement_that_continues_on_the_next_line(self):
        stmt = _statement('    INSPECT F\n        REPLACING ALL "A" BY "B"\n        AFTER INITIAL "X".\n')
        assert stmt.phrases[0].after == "X"

    def test_the_next_statement_is_not_swallowed(self):
        program = CobolParser().parse(
            HEADER + '    INSPECT F REPLACING ALL "A" BY "B"\n    MOVE 1 TO N\n    STOP RUN.\n')
        kinds = [type(s).__name__ for p in program.paragraphs for s in p.statements]
        assert kinds == ["InspectStatement", "MoveStatement", "StopRunStatement"]

    def test_tallying_lowers_to_the_runtime_helper(self):
        source = _java('    INSPECT F TALLYING N FOR ALL "A".\n')
        assert "CobolInspect.tally(F, N, 3," in source
        assert "final class CobolInspect" in source
        assert "gnucobol" not in source.lower()

    def test_replacing_and_converting_lower_to_rewrite(self):
        source = _java('    INSPECT F REPLACING ALL "A" BY "B".\n    INSPECT F CONVERTING "A" TO "C".\n')
        assert 'CobolInspect.rewrite(F, "ALL", "A", "B"' in source
        assert 'CobolInspect.rewrite(F, "CONVERTING", "A", "C"' in source

    def test_no_helper_when_unused(self):
        assert "CobolInspect" not in _java("    MOVE 1 TO N.\n")

    @pytest.mark.parametrize("body,reason", [
        ('    INSPECT NUM REPLACING ALL "1" BY "2".\n', "TARGET"),
        ('    INSPECT G REPLACING ALL "A" BY "B".\n', "TARGET"),
        ('    INSPECT F TALLYING F FOR ALL "A".\n', "COUNTER"),
        ('    INSPECT F TALLYING G1 FOR ALL "A".\n', "COUNTER"),
        ('    INSPECT F TALLYING N FOR TRAILING "A".\n', "CLAUSE_TRAILING"),
        ('    INSPECT MISSING TALLYING N FOR ALL "A".\n', "TARGET"),
    ])
    def test_outside_the_subset_fails_closed_by_name(self, body, reason):
        program = CobolParser().parse(HEADER + body + "    STOP RUN.\n")
        stmt = [s for p in program.paragraphs for s in p.statements if isinstance(s, InspectStatement)][0]
        mapped = map_cobol_statement(stmt, program)
        assert any(f"UNSUPPORTED_INSPECT${reason}" in repr(m) or reason in repr(m) for m in mapped)
        assert "UNSUPPORTED_INSPECT$" in repr(mapped)


def test_registry_marks_inspect_supported_with_the_subset_named():
    entry = CONSTRUCT_REGISTRY["INSPECT"]
    assert entry.level.name == "SUPPORTED"
    assert "literal" in entry.evidence.lower()

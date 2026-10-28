"""Figurative fill semantics (BL-030) — pattern replication, not space padding.

Regression origin (Phase 2): the figurative *parser* understood ``ALL``, but
two emission sites did not materialize the fill at the receiving item's
declared PIC width:

* ``MOVE ALL "." TO PIC X(10)`` emitted the one-character literal padded at
  runtime, so the receiver stored ``".          "`` instead of ``..........``;
* ``MOVE ALL "AB" TO PIC X(10)`` emitted ``"AB   "`` (raw COBOL spelling plus
  space padding) instead of ``ABABABABAB``;
* ``01 WS-V PIC X(10) VALUE ALL "*".`` emitted the raw text
  ``static String WS_V = "ALL "*    ";`` — non-compiling Java produced through
  the ``map_pic_to_java_default`` VALUE path while the verdict stayed
  ``SUPPORTED``;
* ``MOVE ZEROS TO PIC X(5)`` stored ``0     `` instead of ``00000``.

Every expected value below is the byte-for-byte GnuCOBOL 3.1.2 oracle output
(``bl030_post`` / ``bl030_cobol_run.txt`` vs ``bl030_java_run.txt``,
``ORACLE_MATCH=YES``, 11/11 lines).  Deterministic only: no model, no LLM.
"""

from __future__ import annotations

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.transformation import figurative
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_pic_to_java_default
from engine.transformation.ir import CobolApplication, CobolProgramUnit, DataItem
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY, CapabilityLevel


def _program(proc: str, items: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. FILL.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{items}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        + "".join(f"           {line}\n" for line in proc.splitlines())
        + "           STOP RUN.\n"
    )


def _generate(source: str) -> str:
    return JavaGenerator().generate(CobolParser().parse(source))[0].source_code


def _classify(source: str) -> CapabilityLevel:
    program = CobolParser().parse(source)
    unit = CobolProgramUnit(
        program_id="FILL", source_path="FILL.cob",
        program=program, source_text=source,
    )
    report = CapabilityAnalyzer(docker_available=True).analyze(
        CobolApplication(application_id="T", programs=(unit,))
    )
    programs = [c for c in report.components if c.component_type == "PROGRAM"]
    return programs[0].level


# ---------------------------------------------------------------------------
# figurative_to_width — the single fill rule
# ---------------------------------------------------------------------------

class TestFigurativeToWidth:
    @pytest.mark.parametrize(
        ("kind", "fill", "width", "expected"),
        [
            (figurative.SPACES, None, 5, "     "),
            (figurative.QUOTES, None, 3, '"""'),
            (figurative.ZERO, None, 5, "00000"),
            (figurative.ALL, ".", 10, ".........."),
            (figurative.ALL, "*", 10, "**********"),
            (figurative.ALL, "AB", 10, "ABABABABAB"),
            (figurative.ALL, "ABC", 10, "ABCABCABCA"),
            (figurative.ALL, "A", 1, "A"),
        ],
    )
    def test_fill_is_materialized_at_the_width(self, kind, fill, width, expected):
        assert figurative.figurative_to_width(kind, fill, width) == expected

    @pytest.mark.parametrize("width", [0, -1, None])
    def test_non_positive_width_returns_none(self, width):
        # A caller must never invent a fill for an unknown receiver width.
        assert figurative.figurative_to_width(figurative.ALL, "*", width) is None

    def test_all_without_a_pattern_returns_none(self):
        assert figurative.figurative_to_width(figurative.ALL, None, 5) is None

    def test_unknown_kind_returns_none(self):
        assert figurative.figurative_to_width("NOPE", None, 5) is None

    @pytest.mark.parametrize(
        ("spelling", "kind"),
        [
            ("ALL ZEROS", figurative.ZERO),
            ("ALL ZEROES", figurative.ZERO),
            ("ALL SPACE", figurative.SPACES),
            ("ALL QUOTES", figurative.QUOTES),
        ],
    )
    def test_all_figurative_word_collapses_onto_the_word(self, spelling, kind):
        parsed = figurative.parse_figurative_constant(spelling)
        assert parsed is not None
        assert parsed[0] == kind

    def test_all_literal_carries_a_multi_character_pattern(self):
        kind, fill = figurative.parse_figurative_constant('ALL "AB"')
        assert kind == figurative.ALL
        assert fill == "AB"


# ---------------------------------------------------------------------------
# MOVE — oracle-pinned receiver contents
# ---------------------------------------------------------------------------

class TestMoveFillEmission:
    @pytest.mark.parametrize(
        ("stmt", "expected"),
        [
            # WS-R is PIC X(5), WS-W is PIC X(10) — the fill is exactly the
            # receiving width in every case (GnuCOBOL oracle).
            ('MOVE ALL "." TO WS-R.', 'WS_R = ".....";'),
            ('MOVE ALL "AB" TO WS-R.', 'WS_R = "ABABA";'),
            ('MOVE ALL "ABC" TO WS-W.', 'WS_W = "ABCABCABCA";'),
            ("MOVE ZEROS TO WS-R.", 'WS_R = "00000";'),
            ("MOVE ALL ZEROS TO WS-R.", 'WS_R = "00000";'),
            ("MOVE SPACES TO WS-R.", 'WS_R = "     ";'),
            ("MOVE ALL SPACES TO WS-R.", 'WS_R = "     ";'),
            ("MOVE QUOTES TO WS-R.", 'WS_R = "\\"\\"\\"\\"\\"";'),
        ],
    )
    def test_move_stores_the_oracle_value(self, stmt, expected):
        source = _program(
            stmt,
            "01 WS-R PIC X(5).\n01 WS-W PIC X(10).\n",
        )
        assert expected in _generate(source), expected

    def test_no_cobol_spelling_leaks_into_the_java(self):
        source = _program(
            'MOVE ALL "AB" TO WS-R.',
            "01 WS-R PIC X(5).\n",
        )
        code = _generate(source)
        assert "ALL " not in code
        assert 'String.format("%-' not in code

    def test_numeric_move_of_a_figurative_stays_numeric(self):
        source = _program("MOVE ALL ZEROS TO WS-N.", "01 WS-N PIC 9(5).\n")
        assert "WS_N = 0;" in _generate(source)


# ---------------------------------------------------------------------------
# VALUE — the map_pic_to_java_default emission site
# ---------------------------------------------------------------------------

class TestValueFillEmission:
    @staticmethod
    def _value_default(pic: str, value: str, numeric: bool = False) -> str:
        from engine.transformation.ir import PicType

        width = int(pic.split("(")[1].rstrip(")")) if "(" in pic else 1
        item = DataItem(
            name="WS-V",
            pic_type=PicType.NUMERIC if numeric else PicType.ALPHANUMERIC,
            pic_length=width,
            value=value,
        )
        return map_pic_to_java_default(item)

    @pytest.mark.parametrize(
        ("pic", "value", "numeric", "expected"),
        [
            ("X(10)", 'ALL "*"', False, '"**********"'),
            ("X(10)", 'ALL "AB"', False, '"ABABABABAB"'),
            ("X(5)", "ALL ZEROS", False, '"00000"'),
            ("X(10)", "ALL SPACES", False, '"          "'),
            ("X(5)", "SPACES", False, '"     "'),
            ("9(5)", "ALL ZEROS", True, "0"),
            ("9(5)", "ZEROS", True, "0"),
            ("X(10)", '"HELLO"', False, '"HELLO     "'),
        ],
    )
    def test_value_materializes_at_the_pic_width(
        self, pic, value, numeric, expected
    ):
        assert self._value_default(pic, value, numeric) == expected

    def test_quoted_literal_is_never_treated_as_figurative(self):
        # VALUE "ZERO" is data, not the reserved word.
        assert self._value_default("X(5)", '"ZERO"') == '"ZERO "'

    def test_generated_declaration_is_valid_java(self):
        source = _program(
            'DISPLAY WS-V1.',
            '01 WS-V1 PIC X(10) VALUE ALL "*".\n'
            '01 WS-V2 PIC X(10) VALUE ALL "AB".\n'
            '01 WS-V3 PIC X(5) VALUE ALL ZEROS.\n'
            '01 WS-V5 PIC X(10) VALUE ALL SPACES.\n',
        )
        code = _generate(source)
        assert 'static String WS_V1 = "**********";' in code
        assert 'static String WS_V2 = "ABABABABAB";' in code
        assert 'static String WS_V3 = "00000";' in code
        assert 'static String WS_V5 = "          ";' in code
        # the pre-BL-030 emission was non-compiling raw COBOL text
        assert 'static String WS_V1 = "ALL ' not in code
        assert "ALL " not in code


# ---------------------------------------------------------------------------
# Capability truth — the verdict must stay honest
# ---------------------------------------------------------------------------

class TestFillCapabilityTruth:
    def test_registry_evidence_names_bl030(self):
        entry = CONSTRUCT_REGISTRY["FIGURATIVE CONSTANT"]
        assert entry.level is CapabilityLevel.SUPPORTED
        assert "BL-030" in entry.evidence
        assert entry.evidence

    @pytest.mark.parametrize(
        "stmt",
        [
            'MOVE ALL "AB" TO WS-R.',
            "MOVE ZEROS TO WS-R.",
            'MOVE ALL "." TO WS-R.',
        ],
    )
    def test_program_using_fill_forms_is_supported(self, stmt):
        source = _program(stmt, "01 WS-R PIC X(5).\n")
        assert _classify(source) is CapabilityLevel.SUPPORTED

    def test_value_all_program_is_supported(self):
        source = _program(
            "DISPLAY WS-V1.",
            '01 WS-V1 PIC X(10) VALUE ALL "*".\n',
        )
        assert _classify(source) is CapabilityLevel.SUPPORTED

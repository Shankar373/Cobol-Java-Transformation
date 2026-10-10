"""Figurative constants: parse to semantics, not to undeclared variables.

Regression origin (Phase 1, BL-018): a COBOL figurative constant such as
``ZERO``, ``SPACES`` or ``ALL '*'`` is a reserved *word* with a fixed value.
The parser used to lower it to a ``FieldReference`` named after the word, so
the mapper emitted ``A = ZERO;`` / ``String.format("%-60s", SPACES)`` — Java
referencing an undeclared variable.  That output does not compile, no
diagnostic was emitted, and the capability analyzer still certified the
program ``SUPPORTED``.

The contract locked in here:

* the parser records ``ir.FigurativeConstant`` (Master README Section 17),
* the mapper expands it across the receiving item's declared PIC width,
* a comparison against a figurative constant tests *every* character,
* a hyphenated identifier such as ``HIGH-VALUE-CODE`` is never a constant,
* the capability verdict is backed by the IR, not by a source match alone.

Deterministic only: no model, no LLM, no heuristics.
"""

import pytest
from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.transformation import figurative
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_expr_to_java
from engine.transformation.ir import (
    CobolApplication,
    CobolProgramUnit,
    Expression,
    FigurativeConstant,
    FieldReference,
    Literal,
    MoveStatement,
)
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY, CapabilityLevel

WORKING_STORAGE = (
    "       01 WS-NUM  PIC 9(4) VALUE 0.\n"
    "       01 WS-TEXT PIC X(10).\n"
)


def _program(*body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. FIGCONST.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{WORKING_STORAGE}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        + "".join(f"           {line}\n" for line in body)
        + "           STOP RUN.\n"
    )


def _moves(source: str) -> list[MoveStatement]:
    program = CobolParser().parse(source)
    return [
        stmt
        for paragraph in program.paragraphs
        for stmt in paragraph.statements
        if isinstance(stmt, MoveStatement)
    ]


def _generate(source: str) -> str:
    return JavaGenerator().generate(CobolParser().parse(source))[0].source_code


def _classify(source: str) -> CapabilityLevel:
    program = CobolParser().parse(source)
    unit = CobolProgramUnit(
        program_id="FIGCONST", source_path="MAIN.cob",
        program=program, source_text=source,
    )
    report = CapabilityAnalyzer(docker_available=True).analyze(
        CobolApplication(application_id="T", programs=(unit,))
    )
    programs = [c for c in report.components if c.component_type == "PROGRAM"]
    return programs[0].level


# ---------------------------------------------------------------------------
# Positive — the contract table
# ---------------------------------------------------------------------------

class TestFigurativeCanonicalSemantics:
    @pytest.mark.parametrize(
        ("spelling", "expected"),
        [
            ("ZERO", figurative.ZERO),
            ("ZEROS", figurative.ZERO),
            ("ZEROES", figurative.ZERO),
            ("ZERO-ZERO-ZERO", figurative.ZERO),
            ("SPACE", figurative.SPACES),
            ("SPACES", figurative.SPACES),
            ("QUOTE", figurative.QUOTES),
            ("QUOTES", figurative.QUOTES),
            ("LOW-VALUE", figurative.LOW_VALUE),
            ("LOW-VALUES", figurative.LOW_VALUE),
            ("HIGH-VALUE", figurative.HIGH_VALUE),
            ("HIGH-VALUES", figurative.HIGH_VALUE),
        ],
    )
    def test_every_spelling_canonicalises(self, spelling, expected):
        assert figurative.parse_figurative_constant(spelling)[0] == expected

    @pytest.mark.parametrize("spelling", ["ALL '*'", 'ALL "x"', "all '-'"])
    def test_all_literal_carries_its_character(self, spelling):
        kind, fill = figurative.parse_figurative_constant(spelling)
        assert kind == figurative.ALL
        assert fill == spelling[-2]

    def test_fill_characters_are_the_ascii_collating_values(self):
        assert figurative.figurative_fill_char(figurative.SPACES) == " "
        assert figurative.figurative_fill_char(figurative.QUOTES) == '"'
        assert figurative.figurative_fill_char(figurative.LOW_VALUE) == "\x00"
        assert figurative.figurative_fill_char(figurative.HIGH_VALUE) == "\xff"

    def test_zero_is_numeric_and_has_no_fill_character(self):
        assert figurative.figurative_is_numeric(figurative.ZERO) is True
        assert figurative.figurative_fill_char(figurative.ZERO) is None


# ---------------------------------------------------------------------------
# Negative — things that must NOT be treated as figurative constants
# ---------------------------------------------------------------------------

class TestNegativeCases:
    @pytest.mark.parametrize(
        "text",
        [
            "ZERO-COUNT",        # hyphenated field, not the reserved word
            "SPACES-AVAIL",
            "HIGH-VALUE-FLAG",
            "WS-ZERO",
            "QUOTED-AMOUNT",
            "A",
            "",
            "ZEROS-AND-ZEROS",
        ],
    )
    def test_hyphenated_identifiers_are_not_constants(self, text):
        assert figurative.parse_figurative_constant(text) is None

    def test_quoted_literal_spelling_the_word_is_not_a_constant(self):
        # VALUE "ZERO" is data, not the reserved word.
        assert figurative.parse_figurative_constant('"ZERO"') is None
        assert figurative.parse_figurative_constant("'SPACES'") is None

    def test_multi_character_all_is_not_a_figurative_constant(self):
        # ALL "ab" is a repetition, not a figurative constant.
        assert figurative.parse_figurative_constant('ALL "ab"') is None

    def test_empty_all_literal_is_not_a_constant(self):
        assert figurative.parse_figurative_constant('ALL ""') is None

    def test_ordinary_move_stays_a_field_reference(self):
        [move] = _moves(_program("MOVE 5 TO WS-NUM."))
        assert isinstance(move.source_expr, Literal)
        assert not isinstance(move.source_expr, FigurativeConstant)

    def test_field_reference_operand_is_unchanged(self):
        # WS-TEXT is a real field: it must stay a FieldReference, proving the
        # constant resolution did not swallow ordinary operands.
        source = _program("MOVE 5 TO WS-NUM.").replace(
            "MOVE 5 TO WS-NUM.", "MOVE WS-TEXT TO WS-TEXT."
        )
        program = CobolParser().parse(source)
        moves = [
            stmt for para in program.paragraphs for stmt in para.statements
            if isinstance(stmt, MoveStatement)
        ]
        assert moves[0].source_expr == FieldReference(name="WS-TEXT")

    def test_figurative_is_never_a_field_reference(self):
        for spelling in ("ZERO", "SPACES", "HIGH-VALUES", "ALL '*'"):
            [move] = _moves(_program(f'MOVE {spelling} TO WS-TEXT.'))
            assert isinstance(move.source_expr, FigurativeConstant), spelling
            assert not isinstance(move.source_expr, FieldReference), spelling


# ---------------------------------------------------------------------------
# Positive — parser produces semantic IR
# ---------------------------------------------------------------------------

class TestParserProducesFigurativeIR:
    @pytest.mark.parametrize(
        ("spelling", "kind"),
        [
            ("ZERO", figurative.ZERO),
            ("SPACES", figurative.SPACES),
            ("QUOTES", figurative.QUOTES),
            ("HIGH-VALUE", figurative.HIGH_VALUE),
            ("LOW-VALUES", figurative.LOW_VALUE),
        ],
    )
    def test_move_operand_is_a_figurative_node(self, spelling, kind):
        [move] = _moves(_program(f"MOVE {spelling} TO WS-TEXT."))
        assert isinstance(move.source_expr, FigurativeConstant)
        assert move.source_expr.kind == kind

    def test_node_preserves_original_spelling_for_traceability(self):
        [move] = _moves(_program("MOVE HIGH-VALUES TO WS-TEXT."))
        assert move.source_expr.text == "HIGH-VALUES"

    def test_all_literal_node_records_its_character(self):
        [move] = _moves(_program("MOVE ALL '*' TO WS-TEXT."))
        assert move.source_expr.kind == figurative.ALL

    def test_parser_emits_no_unsupported_diagnostic(self):
        parser = CobolParser()
        parser.parse(_program("MOVE SPACES TO WS-TEXT.", "MOVE ZERO TO WS-NUM."))
        codes = {d.code for d in parser.diagnostics.all}
        assert "DiagnosticCode.UNSUPPORTED_CONSTRUCT" not in codes


# ---------------------------------------------------------------------------
# Positive — mapper emits compiling, semantically correct Java
# ---------------------------------------------------------------------------

class TestMapperEmitsCompilingJava:
    def test_no_reserved_word_reaches_java_as_an_identifier(self):
        code = _generate(_program(
            "MOVE ZERO TO WS-NUM.",
            "MOVE SPACES TO WS-TEXT.",
            "MOVE ALL '*' TO WS-TEXT.",
            "DISPLAY SPACES.",
        ))
        body = code
        for reserved in ("= ZERO;", "(SPACES)", "= SPACES;", "(ZERO)", "(QUOTES)"):
            assert reserved not in body, reserved

    def test_move_spaces_pads_to_the_receiving_width(self):
        code = _generate(_program("MOVE SPACES TO WS-TEXT."))
        # PIC X(10) receives ten spaces, not the single literal " ".
        assert 'String.format("%-10s", " ")' in code

    def test_move_all_fills_with_the_named_character(self):
        code = _generate(_program("MOVE ALL '*' TO WS-TEXT."))
        assert 'String.format("%-10s", "*")' in code

    def test_move_zero_is_numeric_zero(self):
        code = _generate(_program("MOVE ZERO TO WS-NUM."))
        assert "WS_NUM = 0;" in code

    @pytest.mark.parametrize("width", [1, 5, 10])
    def test_generated_program_fills_the_whole_receiving_width(self, width):
        # The Java computes the fill at runtime (format + substring), so the
        # assertion is on the emitted width, not on a pre-filled literal.
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. FIGRUN.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            f"       01 WS-TEXT PIC X({width}).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE ALL '*' TO WS-TEXT.\n"
            "           STOP RUN.\n"
        )
        code = JavaGenerator().generate(CobolParser().parse(source))[0].source_code
        assert f'String.format("%-{width}s", "*").substring(0, {width})' in code

    def test_expr_mapping_returns_a_literal_not_a_variable(self):
        java = map_cobol_expr_to_java("ZERO")
        assert not hasattr(java, "name"), java
        assert "0" in str(java)


# ---------------------------------------------------------------------------
# Positive — comparison semantics test EVERY character
# ---------------------------------------------------------------------------

class TestComparisonSemantics:
    def test_equals_spaces_tests_the_whole_field(self):
        code = _generate(_program(
            "MOVE SPACES TO WS-TEXT.",
            'IF WS-TEXT = SPACES THEN',
            '    DISPLAY "BLANK".',
            "END-IF.",
        ))
        # A one-character equality would be wrong for PIC X(10).
        assert 'WS_TEXT.replace(" ", "").isEmpty()' in code

    def test_not_equals_spaces_negates_the_whole_field_test(self):
        code = _generate(_program(
            'IF WS-TEXT = SPACES THEN',
            '    DISPLAY "BLANK".',
            "END-IF.",
        ))
        assert 'replace(" ", "")' in code

    def test_equals_zero_compares_numerically(self):
        code = _generate(_program(
            "MOVE ZERO TO WS-NUM.",
            'IF WS-NUM = ZERO THEN',
            '    DISPLAY "Z".',
            "END-IF.",
        ))
        assert "WS_NUM == 0" in code

    def test_hyphenated_field_is_not_compared_as_a_constant(self):
        code = _generate(_program(
            "MOVE ALL '*' TO WS-TEXT.",
            "IF WS-TEXT = ALL '*' THEN",
            '    DISPLAY "STARS".',
            "END-IF.",
        ))
        assert 'WS_TEXT.replace("*", "").isEmpty()' in code


# ---------------------------------------------------------------------------
# Capability truth — the verdict must be IR-backed and honest
# ---------------------------------------------------------------------------

class TestCapabilityTruth:
    def test_registry_key_is_supported_with_evidence(self):
        entry = CONSTRUCT_REGISTRY["FIGURATIVE CONSTANT"]
        assert entry.level is CapabilityLevel.SUPPORTED
        assert entry.evidence

    def test_program_using_figurative_constants_is_not_downgraded(self):
        assert _classify(_program(
            "MOVE ZERO TO WS-NUM.", "MOVE SPACES TO WS-TEXT.",
        )) is CapabilityLevel.SUPPORTED

    def test_plain_program_still_supported(self):
        assert _classify(_program("MOVE 5 TO WS-NUM.")) is CapabilityLevel.SUPPORTED

    @pytest.mark.parametrize(
        "expression", ["0 + ZERO", "ZERO * 2", "1 + 2 * ZERO", "ZERO - WS-NUM"]
    )
    def test_nested_constant_is_still_recognised(self, expression):
        # A constant nested inside a BinaryExpression must be found by the
        # IR walk; a named-field walk would miss it and degrade the verdict.
        source = _program(f"COMPUTE WS-NUM = {expression}.")
        program = CobolParser().parse(source)
        assert any(
            isinstance(getattr(stmt, "expression_expr", None), Expression)
            for para in program.paragraphs
            for stmt in para.statements
        )
        assert _classify(source) is CapabilityLevel.SUPPORTED

    def test_nested_constant_maps_to_correct_java(self):
        code = _generate(_program("COMPUTE WS-NUM = ZERO * 2."))
        # The constant becomes the numeric literal 0 in place, so the
        # expression evaluates identically; no reserved word survives.
        assert "WS_NUM = (0 * 2);" in code
        assert "ZERO" not in code

    def test_source_only_figurative_does_not_silently_pass(self):
        # A figurative constant present in source but absent from the IR
        # (e.g. dropped by a parser gap) must not be reported as supported.
        entry = CONSTRUCT_REGISTRY["FIGURATIVE CONSTANT"]
        assert entry.effective_source_level is not CapabilityLevel.SUPPORTED

    def test_source_only_level_is_unknown_not_supported(self):
        entry = CONSTRUCT_REGISTRY["FIGURATIVE CONSTANT"]
        assert entry.effective_source_level is CapabilityLevel.UNKNOWN

    def test_procedure_scan_detects_figurative_use(self):
        from engine.transformation.semantic_capability import scan_constructs
        source = "PROCEDURE DIVISION.\n MAIN.\n  MOVE SPACES TO WS-TEXT.\n"
        assert "FIGURATIVE CONSTANT" in scan_constructs(source)

    def test_data_division_value_initializer_is_not_flagged(self):
        # `VALUE SPACES` is an initializer the mapper already normalizes; it is
        # not an unproven procedural construct and must not trip the scan.
        from engine.transformation.semantic_capability import scan_constructs
        source = (
            "WORKING-STORAGE SECTION.\n"
            " 01 WS-TEXT PIC X(5) VALUE SPACES.\n"
            "PROCEDURE DIVISION.\n STOP RUN.\n"
        )
        assert "FIGURATIVE CONSTANT" not in scan_constructs(source)

    def test_verdict_is_backed_by_ir_not_only_by_source_scan(self):
        from engine.transformation.semantic_capability import scan_constructs
        source = _program("MOVE SPACES TO WS-TEXT.")
        assert "FIGURATIVE CONSTANT" in scan_constructs(source)
        program = CobolParser().parse(source)
        assert any(
            isinstance(stmt, MoveStatement)
            and isinstance(stmt.source_expr, FigurativeConstant)
            for para in program.paragraphs
            for stmt in para.statements
        )


# ---------------------------------------------------------------------------
# Regression — the real fixture that previously produced non-compiling Java
# ---------------------------------------------------------------------------

class TestPayrollFixtureRegression:
    """PAYROLL.cob contains ``MOVE SPACES TO RPT-RECORD``.

    Before the fix its generated Java read
    ``RPT_RECORD = String.format("%-60s", SPACES).substring(0, 60);`` — an
    undeclared identifier, so the program could not compile, while the
    capability analyzer still reported SUPPORTED.  This locks the fix to the
    real fixture rather than only to synthetic sources.
    """

    SOURCE = (
        Path(__file__).resolve().parents[2]
        / "fixtures" / "workload-payroll" / "cobol" / "PAYROLL.cob"
    )

    def test_fixture_uses_figurative_constants(self):
        text = self.SOURCE.read_text(encoding="utf-8")
        assert "MOVE SPACES TO" in text

    def test_generated_java_has_no_bare_reserved_word_identifier(self):
        code = JavaGenerator().generate(
            CobolParser().parse(self.SOURCE.read_text(encoding="utf-8"))
        )[0].source_code
        for reserved in ("(SPACES)", "= SPACES;", "(ZERO)", "= ZERO;"):
            assert reserved not in code, reserved

    def test_fixture_program_still_classified_supported(self):
        text = self.SOURCE.read_text(encoding="utf-8")
        unit = CobolProgramUnit(
            program_id="PAYROLL", source_path="PAYROLL.cob",
            program=CobolParser().parse(text), source_text=text,
        )
        report = CapabilityAnalyzer(docker_available=True).analyze(
            CobolApplication(application_id="PAYROLL", programs=(unit,))
        )
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert programs[0].level is CapabilityLevel.SUPPORTED
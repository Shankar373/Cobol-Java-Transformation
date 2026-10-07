"""Focused regression tests for the deterministic numeric semantic contract.

Covers:
- leading-zero VALUE literals must never be emitted as Java octal literals;
- fractional digits are truncated (never rounded) to the PIC scale, matching
  GnuCOBOL (oracle-verified in tests/integration/test_numeric_oracle_proof.py);
- integer overflow keeps the least-significant declared digits;
- ZERO / ZEROS / ZEROES map to 0;
- non-numeric numeric VALUEs fail closed (NumericValueError);
- format_width/pic_length no longer double-count fractional digits;
- generated Java contains the normalized literals.
"""

import subprocess
import sys
import textwrap

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import (
    map_cobol_expr_to_java,
    map_pic_to_java_default,
)
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.numeric_semantics import (
    NumericValueError,
    normalize_numeric_literal,
    normalize_value_for_pic,
)
from engine.transformation.ir import DataItem, PicType


# ---------------------------------------------------------------------------
# Pure contract unit tests
# ---------------------------------------------------------------------------

class TestNormalizeNumericLiteral:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("007", "7"),
            ("009", "9"),
            ("000", "0"),
            ("12", "12"),
            ("-12", "-12"),
            ("+12", "12"),
            ("000000012", "12"),
            ("1.234", "1.234"),
            ("000123.4", "123.4"),
            ("+0.50", "0.5"),
            ("-001.2300", "-1.23"),
            ("0.0", "0.0"),
            ("12.", "12"),
            ("ZERO", "0"),
            ("ZEROS", "0"),
            ("ZEROES", "0"),
        ],
    )
    def test_normalized_literals(self, source, expected):
        assert normalize_numeric_literal(source) == expected

    @pytest.mark.parametrize(
        "source",
        ["SPACE", "SPACES", "LOW-VALUE", "HIGH-VALUE", "QUOTE", "ABC", "12X", ""],
    )
    def test_non_numeric_raises(self, source):
        with pytest.raises(NumericValueError):
            normalize_numeric_literal(source)


class TestNormalizeValueForPic:
    @pytest.mark.parametrize(
        ("source", "integer_digits", "decimal_digits", "expected"),
        [
            # leading-zero literals are decimal, never Java-octal
            ("007", 3, 0, "7"),
            ("009", 3, 0, "9"),
            ("000", 3, 0, "0"),
            # sign is preserved
            ("-12", 4, 0, "-12"),
            ("+12", 4, 0, "12"),
            # fractional digits are truncated (COBOL truncates, not rounds)
            ("1.234", 2, 2, "1.23"),
            ("-1.239", 3, 2, "-1.23"),
            ("12.7", 3, 0, "12"),
            ("000123.4", 6, 2, "123.40"),
            # scale normalizes to exactly the declared fractional digits
            ("1.2", 2, 2, "1.20"),
            ("1", 2, 2, "1.00"),
            ("0", 3, 2, "0.00"),
            # integer overflow keeps least-significant declared digits
            ("1234", 3, 0, "234"),
            ("12345.67", 3, 2, "345.67"),
            ("-1234", 3, 0, "-234"),
            # no overflow
            ("123.45", 3, 2, "123.45"),
        ],
    )
    def test_value_against_pic(self, source, integer_digits, decimal_digits, expected):
        assert (
            normalize_value_for_pic(
                source,
                integer_digits=integer_digits,
                decimal_digits=decimal_digits,
            )
            == expected
        )


# ---------------------------------------------------------------------------
# Parser → Java default value
# ---------------------------------------------------------------------------

def _ws_item(source, name):
    program = CobolParser().parse(source)
    return next(item for item in program.working_storage if item.name == name)


def test_map_pic_default_normalizes_value():
    source = textwrap.dedent(
        """\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. NVAL.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 D PIC 9(3) VALUE 007.
        01 E PIC 9(3) VALUE 009.
        01 F PIC 9(2)V99 VALUE 1.234.
        01 H PIC 9(6)V99 VALUE 000123.4.
        01 NEG PIC S9(4) VALUE -12.
        01 ZED PIC 9(3) VALUE ZEROS.
        PROCEDURE DIVISION.
        MAIN.
            STOP RUN.
        """
    )
    assert map_pic_to_java_default(_ws_item(source, "D")) == "7"
    assert map_pic_to_java_default(_ws_item(source, "E")) == "9"
    assert map_pic_to_java_default(_ws_item(source, "F")) == "1.23"
    assert map_pic_to_java_default(_ws_item(source, "H")) == "123.40"
    assert map_pic_to_java_default(_ws_item(source, "NEG")) == "-12"
    assert map_pic_to_java_default(_ws_item(source, "ZED")) == "0"


def test_map_pic_default_without_value_is_zero():
    item = DataItem(name="X", pic_type=PicType.NUMERIC, pic_length=5, decimal_places=2)
    assert map_pic_to_java_default(item) == "0"


def test_map_pic_default_invalid_numeric_value_fails_closed():
    item = DataItem(
        name="X",
        pic_type=PicType.NUMERIC,
        pic_length=3,
        value="SPACE",
    )
    with pytest.raises(NumericValueError):
        map_pic_to_java_default(item)


# ---------------------------------------------------------------------------
# Expression literals
# ---------------------------------------------------------------------------

def test_expression_literal_normalized_from_raw_string():
    expr = map_cobol_expr_to_java("007")
    assert expr.value == "7"


def test_expression_literal_normalized_binary_operand():
    expr = map_cobol_expr_to_java("A + 009")
    assert expr.right.value == "9"
    expr2 = map_cobol_expr_to_java("007 * B")
    assert expr2.left.value == "7"


# ---------------------------------------------------------------------------
# Generated Java
# ---------------------------------------------------------------------------

def test_generated_java_has_no_octal_and_scaled_defaults():
    program = CobolParser().parse(
        textwrap.dedent(
            """\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. NUMGEN.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 D PIC 9(3) VALUE 007.
            01 F PIC 9(2)V99 VALUE 1.234.
            PROCEDURE DIVISION.
            MAIN.
                STOP RUN.
            """
        )
    )
    source = JavaGenerator().generate(program)[0].source_code
    assert "static int D = 7;" in source
    assert "static double F = 1.23;" in source
    assert "static int D = 007;" not in source


def _java_available() -> bool:
    for candidate in ("javac", "java"):
        try:
            subprocess.run(
                [candidate, "-version"],
                capture_output=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    return True


needs_host_java = pytest.mark.skipif(
    not _java_available(), reason="host javac/java not available"
)


@needs_host_java
def test_generated_java_with_leading_zero_values_compiles(tmp_path):
    program = CobolParser().parse(
        textwrap.dedent(
            """\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. NUMCMP.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 D PIC 9(3) VALUE 007.
            01 E PIC 9(3) VALUE 009.
            01 G PIC 9(3) VALUE 12.
            01 ACC PIC 9(6) VALUE ZEROS.
            PROCEDURE DIVISION.
            MAIN.
                ADD D TO ACC.
                ADD E TO ACC.
                ADD G TO ACC.
                DISPLAY ACC.
                STOP RUN.
            """
        )
    )
    generated = JavaGenerator().generate(program)[0]
    path = tmp_path / generated.filename
    path.write_text(generated.source_code, encoding="utf-8")
    built = subprocess.run(
        ["javac", str(path)], capture_output=True, timeout=120
    )
    assert built.returncode == 0, built.stderr.decode(errors="replace")
    executed = subprocess.run(
        ["java", "-cp", str(tmp_path), generated.class_name],
        capture_output=True,
        timeout=120,
    )
    assert executed.returncode == 0, executed.stderr.decode(errors="replace")
    # 7 + 9 + 12 = 28 == COBOL semantics of the three VALUE literals.
    assert executed.stdout.decode(errors="replace").strip() == "000028"


# ---------------------------------------------------------------------------
# format_width / pic_length consistency
# ---------------------------------------------------------------------------

def test_parsed_decimal_pic_length_and_format_width_are_consistent():
    source = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. FWIDTH.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 AMOUNT PIC 9(6)V99 VALUE 000123.4.\n"
        "01 COUNT PIC 9(3) VALUE 007.\n"
        "PROCEDURE DIVISION.\n"
        "MAIN.\n"
        "    STOP RUN.\n"
    )
    program = CobolParser().parse(source)
    amount = next(i for i in program.working_storage if i.name == "AMOUNT")
    count = next(i for i in program.working_storage if i.name == "COUNT")
    assert amount.pic_length == 8
    assert amount.decimal_places == 2
    assert amount.format_width == 8
    assert amount.integer_digits == 6
    assert count.pic_length == 3
    assert count.format_width == 3
    assert count.integer_digits == 3
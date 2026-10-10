"""Focused regression tests for the deterministic numeric semantic contract.

Covers:
- leading-zero VALUE literals must never be emitted as Java octal literals;
- fractional digits are truncated (never rounded) to the PIC scale, matching
  GnuCOBOL (oracle-verified in tests/integration/test_numeric_oracle_proof.py);
- integer overflow keeps the least-significant declared digits;
- ZERO / ZEROS / ZEROES map to 0;
- non-numeric numeric VALUEs fail closed (NumericValueError);
- a signed literal on an unsigned PIC fails closed (GnuCOBOL: 'data item
  not signed');
- integral literals outside Java's int range are typed long and suffixed L;
- the DISPLAY String.format specifier reproduces the GnuCOBOL digit field
  (sign column, zero fill, scale);
- an unsigned receiver stores the magnitude of a negative result;
- format_width/pic_length no longer double-count fractional digits;
- generated Java contains the normalized literals and compiles/runs.
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
    display_format_spec,
    is_fractional_format_spec,
    java_integral_suffix,
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
        ("source", "integer_digits", "decimal_digits", "signed", "expected"),
        [
            # leading-zero literals are decimal, never Java-octal
            ("007", 3, 0, False, "7"),
            ("009", 3, 0, False, "9"),
            ("000", 3, 0, False, "0"),
            # sign is preserved (signed PIC only — see fail-closed test below)
            ("-12", 4, 0, True, "-12"),
            ("+12", 4, 0, True, "12"),
            # fractional digits are truncated (COBOL truncates, not rounds)
            ("1.234", 2, 2, False, "1.23"),
            ("-1.239", 3, 2, True, "-1.23"),
            ("12.7", 3, 0, False, "12"),
            ("000123.4", 6, 2, False, "123.40"),
            # scale normalizes to exactly the declared fractional digits
            ("1.2", 2, 2, False, "1.20"),
            ("1", 2, 2, False, "1.00"),
            ("0", 3, 2, False, "0.00"),
            # integer overflow keeps least-significant declared digits
            ("1234", 3, 0, False, "234"),
            ("12345.67", 3, 2, False, "345.67"),
            ("-1234", 3, 0, True, "-234"),
            # no overflow
            ("123.45", 3, 2, False, "123.45"),
        ],
    )
    def test_value_against_pic(
        self, source, integer_digits, decimal_digits, signed, expected
    ):
        assert (
            normalize_value_for_pic(
                source,
                integer_digits=integer_digits,
                decimal_digits=decimal_digits,
                signed=signed,
            )
            == expected
        )

    @pytest.mark.parametrize("source", ["-5", "+007"])
    def test_signed_literal_on_unsigned_pic_fails_closed(self, source):
        """GnuCOBOL rejects ``PIC 9(3) VALUE -5`` with 'data item not signed'."""
        with pytest.raises(NumericValueError, match="not signed"):
            normalize_value_for_pic(
                source, integer_digits=3, decimal_digits=0, signed=False
            )


class TestDisplayFormatSpec:
    """The specifier must reproduce GnuCOBOL DISPLAY output byte for byte."""

    @pytest.mark.parametrize(
        ("integer_digits", "decimal_digits", "signed", "expected"),
        [
            (3, 0, False, "%03d"),
            (4, 0, True, "%+05d"),
            (6, 0, False, "%06d"),
            (9, 0, True, "%+010d"),
            (4, 2, False, "%07.2f"),
            (3, 1, True, "%+06.1f"),
            (5, 2, True, "%+09.2f"),
            (7, 2, True, "%+011.2f"),
        ],
    )
    def test_specifier_shape(self, integer_digits, decimal_digits, signed, expected):
        assert (
            display_format_spec(
                integer_digits=integer_digits,
                decimal_digits=decimal_digits,
                signed=signed,
            )
            == expected
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"integer_digits": 0, "decimal_digits": 0, "signed": False},
            {"integer_digits": -1, "decimal_digits": 0, "signed": False},
            {"integer_digits": 3, "decimal_digits": -1, "signed": False},
        ],
    )
    def test_specifier_rejects_degenerate_pics(self, kwargs):
        with pytest.raises(ValueError):
            display_format_spec(**kwargs)

    @pytest.mark.parametrize(
        "spec", ["%03d", "%+05d", "%07.2f", "%+06.1f", "%06d", "%+011.2f"]
    )
    def test_fractional_specs_are_the_only_locale_sensitive_ones(self, spec):
        assert is_fractional_format_spec(spec) is spec.endswith("f")


class TestJavaIntegralSuffix:
    @pytest.mark.parametrize(
        ("canonical", "expected"),
        [
            ("0", ""),
            ("7", ""),
            ("999999999", ""),
            ("-999999999", ""),
            ("1000000000", ""),
            ("2147483647", ""),
            ("2147483648", "L"),
            ("-2147483649", "L"),
            ("12345678901", "L"),
            ("123456789012345678", "L"),
            ("123.45", ""),
            ("-1.2", ""),
        ],
    )
    def test_integral_suffix(self, canonical, expected):
        assert java_integral_suffix(canonical) == expected


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


def test_signed_value_on_unsigned_pic_fails_closed():
    """GnuCOBOL rejects ``PIC 9(3) VALUE -5`` with 'data item not signed'.

    Accepting it would silently store a magnitude the oracle never stores,
    so the mapping must raise instead of emitting a negative literal for an
    unsigned Java field.
    """
    source = textwrap.dedent(
        """\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. SGNVAL.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 BAD PIC 9(3) VALUE -5.
        01 ALSO-BAD PIC 9(3) VALUE +007.
        01 GOOD PIC S9(3) VALUE -5.
        01 GOOD-TOO PIC 9(3) VALUE 007.
        PROCEDURE DIVISION.
        MAIN.
            STOP RUN.
        """
    )
    program = CobolParser().parse(source)
    items = {item.name: item for item in program.working_storage}

    with pytest.raises(NumericValueError, match="not signed"):
        map_pic_to_java_default(items["BAD"])
    with pytest.raises(NumericValueError, match="not signed"):
        map_pic_to_java_default(items["ALSO-BAD"])

    # Signed and plain unsigned literals keep working.
    assert map_pic_to_java_default(items["GOOD"]) == "-5"
    assert map_pic_to_java_default(items["GOOD-TOO"]) == "7"

    # Generation fails closed rather than emitting a wrong-negated field.
    with pytest.raises(NumericValueError, match="not signed"):
        JavaGenerator().generate(program)


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


def test_large_integral_literal_carries_long_suffix():
    """A literal outside Java's int range must be typed and suffixed ``L``."""
    from engine.transformation.java_ir import JavaBasicType

    program = CobolParser().parse(
        textwrap.dedent(
            """\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. BIGLIT.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 BIG PIC 9(18) VALUE 123456789012345678.
            01 MED PIC 9(11) VALUE 12345678901.
            01 SMALL PIC 9(9) VALUE 123456789.
            01 TRUNC PIC 9(10) VALUE 12345678901.
            PROCEDURE DIVISION.
            MAIN.
                STOP RUN.
            """
        )
    )
    source = JavaGenerator().generate(program)[0].source_code
    assert "static long BIG = 123456789012345678L;" in source
    assert "static long MED = 12345678901L;" in source
    assert "static int SMALL = 123456789;" in source
    # PIC 9(10) cannot hold 11 digits: COBOL keeps the least-significant 10.
    assert "static long TRUNC = 2345678901L;" in source
    # The unsuffixed spelling is a compile error in Java.
    assert "static long BIG = 123456789012345678;" not in source
    assert "static long MED = 12345678901;" not in source

    # Expression literals get the same treatment and the same Java type.
    big = map_cobol_expr_to_java("123456789012345678")
    assert big.value.endswith("L")
    assert big.java_type.basic_type == JavaBasicType.LONG
    small = map_cobol_expr_to_java("123456789")
    assert not small.value.endswith("L")
    assert small.java_type.basic_type == JavaBasicType.INT


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
def test_display_specifiers_reproduce_gnucobol_text(tmp_path):
    """Java String.format with our specifiers equals the GnuCOBOL oracle text.

    Oracle (GnuCOBOL DISPLAY) rows, emitted verbatim by the generator:
    PIC 9(3)  7      -> 007        PIC S9(4) -12    -> -0012
    PIC S9(4) 12     -> +0012      PIC 9(4)V99 12.5 -> 0012.50
    PIC S9(3)V9 -1.2 -> -001.2     PIC S9(3)V9 1.2  -> +001.2
    """
    cases = [
        (3, 0, False, 7.0, "007"),
        (4, 0, True, -12.0, "-0012"),
        (4, 0, True, 12.0, "+0012"),
        (4, 2, False, 12.5, "0012.50"),
        (3, 1, True, -1.2, "-001.2"),
        (3, 1, True, 1.2, "+001.2"),
        (5, 2, True, -987.65, "-00987.65"),
        (7, 2, True, 11358.02, "+0011358.02"),
        (4, 2, False, 100.0, "0100.00"),
    ]
    lines = ["public class SpecProbe {"]
    lines.append("  public static void main(String[] a) {")
    for ni, nd, signed, value, _ in cases:
        spec = display_format_spec(
            integer_digits=ni, decimal_digits=nd, signed=signed
        )
        literal = str(value) if is_fractional_format_spec(spec) else str(int(value))
        lines.append(
            f'    System.out.println(String.format(java.util.Locale.US, '
            f'"{spec}", {literal}));'
        )
    lines.append("  }")
    lines.append("}")
    path = tmp_path / "SpecProbe.java"
    path.write_text("\n".join(lines), encoding="utf-8")
    built = subprocess.run(
        ["javac", str(path)], capture_output=True, timeout=120
    )
    assert built.returncode == 0, built.stderr.decode(errors="replace")
    executed = subprocess.run(
        ["java", "-cp", str(tmp_path), "SpecProbe"],
        capture_output=True, timeout=120,
    )
    assert executed.returncode == 0, executed.stderr.decode(errors="replace")
    produced = [
        line.strip("[]").replace("'", "").strip()
        for line in executed.stdout.decode().splitlines()
        if line.strip()
    ]
    assert produced == [expected for *_, expected in cases]


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


def _compile_and_run(tmp_path, program):
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
    return executed.stdout.decode(errors="replace").splitlines()


@needs_host_java
def test_generated_java_with_18_digit_value_compiles_and_displays(tmp_path):
    """Without the ``L`` suffix javac rejects the literal (integer number too large)."""
    program = CobolParser().parse(
        textwrap.dedent(
            """\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. BIGCMP.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 BIG PIC 9(18) VALUE 123456789012345678.
            PROCEDURE DIVISION.
            MAIN.
                DISPLAY BIG.
                STOP RUN.
            """
        )
    )
    assert _compile_and_run(tmp_path, program) == ["123456789012345678"]


@needs_host_java
def test_generated_signed_and_decimal_display_matches_gnucobol_text(tmp_path):
    """The DISPLAY text matches the GnuCOBOL oracle without needing Docker."""
    program = CobolParser().parse(
        textwrap.dedent(
            """\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. DSPTXT.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 INT-S PIC S9(4) VALUE -12.
            01 INT-SP PIC S9(4) VALUE 12.
            01 DEC-U PIC 9(4)V99 VALUE 12.5.
            01 DEC-S PIC S9(3)V9 VALUE -1.29.
            01 INT-U PIC 9(3) VALUE 007.
            PROCEDURE DIVISION.
            MAIN.
                DISPLAY INT-S.
                DISPLAY INT-SP.
                DISPLAY DEC-U.
                DISPLAY DEC-S.
                DISPLAY INT-U.
                STOP RUN.
            """
        )
    )
    assert _compile_and_run(tmp_path, program) == [
        "-0012",
        "+0012",
        "0012.50",
        "-001.2",
        "007",
    ]


@needs_host_java
def test_generated_unsigned_receiver_stores_magnitude(tmp_path):
    """GnuCOBOL stores the magnitude of a negative result in an unsigned PIC."""
    program = CobolParser().parse(
        textwrap.dedent(
            """\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. MAGCMP.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 SHORT PIC 9(3) VALUE 0.
            01 UDEC PIC 9(3)V9 VALUE 0.
            PROCEDURE DIVISION.
            MAIN.
                COMPUTE SHORT = 0 - 5.
                COMPUTE UDEC = 0 - 1.25.
                DISPLAY SHORT.
                DISPLAY UDEC.
                STOP RUN.
            """
        )
    )
    assert _compile_and_run(tmp_path, program) == ["005", "001.2"]


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
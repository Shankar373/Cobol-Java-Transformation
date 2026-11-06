"""Hermetic tests for exponentiation ``**`` (roadmap unit 34); GnuCOBOL proof: tests/integration/test_power_oracle.py."""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_expr_to_java
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import JavaBinaryOp, JavaLiteral, JavaUnaryOp

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9(3) VALUE 7.
       01 B PIC S9(3) VALUE -4.
       01 E PIC 9 VALUE 3.
       01 SE PIC S9 VALUE 2.
       01 F PIC 9V9 VALUE 1.5.
       01 R PIC S9(6)V99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
"""


def _generate(body: str) -> str:
    parser = CobolParser()
    program = parser.parse(HEAD + body + "           STOP RUN.\n")
    assert [d.message for d in parser.diagnostics.all if d.code.name == "UNSUPPORTED_CONSTRUCT"] == []
    return JavaGenerator().generate(program)[0].source_code


def _literal(node) -> str:
    assert isinstance(node, JavaLiteral)
    return node.value


def test_precedence_and_associativity_follow_the_oracle():
    unary = map_cobol_expr_to_java("-2 ** 2")  # (-2) ** 2 = 4
    assert isinstance(unary, JavaBinaryOp) and unary.operator == "**" and isinstance(unary.left, JavaUnaryOp)
    right = map_cobol_expr_to_java("2 ** 3 ** 2")  # 2 ** (3 ** 2) = 512
    assert right.operator == "**" and _literal(right.left) == "2"
    assert right.right.operator == "**" and _literal(right.right.left) == "3"
    mixed = map_cobol_expr_to_java("3 * 2 ** 2")  # 3 * (2 ** 2) = 12
    assert mixed.operator == "*" and mixed.right.operator == "**"
    exponent_sign = map_cobol_expr_to_java("2 ** -2")
    assert exponent_sign.operator == "**" and isinstance(exponent_sign.right, JavaUnaryOp)


def test_a_non_negative_integer_exponent_is_computed_exactly_with_bigdecimal_pow():
    java = _generate("           COMPUTE R = A ** 2 + 3 ** E.\n           COMPUTE R ROUNDED = (A + 1) ** (E + 1).\n")
    assert java.count(".pow(") >= 3 and "intValueExact()" in java


@pytest.mark.parametrize("expression, why", [
    ("A ** -2", "non-negative integer exponents"),
    ("A ** (E - 1)", "non-negative integer exponents"),
    ("A ** SE", "non-negative integer exponents"),
    ("A ** F", "non-negative integer exponents"),
    ("A ** 0.5", "non-negative integer exponents"),
    ("A ** B", "non-negative integer exponents"),
])
def test_negative_fractional_and_signed_exponents_fail_closed_at_generation(expression, why):
    parser = CobolParser()
    program = parser.parse(HEAD + f"           COMPUTE R = {expression}.\n           STOP RUN.\n")
    with pytest.raises(ValueError, match=why):
        JavaGenerator().generate(program)


def test_exponentiation_outside_a_compute_receiver_fails_closed():
    parser = CobolParser()
    program = parser.parse(HEAD + "           IF A ** 2 > 10\n               DISPLAY 'X'\n           END-IF.\n           STOP RUN.\n")
    with pytest.raises(ValueError, match="UNSUPPORTED_COBOL_EXPRESSION"):
        JavaGenerator().generate(program)


def _classify(tmp_path, statements: str):
    from pathlib import Path

    from engine.modernization.capability_analyzer import CapabilityAnalyzer
    from engine.transformation.application_discovery import ApplicationDiscovery

    src = Path(tmp_path) / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "PW.cob").write_text(HEAD + statements + "           STOP RUN.\n", encoding="utf-8")
    app = ApplicationDiscovery().discover(src, application_id="unit34")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, source_root=src)
    return next(c for c in report.components if c.component_type == "PROGRAM" and c.component_id == "PW")


def test_the_capability_gate_agrees_with_the_generator(tmp_path):
    from engine.modernization.capability_analyzer import CapabilityLevel

    def level(name: str, statements: str):
        return _classify(tmp_path / name, statements).level

    assert level("ok", "           COMPUTE R = A ** 2 + 3 ** E.\n") is CapabilityLevel.SUPPORTED
    assert level("neg", "           COMPUTE R = A ** -1.\n") is CapabilityLevel.UNSUPPORTED
    assert level("frac", "           COMPUTE R = A ** 0.5.\n") is CapabilityLevel.UNSUPPORTED
    assert level("cond", "           IF A ** 2 > 10 DISPLAY 'X' END-IF.\n") is CapabilityLevel.UNSUPPORTED


def test_size_error_with_a_possible_zero_to_zero_is_refused_but_a_positive_literal_exponent_is_certified(tmp_path):
    from engine.modernization.capability_analyzer import CapabilityLevel

    sized = ("           COMPUTE R = {expression}\n               ON SIZE ERROR DISPLAY 'S'\n"
             "               NOT ON SIZE ERROR DISPLAY 'K'\n           END-COMPUTE.\n")
    refused = _classify(tmp_path / "zz", sized.format(expression="A ** E"))
    assert refused.level is CapabilityLevel.UNSUPPORTED and "0 ** 0" in refused.reason
    assert _classify(tmp_path / "pos", sized.format(expression="A ** 2")).level is CapabilityLevel.SUPPORTED
    assert _classify(tmp_path / "base", sized.format(expression="3 ** E")).level is CapabilityLevel.SUPPORTED


def test_operator_continuation_line_is_never_dropped_silently():
    # a line beginning with ``*`` after an unfinished COMPUTE is a comment or the rest of the statement; the parser
    # cannot tell which, so it must say so instead of computing a different value
    from engine.transformation.cobol_parser import CobolParser

    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n       01 A PIC 9(4).\n       PROCEDURE DIVISION.\n"
        "       MAIN.\n           COMPUTE A = 5 * 1 +\n             A\n             ** (A + 1).\n"
        "           STOP RUN.\n"
    )
    parser = CobolParser()
    parser.parse(source)
    assert any("follows an unfinished statement" in d.message for d in parser.diagnostics.all)

    comment = source.replace("** (A + 1).", "* just a comment.")
    parser = CobolParser()
    parser.parse(comment)
    assert not any("unfinished statement" in d.message for d in parser.diagnostics.all)

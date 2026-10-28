"""ACCEPT lowering — certified stdin subset and fail-closed contract.

Pins the real, oracle-backed ACCEPT lane (GnuCOBOL 3.1.2 differential
proof in ``tests/integration/test_accept_oracle_proof.py``) at the
generation level:

* the certified forms lower to the shared ``CobolStdin`` helper (one
  program-wide stdin reader) — never a per-statement ``Scanner`` (which
  buffered stdin ahead and broke the second ACCEPT) and never a
  duplicate ``_accept_line`` local (which did not compile);
* numeric targets receive a numeric expression with the ``long`` ->
  ``int`` cast narrowing applied only where the field is int-typed;
* every form outside the certified subset fails closed with an
  unresolvable ``UNSUPPORTED_ACCEPT$...`` symbol so ``javac`` names the
  form instead of a silently wrong value shipping;
* the ``CobolStdin`` support class is emitted whenever generated code
  references it.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_statement
from engine.transformation.ir import AcceptStatement
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import JavaAssignment, JavaMethodCall, JavaVariableRef

HEADER = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. ACCT.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-ALPHA PIC X(10).
01 WS-NUM PIC 9(4).
01 WS-BIG PIC 9(12).
01 WS-SIGNED PIC S9(4).
01 WS-DEC PIC 9(4)V99.
01 WS-COMP PIC 9(4) COMP.
01 WS-TAB PIC X(4) OCCURS 5 TIMES.
01 WS-GROUP.
05 WS-GIN PIC X(4).
PROCEDURE DIVISION.
MAIN.
"""


def _parse_accepts(body: str) -> tuple[CobolParser, object, list[AcceptStatement]]:
    parser = CobolParser()
    program = parser.parse(HEADER + body + "    STOP RUN.\n")
    stmts = [
        s
        for para in program.paragraphs
        for s in para.statements
        if isinstance(s, AcceptStatement)
    ]
    assert stmts, "no AcceptStatement parsed"
    return parser, program, stmts


def _render(stmt: AcceptStatement, program) -> JavaAssignment:
    mapped = map_cobol_statement(stmt, program)
    assert len(mapped) == 1, mapped
    out, = mapped
    assert isinstance(out, JavaAssignment), out
    return out


def _accept_expr(body: str, index: int = -1) -> JavaAssignment:
    _, program, stmts = _parse_accepts(body)
    return _render(stmts[index], program)


def _symbol(assignment: JavaAssignment) -> str:
    expr = assignment.expression
    assert isinstance(expr, JavaVariableRef), expr
    return expr.name


class TestCertifiedForms:
    def test_alnum_target_calls_cobol_stdin_alnum(self) -> None:
        out = _accept_expr("    ACCEPT WS-ALPHA.\n")
        rendered = repr(out.expression)
        assert "CobolStdin" in rendered, rendered
        assert "readLine" in rendered, rendered
        assert "alnum" in rendered, rendered
        assert "Scanner" not in rendered, rendered

    def test_numeric_target_is_numeric_with_int_narrowing(self) -> None:
        out = _accept_expr("    ACCEPT WS-NUM.\n")
        rendered = repr(out.expression)
        assert "number" in rendered, rendered
        # int field (4 digits): the long return is narrowed with a cast.
        assert "JavaCast" in rendered, rendered

    def test_long_numeric_target_has_no_narrowing_cast(self) -> None:
        out = _accept_expr("    ACCEPT WS-BIG.\n")
        rendered = repr(out.expression)
        assert "number" in rendered, rendered
        assert "JavaCast" not in rendered, rendered

    def test_from_console_stdin_sysin_are_certified(self) -> None:
        # FROM STDIN was missing from the alias list and failed closed
        # even though GnuCOBOL reads it from standard input.
        for device in ("CONSOLE", "STDIN", "SYSIN"):
            out = _accept_expr(f"    ACCEPT WS-ALPHA FROM {device}.\n")
            expr = out.expression
            assert isinstance(expr, JavaMethodCall), (device, expr)
            assert expr.class_name == "CobolStdin", (device, expr)


class TestFailClosedForms:
    def test_from_date_is_fail_closed(self) -> None:
        out = _accept_expr("    ACCEPT WS-ALPHA FROM DATE.\n")
        assert _symbol(out) == "UNSUPPORTED_ACCEPT$FROM$DATE"

    def test_from_command_line_is_fail_closed(self) -> None:
        out = _accept_expr("    ACCEPT WS-ALPHA FROM COMMAND-LINE.\n")
        assert _symbol(out) == "UNSUPPORTED_ACCEPT$FROM$COMMAND_LINE"

    def test_signed_numeric_target_is_fail_closed(self) -> None:
        out = _accept_expr("    ACCEPT WS-SIGNED.\n")
        assert _symbol(out) == "UNSUPPORTED_ACCEPT$SIGNED"

    def test_decimal_numeric_target_is_fail_closed(self) -> None:
        out = _accept_expr("    ACCEPT WS-DEC.\n")
        assert _symbol(out) == "UNSUPPORTED_ACCEPT$DECIMAL"

    def test_comp_usage_target_is_fail_closed(self) -> None:
        out = _accept_expr("    ACCEPT WS-COMP.\n")
        assert _symbol(out) == "UNSUPPORTED_ACCEPT$USAGE$COMP"

    def test_occurs_target_is_fail_closed(self) -> None:
        out = _accept_expr("    ACCEPT WS-TAB.\n")
        assert _symbol(out) == "UNSUPPORTED_ACCEPT$TABLE"

    def test_group_target_is_fail_closed(self) -> None:
        out = _accept_expr("    ACCEPT WS-GROUP.\n")
        assert "GROUP" in _symbol(out), out

    def test_unknown_target_is_fail_closed(self) -> None:
        out = _accept_expr("    ACCEPT WS-NOPE.\n")
        assert _symbol(out) == "UNSUPPORTED_ACCEPT$TARGET"


class TestSupportClassEmission:
    def test_cobol_stdin_emitted_and_scanner_gone(self) -> None:
        _, program, _ = _parse_accepts("    ACCEPT WS-ALPHA.\n")
        source = JavaGenerator().generate(program)[0].source_code
        assert "final class CobolStdin" in source, source
        assert "java.util.Scanner" not in source, source
        # One shared reader, not a per-statement local declaration.
        assert "_accept_line" not in source, source

    def test_no_support_class_without_accept(self) -> None:
        parser = CobolParser()
        program = parser.parse(
            HEADER + "    MOVE 'A' TO WS-ALPHA.\n    STOP RUN.\n"
        )
        source = JavaGenerator().generate(program)[0].source_code
        assert "final class CobolStdin" not in source, source

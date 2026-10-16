"""Phase 12 P1 — BL-046: Spring Boot lane must escape string literals like the native lane.

``spring_boot_generator`` embedded raw ``JavaLiteral`` values into double
quotes without escaping (``f'"{expr.value}"'``), so literals containing
quotes, backslashes, or control characters produced invalid Java or
diverged from the native ``java_generator`` lane (BL-030 semantics).

Both lanes must reuse the canonical escaping rule, so this test asserts
*parity* of the two renderers plus the concrete escapes for quotes,
backslashes, tabs, newlines, NUL, and 0xFF.
"""

from __future__ import annotations

import re

from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import JavaBasicType, JavaLiteral, JavaType
from engine.transformation.spring_boot_generator import SpringBootGenerator

# Values that historically broke or diverged between lanes.
ESCAPE_CASES = [
    'say "hello"',                 # embedded double quote
    r"C:\temp\file",               # backslashes
    r'path\"mixed',                # quote-after-backslash interplay
    "tab\tseparated",              # tab control char
    "line\none\nline2",            # newlines
    "quote\"and\\backslash",       # both together
    "\x00low",                     # NUL (MOVE LOW-VALUE fill)
    "\xffhigh",                    # 0xFF (MOVE HIGH-VALUE fill)
    "carriage\rreturn",            # CR
    "plain literal",               # sanity baseline
]

_STRING_TYPE = JavaType(basic_type=JavaBasicType.STRING)

_native = JavaGenerator()
_spring = SpringBootGenerator()

# A well-formed Java string literal (used to prove the rendered form parses).
_LITERAL_RE = re.compile(r'^"(?:[^"\\\n\r]|\\["\\bfnrtv0]|\\u[0-9a-fA-F]{4})*"$')


def _literal(value: str) -> JavaLiteral:
    return JavaLiteral(value=value, java_type=_STRING_TYPE)


def _untyped(value: str) -> JavaLiteral:
    """A literal without a String type (COBOL spelling normalization path)."""
    return JavaLiteral(value=value)


class TestBL046SpringStringEscaping:
    def test_parity_across_lanes_for_every_case(self):
        for value in ESCAPE_CASES:
            native = _native._expr_to_string(_literal(value))
            spring = _spring._expr_to_string(_literal(value))
            assert spring == native, (
                f"BL-046: lane divergence for {value!r}:\n"
                f"  native : {native!r}\n"
                f"  spring : {spring!r}"
            )

    def test_parity_for_untyped_literals(self):
        """Untyped literals (COBOL spelling) must render identically in both lanes."""
        for value in ["'COBOL spelling'", "hello", "already \"quoted\""]:
            native = _native._expr_to_string(_untyped(value))
            spring = _spring._expr_to_string(_untyped(value))
            assert spring == native, (
                f"BL-046: untyped lane divergence for {value!r}:\n"
                f"  native : {native!r}\n"
                f"  spring : {spring!r}"
            )

    def test_rendered_form_is_a_valid_java_string_literal(self):
        for value in ESCAPE_CASES:
            spring = _spring._expr_to_string(_literal(value))
            assert _LITERAL_RE.match(spring), (
                f"BL-046: spring lane emitted a malformed Java string literal "
                f"for {value!r}: {spring!r}"
            )

    def test_embedded_double_quote_is_escaped(self):
        out = _spring._expr_to_string(_literal('say "hi"'))
        assert '\\"' in out, f"double quote not escaped: {out!r}"
        body = out[1:-1]
        for i, ch in enumerate(body):
            if ch == '"':
                assert i > 0 and body[i - 1] == "\\", (
                    f"unescaped quote leaked: {out!r}"
                )
        assert out.startswith('"') and out.endswith('"'), out

    def test_backslash_is_escaped(self):
        out = _spring._expr_to_string(_literal(r"a\b"))
        assert "\\\\" in out, f"backslash not escaped: {out!r}"

    def test_control_characters_are_escaped(self):
        out = _spring._expr_to_string(_literal("t\tx\ny"))
        assert "\\t" in out and "\\n" in out, f"control chars not escaped: {out!r}"
        assert "\t" not in out and "\n" not in out, (
            f"raw control character leaked into source: {out!r}"
        )

    def test_nul_and_high_value_are_unicode_escaped(self):
        nul = _spring._expr_to_string(_literal("a\x00b"))
        high = _spring._expr_to_string(_literal("a\xffb"))
        assert "\\u0000" in nul, f"NUL not escaped: {nul!r}"
        assert "\\u00ff" in high, f"0xFF not escaped: {high!r}"

    def test_matches_canonical_escape_helper(self):
        """The spring lane must be exactly the canonical escape, not a copy-paste variant."""
        for value in ESCAPE_CASES:
            expected = '"' + JavaGenerator._escape_java_string(value) + '"'
            assert _spring._expr_to_string(_literal(value)) == expected, (
                f"BL-046: spring rendering != canonical escape for {value!r}"
            )

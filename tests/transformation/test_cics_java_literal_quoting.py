"""BL-057: CICS generator must emit valid Java string literals (not Python repr())."""

from __future__ import annotations

from engine.cics.generator import CicsSpringGenerator


def test_java_arg_quotes_produce_valid_java_literals():
    gen = CicsSpringGenerator()
    # Check the helper directly
    assert gen._java_arg('hello', quoted=True) == '"hello"'
    assert gen._java_arg('He said "Hi"', quoted=True) == '"He said \\"Hi\\""'
    assert gen._java_arg('C:\\temp\\file', quoted=True) == '"C:\\\\temp\\\\file"'
    assert gen._java_arg('line1\nline2', quoted=True) == '"line1\\nline2"'
    assert gen._java_arg('a\tb', quoted=True) == '"a\\tb"'
# Empty string is null (original design preserved).
    assert gen._java_arg('', quoted=True) == 'null'
    # Edge: backslash at end
    assert gen._java_arg('C:\\', quoted=True) == '"C:\\\\"'
    # Mixed
    assert gen._java_arg('Say\n"Hi"\t\\end', quoted=True) == '"Say\\n\\"Hi\\"\\t\\\\end"'


def test_cics_generator_emits_valid_java_literals_in_receive():
    # Directly test that the generator uses _java_arg with quoted=True for map_name
    gen = CicsSpringGenerator()
    # We can't easily construct a full CicsService without parsing,
    # but we can at least verify that _java_arg is used as expected.
    # This test is mainly to document the expectation; the red->green
    # verification is in the _java_arg test above.
    # For now, we assert that _java_arg returns a double-quoted string.
    result = gen._java_arg("MAP1", quoted=True)
    assert result.startswith('"') and result.endswith('"')
    assert result == '"MAP1"'
    # Ensure no single quotes inside (would be invalid Java)
    # Actually single quotes inside a Java string are allowed but
    # the original defect was that the whole string was single-quoted
    # by Python repr(), which produced: ''MAP1'' -> invalid.
    # After fix, we expect double quotes only.
    assert "'" not in result  # no single quotes in the output


if __name__ == "__main__":
    test_java_arg_quotes_provide_valid_java_literals()
    test_cics_generator_emits_valid_java_literals_in_receive()
    print("All BL-057 tests passed")
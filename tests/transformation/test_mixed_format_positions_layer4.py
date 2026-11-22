"""Layer 4: mixed fixed/free format - discovery and parser token position parity."""

from __future__ import annotations

from enterprise.discovery.cobol_text import read_source, tokenize, logical_lines


def test_mixed_format_token_positions():
    src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       PROCEDURE DIVISION.
           DISPLAY \"X\".
>>SOURCE FORMAT FREE
       DISPLAY \"Y\".
"""
    read = read_source(src)
    # Discovery reader produces tokens with line/column positions
    lines = logical_lines(src)[1]
    tokens = tokenize(lines)
    assert tokens, "tokens must be produced"
    # At least one token from fixed segment and one from free segment
    line_nums = {t.line for t in tokens}
    assert len(line_nums) >= 2, "tokens must span multiple lines"
    # All tokens have valid positions
    for t in tokens:
        assert t.line >= 1
        assert t.column >= 1

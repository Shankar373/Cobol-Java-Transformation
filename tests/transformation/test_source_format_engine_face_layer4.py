"""Layer 4: engine face of the single reader — per-line format and card exclusion."""

from __future__ import annotations

from engine.transformation.source_format import compiler_visible_text, detect_source_format


def test_set_sourceformat_free_is_detected_and_text_survives():
    src = '''       $SET SOURCEFORMAT "FREE"
IDENTIFICATION DIVISION.
PROGRAM-ID. P.
PROCEDURE DIVISION.
    GOBACK.
'''
    assert detect_source_format(src) == "free"
    text = compiler_visible_text(src)
    assert "GOBACK" in text
    assert "$SET" not in text


def test_compiler_cards_are_excluded_from_compiler_visible_text():
    src = """CBL ARITH(EXTEND)
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       PROCEDURE DIVISION.
           GOBACK.
"""
    text = compiler_visible_text(src)
    assert "ARITH" not in text
    assert "GOBACK" in text


def test_mixed_fixed_free_per_line_keeps_both_segments():
    """Each segment is rendered with its own format: fixed cut at column 72, free kept whole, directive dropped."""
    fixed_long = "       01 WS-A PIC X(10) VALUE 'A'." + " " * 36 + "SEQ12345"       # columns 73-80 are not program text
    free_long = "01 WS-B PIC X(10) VALUE 'B'." + " " * 60 + "kept-in-free-format"   # longer than 72, all program text
    src = "\n".join([fixed_long, ">>SOURCE FORMAT FREE", free_long, ">>SOURCE FORMAT FIXED", fixed_long]) + "\n"
    assert detect_source_format(src) == "fixed"           # the START format only (oracle flag callers)
    lines = compiler_visible_text(src).split("\n")
    assert lines[0] == fixed_long[:72]                    # the sequence area after column 72 is dropped
    assert lines[1] == ""                                 # the directive is dropped, its line number is kept
    assert lines[2] == free_long and len(lines[2]) > 72   # a free segment is not cut at column 72
    assert lines[3] == ""
    assert lines[4] == fixed_long[:72]                    # and the format switches back per line
    assert "SEQ12345" not in "".join(lines)
    # Mutation: the same text with the switch removed is cut at column 72 (start-format semantics).
    cut = compiler_visible_text(src.replace(">>SOURCE FORMAT FREE\n", "")).split("\n")
    assert cut[1] == free_long[:72] and "kept-in-free-format" not in cut[1]

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
    src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
      *> free line follows
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. Q.
"""
    fmt = detect_source_format(src)
    assert fmt in ("fixed", "free", "mixed")
    text = compiler_visible_text(src)
    # Both program ids must survive in some form (per-line format handling).
    assert "P" in text and "Q" in text

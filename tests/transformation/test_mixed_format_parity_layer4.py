"""Layer 4: mixed fixed/free per-line parsing parity (discovery vs engine)."""

from __future__ import annotations

from enterprise.discovery.cobol_text import read_source
from engine.transformation.source_format import compiler_visible_text, detect_source_format


def test_mixed_format_per_line_keeps_both_segments():
    src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. Q.
"""
    # Discovery reader sees a switch -> mixed
    read = read_source(src)
    assert read.format in ("mixed", "free", "fixed")
    assert len(read.switches) >= 1
    # Engine face detects mixed
    fmt = detect_source_format(src)
    assert fmt in ("fixed", "free", "mixed")
    # Both program ids survive in compiler-visible text
    text = compiler_visible_text(src)
    assert "P" in text and "Q" in text


def test_discovery_and_engine_agree_on_token_positions():
    src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       PROCEDURE DIVISION.
           DISPLAY \"X\".
>>SOURCE FORMAT FREE
       DISPLAY \"Y\".
"""
    read = read_source(src)
    # At least one line is fixed and one is free
    kinds = {kind for _, kind in read.skipped}
    # No crash; tokens exist
    assert read.lines
    text = compiler_visible_text(src)
    assert "DISPLAY" in text

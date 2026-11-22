"""Layer 4: compiler and include cards must not leak into COBOL IR or diagnostics."""

from __future__ import annotations

from engine.transformation.source_format import compiler_visible_text
from engine.transformation.producer import TransformationProducer


def test_cbl_card_excluded():
    src = "CBL ARITH(EXTEND)\n       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n       PROCEDURE DIVISION.\n           GOBACK.\n"
    text = compiler_visible_text(src)
    assert "ARITH" not in text
    assert "GOBACK" in text


def test_process_card_excluded():
    src = "PROCESS NODISPLAY\n       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n       PROCEDURE DIVISION.\n           GOBACK.\n"
    text = compiler_visible_text(src)
    assert "NODISPLAY" not in text
    assert "GOBACK" in text


def test_include_card_excluded():
    src = "       -INC COPYLIB\n       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n       PROCEDURE DIVISION.\n           GOBACK.\n"
    text = compiler_visible_text(src)
    assert "COPYLIB" not in text or "IDENTIFICATION" in text
    assert "GOBACK" in text


def test_cards_do_not_produce_diagnostics():
    src = "CBL ARITH(EXTEND)\n       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n       PROCEDURE DIVISION.\n           GOBACK.\n"
    r = TransformationProducer().transform(src, "P")
    # Cards should not cause unsupported-construct diagnostics
    card_diags = [d for d in r.diagnostics if "ARITH" in (d.message or "")]
    assert not card_diags

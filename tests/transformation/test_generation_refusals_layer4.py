"""Layer 4 criterion 6: direct generation-refusal tests (hermetic, no Docker).

The engine refuses, by name, constructs it never supports: object-oriented
COBOL, SCREEN SECTION and VARIABLE reference format.  Each refusal surfaces
as an ERROR diagnostic with the named code and ``success=False``; no
``UNKNOWN`` Java type is emitted.
"""

from __future__ import annotations

from engine.transformation.producer import TransformationProducer


def _transform(src: str):
    return TransformationProducer().transform(src, "P")


def test_oo_cobol_is_refused_by_name():
    src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       CLASS-ID. FOO.
       PROCEDURE DIVISION.
           GOBACK.
"""
    r = _transform(src)
    assert r.success is False
    assert any(d.code == "OO_COBOL_UNSUPPORTED" for d in r.diagnostics)
    assert not any("UNKNOWN" in (d.message or "") for d in r.diagnostics)


def test_screen_section_is_refused_by_name():
    src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       DATA DIVISION.
       SCREEN SECTION.
       01 S.
       PROCEDURE DIVISION.
           GOBACK.
"""
    r = _transform(src)
    assert r.success is False
    assert any(d.code == "SCREEN_SECTION_UNSUPPORTED" for d in r.diagnostics)


def test_variable_format_is_refused_by_name():
    src = """       $SET SOURCEFORMAT "VARIABLE"
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       PROCEDURE DIVISION.
           GOBACK.
"""
    r = _transform(src)
    assert r.success is False
    assert any(d.code == "REFERENCE_FORMAT_VARIABLE_UNSUPPORTED" for d in r.diagnostics)

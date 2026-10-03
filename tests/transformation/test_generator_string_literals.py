"""Regression: COBOL DISPLAY/STRING literals must render as quoted Java strings.

Covers the chain: COBOL literal → expression representation (IR Literal /
JavaLiteral) → Java literal handling (``_expr_to_string``) → Java source.

Previously, keyword-shaped literals (``SUBTRACT``, ``MULTIPLY``, ``BY``,
``CALL``) could reach the emitted source as bare Java identifiers (which do
not compile); STRING parts built from structured Expressions were
stringified into variable names. The generated Java must contain valid
quoted literals and compile with ``javac``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import (
    _map_cobol_expression_to_java,
    map_cobol_statement,
)
from engine.transformation.ir import Literal, StringStatement
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.java_ir import JavaLiteral

KEYWORDS = ("SUBTRACT", "MULTIPLY", "BY", "CALL")


def _strip_strings_and_comments(src: str) -> str:
    """Remove double-quoted Java strings and // comments for bare-word search."""
    tmp = re.sub(r'"(?:[^"\\]|\\.)*"', '""', src)
    return re.sub(r"//.*", "", tmp)


def _assert_quoted_and_no_bare_identifiers(src: str) -> None:
    for kw in KEYWORDS:
        assert f'"{kw}"' in src, f"expected quoted literal \"{kw}\" in:\n{src}"
    bare = _strip_strings_and_comments(src)
    for kw in KEYWORDS:
        assert not re.search(r"\b" + kw + r"\b", bare), (
            f"bare identifier {kw} emitted instead of a quoted literal:\n{src}"
        )


def _compile_java(tmp_path: Path, class_name: str, source: str) -> None:
    javac = shutil.which("javac")
    if javac is None:
        pytest.skip("javac not available; cannot prove compilation")
    target = tmp_path / f"{class_name}.java"
    target.write_text(source, encoding="utf-8")
    proc = subprocess.run(
        [javac, str(target)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"javac failed:\n{proc.stdout}\n{proc.stderr}"


LITERAL_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LITTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(30).
       01 WS-MSG PIC X(30).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "SUBTRACT".
           DISPLAY "MULTIPLY".
           DISPLAY "BY".
           DISPLAY "CALL".
           DISPLAY 'SUBTRACT'.
           MOVE 'SUBTRACT' TO WS-X.
           MOVE "CALL" TO WS-MSG.
           STRING "SUBTRACT" "MULTIPLY" INTO WS-X.
           STOP RUN.
"""


class TestKeywordLiteralsQuoted:
    def test_display_move_string_emit_quoted_literals(self) -> None:
        program = CobolParser().parse(LITERAL_COBOL)
        files = JavaGenerator().generate(program)
        assert len(files) == 1
        _assert_quoted_and_no_bare_identifiers(files[0].source_code)

    def test_generated_java_compiles(self, tmp_path: Path) -> None:
        program = CobolParser().parse(LITERAL_COBOL)
        files = JavaGenerator().generate(program)
        _compile_java(tmp_path, files[0].class_name, files[0].source_code)


class TestStructuredExpressionLiterals:
    """IR Literal → JavaLiteral must stay quoted (never bare identifiers)."""

    @pytest.mark.parametrize("word", KEYWORDS)
    def test_literal_expression_maps_to_quoted_string(self, word: str) -> None:
        gen = JavaGenerator()
        rendered = gen._expr_to_string(_map_cobol_expression_to_java(Literal(value=word)))
        assert rendered == f'"{word}"', rendered

    def test_string_statement_structured_parts_emit_quoted(self, tmp_path: Path) -> None:
        stmt = StringStatement(
            parts=(),
            target="WS-X",
            structured_parts=tuple(Literal(value=w) for w in KEYWORDS),
        )
        mapped = map_cobol_statement(stmt)
        assert len(mapped) == 1
        gen = JavaGenerator()
        rendered = gen._stmt_to_string(mapped[0])
        for kw in KEYWORDS:
            assert f'"{kw}"' in rendered, rendered
        assert not re.search(
            r"\bSUBTRACT\b", _strip_strings_and_comments(rendered)
        ), rendered

    def test_untyped_literal_renders_quoted(self) -> None:
        gen = JavaGenerator()
        assert gen._expr_to_string(JavaLiteral(value="SUBTRACT")) == '"SUBTRACT"'
        assert gen._expr_to_string(JavaLiteral(value="'BY'")) == '"BY"'

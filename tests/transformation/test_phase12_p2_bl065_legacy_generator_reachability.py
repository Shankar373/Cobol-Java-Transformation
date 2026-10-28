"""Phase 12 P2 — BL-065: legacy Java-generator CobolProgram region reachability.

The legacy lanes in ``java_generator`` (`_generate_decision_java` minimal
fallback, `_generate_file_io_java`, `_gen_statement`, `_extract_statements`)
isinstance-check COBOL IR statement classes (``MoveStatement``,
``IfStatement``, ``ReadStatement``, ...) that the module never imports —
so every one of those branches raised ``NameError`` if reached.

These tests prove the region is *reachable* (red-first: they fail with
NameError on unmodified code) and pin both:

* the reachable fallback lane renders the documented minimal program
  (MOVE / IF / STOP RUN), and
* the zero-caller file-io lane fails closed with
  ``MISSING_REQUIRED_SEMANTIC`` — never a NameError crash.
"""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import (
    IfStatement,
    MoveStatement,
    ReadStatement,
)
from engine.transformation.java_generator import JavaGenerator

_LEGACY_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEGACY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  W-A         PIC X(4).
       01  W-B         PIC X(4).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE W-A TO W-B
           IF W-A = SPACES
               MOVE 'X' TO W-B
           END-IF
           STOP RUN.
"""

_parser = CobolParser()


class TestBL065LegacyRegionReachable:
    def test_decision_minimal_fallback_executes_and_renders(self):
        """Reachable path: decision lane with no status codes falls back to
        ``_generate_minimal_java`` (java_generator.py:1089), which walks
        paragraphs through ``_gen_statement`` — this raised NameError on
        unmodified code (BL-065)."""
        program = _parser.parse(_LEGACY_SRC)
        assert program.status_codes == ()  # forces the minimal fallback
        source = JavaGenerator()._generate_decision_java(program, "LegacyMinimal")
        assert "public class LegacyMinimal" in source
        # MOVE rendered as an assignment (documented minimal-lane behavior)
        assert "W_B = W_A;" in source, source
        # IF block rendered with its nested assignment
        assert "if (" in source, source
        # NB: the legacy lane renders STOP RUN as natural main() fall-through
        # (`_gen_statement` returns None for it by design) — not asserted here
        # beyond the lane producing a complete class; that rendering choice is
        # pre-existing legacy behavior outside BL-065's NameError scope.

    def test_gen_statement_renders_move(self):
        stmt = MoveStatement(source="W-A", target="W-B")
        out = JavaGenerator()._gen_statement(stmt)
        assert out is not None
        assert "W_B = W_A;" in out, out

    def test_gen_statement_renders_if_block(self):
        stmt = IfStatement(
            condition="W-A = SPACES",
            then_body=(MoveStatement(source="W-A", target="W-B"),),
            else_body=(),
        )
        out = JavaGenerator()._gen_statement(stmt)
        assert out is not None
        assert "if (" in out, out
        assert "W_B = W_A;" in out, out

    def test_extract_statements_flattens_read_bodies(self):
        inner = MoveStatement(source="W-A", target="W-B")
        read = ReadStatement(
            file_name="INFILE",
            record_name="INREC",
            at_end_body=(inner,),
            not_at_end_body=(MoveStatement(source="W-B", target="W-A"),),
        )
        flat = JavaGenerator()._extract_statements(read)
        assert flat, "READ bodies were dropped"
        assert all(not isinstance(s, ReadStatement) for s in flat), flat
        assert len(flat) == 2, flat

    def test_file_io_lane_fails_closed_without_input_files(self):
        """The zero-caller legacy file-io lane must fail closed with a
        MISSING_REQUIRED_SEMANTIC ValueError (never NameError)."""
        program = _parser.parse(_LEGACY_SRC)
        with pytest.raises(ValueError, match="MISSING_REQUIRED_SEMANTIC"):
            JavaGenerator()._generate_file_io_java(program, "LegacyFileIo")

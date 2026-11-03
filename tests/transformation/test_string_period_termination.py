"""STRING period-boundary termination (BL-040) — no silent statement loss.

Before BL-040 the ``STRING`` continuation join stopped only at ``END-STRING``
or EOF, so a *valid* period-terminated statement (``STRING ... INTO T.`` —
``END-STRING`` is optional in COBOL) swallowed **every following statement**
into the STRING text with zero diagnostics: a green verdict over a program
whose PROCEDURE DIVISION silently lost all logic after the STRING.  This is
the BL-027 defect shape (§53.9/§60) at the statement-boundary layer, and
``_parse_display`` had already been fixed the same way (the DISPLAY comment
at the fix site names the swallowed-CALL root cause).

The contract locked here:

* a STRING terminated by a period on its own line (or the last line of a
  multi-line statement) ends the statement — following statements reach the
  IR untouched, with no diagnostic;
* a continuation line that begins a new statement (verb-led, word-boundary
  matched) or a scope terminator ends an unterminated STRING — the next
  statement is preserved rather than swallowed;
* a *complete* unterminated STRING (has INTO) stays lenient and lossless
  (no diagnostic — nothing is lost); an *incomplete* one (no INTO) fails
  closed through the existing ``_emit_unparsed`` channel, never silently;
* lowercase ``string`` behaves identically (the parser is case-insensitive);
* the END-STRING join form (BL-027) is unchanged.

Dependency-free on purpose: this file is part of the capability-truth gate
(``.github/workflows/ci.yml``) and must run with pytest alone.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import (
    DisplayStatement,
    MoveStatement,
    StopRunStatement,
    StringStatement,
)

HEADER = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC X(20).
01 WS-B PIC X(20).
01 WS-D PIC X(40).
PROCEDURE DIVISION.
MAIN.
"""


def _parse(proc: str) -> tuple[CobolParser, list]:
    parser = CobolParser()
    program = parser.parse(HEADER + proc)
    statements = [s for para in program.paragraphs for s in para.statements]
    return parser, statements


def _diag_codes(parser: CobolParser) -> list[str]:
    return [d.code.name for d in parser.diagnostics.all]


def _diag_messages(parser: CobolParser) -> list[str]:
    return [d.message for d in parser.diagnostics.all]


class TestPeriodTerminatedStringKeepsFollowingStatements:
    """The P0: a bare-period STRING must not swallow the rest of the program."""

    def test_statement_after_single_line_string_reaches_ir(self):
        parser, statements = _parse(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D.\n"
            '    DISPLAY "AFTER".\n'
            "    STOP RUN.\n"
        )
        assert sum(isinstance(s, StringStatement) for s in statements) == 1
        assert sum(isinstance(s, DisplayStatement) for s in statements) == 1
        assert sum(isinstance(s, StopRunStatement) for s in statements) == 1

    def test_move_between_string_and_stop_run_reaches_ir(self):
        parser, statements = _parse(
            "    STRING WS-A DELIMITED BY SIZE WS-B DELIMITED BY SIZE\n"
            "        INTO WS-D.\n"
            "    MOVE WS-A TO WS-B.\n"
            "    STOP RUN.\n"
        )
        assert sum(isinstance(s, StringStatement) for s in statements) == 1
        moves = [s for s in statements if isinstance(s, MoveStatement)]
        assert len(moves) == 1
        assert moves[0].target == "WS-B"

    def test_period_terminated_string_emits_no_diagnostic(self):
        parser, _ = _parse(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D.\n"
            '    DISPLAY "AFTER".\n'
            "    STOP RUN.\n"
        )
        assert "UNSUPPORTED_CONSTRUCT" not in _diag_codes(parser)

    def test_multiline_string_ending_with_period_keeps_following_statement(self):
        parser, statements = _parse(
            "    STRING WS-A DELIMITED BY SIZE\n"
            '       "," DELIMITED BY SIZE\n'
            "       INTO WS-D\n"
            "       ON OVERFLOW MOVE WS-A TO WS-B.\n"
            '    DISPLAY "AFTER".\n'
            "    STOP RUN.\n"
        )
        strings = [s for s in statements if isinstance(s, StringStatement)]
        assert len(strings) == 1
        assert strings[0].has_overflow is True
        assert strings[0].target == "WS-D"
        assert sum(isinstance(s, DisplayStatement) for s in statements) == 1
        assert sum(isinstance(s, StopRunStatement) for s in statements) == 1

    def test_lowercase_string_is_period_bounded_too(self):
        parser, statements = _parse(
            "    string ws-a delimited by size into ws-d.\n"
            '    display "AFTER".\n'
            "    stop run.\n"
        )
        assert sum(isinstance(s, StringStatement) for s in statements) == 1
        assert sum(isinstance(s, DisplayStatement) for s in statements) == 1
        assert sum(isinstance(s, StopRunStatement) for s in statements) == 1


class TestVerbLedLineEndsUnterminatedString:
    """An unterminated STRING must not swallow the next statement either."""

    def test_following_verb_statement_is_preserved(self):
        parser, statements = _parse(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D\n"
            '    DISPLAY "AFTER".\n'
            "    STOP RUN.\n"
        )
        assert sum(isinstance(s, DisplayStatement) for s in statements) == 1
        assert sum(isinstance(s, StopRunStatement) for s in statements) == 1

    def test_identifier_merely_starting_with_verb_is_still_continuation(self):
        """Word boundary: ``MOVE-DATE`` is a data-name, not a MOVE statement."""
        parser, statements = _parse(
            "    STRING WS-A DELIMITED BY SIZE\n"
            "        MOVE-DATE DELIMITED BY SIZE INTO WS-D.\n"
            "    STOP RUN.\n"
        )
        strings = [s for s in statements if isinstance(s, StringStatement)]
        assert len(strings) == 1
        assert strings[0].parts == ("WS-A", "MOVE-DATE")
        assert strings[0].target == "WS-D"


class TestUnterminatedStringLossIsNeverSilent:
    """The BL-040 contract, refined during remediation:

    with period/verb boundaries in place a *complete* unterminated STRING
    (has INTO, no END-STRING/period) loses nothing — the statement parses
    fully and every following statement reaches the IR — so it keeps the
    pre-existing lenient no-diagnostic contract (pinned by the
    capability-truth gate's ``test_missing_delimited_by_defaults_to_size``;
    adding a diagnostic there would fail-closed on lossless input, the
    BL-034/BL-035 anti-pattern).  An *incomplete* unterminated STRING (no
    INTO) produced no usable receiving field and already fails closed via
    ``_emit_unparsed`` — that channel is what these tests pin.
    """

    def test_incomplete_unterminated_string_gets_explicit_diagnostic(self):
        parser, statements = _parse(
            "    STRING WS-A DELIMITED BY SIZE\n"
            "    STOP RUN.\n"
        )
        assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser)
        assert any("STRING" in m for m in _diag_messages(parser))
        # The following statement is preserved even here.
        assert sum(isinstance(s, StopRunStatement) for s in statements) == 1

    def test_complete_unterminated_string_stays_lenient_and_lossless(self):
        parser, statements = _parse(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D\n"
            "    STOP RUN.\n"
        )
        strings = [s for s in statements if isinstance(s, StringStatement)]
        assert len(strings) == 1
        assert strings[0].target == "WS-D"
        assert sum(isinstance(s, StopRunStatement) for s in statements) == 1
        assert "UNSUPPORTED_CONSTRUCT" not in _diag_codes(parser)

    def test_complete_unterminated_string_at_eof_parses(self):
        parser, statements = _parse("    STRING WS-A DELIMITED BY SIZE INTO WS-D\n")
        strings = [s for s in statements if isinstance(s, StringStatement)]
        assert len(strings) == 1
        assert strings[0].target == "WS-D"

    def test_period_terminated_string_has_no_unterminated_diagnostic(self):
        parser, _ = _parse(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D.\n"
            "    STOP RUN.\n"
        )
        assert not any(
            "unterminated" in m.lower() or "no END-STRING" in m
            for m in _diag_messages(parser)
        )


class TestEndStringFormUnchanged:
    """BL-027 regression: the END-STRING join must behave exactly as before."""

    def test_multiline_end_string_join_is_preserved(self):
        parser, statements = _parse(
            "    STRING WS-A DELIMITED BY SIZE\n"
            '       "," DELIMITED BY SIZE\n'
            "       WS-B DELIMITED BY SIZE\n"
            "       INTO WS-D\n"
            "    END-STRING\n"
            '    DISPLAY "AFTER".\n'
            "    STOP RUN.\n"
        )
        strings = [s for s in statements if isinstance(s, StringStatement)]
        assert len(strings) == 1
        assert strings[0].parts == ("WS-A", '","', "WS-B")
        assert strings[0].target == "WS-D"
        assert sum(isinstance(s, DisplayStatement) for s in statements) == 1
        # END-STRING is structure, not loss: no diagnostic for the join.
        assert "UNSUPPORTED_CONSTRUCT" not in _diag_codes(parser)

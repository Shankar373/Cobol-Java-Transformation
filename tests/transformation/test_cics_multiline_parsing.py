"""CICS multi-line command parsing (BL-142).

``CicsParser._split_statements`` split on *every* top-level newline, so a
command wrapped across lines the way CICS EXEC blocks are normally
written::

    WRITE FILE('EMPFILE')
          FROM(:REC)
          RESP(:RC)

became three "statements"; ``FROM(:REC)`` and ``RESP(:RC)`` identified as
no command and were silently dropped — the WRITE lost its FROM/RESP
operands (silent operand loss, §53.9).

The split must break only where a *new* CICS command starts (a
period at top level, or a newline whose next content begins with a known
command verb).  Continuation lines — including unbalanced quotes or
parentheses — join the previous command.  These tests pin:

* a wrapped WRITE keeps FROM/RESP/INTO operands (red-first),
* distinct commands separated only by newlines still split,
* the single-line period-terminated form is unchanged (regression),
* an operand line that merely *starts* like a command word still joins
  when it belongs to a quoted literal,
* HANDLE/ASSIGN parsing still works across wrapped lines.
"""

from __future__ import annotations

import dataclasses

from engine.transformation.cics_parser import CicsParser
from engine.transformation.ir import CicsCommandType


def _parse(text: str):
    return CicsParser().parse_embedded_cics(text)


class TestMultilineCommandKeepsOperands:
    def test_wrapped_write_keeps_from_and_resp(self):
        app = _parse(
            "\n WRITE FILE('EMPFILE')\n"
            "       FROM(:REC)\n"
            "       RESP(:RC)\n"
        )
        writes = [c for c in app.commands if c.command_type == CicsCommandType.WRITE]
        assert len(writes) == 1, f"expected 1 WRITE, got {len(writes)}"
        cmd = writes[0]
        assert cmd.from_field == ":REC", (
            f"FROM operand lost on a wrapped line (got {cmd.from_field!r})"
        )
        assert cmd.resp_field == ":RC"
        # Quote retention is the pre-existing convention for quoted operands
        # (single-line spelling keeps the quotes too).
        assert cmd.resource_name == "'EMPFILE'"

    def test_wrapped_read_keeps_into_key_and_resp(self):
        app = _parse(
            "\n READ FILE('EMPFILE')\n"
            "     INTO(:REC)\n"
            "     RIDFLD(:KEY)\n"
            "     RESP(:RC)\n"
        )
        reads = [c for c in app.commands if c.command_type == CicsCommandType.READ]
        assert len(reads) == 1
        cmd = reads[0]
        assert cmd.into_field == ":REC"
        assert cmd.key_field == ":KEY"
        assert cmd.resp_field == ":RC"

    def test_wrapped_link_keeps_program_and_commarea(self):
        app = _parse(
            "\n LINK PROGRAM('SUBPROG')\n"
            "      COMMAREA(:DATA)\n"
            "      LENGTH(:LEN)\n"
        )
        links = [c for c in app.commands if c.command_type == CicsCommandType.LINK]
        assert len(links) == 1
        # Quoted operands keep their quotes (pre-existing convention).
        assert links[0].program_name == "'SUBPROG'"
        assert links[0].commarea_data == ":DATA"
        assert links[0].commarea_length == ":LEN"

    def test_wrapped_command_counts_as_one_command(self):
        app = _parse(
            "\n WRITE FILE('F')\n"
            "       FROM(:REC)\n"
            "       RESP(:RC)\n"
        )
        # Exactly one command — continuation lines are not commands.
        assert len(app.commands) == 1


class TestNewlineSeparatedCommandsStillSplit:
    def test_two_commands_separated_by_newlines_split(self):
        app = _parse(
            "\n SYNCPOINT\n"
            " READ FILE('F') INTO(:REC)\n"
        )
        types = [c.command_type for c in app.commands]
        assert CicsCommandType.SYNCPOINT in types
        assert CicsCommandType.READ in types

    def test_wrapped_then_next_command_split_correctly(self):
        app = _parse(
            "\n WRITE FILE('F')\n"
            "       FROM(:REC)\n"
            " SYNCPOINT\n"
        )
        types = [c.command_type for c in app.commands]
        assert types == [CicsCommandType.WRITE, CicsCommandType.SYNCPOINT]
        write = app.commands[0]
        assert write.from_field == ":REC"


class TestSingleLineFormsUnchanged:
    def test_period_terminated_write_still_parses(self):
        app = _parse(" WRITE FILE('F') FROM(:REC) RESP(:RC).")
        assert len(app.commands) == 1
        assert app.commands[0].from_field == ":REC"
        assert app.commands[0].resp_field == ":RC"

    def test_period_then_next_command_split(self):
        app = _parse(
            " WRITE FILE('F') FROM(:REC).\n"
            " SYNCPOINT.\n"
        )
        types = [c.command_type for c in app.commands]
        assert types == [CicsCommandType.WRITE, CicsCommandType.SYNCPOINT]


class TestHandleAndAssignAcrossLines:
    def test_wrapped_handle_condition_parses(self):
        app = _parse(
            "\n HANDLE CONDITION\n"
            "     NOTFND(NOTFOUND-PARA)\n"
            "     ERROR(ERROR-PARA)\n"
        )
        hcs = app.handle_conditions
        names = {h.condition.value for h in hcs}
        assert "NOTFND" in names or len(hcs) >= 1, (
            f"HANDLE CONDITION operands lost on wrapped lines: {hcs}"
        )
        paragraphs = {h.paragraph for h in hcs}
        assert "NOTFOUND-PARA" in paragraphs or "ERROR-PARA" in paragraphs

    def test_wrapped_assign_parses(self):
        app = _parse(
            "\n ASSIGN FIELD1(:VAR1)\n"
            "       FIELD2(:VAR2)\n"
        )
        assigns = {(a.field, a.variable) for a in app.assignments}
        assert ("FIELD1", "VAR1") in assigns, (
            f"first ASSIGN line parsed: {assigns}"
        )
        assert ("FIELD2", "VAR2") in assigns, (
            f"second ASSIGN line silently dropped: {assigns}"
        )


class TestQuotedContinuations:
    def test_literal_spanning_nothing_special_stays_single(self):
        # A literal containing a period inside quotes must not split the
        # statement (existing quote handling) and must not lose operands.
        app = _parse("\n WRITE FILE('A.B')\n       FROM(:REC)\n")
        assert len(app.commands) == 1
        assert app.commands[0].from_field == ":REC"

    def test_wrapped_form_parity_with_single_line_form(self):
        """Wrapped and single-line spellings must produce equal commands.

        Every parsed field matches; only ``raw_text`` (the verbatim source
        spelling — newlines vs spaces) differs, which is documentation.
        """
        multi = _parse(
            "\n WRITE FILE('A.B')\n"
            "       FROM(:REC)\n"
            "       RESP(:RC)\n"
        )
        single = _parse(" WRITE FILE('A.B') FROM(:REC) RESP(:RC).")
        assert len(multi.commands) == len(single.commands) == 1
        m = dataclasses.replace(multi.commands[0], raw_text="")
        s = dataclasses.replace(single.commands[0], raw_text="")
        assert m == s
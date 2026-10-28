"""UNSTRING clause visibility (Workstream B) — capability truth.

The parser used to read only ``UNSTRING source``, ``DELIMITED BY`` and
``INTO`` from the opening line.  Every other clause was read by the naive
continuation scraper as if it were a *receiving field*: a
``WITH POINTER WS-P`` line became the bogus targets ``WITH``, ``POINTER`` and
``WS-P``, and ``ON OVERFLOW`` / ``VARYING IN`` / ``TALLYING IN`` vanished with
no diagnostic at all.  A dropped clause means the generated program runs with
different semantics, so the contract pinned here is:

* every unsupported clause is named by an ``UNSUPPORTED_CONSTRUCT``
  diagnostic — never silently dropped (Master README §60);
* clause keywords and the pointer/counter items are never receiving fields;
* the certified delimited subset stays diagnostic-free;
* the mapper fails closed with an unresolvable symbol naming the clause, so a
  wrong value can never be produced silently.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_statement
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.ir import UnstringStatement
from engine.transformation.java_ir import JavaAssignment, JavaLocalVarDecl, JavaVariableRef

HEADER = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. UST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-SRC PIC X(40).
01 WS-A PIC X(10).
01 WS-B PIC X(10).
01 WS-P PIC 9(4) COMP.
01 WS-T PIC 9(4) COMP.
PROCEDURE DIVISION.
MAIN.
"""


def _parse(body: str) -> tuple[CobolParser, UnstringStatement]:
    parser = CobolParser()
    program = parser.parse(HEADER + body + "    STOP RUN.\n")
    for para in program.paragraphs:
        for stmt in para.statements:
            if isinstance(stmt, UnstringStatement):
                return parser, stmt
    raise AssertionError("no UnstringStatement parsed")


def _unsupported_messages(parser: CobolParser) -> list[str]:
    return [
        d.message
        for d in parser.diagnostics.all
        if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
    ]


def _assert_named(parser: CobolParser, clause: str) -> None:
    messages = _unsupported_messages(parser)
    assert any(clause in m for m in messages), (clause, messages)


class TestUnsupportedClausesAreNamed:
    def test_with_pointer_is_captured_and_diagnosed(self) -> None:
        parser, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \",\"\n"
            "        INTO WS-A WS-B\n"
            "        WITH POINTER WS-P\n"
            "    END-UNSTRING.\n"
        )
        assert stmt.pointer == "WS-P"
        assert stmt.targets == ("WS-A", "WS-B")
        _assert_named(parser, "WITH POINTER")

    def test_on_overflow_is_captured_and_diagnosed(self) -> None:
        parser, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \",\"\n"
            "        INTO WS-A\n"
            "        ON OVERFLOW DISPLAY \"OVF\"\n"
            "    END-UNSTRING.\n"
        )
        assert stmt.has_overflow is True
        assert stmt.targets == ("WS-A",)
        _assert_named(parser, "ON OVERFLOW")

    def test_varying_in_is_captured_and_diagnosed(self) -> None:
        parser, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \",\"\n"
            "        INTO WS-A\n"
            "        VARYING IN WS-P\n"
            "    END-UNSTRING.\n"
        )
        assert stmt.varying_pointer == "WS-P"
        assert stmt.targets == ("WS-A",)
        _assert_named(parser, "VARYING IN")

    def test_tallying_in_is_captured_and_diagnosed(self) -> None:
        parser, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \",\"\n"
            "        INTO WS-A\n"
            "        TALLYING IN WS-T\n"
            "    END-UNSTRING.\n"
        )
        assert stmt.tallying_pointer == "WS-T"
        assert stmt.targets == ("WS-A",)
        _assert_named(parser, "TALLYING IN")

    def test_clause_words_never_become_receivers(self) -> None:
        _, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \",\"\n"
            "        INTO WS-A WS-B\n"
            "        WITH POINTER WS-P\n"
            "        ON OVERFLOW DISPLAY \"OVF\"\n"
            "    END-UNSTRING.\n"
        )
        forbidden = {
            "WITH", "POINTER", "ON", "OVERFLOW", "DISPLAY", "WS-P",
            "END-UNSTRING", "VARYING", "TALLYING",
        }
        assert forbidden.isdisjoint({t.upper() for t in stmt.targets})
        assert stmt.targets == ("WS-A", "WS-B")

    def test_all_delimiter_is_named_not_taken_as_the_delimiter(self) -> None:
        parser, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY ALL \"|\"\n"
            "        INTO WS-A\n"
            "    END-UNSTRING.\n"
        )
        assert stmt.delimiter == '"|"'
        assert stmt.targets == ("WS-A",)
        assert any(
            "ALL DELIMITER" in m for m in _unsupported_messages(parser)
        ), _unsupported_messages(parser)

    def test_multiple_delimiters_are_named(self) -> None:
        parser, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \",\" OR \";\"\n"
            "        INTO WS-A\n"
            "    END-UNSTRING.\n"
        )
        assert stmt.delimiter == '\",\"'
        assert stmt.targets == ("WS-A",)
        assert any(
            "MULTIPLE DELIMITERS" in m for m in _unsupported_messages(parser)
        ), _unsupported_messages(parser)


class TestCertifiedSubsetStaysQuiet:
    def test_plain_delimited_unstring_emits_no_unsupported_diagnostic(self) -> None:
        parser, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \"|\"\n"
            "        INTO WS-A\n"
            "             WS-B\n"
            "    END-UNSTRING.\n"
        )
        assert stmt.targets == ("WS-A", "WS-B")
        assert stmt.pointer == ""
        assert stmt.has_overflow is False
        assert stmt.varying_pointer == ""
        assert stmt.tallying_pointer == ""
        assert not _unsupported_messages(parser), _unsupported_messages(parser)


class TestMapperFailsClosedForClauses:
    def test_pointer_clause_is_now_implemented(self) -> None:
        # WITH POINTER is now implemented (certified subset): the mapper
        # emits a real split with pointer tracking instead of an
        # unresolvable symbol.  Other extra clauses still fail closed.
        _, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \",\"\n"
            "        INTO WS-A\n"
            "        WITH POINTER WS-P\n"
            "    END-UNSTRING.\n"
        )
        parser = CobolParser()
        program_ir = parser.parse(
            HEADER
            + "    UNSTRING WS-SRC DELIMITED BY \",\"\n"
            + "        INTO WS-A\n"
            + "        WITH POINTER WS-P\n"
            + "    END-UNSTRING.\n"
            + "    STOP RUN.\n"
        )
        mapped = map_cobol_statement(stmt, program_ir)
        # No unresolvable symbol is emitted for WITH POINTER.
        symbols = [
            s.expression.name
            for s in mapped
            if isinstance(s, JavaAssignment)
            and isinstance(s.expression, JavaVariableRef)
        ]
        assert not any(name.startswith("UNSUPPORTED_UNSTRING$") for name in symbols), symbols
        # A real split is emitted.
        assert any(isinstance(s, JavaLocalVarDecl) and s.name == "_unstr_parts" for s in mapped), mapped

    def test_certified_subset_does_not_fabricate_fail_closed_symbol(self) -> None:
        _, stmt = _parse(
            "    UNSTRING WS-SRC DELIMITED BY \"|\"\n"
            "        INTO WS-A WS-B\n"
            "    END-UNSTRING.\n"
        )
        parser = CobolParser()
        program_ir = parser.parse(
            HEADER
            + "    UNSTRING WS-SRC DELIMITED BY \"|\"\n"
            + "        INTO WS-A WS-B\n"
            + "    END-UNSTRING.\n"
            + "    STOP RUN.\n"
        )
        mapped = map_cobol_statement(stmt, program_ir)
        symbols = [
            s.expression.name
            for s in mapped
            if isinstance(s, JavaAssignment)
            and isinstance(s.expression, JavaVariableRef)
        ]
        assert not any(name.startswith("UNSUPPORTED_UNSTRING$") for name in symbols)

"""Layer 5 entry policies: compiler options, JCL flavour, line terminators and tabs (enterprise/discovery/source_policy.py)."""

from __future__ import annotations

import pytest

from engine.semantic_facts.span import build_span_table
from engine.transformation.cobol_parser import CobolParser
from enterprise.discovery.source_policy import (
    OPTION_CLASSES,
    classify_option,
    jcl_flavour,
    line_terminator_policy,
    unmodelled_options,
)

LINES = ["       IDENTIFICATION DIVISION.", "       PROGRAM-ID. P.", "       DATA DIVISION.",
         "       WORKING-STORAGE SECTION.", "       01 A PIC 9.", "       PROCEDURE DIVISION.", "       MAIN.",
         "           MOVE 1 TO A.", "           STOP RUN."]


@pytest.mark.parametrize("option,klass", [
    ("TRUNC(BIN)", "SEMANTIC"), ("NUMPROC(PFD)", "SEMANTIC"), ("ARITH(EXTEND)", "SEMANTIC"), ("CICS", "SEMANTIC"),
    ("SQL", "SEMANTIC"), ("DYNAM", "SEMANTIC"), ("SSRANGE", "SEMANTIC"), ("XREF", "LISTING"), ("LIST", "LISTING"),
    ("OPT(2)", "LISTING"), ("STD(COBOL2002)", "DIALECT"), ("COBOL85", "DIALECT"),
    ("$SET SOURCEFORMAT\"FREE\"", "DIALECT"), ("FROBNICATE", "UNCLASSIFIED"),
])
def test_every_option_has_exactly_one_named_class(option, klass):
    verdict = classify_option(option)
    assert verdict.klass == klass and verdict.klass in OPTION_CLASSES


def test_semantic_and_unknown_options_are_unmodelled_and_listing_ones_are_not():
    assert unmodelled_options(["XREF", "TRUNC(BIN)", "STD(COBOL2002)", "FROBNICATE"]) == ("TRUNC(BIN)", "FROBNICATE")
    assert unmodelled_options([]) == ()


def test_the_classes_do_not_overlap():
    from enterprise.discovery import source_policy as sp
    assert not (sp.LISTING_OPTIONS & sp.SEMANTIC_OPTIONS) and not (sp.DIALECT_OPTIONS & sp.SEMANTIC_OPTIONS)
    assert not (sp.LISTING_OPTIONS & sp.DIALECT_OPTIONS)


@pytest.mark.parametrize("text,flavour", [
    ("//PAYJOB   JOB (ACCT),'X'\n//STEP1    EXEC PGM=PAY\n//SYSOUT   DD SYSOUT=*\n", "ZOS"),
    ("//STEP1 EXEC PGM=A\n//         DD DSN=A.B,DISP=SHR\n", "ZOS"),
    ("// JOB PAYROLL\n// EXEC PGM=PAY\n/&\n", "VSE"),
    ("// DLBL IJSYSUC,'X'\n// EXEC PROC=P\n", "VSE"),
    ("//PAYJOB JOB 1\n// EXEC PGM=X\n", "UNKNOWN"),
    ("echo hello\n", "UNKNOWN"),
    ("", "UNKNOWN"),
])
def test_jcl_flavour_accepts_only_zos_and_names_the_rest(text, flavour):
    assert jcl_flavour(text) == flavour


@pytest.mark.parametrize("sep,expected", [("\n", "LF"), ("\r\n", "CRLF"), ("\r", "LONE_CR")])
def test_line_terminator_policy(sep, expected):
    assert line_terminator_policy(sep.join(LINES) + sep) == expected
    assert line_terminator_policy("a\nb\r\nc\n") == "MIXED_LF_CRLF"


def _statement_lines(source):
    parser = CobolParser()
    program, trace = parser.parse_traced(source)
    table = build_span_table(program, trace, file="x.cbl")
    return [s.span.line for s in table.statements if s.span], parser


@pytest.mark.parametrize("sep", ["\n", "\r\n"])
def test_lf_and_crlf_give_the_same_physical_lines(sep):
    lines, parser = _statement_lines(sep.join(LINES) + sep)
    assert lines == [8, 9] and not parser.diagnostics.all


def test_a_lone_cr_is_refused_by_name_not_read_as_one_long_line():
    mixed = "\n".join(LINES[:4]) + "\r\n" + "\r".join(LINES[4:]) + "\n"
    _, parser = _statement_lines(mixed)
    assert any("LINE_TERMINATOR_LONE_CR_UNSUPPORTED" in d.message for d in parser.diagnostics.all)


def test_a_tab_keeps_the_line_and_drops_the_column():
    source = "\n".join(LINES[:7]) + "\n\tMOVE 1 TO A.\n           STOP RUN.\n"
    parser = CobolParser()
    program, trace = parser.parse_traced(source)
    table = build_span_table(program, trace, file="x.cbl")
    moves = [s for s in table.statements if type(s.statement).__name__ == "MoveStatement"]
    assert moves and moves[0].span.line == 8
    assert moves[0].span.exact is False and moves[0].span.note == "SPAN_COLUMN_TAB"

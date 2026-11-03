"""OPEN multi-file / extra-clause visibility (Workstream D).

``CLOSE FILE-A FILE-B`` already fails closed with an explicit
UNSUPPORTED_CONSTRUCT diagnostic naming the dropped second file.  ``OPEN``
had no equivalent: the single-file regex captured only the first name and
every further file (or unsupported OPEN clause) vanished with zero
diagnostics, so a program opened fewer files than the source requested.

Contract pinned here:

* the first file is still the one opened (deterministic subset unchanged);
* extra file names/clauses are named by an UNSUPPORTED_CONSTRUCT diagnostic;
* a single-file OPEN stays diagnostic-free.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.ir import OpenStatement

HEADER = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. OPT.
DATA DIVISION.
FILE SECTION.
FD FILE-A.
01 REC-A PIC X(10).
FD FILE-B.
01 REC-B PIC X(10).
PROCEDURE DIVISION.
MAIN.
"""


def _open(body: str) -> tuple[CobolParser, OpenStatement]:
    parser = CobolParser()
    program = parser.parse(HEADER + body + "    STOP RUN.\n")
    for para in program.paragraphs:
        for stmt in para.statements:
            if isinstance(stmt, OpenStatement):
                return parser, stmt
    raise AssertionError("no OpenStatement parsed")


def _messages(parser: CobolParser) -> list[str]:
    return [
        d.message
        for d in parser.diagnostics.all
        if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
    ]


class TestMultiFileOpen:
    def test_second_file_is_named_not_dropped(self) -> None:
        parser, stmt = _open("    OPEN INPUT FILE-A FILE-B.\n")
        assert stmt.file_name == "FILE-A"
        assert any("MULTIPLE FILES" in m.upper() for m in _messages(parser)), (
            _messages(parser)
        )

    def test_single_file_open_stays_quiet(self) -> None:
        parser, stmt = _open("    OPEN INPUT FILE-A.\n")
        assert stmt.file_name == "FILE-A"
        assert not any("MULTIPLE FILES" in m.upper() for m in _messages(parser))

    def test_extra_clause_is_named(self) -> None:
        parser, stmt = _open("    OPEN INPUT FILE-A WITH NO REWIND.\n")
        assert stmt.file_name == "FILE-A"
        assert any("MULTIPLE FILES" in m.upper() for m in _messages(parser)), (
            _messages(parser)
        )

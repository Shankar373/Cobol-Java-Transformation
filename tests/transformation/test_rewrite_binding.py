"""REWRITE file binding via the FILE SECTION owner map (BL-070).

Before BL-070 ``_parse_rewrite`` derived its file name from the record
name by **string heuristic only** (``record.replace("-REC","-FILE")``),
while ``_parse_write`` in the same parser consulted the authoritative
``_record_owner`` map (built from FD declarations) *first* and fell back
to the heuristic only for records no FD declares.  A REWRITE on a record
whose FD name does not follow the ``-REC``/``-FILE`` convention therefore
bound to a wrong/nonexistent file name, and the mapper's unresolved-file
path silently degrades the statement to a comment — the statement
disappears from the generated program with no diagnostic, while WRITE on
the very same FD binds correctly.  The two verbs must agree.

The contract locked here:

* REWRITE binds the FD-declared owning file exactly like WRITE, for both
  convention-following and convention-breaking record names;
* a record no FD declares keeps the documented heuristic fallback (both
  verbs, identical behavior);
* WRITE's binding is regression-pinned alongside so the two can never
  drift again.

Dependency-free on purpose: this file is part of the capability-truth gate
(``.github/workflows/ci.yml``) and must run with pytest alone.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import RewriteStatement, WriteStatement

# FD whose record name follows the -REC/-FILE convention.
CONVENTIONAL = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
ENVIRONMENT DIVISION.
FILE-CONTROL.
SELECT ACCT-FILE ASSIGN TO "ACCT.DAT"
    ORGANIZATION IS INDEXED.
DATA DIVISION.
FILE SECTION.
FD ACCT-FILE.
01 ACCT-REC PIC X(100).
WORKING-STORAGE SECTION.
01 WS-BUF PIC X(100).
PROCEDURE DIVISION.
MAIN.
"""

# FD whose record name breaks the convention (real-world shape:
# record and file share no suffix relationship).
UNCONVENTIONAL = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
ENVIRONMENT DIVISION.
FILE-CONTROL.
SELECT IDX-FILE ASSIGN TO "IDX.DAT"
    ORGANIZATION IS INDEXED.
DATA DIVISION.
FILE SECTION.
FD IDX-FILE.
01 IDX-DATA PIC X(100).
WORKING-STORAGE SECTION.
01 WS-BUF PIC X(100).
PROCEDURE DIVISION.
MAIN.
"""


def _parse(header: str, proc: str) -> tuple[CobolParser, list]:
    parser = CobolParser()
    program = parser.parse(header + proc + "    STOP RUN.\n")
    statements = [s for para in program.paragraphs for s in para.statements]
    return parser, statements


class TestRewriteBindsTheFdOwnerFile:
    def test_conventional_record_binds_fd_file(self):
        _, statements = _parse(
            CONVENTIONAL, "    REWRITE ACCT-REC FROM WS-BUF.\n"
        )
        rewrites = [s for s in statements if isinstance(s, RewriteStatement)]
        assert len(rewrites) == 1
        assert rewrites[0].file_name == "ACCT-FILE"

    def test_unconventional_record_binds_fd_file(self):
        """The BL-070 defect: the heuristic yields "IDX-DATA" (no change),
        while the FD owner map says "IDX-FILE"."""
        _, statements = _parse(
            UNCONVENTIONAL, "    REWRITE IDX-DATA FROM WS-BUF.\n"
        )
        rewrites = [s for s in statements if isinstance(s, RewriteStatement)]
        assert len(rewrites) == 1
        assert rewrites[0].file_name == "IDX-FILE"

    def test_undeclared_record_keeps_heuristic_fallback(self):
        """No FD declares the record: the -REC/-FILE fallback (both verbs)."""
        header = CONVENTIONAL.replace(
            "FD ACCT-FILE.\n01 ACCT-REC PIC X(100).\n", ""
        )
        _, statements = _parse(header, "    REWRITE ACCT-REC FROM WS-BUF.\n")
        rewrites = [s for s in statements if isinstance(s, RewriteStatement)]
        assert len(rewrites) == 1
        assert rewrites[0].file_name == "ACCT-FILE"


class TestRewriteAndWriteAgree:
    """The cross-verb invariant: same FD, same binding, both verbs."""

    def test_both_verbs_bind_the_same_file_unconventional(self):
        _, statements = _parse(
            UNCONVENTIONAL,
            "    WRITE IDX-DATA FROM WS-BUF.\n"
            "    REWRITE IDX-DATA FROM WS-BUF.\n",
        )
        write = [s for s in statements if isinstance(s, WriteStatement)]
        rewrite = [s for s in statements if isinstance(s, RewriteStatement)]
        assert len(write) == 1 and len(rewrite) == 1
        assert write[0].file_name == "IDX-FILE"
        assert rewrite[0].file_name == write[0].file_name

    def test_both_verbs_bind_the_same_file_conventional(self):
        _, statements = _parse(
            CONVENTIONAL,
            "    WRITE ACCT-REC FROM WS-BUF.\n"
            "    REWRITE ACCT-REC FROM WS-BUF.\n",
        )
        write = [s for s in statements if isinstance(s, WriteStatement)]
        rewrite = [s for s in statements if isinstance(s, RewriteStatement)]
        assert write[0].file_name == "ACCT-FILE"
        assert rewrite[0].file_name == write[0].file_name

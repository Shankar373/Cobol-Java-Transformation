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

    def test_undeclared_record_is_refused_not_guessed(self):
        """G-14: no FD declares the record -> no owner, a named error.

        The former ``-REC`` -> ``-FILE`` fallback is gone: a naming
        convention is not a semantic relationship.
        """
        header = CONVENTIONAL.replace(
            "FD ACCT-FILE.\n01 ACCT-REC PIC X(100).\n", ""
        )
        for verb in ("REWRITE", "WRITE"):
            parser, statements = _parse(header, f"    {verb} ACCT-REC FROM WS-BUF.\n")
            stmt = [s for s in statements if isinstance(s, (RewriteStatement, WriteStatement))]
            assert len(stmt) == 1 and stmt[0].file_name == ""
            assert any(
                e.code.name == "UNDEFINED_FILE" and "ACCT-REC" in e.message
                for e in parser.diagnostics.errors
            ), verb


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


TWO_FDS_SAME_RECORD = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
ENVIRONMENT DIVISION.
FILE-CONTROL.
SELECT A-FILE ASSIGN TO "A.DAT".
SELECT B-FILE ASSIGN TO "B.DAT".
DATA DIVISION.
FILE SECTION.
FD A-FILE.
01 SHARED-REC PIC X(10).
FD B-FILE.
01 SHARED-REC PIC X(10).
WORKING-STORAGE SECTION.
01 WS-BUF PIC X(10).
PROCEDURE DIVISION.
MAIN.
"""

MULTI_RECORD_FD = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
ENVIRONMENT DIVISION.
FILE-CONTROL.
SELECT MASTER ASSIGN TO "M.DAT".
DATA DIVISION.
FILE SECTION.
FD MASTER.
01 HEADER-LINE PIC X(10).
01 DETAIL-LINE PIC X(10).
WORKING-STORAGE SECTION.
01 WS-BUF PIC X(10).
PROCEDURE DIVISION.
MAIN.
"""


class TestOwnershipIsAFileSectionFact:
    def test_record_declared_under_two_fds_is_ambiguous_and_refused(self):
        for verb in ("WRITE", "REWRITE"):
            parser, statements = _parse(TWO_FDS_SAME_RECORD, f"    {verb} SHARED-REC FROM WS-BUF.\n")
            stmt = [s for s in statements if isinstance(s, (RewriteStatement, WriteStatement))][0]
            assert stmt.file_name == ""
            assert any(
                "ambiguous" in e.message and "A-FILE" in e.message and "B-FILE" in e.message
                for e in parser.diagnostics.errors
            ), verb

    def test_every_01_of_a_multi_record_fd_binds_to_that_fd(self):
        _, statements = _parse(
            MULTI_RECORD_FD,
            "    WRITE HEADER-LINE FROM WS-BUF.\n    WRITE DETAIL-LINE FROM WS-BUF.\n",
        )
        writes = [s for s in statements if isinstance(s, WriteStatement)]
        assert [w.file_name for w in writes] == ["MASTER", "MASTER"]

    def test_read_takes_its_record_from_the_fd_not_from_the_file_name(self):
        from engine.transformation.ir import ReadStatement

        parser, statements = _parse(UNCONVENTIONAL, "    READ IDX-FILE.\n")
        read = [s for s in statements if isinstance(s, ReadStatement)][0]
        assert read.record_name == "IDX-DATA"  # never "IDX-REC"
        assert not parser.diagnostics.errors

    def test_read_of_a_file_with_no_fd_is_refused(self):
        from engine.transformation.ir import ReadStatement

        header = UNCONVENTIONAL.replace("FD IDX-FILE.\n01 IDX-DATA PIC X(100).\n", "")
        parser, statements = _parse(header, "    READ IDX-FILE.\n")
        read = [s for s in statements if isinstance(s, ReadStatement)][0]
        assert read.record_name == ""
        assert any(e.code.name == "UNDEFINED_FILE" and "IDX-FILE" in e.message
                   for e in parser.diagnostics.errors)

    def test_valid_conventional_program_still_parses_without_errors(self):
        parser, _ = _parse(
            CONVENTIONAL, "    WRITE ACCT-REC FROM WS-BUF.\n    READ ACCT-FILE.\n"
        )
        assert not parser.diagnostics.errors


THREE_RECORD_FD = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
ENVIRONMENT DIVISION.
FILE-CONTROL.
SELECT IN-F ASSIGN TO "I.DAT".
DATA DIVISION.
FILE SECTION.
FD IN-F.
01 REC-A PIC X(5).
01 REC-B PIC X(5).
01 REC-C PIC X(5).
WORKING-STORAGE SECTION.
01 WS-BUF PIC X(5).
PROCEDURE DIVISION.
MAIN.
"""

THREE_FDS_SAME_RECORD = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
ENVIRONMENT DIVISION.
FILE-CONTROL.
SELECT A ASSIGN TO "A.DAT".
SELECT B ASSIGN TO "B.DAT".
SELECT C ASSIGN TO "C.DAT".
DATA DIVISION.
FILE SECTION.
FD A.
01 REC PIC X(5).
FD B.
01 REC PIC X(5).
FD C.
01 REC PIC X(5).
WORKING-STORAGE SECTION.
01 WS-BUF PIC X(5).
PROCEDURE DIVISION.
MAIN.
"""

UNRELATED_NAMES = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
ENVIRONMENT DIVISION.
FILE-CONTROL.
SELECT A ASSIGN TO "A.DAT".
SELECT B ASSIGN TO "B.DAT".
DATA DIVISION.
FILE SECTION.
FD A.
01 REC-XREF PIC X(5).
FD B.
01 REC-OF-FOO PIC X(5).
WORKING-STORAGE SECTION.
01 WS-BUF PIC X(5).
PROCEDURE DIVISION.
MAIN.
"""


class TestReviewFindings:
    def test_read_binds_the_fds_buffer_record_not_a_middle_01(self):
        from engine.transformation.ir import ReadStatement

        parser, statements = _parse(THREE_RECORD_FD, "    READ IN-F.\n")
        read = [s for s in statements if isinstance(s, ReadStatement)][0]
        assert read.record_name == "REC-C"  # the FD's record_name, as everywhere else
        assert not parser.diagnostics.errors

    def test_every_01_of_a_three_record_fd_is_an_owner_key(self):
        _, statements = _parse(
            THREE_RECORD_FD,
            "    WRITE REC-A FROM WS-BUF.\n    WRITE REC-B FROM WS-BUF.\n    WRITE REC-C FROM WS-BUF.\n",
        )
        assert [s.file_name for s in statements if isinstance(s, WriteStatement)] == ["IN-F"] * 3

    def test_a_record_declared_under_three_fds_is_ambiguous(self):
        parser, statements = _parse(THREE_FDS_SAME_RECORD, "    WRITE REC FROM WS-BUF.\n")
        write = [s for s in statements if isinstance(s, WriteStatement)][0]
        assert write.file_name == ""
        assert any("ambiguous" in e.message and all(f in e.message for f in ("A", "B", "C"))
                   for e in parser.diagnostics.errors)

    def test_unrelated_names_sharing_a_prefix_do_not_cause_a_false_ambiguity_message(self):
        parser, statements = _parse(UNRELATED_NAMES, "    WRITE REC FROM WS-BUF.\n")
        write = [s for s in statements if isinstance(s, WriteStatement)][0]
        assert write.file_name == ""
        errors = [e.message for e in parser.diagnostics.errors]
        assert any("no FD in the FILE SECTION declares this record" in m for m in errors)
        assert not any("ambiguous" in m for m in errors)

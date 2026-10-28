"""Nested COPY materialization — copybooks that COPY other copybooks (BL-031).

A ``COPY`` statement *inside a copybook* is a real COBOL dependency.  Before
BL-031 the materialization lane parsed only each copybook's own data lines:
``parse_data_description_lines`` ignores the nested ``COPY`` line, the nested
declarations never reached the merged program IR, and generation still
reported ``success=True`` while emitting Java that referenced fields that
were never declared (plan READY, capability SUPPORTED, zero diagnostics).

These tests pin the corrected contract:

* nested (and deeply nested) COPY content is materialized at the COPY
  statement's position, in the merged program IR *and* in the generated Java;
* a missing, ambiguous or cyclic nested COPY fails generation with an
  explicit diagnostic naming the parent copybook (fail-closed, no silent
  drop, no unbounded recursion);
* comment lines inside copybooks are never expanded;
* COBOL sources on disk are never modified.

The tests are dependency-free (stdlib + engine only) so the file is wired
into the fast ``capability-truth`` gate in ``.github/workflows/ci.yml``.
"""
from __future__ import annotations

import re
from pathlib import Path

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.copybook_model import prepare_application_copybooks

HEADER = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {pid}.\n"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _prepare(root: Path):
    app = ApplicationDiscovery().discover(root, application_id="nested-copybook")
    return app, prepare_application_copybooks(app, source_root=root)


def _generate(root: Path, entry: str) -> dict[str, str]:
    app = ApplicationDiscovery().discover(root, application_id="nested-copybook")
    result = ApplicationGenerator().generate(app, entrypoint=entry, source_root=root)
    sources = {
        str(getattr(g, "filename", "")): str(getattr(g, "source_code", ""))
        for g in result.generated_files
    }
    sources["<success>"] = "1" if result.success else "0"
    sources["<errors>"] = "\n".join(result.errors)
    return sources


def _merged_names(prep) -> list[str]:
    program = prep.application.programs[0].program
    return [item.name for item in program.working_storage]


# ---------------------------------------------------------------------------
# 1. Nested COPY is materialized (the BL-031 defect, pre-fix: silent drop)
# ---------------------------------------------------------------------------


class TestNestedCopyMaterialized:
    def _root(self, tmp_path: Path) -> Path:
        root = tmp_path / "app"
        _write(root, "OUTER.cpy",
               "       01  OUTER-FIELD PIC X(10).\n"
               "           COPY INNER.\n")
        _write(root, "INNER.cpy",
               "       01  INNER-FIELD PIC X(4).\n")
        _write(root, "NESTMAIN.cob", HEADER.format(pid="NESTMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "           DISPLAY INNER-FIELD.\n"
            "           STOP RUN.\n"))
        return root

    def test_nested_copybook_fields_materialized_into_program_ir(self, tmp_path):
        root = self._root(tmp_path)
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        names = _merged_names(prep)
        assert "OUTER-FIELD" in names
        assert "INNER-FIELD" in names, (
            "nested COPY INNER declarations must reach the merged program IR")

    def test_generation_declares_every_copybook_field_it_references(self, tmp_path):
        root = self._root(tmp_path)
        sources = _generate(root, "NESTMAIN")
        assert sources["<success>"] == "1", sources["<errors>"]
        program_src = sources["Nestmain.java"]
        assert re.search(r"\bstatic\s+String\s+INNER_FIELD\b", program_src), (
            "generated Java must declare INNER_FIELD before referencing it:\n"
            + program_src)

    def test_deeply_nested_copy_is_materialized(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "LEVEL1.cpy",
               "       01  L1-FIELD PIC X(2).\n           COPY LEVEL2.\n")
        _write(root, "LEVEL2.cpy",
               "       01  L2-FIELD PIC X(2).\n           COPY LEVEL3.\n")
        _write(root, "LEVEL3.cpy",
               "       01  L3-FIELD PIC X(2).\n")
        _write(root, "DEEPMAIN.cob", HEADER.format(pid="DEEPMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY LEVEL1.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        names = _merged_names(prep)
        assert {"L1-FIELD", "L2-FIELD", "L3-FIELD"} <= set(names), names

    def test_nested_copy_inside_group_keeps_its_position(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "OUTER.cpy",
               "       01  OUTER-REC.\n"
               "           05  O-A PIC X(2).\n"
               "               COPY INNER.\n"
               "           05  O-B PIC X(3).\n")
        _write(root, "INNER.cpy",
               "           05  I-MID PIC X(4).\n")
        _write(root, "GMAIN.cob", HEADER.format(pid="GMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        rec = _merged_names(prep)[0]
        program = prep.application.programs[0].program
        group = next(i for i in program.working_storage if i.name == rec)
        assert [c.name for c in group.children] == ["O-A", "I-MID", "O-B"], (
            "nested content must merge at the COPY statement's position")


# ---------------------------------------------------------------------------
# 2. Fail-closed handling: missing / ambiguous / cyclic nested COPY
# ---------------------------------------------------------------------------


class TestNestedCopyFailClosed:
    def test_missing_nested_copy_fails_generation_with_parent_named(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "OUTER.cpy",
               "       01  OUTER-FIELD PIC X(10).\n           COPY NO-SUCH-INNER.\n")
        _write(root, "MMAIN.cob", HEADER.format(pid="MMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)
        assert prep.has_errors, "missing nested COPY must fail closed"
        messages = " ".join(prep.error_messages())
        assert "NO-SUCH-INNER" in messages
        assert "OUTER" in messages, (
            "the diagnostic must name the copybook that contains the COPY: "
            + messages)
        sources = _generate(root, "MMAIN")
        assert sources["<success>"] == "0"
        assert "NO-SUCH-INNER" in sources["<errors>"]

    def test_cyclic_copy_fails_closed_and_terminates(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "CICA.cpy",
               "       01  CA-FLD PIC X(2).\n           COPY CICB.\n")
        _write(root, "CICB.cpy",
               "       01  CB-FLD PIC X(2).\n           COPY CICA.\n")
        _write(root, "CYCMAIN.cob", HEADER.format(pid="CYCMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY CICA.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)  # must terminate: cycle detection, not recursion
        assert prep.has_errors, "cyclic COPY must fail closed"
        messages = " ".join(prep.error_messages())
        assert "Cyclic COPY reference" in messages
        assert "CICA" in messages and "CICB" in messages, messages
        sources = _generate(root, "CYCMAIN")
        assert sources["<success>"] == "0"
        assert "Cyclic COPY reference" in sources["<errors>"]

    def test_self_referencing_copybook_fails_closed(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "SELF.cpy",
               "       01  SELF-FLD PIC X(2).\n           COPY SELF.\n")
        _write(root, "SMAIN.cob", HEADER.format(pid="SMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY SELF.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)
        assert prep.has_errors, "self COPY must fail closed"
        assert "Cyclic COPY reference" in " ".join(prep.error_messages())


# ---------------------------------------------------------------------------
# 3. No phantom expansion, no source mutation
# ---------------------------------------------------------------------------


class TestNestedCopyNoPhantomAndNoMutation:
    def test_comment_line_inside_copybook_is_not_expanded(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "OUTER.cpy",
               "       01  OUTER-FIELD PIC X(10).\n"
               "      *    COPY NOT-A-REAL-BOOK.\n")
        _write(root, "CMAIN.cob", HEADER.format(pid="CMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        messages = " ".join(prep.error_messages())
        assert "NOT-A-REAL-BOOK" not in messages
        sources = _generate(root, "CMAIN")
        assert sources["<success>"] == "1", sources["<errors>"]

    def test_copybook_sources_are_never_modified(self, tmp_path):
        root = tmp_path / "app"
        outer = "       01  OUTER-FIELD PIC X(10).\n           COPY INNER.\n"
        inner = "       01  INNER-FIELD PIC X(4).\n"
        _write(root, "OUTER.cpy", outer)
        _write(root, "INNER.cpy", inner)
        _write(root, "NMMAIN.cob", HEADER.format(pid="NMMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _prepare(root)
        _generate(root, "NMMAIN")
        assert (root / "OUTER.cpy").read_text(encoding="utf-8") == outer
        assert (root / "INNER.cpy").read_text(encoding="utf-8") == inner


# ---------------------------------------------------------------------------
# 4. Fixed format and masking edge cases (statement-position guard)
# ---------------------------------------------------------------------------


class TestNestedCopyFormatRobustness:
    def test_fixed_format_sequence_numbers_do_not_block_expansion(self, tmp_path):
        """6-column sequence numbers precede every line in fixed-format
        sources; the statement-position guard must treat them as part of the
        sequence field, not as statement text (BL-031 hardening)."""
        root = tmp_path / "app"
        _write(root, "OUTER.cpy",
               "000100 01  OUTER-FIELD PIC X(10).\n"
               "000200*    COPY NOT-A-REAL-BOOK.\n"
               "000300     COPY INNER.\n")
        _write(root, "INNER.cpy",
               "000100 01  INNER-FIELD PIC X(4).\n")
        _write(root, "FFMAIN.cob", HEADER.format(pid="FFMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        names = _merged_names(prep)
        assert "OUTER-FIELD" in names
        assert "INNER-FIELD" in names, (
            "sequence-numbered fixed-format COPY must still expand: " + str(names))
        assert "NOT-A-REAL-BOOK" not in " ".join(prep.error_messages())

    def test_inline_comment_marker_inside_value_literal_is_data(self, tmp_path):
        """``VALUE "*>"`` contains the inline-comment marker; masking must be
        quote-aware so the literal is data and the COPY after it still
        expands (BL-031 hardening)."""
        root = tmp_path / "app"
        _write(root, "OUTER.cpy",
               "       01  OUTER-FIELD PIC X(2) VALUE \"*>\".\n"
               "           COPY INNER.\n")
        _write(root, "INNER.cpy",
               "       01  INNER-FIELD PIC X(4).\n")
        _write(root, "QMAIN.cob", HEADER.format(pid="QMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        names = _merged_names(prep)
        assert "OUTER-FIELD" in names
        assert "INNER-FIELD" in names, names

    def test_copy_token_inside_value_literal_is_not_a_dependency(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "OUTER.cpy",
               "       01  OUTER-FIELD PIC X(20) VALUE \"DO NOT COPY THIS\".\n")
        _write(root, "LMAIN.cob", HEADER.format(pid="LMAIN") + (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "           COPY OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        assert "THIS" not in " ".join(prep.error_messages())

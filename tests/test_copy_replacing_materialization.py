"""COPY ... REPLACING materialization (BL-032).

``COPY x REPLACING ==&TAG-NAME== BY ==WS-NAME== …`` is the standard
mechanism for parameterized copybooks.  Before BL-032 the expansion
consumed the clause span but never applied it: pseudo-text names are not
valid data-names, so the copybook's entries parsed to nothing and the
program silently lost every declaration while generation reported
``success=True`` (plan READY, capability SUPPORTED) — the same §53.9/§60
counterexample shape BL-031 fixed for nested COPY.

These tests pin the corrected contract:

* supported operand forms (pseudo-text ``==…==`` pairs, word operands,
  multiple pairs, multi-line clauses, case-insensitive) substitute before
  data parsing and the substituted field names appear in the merged
  program IR *and* in the generated Java;
* quoted literals are data — a tag inside ``'...'``/``"..."`` is never
  substituted;
* clause forms the lane does not implement (``LEADING``/``TRAILING``/
  ``PARTIAL`` phrases, ``+``/``-`` prefixed operands, literal operands)
  and malformed clauses fail generation with an explicit diagnostic
  naming ``REPLACING`` — never applied partially, never silently dropped;
* capability classifies a program whose clause cannot be applied as
  UNSUPPORTED (never SUPPORTED over an unapplied clause);
* nested COPY statements inside copybooks carry their own clause;
* COBOL sources are never modified.

The tests are dependency-free (stdlib + engine only) so the file is wired
into the fast ``capability-truth`` gate in ``.github/workflows/ci.yml``.
"""
from __future__ import annotations

import re
from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.copybook_model import prepare_application_copybooks

HEADER = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {pid}.\n"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _prepare(root: Path):
    app = ApplicationDiscovery().discover(root, application_id="replacing")
    return app, prepare_application_copybooks(app, source_root=root)


def _generate(root: Path, entry: str) -> dict[str, str]:
    app = ApplicationDiscovery().discover(root, application_id="replacing")
    prep = prepare_application_copybooks(app, source_root=root)
    result = ApplicationGenerator().generate(
        prep.application, entrypoint=entry, source_root=root)
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


def _main_program(pid: str, copy_stmt: str, body: str = "") -> str:
    return HEADER.format(pid=pid) + (
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{copy_stmt}"
        "       PROCEDURE DIVISION.\n"
        f"{body}"
        "           STOP RUN.\n")


# ---------------------------------------------------------------------------
# 1. Supported operand forms substitute (the BL-032 defect, pre-fix: silent)
# ---------------------------------------------------------------------------


class TestReplacingSubstitution:
    def _root(self, tmp_path: Path) -> Path:
        root = tmp_path / "app"
        _write(root, "REPL.cpy", "       01  &WS-NAME PIC X(&WS-LEN).\n")
        _write(root, "RMAIN.cob", _main_program(
            "RMAIN",
            "           COPY REPL REPLACING ==&WS-NAME== BY ==WS-TOKEN==\n"
            "                                ==&WS-LEN==  BY ==8==.\n",
            "           DISPLAY WS-TOKEN.\n"))
        return root

    def test_replacing_substitutes_tags_in_merged_ir(self, tmp_path):
        root = self._root(tmp_path)
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        names = _merged_names(prep)
        assert names == ["WS-TOKEN"], (
            "pseudo-text names must be substituted before data parsing: "
            + str(names))

    def test_substituted_field_is_declared_in_generated_java(self, tmp_path):
        root = self._root(tmp_path)
        sources = _generate(root, "RMAIN")
        assert sources["<success>"] == "1", sources["<errors>"]
        program_src = sources["Rmain.java"]
        assert re.search(r"\bstatic\s+String\s+WS_TOKEN\b", program_src), (
            "generated Java must declare WS_TOKEN (pre-fix it was referenced "
            "but never declared):\n" + program_src)
        assert "WS-NAME" not in program_src, (
            "unsubstituted pseudo-text must never reach generated source")

    def test_multiple_pairs_and_length_substitution(self, tmp_path):
        root = self._root(tmp_path)
        _, prep = _prepare(root)
        program = prep.application.programs[0].program
        item = program.working_storage[0]
        assert item.pic_length == 8, (
            "the ==&WS-LEN== BY ==8== pair must substitute the PIC length")

    def test_clause_spanning_multiple_lines(self, tmp_path):
        root = self._root(tmp_path)
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        assert "WS-TOKEN" in _merged_names(prep)

    def test_word_operands_substitute(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "WOPER.cpy", "       01  WS-OLD PIC X(4).\n")
        _write(root, "WMAIN.cob", _main_program(
            "WMAIN",
            "           COPY WOPER REPLACING WS-OLD BY WS-NEW.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        assert _merged_names(prep) == ["WS-NEW"]

    def test_substitution_is_case_insensitive(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "CI.cpy", "       01  &tag-name PIC X(3).\n")
        _write(root, "CIMAIN.cob", _main_program(
            "CIMAIN",
            "           COPY CI REPLACING ==&TAG-NAME== BY ==WS-CI==.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        assert _merged_names(prep) == ["WS-CI"]

    def test_tag_inside_quoted_literal_is_data_not_substituted(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "LIT.cpy",
               '       01  WS-LIT PIC X(10) VALUE "&WS-NAME".\n')
        _write(root, "LITMAIN.cob", _main_program(
            "LITMAIN",
            "           COPY LIT REPLACING ==&WS-NAME== BY ==WS-REAL==.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        program = prep.application.programs[0].program
        item = program.working_storage[0]
        assert item.name == "WS-LIT"
        assert item.value == '"&WS-NAME"', (
            "a tag inside a quoted VALUE literal is data, never substituted")

    def test_word_boundary_prevents_partial_substitution(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "WB.cpy", "       01  &WS-A PIC X(2).\n"
                               "       01  &WS-AB PIC X(2).\n")
        _write(root, "WBMAIN.cob", _main_program(
            "WBMAIN",
            "           COPY WB REPLACING ==&WS-A== BY ==WS-ONE==.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        names = _merged_names(prep)
        assert "WS-ONE" in names, names
        # Without the word-boundary guard the longer word would become
        # WS-ONEB (partial substitution).  The unsubstituted &WS-AB line
        # is not a valid data-name and the parser drops it — so the pin
        # is the absence of any partially-substituted name.
        assert "WS-ONEB" not in names, (
            "a longer word sharing the pattern prefix must not be partially "
            "substituted: " + str(names))
        assert names == ["WS-ONE"], names


# ---------------------------------------------------------------------------
# 2. Fail-closed: unsupported phrase forms and malformed clauses
# ---------------------------------------------------------------------------


class TestReplacingFailClosed:
    def _expect_failure(self, tmp_path, clause: str, needle: str) -> None:
        root = tmp_path / "app"
        _write(root, "U.cpy", "       01  WS-U PIC X(2).\n")
        _write(root, "UMAIN.cob", _main_program(
            "UMAIN", f"           COPY U REPLACING {clause}.\n"))
        _, prep = _prepare(root)
        assert prep.has_errors, (
            f"clause {clause!r} must fail closed, preparation succeeded")
        messages = " ".join(prep.error_messages())
        assert "REPLACING" in messages, messages
        assert needle in messages, messages
        sources = _generate(root, "UMAIN")
        assert sources["<success>"] == "0"
        assert "REPLACING" in sources["<errors>"]

    def test_leading_phrase_fails_closed(self, tmp_path):
        self._expect_failure(
            tmp_path, "LEADING ==&A== BY ==B==", "LEADING")

    def test_trailing_phrase_fails_closed(self, tmp_path):
        self._expect_failure(
            tmp_path, "TRAILING ==&A== BY ==B==", "TRAILING")

    def test_partial_phrase_fails_closed(self, tmp_path):
        self._expect_failure(
            tmp_path, "PARTIAL ==&A== BY ==B==", "PARTIAL")

    def test_prefixed_operand_fails_closed(self, tmp_path):
        self._expect_failure(
            tmp_path, "+&A BY +&B", "prefixed operand")

    def test_literal_operand_fails_closed(self, tmp_path):
        self._expect_failure(
            tmp_path, "'ABC' BY 'DEF'", "literal")

    def test_unterminated_pseudo_text_fails_closed(self, tmp_path):
        # No second == anywhere: the pseudo-text operand never closes.
        self._expect_failure(
            tmp_path, "==&A BY", "not terminated")

    def test_missing_by_fails_closed(self, tmp_path):
        self._expect_failure(
            tmp_path, "==&A== ==", "missing the BY")

    def test_empty_clause_fails_closed(self, tmp_path):
        self._expect_failure(tmp_path, "", "no operand pairs")


# ---------------------------------------------------------------------------
# 3. Capability truth: an unapplied clause is never SUPPORTED
# ---------------------------------------------------------------------------


class TestReplacingCapabilityTruth:
    def test_capability_is_unsupported_for_unapplied_clause(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "U.cpy", "       01  WS-U PIC X(2).\n")
        _write(root, "UMAIN.cob", _main_program(
            "UMAIN", "           COPY U REPLACING LEADING ==&A== BY ==B==.\n"))
        app = ApplicationDiscovery().discover(root, application_id="cap")
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        program = next(
            c for c in report.components
            if c.component_id == "UMAIN" and c.component_type == "PROGRAM"
        )
        assert program.level.name == "UNSUPPORTED", (
            "a program whose REPLACING is never applied must not classify "
            f"SUPPORTED: {program.level} ({program.reason})")
        assert "REPLACING" in program.reason, program.reason

    def test_capability_unchanged_for_applied_clause(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "R.cpy", "       01  &WS-NAME PIC X(4).\n")
        _write(root, "RMAIN2.cob", _main_program(
            "RMAIN2",
            "           COPY R REPLACING ==&WS-NAME== BY ==WS-OK==.\n"))
        app = ApplicationDiscovery().discover(root, application_id="cap2")
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        program = next(
            c for c in report.components
            if c.component_id == "RMAIN2" and c.component_type == "PROGRAM"
        )
        assert program.level.name == "SUPPORTED", (
            "an applied (well-formed) clause preserves semantics and must "
            f"not be flagged: {program.level} ({program.reason})")
        assert "REPLACING" not in program.reason, program.reason


# ---------------------------------------------------------------------------
# 4. Nested clauses, shared-model bound, no source mutation
# ---------------------------------------------------------------------------


class TestReplacingNestedAndContracts:
    def test_nested_copy_inside_copybook_carries_its_own_clause(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "OUTER.cpy",
               "       01  OUTER-FLD PIC X(2).\n"
               "           COPY INNER REPLACING ==&TAG== BY ==WS-INNER==\n"
               "                                  ==&LEN== BY ==3==.\n")
        _write(root, "INNER.cpy", "       01  &TAG PIC X(&LEN).\n")
        _write(root, "NMAIN.cob", _main_program(
            "NMAIN", "           COPY OUTER.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        names = _merged_names(prep)
        assert "WS-INNER" in names, names
        assert "&TAG" not in " ".join(names), names
        program = prep.application.programs[0].program
        inner = next(i for i in program.working_storage if i.name == "WS-INNER")
        assert inner.pic_length == 3, (
            "the nested clause's ==&LEN== BY ==3== pair must substitute "
            f"the PIC length: {inner.pic_length}")

    def test_outer_clause_reaches_nested_body(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "OUTER2.cpy", "           COPY INNER2.\n")
        _write(root, "INNER2.cpy", "       01  &DEEP PIC X(3).\n")
        _write(root, "N2MAIN.cob", _main_program(
            "N2MAIN",
            "           COPY OUTER2 REPLACING ==&DEEP== BY ==WS-DEEP==.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        assert "WS-DEEP" in _merged_names(prep), (
            "the caller's clause applies to the fully-expanded text, "
            "nested targets included (documented BL-032 semantics)")

    def test_no_shared_model_plan_for_clause_parameterized_copybook(
        self, tmp_path
    ):
        root = tmp_path / "app"
        _write(root, "R.cpy", "       01  &WS-NAME PIC X(4).\n")
        _write(root, "RMAIN3.cob", _main_program(
            "RMAIN3",
            "           COPY R REPLACING ==&WS-NAME== BY ==WS-OK==.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        assert prep.plans == (), (
            "substituted content is program-specific: no shared model plan "
            f"may be registered for it: {prep.plans}")

    def test_copybook_sources_are_never_modified(self, tmp_path):
        root = tmp_path / "app"
        repl = "       01  &WS-NAME PIC X(&WS-LEN).\n"
        _write(root, "R.cpy", repl)
        _write(root, "RMAIN4.cob", _main_program(
            "RMAIN4",
            "           COPY R REPLACING ==&WS-NAME== BY ==WS-TOKEN==\n"
            "                                ==&WS-LEN==  BY ==8==.\n"))
        _prepare(root)
        _generate(root, "RMAIN4")
        assert (root / "R.cpy").read_text(encoding="utf-8") == repl

    def test_plain_copy_without_clause_is_unchanged(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "P.cpy", "       01  WS-PLAIN PIC X(5).\n")
        _write(root, "PMAIN.cob", _main_program(
            "PMAIN", "           COPY P.\n"))
        _, prep = _prepare(root)
        assert not prep.has_errors, prep.error_messages()
        assert _merged_names(prep) == ["WS-PLAIN"]
        assert [p.copybook_name for p in prep.plans] == ["P"], (
            "clause-free copybooks keep their shared model plan")

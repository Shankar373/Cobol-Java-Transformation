"""Layer 7 L7-P2: every Layer 5 note kind/code has a documented disposition in the capability analyzer.

Unit (the closed disposition table), mutation (forged notes on a plain program: a floor is applied, never lifted), adversarial
(unknown code, unattributable note, JCL refusal, reordered notes) and end-to-end (a real parser refusal reaches the report with
its provenance).
"""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path

import pytest

from engine.application_ir.consume import ir_for_application
from engine.application_ir.model import IRNote
from engine.modernization import ir_unsupported
from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.semantic_facts.references import UNSUPPORTED_USE_CODES
from engine.transformation.application_discovery import ApplicationDiscovery

L = CapabilityLevel
SRC = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P1.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
       "       01 A PIC 9(4).\n       PROCEDURE DIVISION.\n       R.\n           MOVE 1 TO A.\n           STOP RUN.\n")


def _setup(tmp_path: Path, source: str = SRC):
    (tmp_path / "P1.cob").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    return app, ir_for_application(app, tmp_path)


def _with_notes(ir, *notes):
    return dataclasses.replace(ir, notes=ir.notes + tuple(notes))


def _note(ir, kind, code, subject="", note_id="forged:1"):
    return IRNote(note_id, kind, subject or f"diag:{ir.programs[0].file}:{code}:line 1", code, None, note_id, ())


def _p1(app, ir, tmp_path):
    report = CapabilityAnalyzer(docker_available=True).analyze(app, tmp_path, ir=ir)
    return report, next(c for c in report.components if c.component_type == "PROGRAM")


def test_a_refusal_note_floors_its_program_at_unsupported(tmp_path):
    app, ir = _setup(tmp_path)
    _, comp = _p1(app, _with_notes(ir, _note(ir, "refusal", "ANY_CODE")), tmp_path)
    assert comp.level is L.UNSUPPORTED and comp.details["ir_provenance"] == "forged:1"


@pytest.mark.parametrize("code", sorted(UNSUPPORTED_USE_CODES))
def test_every_layer5_unsupported_use_code_has_a_disposition(code):
    assert code in ir_unsupported.UNSUPPORTED_NOTE_FLOORS


@pytest.mark.parametrize("code", ["STATEMENT_PARTLY_PARSED", "OPERAND_UNPARSED", "INSPECT_OPERAND_KIND_UNKNOWN",
                                  "GOTO_TARGET_UNPARSED"])
def test_a_partly_read_statement_is_never_supported(tmp_path, code):
    app, ir = _setup(tmp_path)
    _, comp = _p1(app, _with_notes(ir, _note(ir, "unsupported", code, f"stmt:program:P1/R/1")), tmp_path)
    assert comp.level is L.PARTIAL and code in comp.reason


def test_the_documented_non_blocking_codes_leave_the_level_alone(tmp_path):
    app, ir = _setup(tmp_path)
    forged = _with_notes(ir, _note(ir, "unsupported", "CONDITION_UNSTRUCTURED", "stmt:program:P1/R/1", "f:1"),
                         _note(ir, "unsupported", "COPYBOOK_NOT_EXPANDED", f"copy:{ir.programs[0].file}:X", "f:2"),
                         _note(ir, "diagnostic", "PARTIAL_SUPPORT", note_id="f:3"),
                         _note(ir, "cancel", "x", note_id="f:4"))
    _, comp = _p1(app, forged, tmp_path)
    assert comp.level is L.SUPPORTED and "ir_provenance" not in comp.details


def test_an_unknown_unsupported_code_fails_closed_to_unknown(tmp_path):
    app, ir = _setup(tmp_path)
    _, comp = _p1(app, _with_notes(ir, _note(ir, "unsupported", "SOME_FUTURE_CODE", "stmt:program:P1/R/1")), tmp_path)
    assert comp.level is L.UNKNOWN


def test_an_unmodelled_compiler_option_is_partial_and_a_modelled_one_is_not(tmp_path):
    app, ir = _setup(tmp_path)
    _, bad = _p1(app, _with_notes(ir, _note(ir, "option", "COMPILER_OPTION_UNMODELLED", f"option:{ir.programs[0].file}:X")), tmp_path)
    _, ok = _p1(app, _with_notes(ir, _note(ir, "option", "ok", f"option:{ir.programs[0].file}:Y")), tmp_path)
    assert bad.level is L.PARTIAL and ok.level is L.SUPPORTED


def test_a_note_that_names_no_program_is_an_application_level_finding(tmp_path):
    app, ir = _setup(tmp_path)
    report, _ = _p1(app, _with_notes(ir, _note(ir, "refusal", "X", "diag:ELSEWHERE.cob:X:line 1")), tmp_path)
    finding = next(c for c in report.components if c.component_id == "IR-NOTES")
    assert finding.level is L.UNSUPPORTED and report.overall_level is L.UNSUPPORTED


def test_a_jcl_refusal_is_not_a_capability_component(tmp_path):
    app, ir = _setup(tmp_path)
    report, comp = _p1(app, _with_notes(ir, _note(ir, "refusal", "JCL_FLAVOUR_UNSUPPORTED", "jcl:JOB.jcl")), tmp_path)
    assert comp.level is L.SUPPORTED and not any(c.component_id == "IR-NOTES" for c in report.components)


def test_a_note_never_lifts_a_level(tmp_path):
    app, ir = _setup(tmp_path, SRC.replace("MOVE 1 TO A.", "ENTRY 'X'.\n           MOVE 1 TO A."))
    base = _p1(app, ir, tmp_path)[1].level
    lifted = _p1(app, _with_notes(ir, _note(ir, "diagnostic", "PARTIAL_SUPPORT")), tmp_path)[1].level
    assert lifted is base


def test_note_order_does_not_change_the_report(tmp_path):
    app, ir = _setup(tmp_path)
    notes = [_note(ir, "unsupported", "OPERAND_UNPARSED", "stmt:program:P1/R/1", f"n:{i}") for i in range(6)]
    notes.append(_note(ir, "refusal", "X", note_id="n:r"))
    reports = []
    for seed in range(4):
        shuffled = notes[:]
        random.Random(seed).shuffle(shuffled)
        report, comp = _p1(app, dataclasses.replace(ir, notes=ir.notes + tuple(shuffled)), tmp_path)
        reports.append((report.to_dict(), comp.details["ir_provenance"], comp.reason))
    assert all(r == reports[0] for r in reports)


def test_a_real_parser_refusal_reaches_the_report_with_its_provenance(tmp_path):
    twice = SRC.replace("       PROCEDURE", "       WORKING-STORAGE SECTION.\n       01 B PIC 9.\n       PROCEDURE")
    app, ir = _setup(tmp_path, twice)
    assert any(n.kind == "refusal" for n in ir.notes)
    report, comp = _p1(app, ir, tmp_path)
    refusal_ids = {n.provenance for n in ir.notes if n.kind == "refusal"}
    assert comp.level is L.UNSUPPORTED and refusal_ids <= set(comp.details["ir_provenance"].split(","))
    assert report.overall_level is L.UNSUPPORTED


def test_without_an_ir_notes_are_not_consulted(tmp_path):
    app, ir = _setup(tmp_path)
    report = CapabilityAnalyzer(docker_available=True).analyze(app, tmp_path)
    assert report.overall_level is L.SUPPORTED


def test_a_note_kind_outside_the_vocabulary_fails_closed(tmp_path):
    app, ir = _setup(tmp_path)
    assert ir_unsupported.note_floor("weird", "X") is L.UNKNOWN
    report, _ = _p1(app, _with_notes(ir, _note(ir, "weird", "X", "")), tmp_path)
    assert report.overall_level is not L.SUPPORTED


def test_empty_and_odd_note_fields_neither_crash_nor_pass(tmp_path):
    app, ir = _setup(tmp_path)
    odd = IRNote("", "unsupported", "", "", None, "", ())
    report, _ = _p1(app, _with_notes(ir, odd), tmp_path)
    assert report.overall_level is L.UNKNOWN


@pytest.mark.parametrize("mutation", ["refusal_ignored", "unknown_code_passes"])
def test_weakening_the_note_rules_is_detected(tmp_path, monkeypatch, mutation):
    app, ir = _setup(tmp_path)
    forged = _with_notes(ir, _note(ir, "refusal", "X", note_id="m:1"),
                         _note(ir, "unsupported", "NEW_CODE", "stmt:program:P1/R/1", "m:2"))
    original = ir_unsupported.note_floor
    if mutation == "refusal_ignored":
        monkeypatch.setattr(ir_unsupported, "note_floor", lambda k, c: None if k == "refusal" else original(k, c))
        expected_at_least = L.UNKNOWN          # the unknown code alone still blocks
    else:
        monkeypatch.setattr(ir_unsupported, "note_floor", lambda k, c: None if k == "unsupported" else original(k, c))
        expected_at_least = L.UNSUPPORTED      # the refusal alone still blocks
    _, comp = _p1(app, forged, tmp_path)
    assert comp.level is expected_at_least

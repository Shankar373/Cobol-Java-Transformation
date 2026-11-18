"""Structural pass: sections/paragraphs, data descriptions, control flow, file verbs, data flow, COPY REPLACING.

The pass is tested at its own level (:func:`scan_structure`) and through the scanner that turns its findings into
``Ref`` objects, so a wiring mistake is as visible as a parsing mistake.
"""

from __future__ import annotations

import pytest

from enterprise.discovery.cobol_structure import (SUPPORTED_REPLACING_FORMS, UNSUPPORTED_REPLACING_FORMS,
                                                  parse_replacing, scan_structure)
from enterprise.discovery.cobol_text import logical_lines, tokenize
from enterprise.discovery.scan_cobol import scan_cobol
from tests.discovery.helpers import _fixed


def structure(text: str, path: str = "p.cbl", copybook: bool = False):
    _fmt, lines, _directives = logical_lines(text)
    return scan_structure(tokenize(lines), path=path, copybook=copybook)


def unit_names(scan, kind: str) -> list[str]:
    return [u.name for u in scan.units if u.kind == kind]


def flows(scan, relation: str):
    return [f for f in scan.refs if f.relation == relation]


def refs(scan, relation: str | None = None, kind: str | None = None):
    return [r for r in scan.refs if (relation is None or r.relation == relation)
            and (kind is None or r.target_kind == kind)]


# --- sections and paragraphs -----------------------------------------------------------------------------


def test_sections_and_paragraphs_are_only_recognised_in_a_procedure_division() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                  "WORKING-STORAGE SECTION.", "01 A PIC X.", "PROCEDURE DIVISION.",
                  "MAIN SECTION.", "MAIN-PARA.", "    GOBACK.")
    scan = structure(text)
    assert unit_names(scan, "section") == ["MAIN"]
    assert unit_names(scan, "paragraph") == ["MAIN-PARA"]
    assert [u.program for u in scan.units] == ["P", "P"]


def test_a_copybook_with_no_procedure_division_contributes_data_only() -> None:
    scan = structure(_fixed("01 REC-AREA.", "    05 F1 PIC X."), path="cpy/REC.cpy", copybook=True)
    assert scan.units == [] and [(d.kind, d.name) for d in scan.data] == [("record-layout", "REC-AREA"),
                                                                         ("data-item", "F1")]


def test_data_descriptions_are_scoped_to_the_declaring_owner() -> None:
    scan = structure(_fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                            "WORKING-STORAGE SECTION.", "01 WS-REC.", "    05 WS-ID PIC X(8).",
                            "77 WS-TOTAL PIC S9(9)."))
    assert [(d.kind, d.name, d.owner) for d in scan.data] == [
        ("record-layout", "WS-REC", "program:P"), ("data-item", "WS-ID", "program:P"),
        ("data-item", "WS-TOTAL", "program:P")]


def test_a_screen_section_makes_its_fields_screen_fields() -> None:
    scan = structure(_fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                            "SCREEN SECTION.", "01 SCR-1.", "    05 SCR-FLD PIC X(10)."))
    assert [(d.kind, d.name) for d in scan.data] == [("record-layout", "SCR-1"), ("screen-field", "SCR-FLD")]


def test_a_level_number_that_is_not_a_data_level_is_reported_not_guessed() -> None:
    scan = structure(_fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                            "    99 NOT-A-LEVEL PIC X."))
    assert [(code) for _line, code, _message in scan.problems] == ["DATA_DECL_LEVEL_UNKNOWN"]


def test_an_unknown_level_outside_the_data_division_is_not_reported() -> None:
    scan = structure(_fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                            "    99 NOT-A-LEVEL."))
    assert scan.problems == []


# --- control flow ----------------------------------------------------------------------------------------


def test_perform_targets_are_paragraph_references_with_exact_positions() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", "    PERFORM STEP-1.", "    PERFORM STEP-2 THRU STEP-3.", "    GOBACK.",
                  "STEP-1.", "    EXIT.", "STEP-2.", "    EXIT.", "STEP-3.", "    EXIT.")
    scan = structure(text)
    performs = flows(scan, "performs")
    assert [(f.target, f.line, f.clause) for f in performs] == [("STEP-1", 5, "PERFORM"),
                                                                ("STEP-2", 6, "PERFORM"),
                                                                ("STEP-3", 6, "PERFORM THRU")]
    assert dict(performs[1].detail)["thru"] == "STEP-3"


def test_performed_paragraphs_resolve_against_the_programs_own_declarations() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", "    PERFORM STEP-1.", "    GOBACK.", "STEP-1.", "    EXIT.")
    scan = scan_cobol("p.cbl", text)
    edge_refs = refs(scan, "performs", "paragraph")
    assert [(r.target, r.owner, r.line) for r in edge_refs] == [("STEP-1", "program:P", 5)]


def test_perform_n_times_is_a_count_and_never_a_paragraph_reference() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                  "WORKING-STORAGE SECTION.", "01 WS-COUNT PIC 9(4).", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", "    PERFORM WS-COUNT TIMES.", "    PERFORM 5 TIMES.", "    GOBACK.")
    scan = structure(text)
    assert flows(scan, "performs") == []


def test_an_inline_perform_until_has_no_paragraph_target() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", "    PERFORM UNTIL WS-EOF", "        ADD 1 TO WS-I",
                  "    END-PERFORM.", "    GOBACK.")
    assert flows(structure(text), "performs") == []


def test_go_to_is_a_static_transfer_and_go_to_a_data_item_is_dynamic() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                  "WORKING-STORAGE SECTION.", "01 WS-PARA PIC X(8).", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", "    GO TO NEXT-PARA.", "    GO TO WS-PARA.", "    GOBACK.",
                  "NEXT-PARA.", "    EXIT.")
    scan = structure(text)
    goto = flows(scan, "goes-to")
    assert [(g.target, g.dynamic, g.variable, g.line) for g in goto] == [("NEXT-PARA", False, "", 8),
                                                                         ("", True, "WS-PARA", 9)]


def test_control_flow_is_not_emitted_outside_a_procedure_division() -> None:
    scan = structure(_fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                            "WORKING-STORAGE SECTION.", "01 A PIC X.", "PERFORM B."))
    assert flows(scan, "performs") == []


# --- file verbs ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("statement, relation, mode", [
    ("READ EMP-FILE INTO WS-REC.", "reads-file", "read"),
    ("WRITE RPT-REC FROM WS-REC.", "writes-file", "write"),
    ("REWRITE EMP-REC FROM WS-REC.", "rewrites-file", "update"),
])
def test_file_verbs_carry_the_relation_the_mode_and_the_line(statement: str, relation: str, mode: str) -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", f"    {statement}", "    GOBACK.")
    scan = structure(text)
    found = flows(scan, relation)
    assert len(found) == 1 and found[0].mode == mode and found[0].line == 5
    assert found[0].target_kind == "logical-file" and found[0].column > 1


# --- intra-program data flow -----------------------------------------------------------------------------


def test_move_arithmetic_and_conditions_reference_declared_data_items() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                  "WORKING-STORAGE SECTION.", "01 WS-SRC PIC X(8).", "01 WS-DST PIC X(8).",
                  "77 WS-I PIC 9(4).", "77 WS-TOTAL PIC 9(6).", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", "    MOVE WS-SRC TO WS-DST.", "    ADD 1 TO WS-TOTAL.",
                  "    IF WS-DST = 'X' GOBACK.", "    GOBACK.")
    scan = structure(text)
    assert [(f.target, f.mode) for f in flows(scan, "moves-to")] == [("WS-DST", "write")]
    assert [(f.target, f.mode, f.clause) for f in flows(scan, "writes-item")] == [("WS-TOTAL", "write", "ADD")]
    assert [(f.target, f.mode) for f in flows(scan, "reads-item")] == [("WS-DST", "read")]


def test_data_flow_never_follows_a_name_the_file_does_not_describe() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                  "WORKING-STORAGE SECTION.", "01 WS-DST PIC X(8).", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", "    MOVE NOT-DECLARED TO WS-DST.", "    GOBACK.")
    scan = structure(text)
    assert flows(scan, "moves-to") == [] and flows(scan, "reads-item") == []


def test_a_copybook_name_is_not_re_emitted_as_a_data_flow_reference() -> None:
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                  "WORKING-STORAGE SECTION.", "    COPY REC.", "PROCEDURE DIVISION.",
                  "MAIN-PARA.", "    MOVE WS-ID TO WS-OUT.", "    GOBACK.")
    assert flows(structure(text), "moves-to") == []


# --- COPY REPLACING --------------------------------------------------------------------------------------


def test_replacing_pairs_are_recorded_in_source_order() -> None:
    _fmt, lines, _d = logical_lines(_fixed("COPY TALLY REPLACING ==A== BY ==B== C BY D."))
    tokens = tokenize(lines)
    pairs, unsupported = parse_replacing(tokens, 0, len(tokens))
    assert pairs == [("A", "B"), ("C", "D")] and unsupported == []


def test_replacing_records_pseudo_text_words_and_literals() -> None:
    _fmt, lines, _d = logical_lines(_fixed("COPY TALLY REPLACING ==A B== BY ==C D== E BY F BY 'G' BY 'H'."))
    tokens = tokenize(lines)
    pairs, unsupported = parse_replacing(tokens, 0, len(tokens))
    assert pairs == [("A B", "C D"), ("E", "F"), ("'G'", "'H'")]
    assert unsupported == []


def test_leading_trailing_and_partial_replacing_are_refused_by_name() -> None:
    for form in UNSUPPORTED_REPLACING_FORMS:
        _fmt, lines, _d = logical_lines(_fixed(f"COPY TALLY REPLACING {form} ==A== BY ==B==."))
        tokens = tokenize(lines)
        _pairs, unsupported = parse_replacing(tokens, 0, len(tokens))
        assert form in unsupported, form
    assert SUPPORTED_REPLACING_FORMS == ("BY",)


def test_an_unpaired_pseudo_text_operand_is_refused_not_guessed() -> None:
    _fmt, lines, _d = logical_lines(_fixed("COPY TALLY REPLACING ==A== BY."))
    tokens = tokenize(lines)
    pairs, unsupported = parse_replacing(tokens, 0, len(tokens))
    assert "UNPAIRED-PSEUDO-TEXT" in unsupported and pairs == []


def test_a_copy_without_replacing_produces_no_pairs() -> None:
    _fmt, lines, _d = logical_lines(_fixed("COPY TALLY."))
    tokens = tokenize(lines)
    assert parse_replacing(tokens, 0, len(tokens)) == ([], [])


def test_replacing_is_reported_on_the_copy_reference_through_the_scanner() -> None:
    scan = scan_cobol("p.cbl", _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                                      "    COPY TALLY REPLACING ==OLD-NAME== BY ==NEW-NAME==.", "    GOBACK."))
    copy_ref = refs(scan, "copies")[0]
    assert dict(copy_ref.detail)["replacing_pairs"] == "OLD-NAME BY NEW-NAME"
    assert dict(copy_ref.detail)["replacing_count"] == "1"


def test_an_unsupported_replacing_form_is_a_named_problem_not_a_silent_expansion() -> None:
    scan = scan_cobol("p.cbl", _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "PROCEDURE DIVISION.",
                                      "    COPY TALLY REPLACING LEADING ==OLD-NAME== BY ==NEW-NAME==.",
                                      "    GOBACK."))
    assert "COPY_REPLACING_UNSUPPORTED" in {p.code for p in scan.problems}

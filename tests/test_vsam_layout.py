"""ADR-0009: record layouts are derived from the COBOL record description, or refused by name.

Byte sizes follow the documented storage rules (DOCUMENTED_SEMANTICS evidence - no GnuCOBOL or
IBM run in this repository proves a byte layout).  The binary width model is an explicit option
with no default.  Anything the rules do not cover is a named diagnostic, never an approximation.
Dependency-free (pytest only).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.copybook_model import prepare_application_copybooks
from engine.vsam.convert import FieldKind, convert_dataset, validate_layout
from engine.vsam.layout import BinaryWidthModel, RecordLayout, derive_file_layout, derive_layout
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization

IBM = BinaryWidthModel.IBM_2_4_8
GNU = BinaryWidthModel.GNUCOBOL_1_2_4_8


def fd_source(*record_lines: str) -> str:
    body = "\n".join("       " + line for line in record_lines)
    header = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. T.",
        "       ENVIRONMENT DIVISION.",
        "       INPUT-OUTPUT SECTION.",
        "       FILE-CONTROL.",
        '           SELECT F ASSIGN TO "F.DAT".',
        "       DATA DIVISION.",
        "       FILE SECTION.",
        "       FD F.",
    ]
    footer = ["       PROCEDURE DIVISION.", "       MAIN-PARA.", "           STOP RUN."]
    return "\n".join(header) + "\n" + body + "\n" + "\n".join(footer) + "\n"


def layout_for(*record_lines: str, model=IBM, selection=None, record_name="") -> RecordLayout:
    program = CobolParser().parse(fd_source(*record_lines))
    return derive_file_layout(program.file_definitions[0], binary_width_model=model,
                              overlay_selection=selection, record_name=record_name)


def codes(layout: RecordLayout) -> list[str]:
    return [d.code for d in layout.diagnostics]


def spans(layout: RecordLayout) -> list[tuple[str, int, int, str]]:
    return [(f.path, f.offset, f.length, f.kind.value) for f in layout.fields]


# --- DISPLAY fields -----------------------------------------------------------------------------

def test_alphanumeric_and_numeric_display_fields_get_exact_offsets_and_lengths():
    layout = layout_for("01 REC.", "   05 ID PIC 9(5).", "   05 NAME PIC X(10).", "   05 AMT PIC S9(3).")
    assert layout.supported and layout.record_length == 18
    assert spans(layout) == [("REC.ID", 0, 5, "DISPLAY"), ("REC.NAME", 5, 10, "DISPLAY"), ("REC.AMT", 15, 3, "DISPLAY")]


def test_scaled_decimal_stores_every_digit_and_no_decimal_point():
    layout = layout_for("01 REC.", "   05 PRICE PIC 9(5)V99.", "   05 DELTA PIC S9V9(3).")
    assert [(f.offset, f.length) for f in layout.fields] == [(0, 7), (7, 4)]


@pytest.mark.parametrize("clause,length", [("SIGN IS LEADING", 5), ("SIGN IS TRAILING", 5),
                                           ("SIGN IS LEADING SEPARATE", 6), ("SIGN IS TRAILING SEPARATE CHARACTER", 6)])
def test_sign_separate_adds_one_byte_and_inline_signs_add_none(clause, length):
    layout = layout_for("01 REC.", f"   05 AMT PIC S9(5) {clause}.")
    assert layout.fields[0].length == length and layout.record_length == length


def test_filler_is_an_explicit_display_field_and_keeps_the_record_covered():
    layout = layout_for("01 REC.", "   05 A PIC X(4).", "   05 FILLER PIC X(6).", "   05 B PIC X(2).")
    assert layout.record_length == 12
    assert [(f.offset, f.length) for f in layout.fields] == [(0, 4), (4, 6), (10, 2)]
    assert validate_layout(layout.field_specs(), layout.record_length) == ()


def test_an_elementary_01_record_is_one_field():
    layout = layout_for("01 REC PIC X(20).")
    assert layout.record_length == 20 and spans(layout) == [("REC", 0, 20, "DISPLAY")]


def test_numeric_edited_items_are_character_fields_of_their_edited_width():
    record = CobolParser().parse_data_description_lines(
        ["       01 REC.", "          05 SHOWN PIC ZZ,ZZ9.99."])[0]
    layout = derive_layout(record, binary_width_model=IBM)
    assert layout.fields[0].length == 9 and layout.fields[0].kind is FieldKind.DISPLAY


def test_a_numeric_edited_picture_inside_an_fd_is_refused_by_the_parser():
    from engine.transformation.cobol_parser import CobolParseError

    with pytest.raises(CobolParseError, match="Unsupported PIC"):
        CobolParser().parse(fd_source("01 REC.", "   05 SHOWN PIC ZZ,ZZ9.99."))


# --- COMP-3 and binary --------------------------------------------------------------------------------

@pytest.mark.parametrize("digits,length", [(1, 1), (2, 2), (3, 2), (4, 3), (7, 4), (9, 5), (18, 10)])
def test_comp3_length_is_digits_div_2_plus_1_and_the_field_is_packed(digits, length):
    layout = layout_for("01 REC.", f"   05 AMT PIC S9({digits}) COMP-3.")
    assert layout.fields[0].length == length and layout.fields[0].kind is FieldKind.PACKED


def test_comp3_counts_decimal_digits():
    assert layout_for("01 REC.", "   05 AMT PIC S9(7)V99 COMP-3.").fields[0].length == 5


@pytest.mark.parametrize("digits,ibm,gnu", [
    (1, 2, 1), (2, 2, 1), (3, 2, 2), (4, 2, 2), (5, 4, 4), (9, 4, 4), (10, 8, 8), (18, 8, 8),
])
def test_binary_width_depends_on_the_explicit_model(digits, ibm, gnu):
    for model, expected in ((IBM, ibm), (GNU, gnu)):
        for usage in ("COMP", "COMP-5", "BINARY"):
            layout = layout_for("01 REC.", f"   05 N PIC S9({digits}) {usage}.", model=model)
            assert layout.fields[0].length == expected and layout.fields[0].kind is FieldKind.BINARY, (model, usage)


def test_more_than_eighteen_binary_digits_is_refused():
    assert "BINARY_TOO_WIDE" in codes(layout_for("01 REC.", "   05 N PIC S9(19) COMP."))


def test_the_binary_width_model_is_required_and_has_no_default():
    program = CobolParser().parse(fd_source("01 REC.", "   05 N PIC S9(4) COMP."))
    with pytest.raises(TypeError):
        derive_file_layout(program.file_definitions[0])          # type: ignore[call-arg]
    with pytest.raises(ValueError):
        derive_file_layout(program.file_definitions[0], binary_width_model="whatever")  # type: ignore[arg-type]


def test_the_model_changes_the_layout_and_therefore_its_identity():
    a = layout_for("01 REC.", "   05 N PIC S9(2) COMP.", "   05 T PIC X(3).", model=IBM)
    b = layout_for("01 REC.", "   05 N PIC S9(2) COMP.", "   05 T PIC X(3).", model=GNU)
    assert a.record_length == 5 and b.record_length == 4 and a.identity != b.identity


# --- fixed OCCURS ----------------------------------------------------------------------------------------

def test_a_fixed_occurs_group_is_expanded_element_by_element():
    layout = layout_for("01 REC.", "   05 CODE PIC X(2).", "   05 ITEM OCCURS 3 TIMES.",
                        "      10 SKU PIC X(4).", "      10 QTY PIC 9(2).")
    assert layout.supported and layout.record_length == 2 + 3 * 6
    assert [(f.path, f.offset, f.length) for f in layout.fields] == [
        ("REC.CODE", 0, 2),
        ("REC.ITEM(1).SKU", 2, 4), ("REC.ITEM(1).QTY", 6, 2),
        ("REC.ITEM(2).SKU", 8, 4), ("REC.ITEM(2).QTY", 12, 2),
        ("REC.ITEM(3).SKU", 14, 4), ("REC.ITEM(3).QTY", 18, 2),
    ]


def test_an_elementary_occurs_item_is_repeated():
    layout = layout_for("01 REC.", "   05 DIGITS PIC 9 OCCURS 4 TIMES.")
    assert [(f.path, f.offset, f.length) for f in layout.fields] == [
        (f"REC.DIGITS({i})", i - 1, 1) for i in range(1, 5)]


def test_nested_fixed_occurs_multiplies_and_names_every_subscript():
    layout = layout_for("01 REC.", "   05 ROW OCCURS 2 TIMES.", "      10 CELL PIC X(3) OCCURS 3 TIMES.")
    assert layout.record_length == 18
    assert [f.path for f in layout.fields][:4] == ["REC.ROW(1).CELL(1)", "REC.ROW(1).CELL(2)",
                                                    "REC.ROW(1).CELL(3)", "REC.ROW(2).CELL(1)"]
    assert [f.offset for f in layout.fields] == [0, 3, 6, 9, 12, 15]


def test_occurs_depending_on_is_refused_and_never_sized_by_a_guess():
    layout = layout_for("01 REC.", "   05 CNT PIC 9(2).", "   05 ROW PIC X(4) OCCURS 1 TO 9 TIMES DEPENDING ON CNT.")
    assert "OCCURS_DEPENDING_ON" in codes(layout) and not layout.supported


# --- REDEFINES ------------------------------------------------------------------------------------------------

REDEF = ("01 REC.", "   05 DATE-NUM PIC 9(8).", "   05 DATE-PARTS REDEFINES DATE-NUM.",
         "      10 YY PIC 9(4).", "      10 MM PIC 9(2).", "      10 DD PIC 9(2).", "   05 TAIL PIC X(2).")


def test_a_redefines_without_a_selection_is_refused_not_resolved_by_declaration_order():
    layout = layout_for(*REDEF)
    assert "OVERLAY_UNSELECTED" in codes(layout) and not layout.supported
    message = next(d.message for d in layout.diagnostics if d.code == "OVERLAY_UNSELECTED")
    assert "DATE-NUM" in message and "DATE-PARTS" in message          # names every alternative


@pytest.mark.parametrize("chosen,expected", [
    ("DATE-NUM", [("REC.DATE-NUM", 0, 8), ("REC.TAIL", 8, 2)]),
    ("DATE-PARTS", [("REC.DATE-PARTS.YY", 0, 4), ("REC.DATE-PARTS.MM", 4, 2),
                    ("REC.DATE-PARTS.DD", 6, 2), ("REC.TAIL", 8, 2)]),
])
def test_an_explicit_selection_emits_only_that_alternative_over_the_shared_bytes(chosen, expected):
    layout = layout_for(*REDEF, selection={"DATE-NUM": chosen})
    assert layout.supported and layout.record_length == 10
    assert [(f.path, f.offset, f.length) for f in layout.fields] == expected
    assert validate_layout(layout.field_specs(), layout.record_length) == ()


def test_the_selection_is_part_of_the_layout_identity():
    a = layout_for(*REDEF, selection={"DATE-NUM": "DATE-NUM"})
    b = layout_for(*REDEF, selection={"DATE-NUM": "DATE-PARTS"})
    assert a.identity != b.identity


def test_an_unknown_selection_is_refused():
    assert "OVERLAY_SELECTION_INVALID" in codes(layout_for(*REDEF, selection={"DATE-NUM": "NOT-AN-ALTERNATIVE"}))


def test_a_selection_for_something_that_is_not_redefined_is_refused():
    assert "OVERLAY_SELECTION_INVALID" in codes(layout_for("01 REC.", "   05 A PIC X(4).", selection={"A": "A"}))


def test_a_selected_alternative_that_does_not_cover_the_redefined_area_is_refused():
    layout = layout_for("01 REC.", "   05 WIDE PIC X(8).", "   05 NARROW REDEFINES WIDE PIC X(3).",
                        selection={"WIDE": "NARROW"})
    assert "OVERLAY_PARTIAL_COVER" in codes(layout)


def test_a_redefining_item_longer_than_the_redefined_one_is_refused():
    layout = layout_for("01 REC.", "   05 SHORT PIC X(3).", "   05 LONG REDEFINES SHORT PIC X(8).",
                        selection={"SHORT": "LONG"})
    assert "REDEFINES_LONGER" in codes(layout)


def test_a_redefines_of_an_unknown_item_is_refused():
    assert "REDEFINES_TARGET" in codes(layout_for("01 REC.", "   05 A REDEFINES NOWHERE PIC X(4)."))


# --- unsupported features are named ---------------------------------------------------------------------------------

@pytest.mark.parametrize("entry,code", [
    ("05 F PIC S9(4) COMP SYNC.", "SYNCHRONIZED"),
    ("05 F COMP-1.", "FLOATING_POINT"),
    ("05 F COMP-2.", "FLOATING_POINT"),
    ("05 F PIC S9(4) COMP-3 SIGN IS LEADING SEPARATE.", "SIGN_SEPARATE_USAGE"),
])
def test_unsupported_storage_features_are_refused_with_a_named_diagnostic(entry, code):
    layout = layout_for("01 REC.", "   " + entry)
    assert code in codes(layout) and not layout.supported
    with pytest.raises(ValueError):
        layout.field_specs()                       # an unsupported layout can never drive a conversion


def test_every_refusal_carries_the_cobol_path_of_the_offending_item():
    layout = layout_for("01 REC.", "   05 GRP.", "      10 BAD PIC S9(4) COMP SYNC.")
    assert layout.diagnostics[0].path == "REC.GRP.BAD"


# --- records of a file ---------------------------------------------------------------------------------------------------

TWO_RECORDS = ("01 HEADER-REC.", "   05 H PIC X(4).", "01 DETAIL-REC.", "   05 D PIC X(9).")


def test_an_fd_with_several_records_requires_a_choice_and_never_takes_the_first():
    layout = layout_for(*TWO_RECORDS)
    assert "RECORD_AMBIGUOUS" in codes(layout) and not layout.supported
    chosen = layout_for(*TWO_RECORDS, record_name="DETAIL-REC")
    assert chosen.supported and chosen.record_name == "DETAIL-REC" and chosen.record_length == 9


def test_an_unknown_record_name_is_refused():
    assert "RECORD_UNKNOWN" in codes(layout_for(*TWO_RECORDS, record_name="NOPE"))


def test_a_copy_inside_an_fd_now_reaches_the_same_layout_as_the_inline_fd():
    """G-26: the FILE SECTION COPY is expanded before parsing, so the FD has its record."""
    record = "       01 CUST-REC.\n          05 CUST-ID PIC 9(5).\n          05 CUST-NAME PIC X(10).\n"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "REC.cpy").write_text(record, encoding="utf-8")
        (d / "p.cob").write_text(fd_source("COPY REC."), encoding="utf-8")
        program = ApplicationDiscovery().discover(d).programs[0].program
        layout = derive_file_layout(program.file_definitions[0], binary_width_model=IBM)
    inline = layout_for("01 CUST-REC.", "   05 CUST-ID PIC 9(5).", "   05 CUST-NAME PIC X(10).")
    assert layout.supported and layout.record_length == 15
    assert layout.identity == inline.identity


def test_an_fd_whose_copybook_cannot_be_resolved_still_has_no_record_and_is_refused_by_name():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "p.cob").write_text(fd_source("COPY NOSUCH."), encoding="utf-8")
        unit = ApplicationDiscovery().discover(d).programs[0]
        layout = derive_file_layout(unit.program.file_definitions[0], binary_width_model=IBM)
    assert "FD_NO_RECORD" in codes(layout) and not layout.supported
    assert any(x.startswith("COPYBOOK_UNRESOLVED") for x in unit.parse_diagnostics)


def test_a_materialised_working_storage_copybook_record_can_be_passed_explicitly():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "REC.cpy").write_text("       01 CUST-REC.\n          05 CUST-ID PIC 9(5).\n"
                                   "          05 CUST-NAME PIC X(10).\n", encoding="utf-8")
        source = fd_source("01 DUMMY PIC X.").replace("       PROCEDURE DIVISION.", "       WORKING-STORAGE SECTION.\n       COPY REC.\n       PROCEDURE DIVISION.")
        (d / "p.cob").write_text(source, encoding="utf-8")
        app = ApplicationDiscovery().discover(d)
        materialised = prepare_application_copybooks(app, source_root=d).application.programs[0].program
        record = next(i for i in materialised.working_storage if i.name == "CUST-REC")
    layout = derive_layout(record, binary_width_model=IBM)
    assert layout.supported and layout.record_length == 15
    assert [f.path for f in layout.fields] == ["CUST-REC.CUST-ID", "CUST-REC.CUST-NAME"]


# --- identity, provenance, determinism ---------------------------------------------------------------------------------------

def test_fields_carry_provenance_and_the_layout_a_stable_identity():
    layout = layout_for("01 REC.", "   05 GRP.", "      10 A PIC X(3).")
    field = layout.fields[0]
    assert (field.path, field.level, field.source) == ("REC.GRP.A", 10, "A")
    again = layout_for("01 REC.", "   05 GRP.", "      10 A PIC X(3).")
    assert layout.identity == again.identity and len(layout.identity) == 64
    assert json.dumps(layout.to_dict(), sort_keys=True) == json.dumps(again.to_dict(), sort_keys=True)
    assert layout.to_dict()["binary_width_model"] == "IBM_2_4_8"


def test_a_changed_picture_changes_the_identity():
    a = layout_for("01 REC.", "   05 A PIC X(3).")
    b = layout_for("01 REC.", "   05 A PIC X(4).")
    assert a.identity != b.identity


# --- the derived layout drives the conversion --------------------------------------------------------------------------------

def test_the_derived_layout_drives_the_field_aware_conversion_in_declaration_order():
    layout = layout_for("01 REC.", "   05 ID PIC X(4).", "   05 AMT PIC S9(5) COMP-3.", "   05 CNT PIC S9(4) COMP.")
    assert layout.record_length == 4 + 3 + 2
    source = DatasetDefinition("SRC", Organization.KSDS, record_length=layout.record_length,
                               primary_key=KeyDefinition(0, 4))
    record = b"AB12" + bytes([0x12, 0x34, 0x5C]) + (7).to_bytes(2, "big")
    result = convert_dataset(source, record, layout.field_specs(), Encoding.EBCDIC_CP037)
    assert result.rejected == ()
    assert result.output[:4] == "AB12".encode("cp037") and result.output[4:] == record[4:]   # text translated, numbers untouched


def test_a_corrupt_packed_field_is_rejected_through_the_derived_layout():
    layout = layout_for("01 REC.", "   05 ID PIC X(2).", "   05 AMT PIC S9(3) COMP-3.")
    source = DatasetDefinition("SRC", Organization.SEQUENTIAL, record_length=layout.record_length)
    bad = b"AB" + bytes([0x1A, 0x3C])             # high nibble A is not a decimal digit
    result = convert_dataset(source, bad, layout.field_specs(), Encoding.EBCDIC_CP037)
    assert [r.record_number for r in result.rejected] == [1] and "non-decimal digit" in result.rejected[0].reason


def test_national_pictures_are_refused_by_the_parser_before_any_layout_exists():
    from engine.transformation.cobol_parser import CobolParseError

    with pytest.raises(CobolParseError, match="Unsupported PIC"):
        CobolParser().parse(fd_source("01 REC.", "   05 F PIC N(4)."))


# --- usage is part of the layout (COMP is big-endian, COMP-5 native byte order) ---------------------------------------------------

def test_fields_record_their_usage_and_comp_and_comp5_get_different_identities():
    comp = layout_for("01 REC.", "   05 N PIC S9(4) COMP.")
    comp5 = layout_for("01 REC.", "   05 N PIC S9(4) COMP-5.")
    packed = layout_for("01 REC.", "   05 N PIC S9(4) COMP-3.")
    plain = layout_for("01 REC.", "   05 N PIC S9(4).")
    assert [l.fields[0].usage for l in (comp, comp5, packed, plain)] == ["COMP", "COMP-5", "COMP-3", ""]
    # same size and kind, different byte-order semantics: they must not share an identity
    assert comp.fields[0].length == comp5.fields[0].length and comp.fields[0].kind is comp5.fields[0].kind
    assert comp.identity != comp5.identity
    assert comp5.to_dict()["fields"][0]["usage"] == "COMP-5"


# --- resource limits (security review): a hostile layout must be refused, not expanded ------------------------------------------

def test_a_huge_occurs_is_refused_without_expanding_it():
    import time

    started = time.monotonic()
    layout = layout_for("01 REC.", "   05 T PIC X OCCURS 99999999 TIMES.")
    assert "OCCURS_TOO_LARGE" in codes(layout) and not layout.supported and layout.fields == ()
    assert time.monotonic() - started < 5          # decided by arithmetic, not by creating 10**8 fields


def test_nested_occurs_multiplies_towards_the_limit():
    layout = layout_for("01 REC.", "   05 A OCCURS 9999 TIMES.", "      10 B PIC X OCCURS 9999 TIMES.")
    assert "OCCURS_TOO_LARGE" in codes(layout)


def test_the_field_limit_is_exact():
    from engine.vsam.layout import MAX_LAYOUT_FIELDS

    ok = layout_for("01 REC.", f"   05 T PIC X OCCURS {MAX_LAYOUT_FIELDS} TIMES.")
    assert ok.supported and len(ok.fields) == MAX_LAYOUT_FIELDS
    over = layout_for("01 REC.", f"   05 T PIC X OCCURS {MAX_LAYOUT_FIELDS + 1} TIMES.")
    assert "OCCURS_TOO_LARGE" in codes(over)


def test_a_record_longer_than_the_limit_is_refused():
    from engine.vsam.layout import MAX_RECORD_BYTES

    layout = layout_for("01 REC.", f"   05 BIG PIC X({MAX_RECORD_BYTES + 1}).")
    assert "RECORD_TOO_LARGE" in codes(layout) and not layout.supported
    assert layout_for("01 REC.", f"   05 BIG PIC X({MAX_RECORD_BYTES}).").supported


# --- independent review: group-level clauses, duplicate names, duplicate diagnostics ----------------------------------------------

@pytest.mark.parametrize("group_clause,child", [
    ("COMP-3", "10 M PIC S9(3)."),
    ("COMP", "10 M PIC S9(4)."),
    ("SIGN IS LEADING SEPARATE", "10 N PIC S9(3)."),
    ("SIGN IS TRAILING", "10 N PIC S9(3)."),
])
def test_a_usage_or_sign_clause_on_a_group_is_refused_because_children_would_inherit_it(group_clause, child):
    layout = layout_for("01 R.", f"   05 H {group_clause}.", f"      {child}")
    assert "GROUP_CLAUSE_INHERITED" in codes(layout) and not layout.supported
    assert layout.diagnostics[0].path == "R.H"


def test_the_same_clause_on_the_elementary_item_is_still_fine():
    assert layout_for("01 R.", "   05 H.", "      10 M PIC S9(3) COMP-3.").supported


def test_duplicate_filler_names_get_unique_paths_in_declaration_order():
    layout = layout_for("01 R.", "   05 FILLER PIC X(2).", "   05 A PIC X.", "   05 FILLER PIC X(3).",
                        "   05 FILLER PIC X(1).")
    assert [f.path for f in layout.fields] == ["R.FILLER", "R.A", "R.FILLER#2", "R.FILLER#3"]
    assert len({f.path for f in layout.fields}) == len(layout.fields)


def test_a_refusal_is_reported_once_not_once_per_internal_pass():
    layout = layout_for("01 R.", "   05 GRP.", "      10 BAD PIC S9(4) COMP SYNC.", "   05 OK PIC X.")
    assert [d.code for d in layout.diagnostics] == ["SYNCHRONIZED"]
    redef = layout_for("01 R.", "   05 A PIC X(8).", "   05 B REDEFINES A PIC X(3).", "   05 C REDEFINES A PIC X(8).")
    assert len({(d.code, d.path) for d in redef.diagnostics}) == len(redef.diagnostics)


# --- resource limits: the cap is checked before any field is created --------------------------------------------------------------

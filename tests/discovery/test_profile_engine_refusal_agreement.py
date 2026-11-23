"""Layer 4 residual audit: discovery's ``DialectProfile`` and the engine's named refusals fire together.

The engine does NOT read ``DialectProfile.unsupported``: it re-detects each construct with its own pre-parse
checks (``CobolParser.parse``).  Nothing structural keeps the two in step, so this file pins their agreement
over one fixture per construct and its clean variant: the profile entry and the engine ``DiagnosticCode`` must
be present together and absent together.  Every pair is mutation-sensitive (the clean variant must flip both
sides), and a finding where they disagree is pinned by a strict ``xfail`` that fails the day the disagreement
is fixed, so it cannot be forgotten.
"""

from __future__ import annotations

import hashlib

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.source_format import mixed_format_refusal
from enterprise.discovery.classify import classify
from enterprise.discovery.discover import scan_file
from enterprise.discovery.dialect_profile import DialectProfile, build_profiles
from enterprise.discovery.inventory import FileRecord

HEAD = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n"
TAIL = "       PROCEDURE DIVISION.\n           GOBACK.\n"
PLAIN = HEAD + TAIL


def _profile(text: str) -> DialectProfile:
    cls = classify("src/P.cbl", text).cls
    scan = scan_file("src/P.cbl", cls, text)
    record = FileRecord("src/P.cbl", hashlib.sha256(text.encode()).hexdigest(), len(text), cls,
                        source_format=scan.source_format if scan else "", scan=scan)
    (profile,) = build_profiles([record])
    return profile


def _engine_codes(text: str) -> set[DiagnosticCode]:
    parser = CobolParser()
    parser.parse(text)
    return {d.code for d in parser.diagnostics.all}


OO = HEAD.replace("PROGRAM-ID. P.", "CLASS-ID. FOO.") + TAIL
SCREEN = HEAD + "       DATA DIVISION.\n       SCREEN SECTION.\n       01 S.\n           05 F1 PIC X.\n" + TAIL
SCREEN_GROUP_ONLY = HEAD + "       DATA DIVISION.\n       SCREEN SECTION.\n       01 S.\n" + TAIL
VARIABLE = '       $SET SOURCEFORMAT"VARIABLE"\n' + PLAIN
UNEVALUATED = "       >>IF X = 1\n" + PLAIN + "       >>END-IF\n"
EVALUATED = "       >>DEFINE X AS 1\n       >>IF X = 1\n" + PLAIN + "       >>END-IF\n"

#: (fixture, clean variant, profile construct name, engine code)
PAIRS = {
    "oo": (OO, PLAIN, "OO_COBOL_UNSUPPORTED", DiagnosticCode.OO_COBOL_UNSUPPORTED),
    "screen": (SCREEN, PLAIN, "SCREEN_SECTION_UNSUPPORTED", DiagnosticCode.SCREEN_SECTION_UNSUPPORTED),
    "variable": (VARIABLE, PLAIN, "REFERENCE_FORMAT_VARIABLE_UNSUPPORTED",
                 DiagnosticCode.REFERENCE_FORMAT_VARIABLE_UNSUPPORTED),
    "unevaluated": (UNEVALUATED, EVALUATED, "CONDITIONAL_COMPILATION_UNEVALUATED",
                    DiagnosticCode.CONDITIONAL_COMPILATION_UNEVALUATED),
}


@pytest.mark.parametrize("key", sorted(PAIRS))
def test_profile_unsupported_and_engine_refusal_fire_together(key: str) -> None:
    refused, _clean, name, code = PAIRS[key]
    assert name in _profile(refused).unsupported
    assert code in _engine_codes(refused)
    # The engine's error is a hard refusal (fail closed), not a note.
    parser = CobolParser()
    parser.parse(refused)
    assert parser.diagnostics.has_errors


@pytest.mark.parametrize("key", sorted(PAIRS))
def test_profile_unsupported_and_engine_refusal_are_absent_together_on_the_clean_variant(key: str) -> None:
    _refused, clean, name, code = PAIRS[key]
    profile = _profile(clean)
    assert name not in profile.unsupported and profile.unsupported == ()
    assert code not in _engine_codes(clean)


def test_the_four_constructs_are_distinguished_not_a_blanket() -> None:
    """Each fixture trips exactly its own name on both sides (a blanket refusal would fail this)."""
    for key, (refused, _clean, name, code) in PAIRS.items():
        assert _profile(refused).unsupported == (name,), key
        own = {c for _k, (_t, _c, _n, c) in PAIRS.items()}
        assert _engine_codes(refused) & own == {code}, key


MIXED = HEAD + ">>SOURCE FORMAT FREE\nPROCEDURE DIVISION.\nGOBACK.\n"


def test_mixed_format_profile_value_and_engine_refusal_agree() -> None:
    """``reference_format == "mixed"`` is the profile's face of the engine's ``mixed_format_refusal`` (the oracle and
    JCL reference lanes refuse it by name; the parser itself reads each line in its own format)."""
    assert _profile(MIXED).reference_format == "mixed"
    refusal = mixed_format_refusal(MIXED, "P.cbl")
    assert refusal is not None and refusal.startswith("REFERENCE_FORMAT_MIXED_UNSUPPORTED: P.cbl:3:")
    single = ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\nPROGRAM-ID. P.\nPROCEDURE DIVISION.\nGOBACK.\n"
    assert _profile(single).reference_format == "free"
    assert mixed_format_refusal(single, "P.cbl") is None
    assert _profile(PLAIN).reference_format == "fixed" and mixed_format_refusal(PLAIN) is None
    # The parser does not refuse a mixed file: mixed is not a ``profile.unsupported`` name either.
    assert _profile(MIXED).unsupported == ()
    assert DiagnosticCode.REFERENCE_FORMAT_MIXED_UNSUPPORTED not in _engine_codes(MIXED)


def test_oracle_std_is_recorded_by_the_profile_but_read_by_no_engine_or_api_module() -> None:
    """``DialectProfile.oracle_std`` carries the dialect's ``-std`` (``default`` when undetermined) but the oracle is
    dialect-blind: no module under ``engine/`` or ``api/`` reads it, nor calls ``std_for_dialect``.  Wiring it would
    change oracle behaviour (owner decision); this pin must then be changed deliberately, not silently."""
    import re
    from pathlib import Path

    from enterprise.discovery.compilers import _STD_BY_DIALECT

    assert _profile(PLAIN).oracle_std == "default" and _profile(PLAIN).dialect == "undetermined"
    assert _STD_BY_DIALECT, "the mapping exists, so a non-default std is a real possibility"
    root = Path(__file__).resolve().parents[2]
    readers = sorted(
        str(path.relative_to(root)) for folder in ("engine", "api") for path in (root / folder).rglob("*.py")
        if re.search(r"\b(oracle_std|std_for_dialect|_STD_BY_DIALECT)\b", path.read_text(encoding="utf-8")))
    assert readers == []


def test_engine_modules_read_only_the_profile_id_never_its_fields() -> None:
    """The engine carries ``(file, profile_id)`` pairs; it never reads ``unsupported``/``reference_format``/
    ``compiler_options`` from a ``DialectProfile`` (it re-detects with its own pre-parse checks)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    field_read = re.compile(r"profile\w*\.(unsupported|reference_format|compiler_options|library_order|oracle_std"
                            r"|oracle_format|directive_state)")
    hits = sorted(
        str(path.relative_to(root)) for folder in ("engine", "api") for path in (root / folder).rglob("*.py")
        if field_read.search(path.read_text(encoding="utf-8")))
    assert hits == []


# --- finding: the engine over-refuses what the profile (correctly) does not -------------------------------------------

OBJECT_COMPUTER = (HEAD + "       ENVIRONMENT DIVISION.\n       CONFIGURATION SECTION.\n"
                   "       OBJECT-COMPUTER. IBM-370.\n" + TAIL)
OO_WORD_IN_COMMENT = HEAD + "      * the OBJECT of this program\n" + TAIL
SCREEN_WORD_IN_COMMENT = HEAD + "      * no SCREEN SECTION here\n" + TAIL


@pytest.mark.parametrize("text", [OBJECT_COMPUTER, OO_WORD_IN_COMMENT])
def test_discovery_profile_does_not_flag_standard_object_text_as_oo(text: str) -> None:
    assert _profile(text).unsupported == ()


@pytest.mark.parametrize("text", [OBJECT_COMPUTER, OO_WORD_IN_COMMENT])
def test_engine_does_not_refuse_object_computer_or_a_comment_as_oo(text: str) -> None:
    """FIXED (Layer 4 residual audit finding): the engine matched ``\\bOBJECT\\b`` on the whole text, so the standard
    OBJECT-COMPUTER paragraph and the word OBJECT in a comment were refused as object-oriented COBOL while the
    discovery profile was clean.  A COBOL word now continues across hyphens and only live program text is scanned."""
    assert DiagnosticCode.OO_COBOL_UNSUPPORTED not in _engine_codes(text)


def test_a_screen_section_mentioned_in_a_comment_is_not_a_screen_section() -> None:
    assert DiagnosticCode.SCREEN_SECTION_UNSUPPORTED not in _engine_codes(SCREEN_WORD_IN_COMMENT)
    assert _profile(SCREEN_WORD_IN_COMMENT).unsupported == ()


@pytest.mark.parametrize("marker", ["CLASS-ID. P.", "INTERFACE-ID. P.", "METHOD-ID. M.", "FACTORY.", "OBJECT."])
def test_real_oo_markers_in_live_code_are_still_refused(marker: str) -> None:
    """The narrowing must not weaken the refusal: each OO marker as a real COBOL word in live text is still named."""
    text = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n       ENVIRONMENT DIVISION.\n"
            f"       {marker}\n       PROCEDURE DIVISION.\n           GOBACK.\n")
    assert DiagnosticCode.OO_COBOL_UNSUPPORTED in _engine_codes(text)


def test_an_oo_marker_hidden_in_a_comment_or_a_literal_does_not_refuse() -> None:
    text = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n       PROCEDURE DIVISION.\n"
            "      * CLASS-ID. METHOD-ID. FACTORY. OBJECT.\n           DISPLAY 'CLASS-ID OBJECT'.\n           GOBACK.\n")
    assert DiagnosticCode.OO_COBOL_UNSUPPORTED not in _engine_codes(text)


def test_a_screen_section_without_any_field_is_refused_by_the_engine_but_not_flagged_by_the_profile() -> None:
    """Edge finding (discovery under-reports): the profile derives ``SCREEN_SECTION_UNSUPPORTED`` from ``screen-field``
    refs, so a SCREEN SECTION holding only a group item is invisible to it while the engine refuses it.  Fail-closed
    on the engine side; the profile entry is the weaker face.  Pinned as it is today, no behaviour invented."""
    assert DiagnosticCode.SCREEN_SECTION_UNSUPPORTED in _engine_codes(SCREEN_GROUP_ONLY)
    assert _profile(SCREEN_GROUP_ONLY).unsupported == ()

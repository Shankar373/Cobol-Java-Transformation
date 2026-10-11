"""STRING delimiter / WITH POINTER semantics (BL-027) — capability truth.

Before BL-027 the parser appended a literal delimiter to ``parts`` as if it
were sending *data* (``STRING A DELIMITED BY "," B ...`` emitted
``D = A + "," + B``), dropped ``WITH POINTER`` entirely, and the verdict
stayed ``SUPPORTED`` with zero diagnostics — a direct §60 counterexample
and the §53.9 blocker.  These tests lock the fix at every layer:

* IR: per-phrase ``delimiter_exprs``, ``pointer``, ``has_overflow``;
* mapper: delimiter truncation excludes the delimiter from the result,
  write-position + tail preservation, pointer clamp/advance;
* fail-closed: identifier delimiter / ON OVERFLOW / non-integer pointer
  produce an ``UNSUPPORTED_STRING$`` symbol and an UNSUPPORTED verdict
  with a diagnostic naming the construct — never a silently wrong value;
* verdict truth through the real ApplicationDiscovery + CapabilityAnalyzer
  path for SIZE, literal and SPACE delimiters.

Dependency-free on purpose: this file is part of the capability-truth
gate (``.github/workflows/ci.yml``) and must run with pytest alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_statement
from engine.transformation.ir import (
    FieldReference,
    FigurativeConstant,
    Literal,
    StringStatement,
)
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import CapabilityLevel

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

HEADER = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC X(20).
01 WS-B PIC X(20).
01 WS-D PIC X(40).
PROCEDURE DIVISION.
MAIN.
"""

# WITH POINTER needs a receiving-position item.  COMP is deliberate: the
# pointer clamp/advance arithmetic must work on an integer-typed item.
POINTER_ITEMS = "01 WS-P PIC 9(4) COMP.\n"
# Non-integer pointer item: decimal scale means the pointer arithmetic
# would not be integral, so the mapper must fail closed.
BAD_POINTER_ITEMS = "01 WS-C PIC 9(4)V99.\n"


def _program(proc: str, extra_items: str = ""):
    """Parse HEADER (+ optional extra data items) + body; return (program, parser)."""
    header = HEADER.replace(
        "PROCEDURE DIVISION.", extra_items + "PROCEDURE DIVISION."
    )
    parser = CobolParser()
    program = parser.parse(header + proc + "    STOP RUN.\n")
    return program, parser


def _string_stmt(program) -> StringStatement:
    for para in program.paragraphs:
        for stmt in para.statements:
            if isinstance(stmt, StringStatement):
                return stmt
    raise AssertionError("no StringStatement parsed")


def _mapped(proc: str, extra_items: str = ""):
    """Parse + map the single STRING statement; return (java_stmts, program)."""
    program, _ = _program(proc, extra_items)
    stmt = _string_stmt(program)
    return map_cobol_statement(stmt, program), program


def _rendered(proc: str, extra_items: str = "") -> list[str]:
    gen = JavaGenerator()
    return [gen._stmt_to_string(s) for s in _mapped(proc, extra_items)[0]]


def _verdict(source: str, tmp_path: Path) -> tuple[CapabilityLevel, str]:
    """Verdict through the real discovery + analyzer path."""
    src_dir = tmp_path / "cobol"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "tst.cbl").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(src_dir, application_id="APP")
    # docker_available=True mirrors TestPayrollFixtureRegression: with the
    # infra flag down, a finding-free program would aggregate UNAVAILABLE
    # (infrastructure) instead of its construct verdict.  No Docker call is
    # made for this program shape, so the gate stays dependency-free.
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    programs = [c for c in report.components if c.component_type == "PROGRAM"]
    assert len(programs) == 1
    return programs[0].level, programs[0].reason


def _diag_codes(parser: CobolParser) -> list[str]:
    return [d.code.name for d in parser.diagnostics.all]


# ---------------------------------------------------------------------------
# IR representation — the parser must represent every phrase's delimiter
# ---------------------------------------------------------------------------

class TestStringIRRepresentation:
    def test_literal_delimiter_is_not_a_sending_part(self):
        """The BL-027 core defect: the delimiter was appended to ``parts``."""
        program, _ = _program(
            '    STRING WS-A DELIMITED BY "," WS-B DELIMITED BY SIZE INTO WS-D.'
        )
        stmt = _string_stmt(program)
        assert stmt.parts == ("WS-A", "WS-B")
        assert stmt.target == "WS-D"
        assert len(stmt.delimiter_exprs) == 2
        assert isinstance(stmt.delimiter_exprs[0], Literal)
        assert stmt.delimiter_exprs[0].value == ","
        assert stmt.delimiter_exprs[1] is None  # SIZE

    def test_size_phrases_carry_none_delimiters(self):
        program, _ = _program(
            "    STRING WS-A DELIMITED BY SIZE WS-B DELIMITED BY SIZE INTO WS-D."
        )
        stmt = _string_stmt(program)
        assert stmt.parts == ("WS-A", "WS-B")
        assert stmt.delimiter_exprs == (None, None)

    def test_space_delimiter_is_figurative_constant(self):
        program, _ = _program("    STRING WS-A DELIMITED BY SPACE INTO WS-D.")
        stmt = _string_stmt(program)
        assert isinstance(stmt.delimiter_exprs[0], FigurativeConstant)
        assert stmt.delimiter_exprs[0].kind == "SPACE"

    def test_identifier_delimiter_is_field_reference_with_diagnostic(self):
        program, parser = _program(
            "    STRING WS-A DELIMITED BY WS-B INTO WS-D."
        )
        stmt = _string_stmt(program)
        assert isinstance(stmt.delimiter_exprs[0], FieldReference)
        assert stmt.delimiter_exprs[0].name == "WS-B"
        assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser)
        messages = [d.message for d in parser.diagnostics.all]
        assert any("DELIMITED BY identifier WS-B" in m for m in messages)

    def test_with_pointer_is_captured(self):
        program, _ = _program(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D WITH POINTER WS-P.",
            POINTER_ITEMS,
        )
        stmt = _string_stmt(program)
        assert stmt.pointer == "WS-P"

    def test_on_overflow_is_captured_with_diagnostic(self):
        program, parser = _program(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D "
            "ON OVERFLOW MOVE \"X\" TO WS-A."
        )
        stmt = _string_stmt(program)
        assert stmt.has_overflow is True
        assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser)
        messages = [d.message for d in parser.diagnostics.all]
        assert any("ON OVERFLOW" in m for m in messages)

    def test_multiline_end_string_phrases_are_joined(self):
        program, _ = _program(
            "    STRING WS-A DELIMITED BY SIZE\n"
            '       "," DELIMITED BY SIZE\n'
            "       WS-B DELIMITED BY SIZE\n"
            "       INTO WS-D\n"
            "    END-STRING"
        )
        stmt = _string_stmt(program)
        assert stmt.parts == ("WS-A", '","', "WS-B")
        assert stmt.delimiter_exprs == (None, None, None)
        assert stmt.target == "WS-D"

    def test_missing_into_fails_closed(self):
        program, parser = _program('    STRING WS-A DELIMITED BY SIZE.')
        stmt = _string_stmt(program)
        assert stmt.target == ""
        assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser)

    def test_missing_delimited_by_defaults_to_size(self):
        """Lenient legacy form (invalid but simplified COBOL): SIZE."""
        program, parser = _program('    STRING "SUBTRACT" "MULTIPLY" INTO WS-D')
        stmt = _string_stmt(program)
        assert stmt.parts == ('"SUBTRACT"', '"MULTIPLY"')
        assert stmt.delimiter_exprs == (None, None)
        assert stmt.target == "WS-D"
        assert "UNSUPPORTED_CONSTRUCT" not in _diag_codes(parser)


# ---------------------------------------------------------------------------
# Mapper / generated Java — delimiter excluded, write position, pointer
# ---------------------------------------------------------------------------

class TestStringGeneratedJava:
    def test_literal_delimiter_is_never_emitted_as_data(self):
        """BL-027: ``D = A + "," + B`` (delimiter as data) must be gone."""
        rendered = _rendered(
            '    STRING WS-A DELIMITED BY "," WS-B DELIMITED BY SIZE INTO WS-D.'
        )[0]
        assert 'indexOf(",")' in rendered
        # the delimiter appears only as the indexOf argument, never as a
        # concatenated data literal
        assert '+ "," +' not in rendered
        assert rendered.count('","') == rendered.count('indexOf(",")')
        assert "WS_D = " in rendered

    def test_size_phrases_concatenate_and_preserve_tail(self):
        rendered = _rendered(
            "    STRING WS-A DELIMITED BY SIZE WS-B DELIMITED BY SIZE INTO WS-D."
        )[0]
        # delimiter never part of the value; unwritten tail of the old
        # receiver value stays unchanged (COBOL write semantics)
        assert rendered.startswith("WS_D = WS_A + WS_B + WS_D.substring(")
        assert "Math.min(WS_D.length(), (WS_A + WS_B).length())" in rendered

    def test_space_truncates_at_first_space(self):
        rendered = _rendered(
            "    STRING WS-A DELIMITED BY SPACE INTO WS-D."
        )[0]
        # the prefix BEFORE the first space is copied, never the suffix
        assert 'WS_A.substring(0, ((WS_A.indexOf(" ") >= 0)' in rendered
        assert 'indexOf(" ")' in rendered

    def test_delimiter_absence_copies_whole_item(self):
        """indexOf == -1 must fall back to the item's length (COBOL rule)."""
        rendered = _rendered(
            '    STRING WS-A DELIMITED BY "," INTO WS-D.'
        )[0]
        assert (
            'WS_A.substring(0, ((WS_A.indexOf(",") >= 0) '
            '? WS_A.indexOf(",") : WS_A.length()))' in rendered
        )

    def test_with_pointer_clamps_inserts_and_advances(self):
        mapped = _mapped(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D WITH POINTER WS-P.",
            POINTER_ITEMS,
        )[0]
        assert len(mapped) == 3
        gen = JavaGenerator()
        clamp, assign, advance = (gen._stmt_to_string(s) for s in mapped)
        assert clamp == "WS_P = Math.max(1, WS_P);"
        assert 'String.format("%-" + (WS_P - 1) + "s", WS_D)' in assign
        assert ".substring(0, (WS_P - 1))" in assign
        assert "Math.min(" in assign
        assert advance == "WS_P = (WS_P + WS_A.length());"

    def test_overlapping_source_and_target_is_one_atomic_assignment(self):
        """D appears as source and receiver: one assignment, pre-state read."""
        mapped = _mapped(
            "    STRING WS-D DELIMITED BY SIZE WS-A DELIMITED BY SIZE INTO WS-D."
        )[0]
        assert len(mapped) == 1
        rendered = JavaGenerator()._stmt_to_string(mapped[0])
        assert rendered.count("WS_D = ") == 1
        assert "WS_D.substring(" in rendered


# ---------------------------------------------------------------------------
# Fail closed — never a silently wrong value, verdict never falsely SUPPORTED
# ---------------------------------------------------------------------------

class TestStringFailClosed:
    def test_identifier_delimiter_emits_fail_closed_symbol(self):
        rendered = _rendered(
            "    STRING WS-A DELIMITED BY WS-B INTO WS-D."
        )[0]
        assert "WS_D = UNSUPPORTED_STRING$DELIMITED_BY_IDENTIFIER_WS_B;" in rendered

    def test_on_overflow_emits_fail_closed_symbol(self):
        rendered = _rendered(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D "
            'ON OVERFLOW MOVE "X" TO WS-A.'
        )[0]
        assert "WS_D = UNSUPPORTED_STRING$OVERFLOW;" in rendered

    def test_combined_reasons_are_all_named(self):
        rendered = _rendered(
            "    STRING WS-A DELIMITED BY WS-B INTO WS-D "
            'ON OVERFLOW MOVE "X" TO WS-A.'
        )[0]
        assert (
            "WS_D = UNSUPPORTED_STRING$DELIMITED_BY_IDENTIFIER_WS_B$OVERFLOW;"
            in rendered
        )

    def test_non_integer_pointer_fails_closed(self):
        program, parser = _program(
            "    STRING WS-A DELIMITED BY SIZE INTO WS-D WITH POINTER WS-C.",
            BAD_POINTER_ITEMS,
        )
        stmt = _string_stmt(program)
        assert stmt.pointer == "WS-C"
        mapped = map_cobol_statement(stmt, program)
        rendered = JavaGenerator()._stmt_to_string(mapped[0])
        assert "UNSUPPORTED_STRING$NON_INTEGER_POINTER" in rendered


# ---------------------------------------------------------------------------
# Verdict truth — real discovery + analyzer, exact levels
# ---------------------------------------------------------------------------

class TestStringVerdicts:
    def test_size_program_is_supported(self, tmp_path: Path):
        level, _ = _verdict(
            HEADER
            + "    STRING WS-A DELIMITED BY SIZE WS-B DELIMITED BY SIZE INTO WS-D.\n"
            "    STOP RUN.\n",
            tmp_path,
        )
        assert level is CapabilityLevel.SUPPORTED

    def test_literal_delimiter_program_is_supported(self, tmp_path: Path):
        level, _ = _verdict(
            HEADER
            + '    STRING WS-A DELIMITED BY "," WS-B DELIMITED BY SIZE INTO WS-D.\n'
            "    STOP RUN.\n",
            tmp_path,
        )
        assert level is CapabilityLevel.SUPPORTED

    def test_space_delimiter_program_is_supported(self, tmp_path: Path):
        """SPACE is proven by IR (FigurativeConstant delimiter), not re-read
        from source as a source-only figurative finding."""
        level, _ = _verdict(
            HEADER + "    STRING WS-A DELIMITED BY SPACE INTO WS-D.\n    STOP RUN.\n",
            tmp_path,
        )
        assert level is CapabilityLevel.SUPPORTED

    def test_identifier_delimiter_program_is_unsupported(self, tmp_path: Path):
        level, reason = _verdict(
            HEADER
            + "    STRING WS-A DELIMITED BY WS-B INTO WS-D.\n    STOP RUN.\n",
            tmp_path,
        )
        assert level is CapabilityLevel.UNSUPPORTED
        assert "DELIMITED BY identifier WS-B" in reason

    def test_on_overflow_program_is_unsupported(self, tmp_path: Path):
        level, reason = _verdict(
            HEADER
            + "    STRING WS-A DELIMITED BY SIZE INTO WS-D "
            'ON OVERFLOW MOVE "X" TO WS-A.\n    STOP RUN.\n',
            tmp_path,
        )
        assert level is CapabilityLevel.UNSUPPORTED
        assert "ON OVERFLOW" in reason


# ---------------------------------------------------------------------------
# Real fixtures — the shipped workloads keep working, string diagnostics free
# ---------------------------------------------------------------------------

class TestStringFixtures:
    @pytest.mark.parametrize(
        "rel",
        [
            "workload_inventory/cobol/INVENTORY.cob",
            "workload-payroll/cobol/PAYROLL.cob",
            "workload-claims/cobol/CLAIMS.cob",
        ],
    )
    def test_fixture_parses_without_string_diagnostics(self, rel: str):
        source = (FIXTURES / rel).read_text(encoding="utf-8")
        parser = CobolParser()
        program = parser.parse(source)
        string_diags = [
            d for d in parser.diagnostics.all if d.location == "STRING"
        ]
        assert string_diags == [], [d.message for d in string_diags]

    def test_inventory_string_phrases_are_all_size(self):
        source = (
            FIXTURES / "workload_inventory/cobol/INVENTORY.cob"
        ).read_text(encoding="utf-8")
        program = CobolParser().parse(source)
        stmts = [
            s
            for para in program.paragraphs
            for s in para.statements
            if isinstance(s, StringStatement)
        ]
        assert stmts
        for stmt in stmts:
            assert all(d is None for d in stmt.delimiter_exprs)
            assert not stmt.has_overflow
            assert stmt.pointer == ""

    def test_payroll_space_delimiter_is_figurative_in_ir(self):
        source = (
            FIXTURES / "workload-payroll/cobol/PAYROLL.cob"
        ).read_text(encoding="utf-8")
        program = CobolParser().parse(source)
        stmts = [
            s
            for para in program.paragraphs
            for s in para.statements
            if isinstance(s, StringStatement)
        ]
        assert any(
            isinstance(d, FigurativeConstant) and d.kind == "SPACE"
            for stmt in stmts
            for d in stmt.delimiter_exprs
        )

    def test_fixture_generated_java_has_no_fail_closed_symbol(self):
        for rel in (
            "workload_inventory/cobol/INVENTORY.cob",
            "workload-payroll/cobol/PAYROLL.cob",
        ):
            source = (FIXTURES / rel).read_text(encoding="utf-8")
            code = JavaGenerator().generate(CobolParser().parse(source))[0]
            assert "UNSUPPORTED_STRING" not in code.source_code, rel

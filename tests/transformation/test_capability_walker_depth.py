"""BL-059 focused gate: capability derivation sees every statement at any depth.

``derive_capabilities`` counted only ADD/DIVIDE as arithmetic
(``ir.py`` L842) and ``_flatten_statements`` never recursed into
inline-PERFORM bodies or INVALID KEY bodies — statements nested there
were invisible to *every* detection (arithmetic, assignment, display, …),
so valid programs were classified with reduced capability (conservative
under-report: blocks valid applications, no false green).

Acceptance (docs/BACKLOG.md BL-059):
1. SUBTRACT/MULTIPLY/COMPUTE count as arithmetic alongside ADD/DIVIDE;
2. every compound body is walked: inline PERFORM ``body`` and the
   INVALID KEY / NOT INVALID KEY bodies of READ/START/WRITE/REWRITE/
   DELETE, alongside the existing IF/ELSE and AT END recursion;
3. nested statements contribute to *all* detections (assignment/display
   inside an inline PERFORM body);
4. end-to-end: a parsed program whose only executable arithmetic sits
   inside an inline PERFORM derives ``arithmetic``;
5. existing recursion (IF, AT END) preserved as controls.
"""

from __future__ import annotations

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import (
    AddStatement,
    CobolProgram,
    ComputeStatement,
    DeleteStatement,
    DisplayStatement,
    IfStatement,
    MoveStatement,
    MultiplyStatement,
    Paragraph,
    PerformStatement,
    ReadStatement,
    RewriteStatement,
    StartStatement,
    SubtractStatement,
    WriteStatement,
    derive_capabilities,
)


def _caps(*statements):
    return derive_capabilities(
        CobolProgram(
            program_id="WALK",
            paragraphs=(
                Paragraph(name="MAIN", statements=tuple(statements)),
            ),
        )
    )


# ---------------------------------------------------------------------------
# Controls: recursion that already worked (must stay green)
# ---------------------------------------------------------------------------


def test_add_at_top_level_counts_as_arithmetic():
    """Control: the ADD detection this fix extends."""
    assert _caps(AddStatement(source="A", target="B")).arithmetic is True


def test_add_inside_if_body_still_counts():
    """Control: existing IF/ELSE recursion is preserved."""
    caps = _caps(
        IfStatement(
            condition="A = B",
            then_body=(AddStatement(source="A", target="B"),),
        )
    )
    assert caps.arithmetic is True


def test_add_inside_read_at_end_body_still_counts():
    """Control: existing AT END recursion is preserved."""
    caps = _caps(
        ReadStatement(
            file_name="F",
            record_name="R",
            at_end_body=(AddStatement(source="A", target="B"),),
        )
    )
    assert caps.arithmetic is True


# ---------------------------------------------------------------------------
# Arithmetic statement types (L842 tuple was ADD/DIVIDE only)
# ---------------------------------------------------------------------------


def test_subtract_counts_as_arithmetic():
    assert _caps(SubtractStatement(source="A", from_field="B")).arithmetic is True


def test_multiply_counts_as_arithmetic():
    assert _caps(
        MultiplyStatement(source="A", multiplicand="B")
    ).arithmetic is True


def test_compute_counts_as_arithmetic():
    assert _caps(
        ComputeStatement(target="B", expression="A + 1")
    ).arithmetic is True


# ---------------------------------------------------------------------------
# Nested bodies (walker recursion gaps — ADD isolates recursion from type fix)
# ---------------------------------------------------------------------------


def test_inline_perform_body_counts_nested_arithmetic():
    caps = _caps(
        PerformStatement(
            paragraph_name="",
            body=(AddStatement(source="A", target="B"),),
        )
    )
    assert caps.arithmetic is True


def test_inline_perform_body_counts_assignment_and_display():
    """Recursion feeds *every* detection, not just arithmetic."""
    caps = _caps(
        PerformStatement(
            paragraph_name="",
            body=(
                MoveStatement(source="A", target="B"),
                DisplayStatement(parts=("B",), destination="STDOUT"),
            ),
        )
    )
    assert caps.assignment is True
    assert caps.display is True


@pytest.mark.parametrize(
    "make_stmt",
    [
        pytest.param(
            lambda body: ReadStatement(
                file_name="F", record_name="R", invalid_key_body=body
            ),
            id="read",
        ),
        pytest.param(
            lambda body: StartStatement(file_name="F", invalid_key_body=body),
            id="start",
        ),
        pytest.param(
            lambda body: WriteStatement(
                record_name="R", file_name="F", invalid_key_body=body
            ),
            id="write",
        ),
        pytest.param(
            lambda body: RewriteStatement(
                record_name="R", file_name="F", invalid_key_body=body
            ),
            id="rewrite",
        ),
        pytest.param(
            lambda body: DeleteStatement(file_name="F", invalid_key_body=body),
            id="delete",
        ),
    ],
)
def test_invalid_key_body_counts_nested_arithmetic(make_stmt):
    caps = _caps(make_stmt((AddStatement(source="A", target="B"),)))
    assert caps.arithmetic is True


def test_read_not_invalid_key_body_counts_nested_arithmetic():
    caps = _caps(
        ReadStatement(
            file_name="F",
            record_name="R",
            not_invalid_key_body=(AddStatement(source="A", target="B"),),
        )
    )
    assert caps.arithmetic is True


# ---------------------------------------------------------------------------
# End-to-end: backlog's observed scenario
# ---------------------------------------------------------------------------


def test_parsed_perform_until_subtract_inside_body_derives_arithmetic():
    """Backlog observed case: SUBTRACT whose only home is an inline PERFORM."""
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. WALK.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "           01  WS-A  PIC 9(4).\n"
        "       PROCEDURE DIVISION.\n"
        "           PERFORM UNTIL WS-A > 5\n"
        "               SUBTRACT 1 FROM WS-A\n"
        "           END-PERFORM\n"
        "           STOP RUN.\n"
    )
    program = CobolParser().parse(source)
    caps = derive_capabilities(program)
    assert caps.arithmetic is True
    assert caps.perform is True

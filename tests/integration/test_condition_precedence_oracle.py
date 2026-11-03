"""GnuCOBOL differential proof: AND binds tighter than OR with level-88 names.

Audit 2026-11-03 (T2): whenever a program declared any level-88 item, a
compound condition was folded left to right, so ``A = 1 OR I = 2 AND J = 3``
became ``((A == 1) || (I == 2)) && (J == 3)`` with no diagnostic.  The
combinations below mix condition names, NOT, alphanumeric and decimal
operands, three-term chains and explicit parentheses; several of them flip
under the left-to-right fold.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

CONDITIONS = [
    ("C01", "A = 1 OR I = 2 AND J = 3", "T"),
    ("C02", "I = 2 AND J = 3 OR A = 1", "T"),
    ("C03", "F-NO OR A = 1 AND I = 0", "T"),
    ("C04", "F-YES AND I = 1 OR J = 1", "F"),
    ("C05", "F-YES AND (I = 1 OR A = 1)", "T"),
    ("C06", "NOT F-YES OR I = 0 AND J = 0", "T"),
    ("C07", "N = 'BOB' AND F-YES OR A = 0", "T"),
    ("C08", "D > 1.25 AND F-NO OR I = 0 AND D < 2", "T"),
    ("C09", "A = 0 OR F-NO OR J = 0 AND I = 1", "F"),
    ("C10", "(A = 1 OR I = 2) AND J = 3", "F"),
]


def _program() -> str:
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. CONDPREC.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01 A PIC 9 VALUE 1.",
        "       01 I PIC 9 VALUE 0.",
        "       01 J PIC 9 VALUE 0.",
        "       01 F PIC X VALUE 'Y'.",
        "           88 F-YES VALUE 'Y'.",
        "           88 F-NO VALUE 'N'.",
        "       01 N PIC X(3) VALUE 'BOB'.",
        "       01 D PIC 9V99 VALUE 1.50.",
        "       PROCEDURE DIVISION.",
        "       MAIN.",
    ]
    for label, condition, _ in CONDITIONS:
        lines += [
            f"           IF {condition}",
            f"               DISPLAY '{label}-T'",
            "           ELSE",
            f"               DISPLAY '{label}-F'",
            "           END-IF.",
        ]
    lines.append("           STOP RUN.")
    return "\n".join(lines) + "\n"


EXPECTED = [f"{label}-{result}" for label, _, result in CONDITIONS]


def test_or_is_split_before_and_in_ir() -> None:
    """Hermetic: the 88-level path renders AND inside OR."""
    program = CobolParser().parse(_program())
    rendered = JavaGenerator().generate(program)[0].source_code
    assert "((A == 1) || ((I == 2) && (J == 3)))" in rendered, rendered[:2000]


def test_precedence_byte_identical_to_gnucobol(tmp_path: Path) -> None:
    (tmp_path / "cobol").mkdir()
    (tmp_path / "java").mkdir()
    source = _program()
    oracle = run_gnucobol(source, "CONDPREC", tmp_path / "cobol")
    java = run_generated_java(source, "CONDPREC", tmp_path / "java")
    assert oracle.splitlines() == EXPECTED, oracle
    assert java == oracle

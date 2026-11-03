"""REDEFINES digit views (Phase 3, increment 10).

The overlay model (``engine/transformation/redefines.py``) certified only
alphanumeric views at offset 0.  It now also takes an unsigned DISPLAY
integer base or view (its bytes are its digits) and a redefining group whose
leaves sit at their offsets — the everyday ``PIC 9(8)`` date redefined as
``YYYY``/``MM``/``DD``.  Writes splice the view's bytes into the shared
storage; overlapping views are refreshed.  ``tests/data/phase3/REDEF.cob``
exercises every direction; its GnuCOBOL 3.1.2 output is ``REDEF.expected``.

Still refused: a numeric view over bytes that are not digits.  GnuCOBOL
decodes such bytes compiler-specifically (``MOVE "ABCDEF"`` over a PIC 9(6)
displays ``A CDEF``) — refused at generation when a literal does it
(``workload-redefines``), and the Java stops at run time if data does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import CobolApplication, CobolProgramUnit
from engine.transformation.redefines import build_redefines_plan
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

DATA = Path(__file__).parent / "data" / "phase3"
REPO = Path(__file__).resolve().parents[1]
SOURCE = (DATA / "REDEF.cob").read_text()
EXPECTED = (DATA / "REDEF.expected").read_text()


def _level(source: str) -> tuple[CapabilityLevel, str]:
    unit = CobolProgramUnit(program_id="R", source_path="R.cob",
                            program=CobolParser().parse(source), source_text=source)
    report = CapabilityAnalyzer(docker_available=True).analyze(
        CobolApplication(application_id="T", programs=(unit,)))
    program = next(c for c in report.components if c.component_type == "PROGRAM")
    return program.level, program.reason


def test_plan_places_group_leaves_at_their_offsets() -> None:
    plan = build_redefines_plan(CobolParser().parse(SOURCE).working_storage)
    assert not plan.problems
    layout = {name: (v.offset, v.length, v.numeric) for name, v in plan.views.items()}
    assert layout["WS-YYYY"] == (0, 4, True)
    assert layout["WS-MM"] == (4, 2, True)
    assert layout["WS-DD"] == (6, 2, True)
    assert layout["WS-NUM"] == (2, 4, True)
    assert layout["WS-AMT-X"] == (0, 6, False)


def test_probe_is_supported() -> None:
    level, reason = _level(SOURCE)
    assert level is CapabilityLevel.SUPPORTED, reason


def test_non_digit_literal_into_a_numeric_view_is_refused() -> None:
    app = ApplicationDiscovery().discover(REPO / "fixtures" / "workload-redefines" / "cobol")
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    program = next(c for c in report.components if c.component_type == "PROGRAM")
    assert program.level is CapabilityLevel.UNSUPPORTED
    assert "non-digit bytes into numeric view WS-NUMERIC" in program.reason


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ("       01  B  PIC S9(4) VALUE 12.\n       01  V REDEFINES B PIC X(4).\n", "signed"),
        ("       01  B  PIC 9(2)V99 VALUE 12.\n       01  V REDEFINES B PIC X(4).\n", "scaled"),
        ("       01  B  PIC X(4).\n       01  V REDEFINES B PIC 9(4).\n", "not digits"),
        ("       01  B  PIC 9(4) COMP.\n       01  V REDEFINES B PIC X(2).\n", "USAGE"),
    ],
)
def test_uncertified_overlays_stay_refused(data: str, reason: str) -> None:
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. R.\n"
        "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        f"{data}"
        "       PROCEDURE DIVISION.\n       MAIN-LOGIC.\n           DISPLAY V.\n"
        "           STOP RUN.\n"
    )
    plan = build_redefines_plan(CobolParser().parse(source).working_storage)
    assert any(reason in r for r in plan.problems.values()), plan.problems
    assert _level(source)[0] is not CapabilityLevel.SUPPORTED


def test_generated_java_matches_oracle(tmp_path: Path) -> None:
    assert run_generated_java(SOURCE, "REDEF", tmp_path) == EXPECTED


def test_oracle_pin(tmp_path: Path) -> None:
    assert run_gnucobol(SOURCE, "REDEF", tmp_path) == EXPECTED

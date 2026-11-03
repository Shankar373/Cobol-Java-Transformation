"""OCCURS tables referenced by element (Phase 3, increment 10).

Every program with OCCURS used to be PARTIAL.  A table that is a fixed-size,
one-dimensional, DISPLAY elementary WORKING-STORAGE item, always referenced
with a subscript and inside groups the procedure never names, is now
SUPPORTED.  The probe (``tests/data/phase3/OCC.cob``) found and fixed two
defects on the way:

* a subscripted operand in any condition (``IF WS-N(2) > WS-N(1)``) was
  refused — the condition operand matcher accepted bare names only;
* an arithmetic receiver that is a table element got no receiver semantics:
  its Java spelling (``WS_N[(I - 1)]``) did not resolve to the item, so an
  integer element was never truncated to its PIC (``ADD 10`` to 995 in a
  ``PIC 9(3)`` element kept 1005) and a decimal element did not compile.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import CobolApplication, CobolProgramUnit
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

DATA = Path(__file__).parent / "data" / "phase3"
REPO = Path(__file__).resolve().parents[1]
SOURCE = (DATA / "OCC.cob").read_text()
EXPECTED = (DATA / "OCC.expected").read_text()


def _level(source: str) -> CapabilityLevel:
    unit = CobolProgramUnit(program_id="O", source_path="O.cob",
                            program=CobolParser().parse(source), source_text=source)
    report = CapabilityAnalyzer(docker_available=True).analyze(
        CobolApplication(application_id="T", programs=(unit,)))
    return next(c for c in report.components if c.component_type == "PROGRAM").level


def test_probe_and_fixture_are_supported() -> None:
    assert _level(SOURCE) is CapabilityLevel.SUPPORTED
    app = ApplicationDiscovery().discover(REPO / "fixtures" / "workload-occurs" / "cobol")
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    program = next(c for c in report.components if c.component_type == "PROGRAM")
    assert program.level is CapabilityLevel.SUPPORTED, program.reason


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("           DISPLAY 'TOTAL ' WS-TOTAL\n",
         "           DISPLAY 'TOTAL ' WS-TOTAL\n           DISPLAY WS-NUMS\n"),   # whole table
        ("05  WS-N              PIC 9(3) OCCURS 5 TIMES.",
         "05  WS-N              PIC 9(3) OCCURS 1 TO 5 DEPENDING ON WS-I."),
        ("05  WS-N              PIC 9(3) OCCURS 5 TIMES.",
         "05  WS-N              PIC 9(3) OCCURS 5 TIMES INDEXED BY IX."),
    ],
)
def test_outside_the_subset_stays_partial(old: str, new: str) -> None:
    source = SOURCE.replace(old, new, 1)
    assert source != SOURCE
    assert _level(source) is not CapabilityLevel.SUPPORTED


def test_generated_java_matches_oracle(tmp_path: Path) -> None:
    assert run_generated_java(SOURCE, "OCC", tmp_path) == EXPECTED


def test_oracle_pin(tmp_path: Path) -> None:
    assert run_gnucobol(SOURCE, "OCC", tmp_path) == EXPECTED

"""Roadmap unit 7: which keyed-file access modes the analyzer certifies.

``ACCESS MODE IS RANDOM`` on INDEXED and RELATIVE files is certified (proven against
GnuCOBOL in ``tests/integration/test_keyed_random_oracle.py``) as long as the program does
not use START or READ NEXT on that file, which RANDOM access does not allow. SEQUENTIAL
(and the default, which is SEQUENTIAL) stays refused, as does ALTERNATE RECORD KEY.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery

HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. KEYED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "KEYED.DAT"
               ORGANIZATION IS INDEXED
{access}               RECORD KEY IS KF-KEY
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KF-KEY PIC X(4).
           05 KF-DATA PIC X(8).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN I-O KF
{body}           CLOSE KF
           STOP RUN.
"""

KEYED_READ = "           MOVE \"K001\" TO KF-KEY\n           READ KF\n"
START = "           MOVE \"K001\" TO KF-KEY\n           START KF KEY >= KF-KEY\n"
READ_NEXT = "           READ KF NEXT\n"


def _program(tmp_path: Path, access: str, body: str):
    src = tmp_path / "src"
    src.mkdir()
    (src / "KEYED.cob").write_text(HEAD.format(access=access, body=body), encoding="utf-8")
    app = ApplicationDiscovery().discover(src, application_id="unit7")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, source_root=src)
    return next(
        c for c in report.components
        if c.component_type == "PROGRAM" and c.component_id == "KEYED"
    )


RANDOM = "               ACCESS MODE IS RANDOM\n"
DYNAMIC = "               ACCESS MODE IS DYNAMIC\n"
SEQUENTIAL = "               ACCESS MODE IS SEQUENTIAL\n"


def test_random_with_keyed_operations_is_supported(tmp_path):
    assert _program(tmp_path, RANDOM, KEYED_READ).level is CapabilityLevel.SUPPORTED


@pytest.mark.parametrize("body", [START, READ_NEXT])
def test_random_with_start_or_read_next_is_refused(tmp_path, body):
    program = _program(tmp_path, RANDOM, body)
    assert program.level is CapabilityLevel.UNSUPPORTED
    assert "START or READ NEXT" in program.reason


def test_dynamic_still_allows_start_and_read_next(tmp_path):
    assert _program(tmp_path, DYNAMIC, START + READ_NEXT).level is CapabilityLevel.SUPPORTED


@pytest.mark.parametrize("access", [SEQUENTIAL, ""])
def test_sequential_access_stays_refused(tmp_path, access):
    program = _program(tmp_path, access, KEYED_READ)
    assert program.level is CapabilityLevel.UNSUPPORTED
    assert "outside the certified subset" in program.reason
    assert "DYNAMIC and RANDOM" in program.reason

"""Roadmap unit 7: which keyed-file access modes the analyzer certifies.

``ACCESS MODE IS RANDOM`` on INDEXED and RELATIVE files is certified (proven against
GnuCOBOL in ``tests/integration/test_keyed_random_oracle.py``) as long as the program does
not use START or READ NEXT on that file, which RANDOM access does not allow. SEQUENTIAL
(and the default, which is SEQUENTIAL) is certified since unit 27 for the subset in
``capability_analyzer._sequential_access_problem``; ALTERNATE RECORD KEY stays refused.
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
def test_sequential_access_is_certified_with_file_status_and_no_invalid_key_scope(tmp_path, access):
    # roadmap unit 27 (Stage 1): a plain READ is READ NEXT; status rules proven in test_keyed_sequential_oracle.py
    program = _program(tmp_path, access, KEYED_READ + START)
    assert program.level is CapabilityLevel.SUPPORTED


@pytest.mark.parametrize("access", [SEQUENTIAL, ""])
@pytest.mark.parametrize("body, why", [
    ("           READ KF\n               INVALID KEY DISPLAY \"X\"\n           END-READ\n", "INVALID KEY"),
    ("           MOVE \"K001\" TO KF-KEY\n           READ KF KEY IS KF-KEY\n", "KEY IS"),
    ("           MOVE \"K001\" TO KF-KEY\n           DELETE KF RECORD\n"
     "               INVALID KEY DISPLAY \"X\"\n           END-DELETE\n", "INVALID KEY"),
])
def test_sequential_access_forms_outside_the_subset_stay_refused(tmp_path, access, body, why):
    program = _program(tmp_path, access, body)
    assert program.level is CapabilityLevel.UNSUPPORTED
    assert "ACCESS MODE SEQUENTIAL is outside the certified subset" in program.reason
    assert why in program.reason


def test_sequential_access_without_file_status_stays_refused(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    text = HEAD.format(access=SEQUENTIAL, body=KEYED_READ)
    text = text.replace("RECORD KEY IS KF-KEY\n               FILE STATUS IS FS.\n", "RECORD KEY IS KF-KEY.\n")
    assert "FILE STATUS" not in text.split("DATA DIVISION")[0]
    (src / "KEYED.cob").write_text(text, encoding="utf-8")
    app = ApplicationDiscovery().discover(src, application_id="unit27")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, source_root=src)
    program = next(c for c in report.components if c.component_type == "PROGRAM" and c.component_id == "KEYED")
    assert program.level is CapabilityLevel.UNSUPPORTED
    assert "no FILE STATUS clause" in program.reason

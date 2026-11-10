"""Indexed READ NEXT position after OPEN (GnuCOBOL 3.1.2 differential).

``OPEN INPUT`` / ``OPEN I-O`` of an indexed file that holds records puts the cursor on its first record, unread.
A record written afterwards below that key is therefore never reached by READ NEXT, and when the first record is
deleted before the first READ NEXT the following one is returned. A failed keyed READ does not end the end-of-file
condition: after a READ NEXT reached the end, the next READ NEXT answers 46. Found by the alternate-key browsing sweep; the
generated Java used to start from the lowest key at the time of the READ NEXT (a false success in the certified
ACCESS MODE DYNAMIC subset, with or without alternate keys).
"""

from __future__ import annotations

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OPOS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "OPOS.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS KEYF
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KEYF PIC X(2).
           05 DAT PIC X(2).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
"""


def _program(ops: list[str]) -> str:
    """ops: ``O out|io|in``, ``C``, ``W <key> <data>``, ``D <key>``, ``R <key>`` (keyed READ), ``N`` (READ NEXT)."""
    lines: list[str] = []
    for op in ops:
        token = op.split()
        if token[0] == "O":
            mode = {"out": "OUTPUT", "io": "I-O", "in": "INPUT"}[token[1]]
            lines.append(f"           OPEN {mode} KF")
        elif token[0] == "C":
            lines.append("           CLOSE KF")
        elif token[0] == "W":
            lines += [f'           MOVE "{token[1]}" TO KEYF', f'           MOVE "{token[2]}" TO DAT',
                      "           WRITE KF-REC", f'           DISPLAY "{op} " FS']
        elif token[0] == "R":
            lines += [f'           MOVE "{token[1]}" TO KEYF', "           READ KF",
                      f'           DISPLAY "{op} " FS " " KEYF " " DAT']
        elif token[0] == "D":
            lines += [f'           MOVE "{token[1]}" TO KEYF', "           DELETE KF RECORD",
                      f'           DISPLAY "{op} " FS']
        else:
            lines += ["           READ KF NEXT", '           DISPLAY "N " FS " " KEYF " " DAT']
    lines.append("           CLOSE KF")
    lines.append("           STOP RUN.")
    return HEAD + "\n".join(lines) + "\n"


BASE = ["O out", "W K3 aa", "W K4 bb", "W K6 cc", "C"]

CASES = {
    "write below the first record is skipped": BASE + ["O io", "W K0 zz", "N", "N", "N", "N"],
    "write between records is seen": BASE + ["O io", "W K5 zz", "N", "N", "N", "N"],
    "write above the last record is seen": BASE + ["O io", "W K9 zz", "N", "N", "N", "N", "N"],
    "first record deleted before the first READ NEXT": BASE + ["O io", "W K0 zz", "D K3", "N", "N", "N"],
    "write after the first READ NEXT": BASE + ["O io", "N", "W K0 zz", "N", "N", "N"],
    "empty file at open has no position": ["O out", "C", "O io", "W K5 zz", "W K2 yy", "N", "N", "N"],
    "OPEN INPUT starts at the first record": BASE + ["O in", "N", "N", "N", "N"],
    # the end-of-file condition survives a failed keyed READ (it used to be forgotten: 10 instead of 46)
    "end of file, failed keyed READ, READ NEXT": BASE + ["O io", "N", "N", "N", "N", "R K9", "N", "N"],
    "second end-of-file answer, failed keyed READ": BASE + ["O io", "N", "N", "N", "N", "N", "R K9", "N", "N"],
    "a successful keyed READ ends the end-of-file condition": BASE + ["O io", "N", "N", "N", "N", "R K3", "N"],
}


@needs_docker
def test_the_open_position_matches_the_oracle(tmp_path):
    names = list(CASES)
    results = run_batch(tmp_path, [_program(CASES[name]) for name in names])
    bad = [name for name, (cobol, java) in zip(names, results) if cobol != java]
    assert bad == []


def test_the_cases_cover_the_documented_behaviours():
    assert len(CASES) >= 10
    assert all("N" in ops for ops in CASES.values())

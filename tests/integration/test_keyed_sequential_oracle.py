"""Roadmap unit 27 (Stage 1): ``ACCESS MODE IS SEQUENTIAL`` on INDEXED files, GnuCOBOL 3.1.2 differential.

A plain READ is READ NEXT; WRITE needs OUTPUT/EXTEND and strictly ascending keys (status 21), REWRITE and DELETE act on
the record last READ (43 otherwise, 49 in INPUT), REWRITE with a changed key moves the record (22 if that key exists),
a failed START leaves no next record (46), reads after the end give 46, WRITE in INPUT/I-O gives 48. Generated programs
display the FILE STATUS after every verb; the output of GnuCOBOL and of the generated Java must be identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. KSQ.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "KSQ.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS KF-KEY
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KF-KEY PIC X(4).
           05 KF-DATA PIC X(4).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
"""


def _key(rng: random.Random) -> str:
    return f"K{rng.randint(1, 9)}0{rng.randint(0, 2)}"


def _data(rng: random.Random) -> str:
    return rng.choice(["AAAA", "BBBB", "CCCC", "DD", "E"])


def _write_phase(rng: random.Random, mode: str, lines: list[str], tag: str) -> None:
    lines += [f"           OPEN {mode} KF", f'           DISPLAY "{tag} open {mode} " FS']
    keys = sorted({_key(rng) for _ in range(rng.randint(2, 6))})
    for index in range(rng.randint(2, 8)):
        # mostly ascending, now and then out of order or a repeat
        key = keys[index] if index < len(keys) and rng.random() < 0.75 else _key(rng)
        lines += [f'           MOVE "{key}" TO KF-KEY', f'           MOVE "{_data(rng)}" TO KF-DATA',
                  "           WRITE KF-REC", f'           DISPLAY "{tag} w {key} " FS']
    lines.append("           CLOSE KF")


def _read_phase(rng: random.Random, mode: str, lines: list[str], tag: str) -> None:
    lines += [f"           OPEN {mode} KF", f'           DISPLAY "{tag} open {mode} " FS']
    for step in range(rng.randint(3, 12)):
        label = f"{tag}{step}"
        op = rng.choice(["read", "read", "read", "rewrite", "rewrite_key", "delete", "start", "write", "bare"])
        if op == "read":
            lines += ["           READ KF", f'           DISPLAY "{label} r " FS " " KF-KEY " " KF-DATA']
        elif op == "rewrite":
            lines += [f'           MOVE "{_data(rng)}" TO KF-DATA', "           REWRITE KF-REC",
                      f'           DISPLAY "{label} rw " FS']
        elif op == "rewrite_key":
            lines += [f'           MOVE "{_key(rng)}" TO KF-KEY', "           REWRITE KF-REC",
                      f'           DISPLAY "{label} rwk " FS']
        elif op == "delete":
            lines += ["           DELETE KF RECORD", f'           DISPLAY "{label} d " FS']
        elif op == "start":
            lines += [f'           MOVE "{_key(rng)}" TO KF-KEY',
                      f"           START KF KEY {rng.choice(['=', '>', '>=', '<', '<='])} KF-KEY",
                      f'           DISPLAY "{label} s " FS']
        elif op == "write":
            lines += [f'           MOVE "{_key(rng)}" TO KF-KEY', "           WRITE KF-REC",
                      f'           DISPLAY "{label} w " FS']
        else:
            lines += ["           READ KF", "               AT END DISPLAY \"" + label + " end\"",
                      "           END-READ", f'           DISPLAY "{label} ra " FS']
    lines.append("           CLOSE KF")


def _program(rng: random.Random) -> str:
    lines = HEAD.rstrip("\n").split("\n")
    _write_phase(rng, "OUTPUT", lines, "a")
    for phase in range(rng.randint(1, 3)):
        kind = rng.choice(["I-O", "I-O", "INPUT", "EXTEND"])
        if kind == "EXTEND":
            _write_phase(rng, "EXTEND", lines, f"e{phase}")
        else:
            _read_phase(rng, kind, lines, f"p{phase}")
    lines += ["           OPEN INPUT KF", "           READ KF", '           DISPLAY "final " FS " " KF-KEY',
              "           CLOSE KF", "           STOP RUN."]
    return "\n".join(lines) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [31, 32, 33, 34])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(96)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

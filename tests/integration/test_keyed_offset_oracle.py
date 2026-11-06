"""Roadmap unit 29 (Stage 1): an INDEXED file whose RECORD KEY is not the first field, GnuCOBOL 3.1.2 differential.

Before this unit such a program was classified SUPPORTED while the generated Java derived the key from the first bytes of
the record (READ by key answered 23 for a record GnuCOBOL found). Generated programs place the key at a random position
of a record of 3-5 fields, use ACCESS MODE DYNAMIC or SEQUENTIAL and mix WRITE (new and duplicate keys), keyed READ, READ
NEXT, START, REWRITE and DELETE; every FILE STATUS and every field read is displayed and must be identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. KOF.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "KOF.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS {access}
               RECORD KEY IS KEYF
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
{fields}       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
"""


def _key(rng: random.Random) -> str:
    return f"K{rng.randint(1, 8)}0{rng.randint(0, 1)}"


def _program(rng: random.Random) -> str:
    leaf_count = rng.randint(3, 5)
    names = [f"D{i}" for i in range(1, leaf_count)]
    position = rng.randint(0, len(names))
    order = names[:position] + ["KEYF"] + names[position:]
    widths = {name: rng.randint(1, 4) for name in names}
    fields = "".join(
        "           05 KEYF PIC X(4).\n" if name == "KEYF" else f"           05 {name} PIC X({widths[name]}).\n"
        for name in order)
    access = rng.choice(["DYNAMIC", "SEQUENTIAL"])
    lines = HEAD.format(access=access, fields=fields).rstrip("\n").split("\n")

    def fill(tag: str) -> list[str]:
        return [f'           MOVE "{tag[: widths[name]]}" TO {name}' for name in names]

    shown = " ".join(f'" " {name}' for name in ["KEYF"] + names)
    keys = sorted({_key(rng) for _ in range(rng.randint(2, 6))})
    lines += ["           OPEN OUTPUT KF", '           DISPLAY "open " FS']
    for index, key in enumerate(keys):
        lines += [f'           MOVE "{key}" TO KEYF'] + fill(f"v{index}x") + ["           WRITE KF-REC",
                                                                         f'           DISPLAY "w{index} " FS']
    if access == "DYNAMIC":  # out-of-order and duplicate keys are legal there
        lines += [f'           MOVE "{_key(rng)}" TO KEYF'] + fill("dup") + ["           WRITE KF-REC",
                                                                         '           DISPLAY "wd " FS']
    lines += ["           CLOSE KF", "           OPEN I-O KF", '           DISPLAY "open2 " FS']
    for step in range(rng.randint(3, 9)):
        label = f"s{step}"
        if access == "DYNAMIC":
            op = rng.choice(["read", "read", "next", "rewrite", "delete", "start"])
        else:
            op = rng.choice(["next", "next", "next", "rewrite", "delete", "start"])
        if op == "read":
            lines += [f'           MOVE "{_key(rng)}" TO KEYF', "           READ KF",
                      f'           DISPLAY "{label} r " FS {shown}']
        elif op == "next":
            lines += ["           READ KF" + (" NEXT" if access == "DYNAMIC" else ""),
                      f'           DISPLAY "{label} n " FS {shown}']
        elif op == "rewrite":
            key_line = [f'           MOVE "{_key(rng)}" TO KEYF'] if access == "DYNAMIC" else []
            lines += key_line + fill(f"re{step}") + ["           REWRITE KF-REC", f'           DISPLAY "{label} rw " FS']
        elif op == "delete":
            key_line = [f'           MOVE "{_key(rng)}" TO KEYF'] if access == "DYNAMIC" else []
            lines += key_line + ["           DELETE KF RECORD", f'           DISPLAY "{label} d " FS']
        else:
            lines += [f'           MOVE "{_key(rng)}" TO KEYF',
                      f"           START KF KEY {rng.choice(['=', '>', '>=', '<'])} KEYF",
                      f'           DISPLAY "{label} s " FS']
    lines += ["           CLOSE KF", "           STOP RUN."]
    wrapped: list[str] = []
    for line in lines:
        while len(line) > 72:
            cut = line.rfind(' " "', 0, 70)
            if cut < 20:
                cut = line.rfind(" ", 0, 70)
            wrapped.append(line[:cut])
            line = "               " + line[cut:].lstrip()
        wrapped.append(line)
    return "\n".join(wrapped) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [71, 72, 73, 74])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(94)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

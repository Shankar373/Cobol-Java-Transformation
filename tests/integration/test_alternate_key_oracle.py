"""Roadmap unit 30 (Stage 1): ALTERNATE RECORD KEY on INDEXED files, GnuCOBOL 3.1.2 differential.

Generated programs declare an INDEXED file (ACCESS MODE DYNAMIC) with a primary key, one alternate key WITH DUPLICATES
and one unique alternate key, placed at random positions of a 3-5 field record; they write records whose keys collide
(statuses 00, 02 and 22), then read by primary and alternate key, REWRITE (changing alternate values), DELETE and
WRITE again, mixing statements that succeed and fail. Every FILE STATUS and every field read is displayed; the output of
GnuCOBOL and of the generated Java must be identical. START and READ NEXT are deliberately absent: browsing along an
alternate key is refused by the capability gate (see ``engine/transformation/alternate_key.py`` for the evidence).
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "ALT.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS KEYF
               ALTERNATE RECORD KEY IS AKD WITH DUPLICATES
               ALTERNATE RECORD KEY IS AKU
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
{fields}       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
"""


def _program(rng: random.Random) -> str:
    names = ["KEYF", "AKD", "AKU", "DAT"][: rng.randint(3, 4)]
    rng.shuffle(names)
    if "KEYF" not in names or "AKD" not in names or "AKU" not in names:
        names = ["KEYF", "AKD", "AKU"] + (["DAT"] if "DAT" in names else [])
        rng.shuffle(names)
    fields = "".join(f"           05 {name} PIC X(2).\n" for name in names)
    lines = HEAD.format(fields=fields).rstrip("\n").split("\n")
    shown = " ".join(f'" " {name}' for name in names)

    def key() -> str:
        return f"K{rng.randint(1, 6)}"

    def dup() -> str:
        return rng.choice(["AA", "BB", "CC", "DD"])

    def unq() -> str:
        return f"U{rng.randint(1, 7)}"

    def record(tag: str) -> list[str]:
        out = [f'           MOVE "{key()}" TO KEYF', f'           MOVE "{dup()}" TO AKD',
               f'           MOVE "{unq()}" TO AKU']
        if "DAT" in names:
            out.append(f'           MOVE "{tag}" TO DAT')
        return out

    lines += ["           OPEN OUTPUT KF", '           DISPLAY "open " FS']
    for index in range(rng.randint(3, 9)):
        lines += record(f"w{index}") + ["           WRITE KF-REC", f'           DISPLAY "w{index} " FS']
    lines += ["           CLOSE KF", "           OPEN I-O KF", '           DISPLAY "open2 " FS']
    for step in range(rng.randint(5, 14)):
        label = f"s{step}"
        op = rng.choice(["rkey", "ralt", "ralt", "rewrite", "delete", "write"])
        if op == "rkey":
            lines += [f'           MOVE "{key()}" TO KEYF', "           READ KF",
                      f'           DISPLAY "{label} rk " FS {shown}']
        elif op == "ralt":
            field, value = rng.choice([("AKD", dup()), ("AKU", unq())])
            lines += [f'           MOVE "{value}" TO {field}', f"           READ KF KEY IS {field}",
                      f'           DISPLAY "{label} ra " FS {shown}']
        elif op == "next":
            lines += ["           READ KF NEXT", f'           DISPLAY "{label} n " FS {shown}']
        elif op == "start":
            field, value = rng.choice([("AKD", dup()), ("AKU", unq())])
            lines += [f'           MOVE "{value}" TO {field}',
                      f"           START KF KEY {rng.choice(['=', '>', '>='])} {field}",
                      f'           DISPLAY "{label} s " FS']
        elif op == "startp":
            lines += [f'           MOVE "{key()}" TO KEYF',
                      f"           START KF KEY {rng.choice(['=', '>', '>=', '<'])} KEYF",
                      f'           DISPLAY "{label} sp " FS']
        elif op == "rewrite":
            lines += record(f"r{step}") + ["           REWRITE KF-REC", f'           DISPLAY "{label} rw " FS']
        elif op == "delete":
            lines += [f'           MOVE "{key()}" TO KEYF', "           DELETE KF RECORD",
                      f'           DISPLAY "{label} d " FS']
        else:
            lines += record(f"x{step}") + ["           WRITE KF-REC", f'           DISPLAY "{label} w " FS']
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
@pytest.mark.parametrize("seed", [81, 82, 83, 84])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(93)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

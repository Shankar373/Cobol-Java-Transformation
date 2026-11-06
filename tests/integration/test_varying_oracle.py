"""Roadmap unit 33 (Stage 1): PERFORM VARYING ... AFTER ... (nested varying) and WITH TEST AFTER, GnuCOBOL 3.1.2 differential.

Generated programs run PERFORM VARYING with one to three levels (VARYING plus up to two AFTER clauses), TEST BEFORE or
TEST AFTER, an inline body or one or two out-of-line paragraphs (PERFORM p1 VARYING ...; THRU ranges with VARYING are refused by the parser), literal and
earlier-variable FROM values, positive and negative steps with matching UNTIL tests. Every control item and its final value
is displayed, so the initialisation of the deeper items, their re-initialisation after each outer step and the values left
behind (also by zero-iteration loops) are compared. Standard output must be identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. VAR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 VI PIC S99 VALUE 0.
       01 VJ PIC S99 VALUE 0.
       01 VK PIC S99 VALUE 0.
       01 CNT PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
"""

NAMES = ["VI", "VJ", "VK"]


def _clause(rng: random.Random, index: int, outer: list[str]) -> list[str]:
    name = NAMES[index]
    if rng.random() < 0.35:
        step = rng.choice([-1, -2, -1])
        start = rng.randint(3, 8)
        limit = rng.randint(0, 3)
        cond = f"{name} {rng.choice(['<', '<='])} {limit}"
    else:
        step = rng.choice([1, 1, 2, 3])
        start = rng.randint(0, 3)
        limit = rng.randint(2, 6)
        cond = f"{name} {rng.choice(['>', '>='])} {limit}"
    from_text = rng.choice(outer) if outer and rng.random() < 0.35 else str(start)
    by = f"BY {step}" if rng.random() < 0.9 else ""
    if not by and step != 1:
        by = f"BY {step}"
    if rng.random() < 0.08 and step == 1:
        by = ""  # BY is optional and defaults to 1
    keyword = "VARYING" if index == 0 else "AFTER"
    head = f"{keyword} {name} FROM {from_text} {by}".replace("  ", " ").rstrip()
    return [head, f"UNTIL {cond}"]


def _program(rng: random.Random) -> str:
    lines = HEAD.rstrip("\n").split("\n")
    paragraphs: list[str] = []
    for loop in range(rng.randint(2, 4)):
        depth = rng.randint(1, 3)
        clauses: list[str] = []
        for index in range(depth):
            clauses += _clause(rng, index, NAMES[:index])
        test = rng.choice(["", "", "WITH TEST AFTER ", "WITH TEST BEFORE "])
        shown = " ' ' ".join(NAMES[:depth])
        form = rng.choice(["inline", "inline", "para"])
        if form == "inline":
            lines.append(f"           PERFORM {test}{clauses[0]}")
            lines += [f"               {c}" for c in clauses[1:]]
            lines += [f"               DISPLAY 'b{loop} ' {shown}", "               ADD 1 TO CNT",
                      "           END-PERFORM."]
        else:
            name = f"P{loop}A"
            paragraphs += [f"       {name}.", f"           DISPLAY 'p{loop} ' {shown}.", "           ADD 1 TO CNT."]
            lines.append(f"           PERFORM {name} {test}{clauses[0]}")
            lines += [f"               {c}" for c in clauses[1:]]
            lines[-1] += "."
        lines.append(f"           DISPLAY 'e{loop} ' VI ' ' VJ ' ' VK ' ' CNT.")
    lines.append("           STOP RUN.")
    return "\n".join(lines + paragraphs) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [131, 132, 133, 134])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(90)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

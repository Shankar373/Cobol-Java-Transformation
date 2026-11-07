"""Roadmap unit 37 (Stage 1): EVALUATE ... ALSO and stacked WHEN clauses, GnuCOBOL 3.1.2 differential.

Generated programs run EVALUATE statements with one to three subjects (numeric items, a text item, TRUE) inside nested
PERFORM VARYING loops so every combination of values is tried: WHEN objects are values, THRU ranges and ANY, WHEN
clauses are stacked (``WHEN 1`` directly followed by ``WHEN 2 stmt`` runs ``stmt`` for both), and WHEN OTHER closes some
of them. Standard output must be identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9 VALUE 0.
       01 B PIC 9 VALUE 0.
       01 C PIC 9 VALUE 0.
       01 T PIC X VALUE 'a'.
       01 TI PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
"""

NUMERIC = ("A", "B", "C")


def _object(rng: random.Random, subject: str) -> str:
    if rng.random() < 0.25:
        return "ANY"
    if subject == "T":
        return "'" + rng.choice("abc") + "'"
    if subject == "TRUE":
        return rng.choice(["A > 1", "B < 2", "C = 0", "A = B", "A + B > 3"])
    if rng.random() < 0.3:
        low = rng.randint(0, 2)
        return f"{low} THRU {low + rng.randint(0, 2)}"
    return str(rng.randint(0, 3))


def _evaluate(rng: random.Random, label: int) -> list[str]:
    count = rng.randint(1, 3)
    if rng.random() < 0.2:
        subjects = ["TRUE"] * count
    else:
        subjects = [rng.choice(["A", "B", "C", "T"]) for _ in range(count)]
    lines = [f"               EVALUATE {' ALSO '.join(subjects)}"]
    for arm in range(rng.randint(2, 5)):
        stacked = rng.randint(1, 2) if rng.random() < 0.4 else 1
        for _ in range(stacked):
            lines.append("                   WHEN " + " ALSO ".join(_object(rng, s) for s in subjects))
        lines.append(f"                       DISPLAY 'e{label} arm{arm} ' A B C T")
    if rng.random() < 0.6:
        lines.append("                   WHEN OTHER")
        lines.append(f"                       DISPLAY 'e{label} other ' A B C T")
    lines.append("               END-EVALUATE")
    return lines


def _program(rng: random.Random) -> str:
    lines = [
        "           PERFORM VARYING A FROM 0 BY 1 UNTIL A > 3",
        "             PERFORM VARYING B FROM 0 BY 1 UNTIL B > 3",
        "               PERFORM VARYING C FROM 0 BY 2 UNTIL C > 3",
        "                 MOVE 'a' TO T",
        "                 COMPUTE TI = A + B + C",
        "                 IF TI > 2 MOVE 'b' TO T END-IF",
        "                 IF TI > 5 MOVE 'c' TO T END-IF",
    ]
    body = []
    for label in range(rng.randint(1, 2)):
        body += _evaluate(rng, label)
    text = lines + body + [
        "               END-PERFORM", "             END-PERFORM", "           END-PERFORM", "           STOP RUN.",
    ]
    wrapped: list[str] = []
    for line in text:
        while len(line) > 72:
            cut = line.rfind(" ", 0, 70)
            wrapped.append(line[:cut])
            line = "               " + line[cut:].lstrip()
        wrapped.append(line)
    return HEAD + "\n".join(wrapped) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [401, 402, 403, 404])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(20)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(94)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

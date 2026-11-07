"""Roadmap unit 35 (Stage 1): FUNCTION UPPER-CASE / LOWER-CASE / REVERSE / TRIM / LENGTH, GnuCOBOL 3.1.2 differential.

Generated programs apply each function to quoted literals, plain alphanumeric items (mixed case, leading and trailing
spaces, all spaces) and reference modifications, as DISPLAY operands and MOVE senders into alphanumeric receivers of
different widths (padded or truncated); LENGTH also moves into numeric receivers. Standard output must be identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. INT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
{items}       01 R1 PIC X(12) VALUE SPACES.
       01 R2 PIC X(4) VALUE '....'.
       01 R3 PIC X(20) VALUE ALL '-'.
       01 N1 PIC 9(4) VALUE 0.
       01 N2 PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
"""

ALPHABET = "abcXYZ019*-  "
WIDTHS = (1, 3, 6, 10)
FUNCTIONS = ("UPPER-CASE", "LOWER-CASE", "REVERSE", "TRIM", "TRIM LEADING", "TRIM TRAILING")


def _value(rng: random.Random, width: int) -> str:
    shape = rng.choice(["plain", "padded", "blank", "leading"])
    if shape == "blank":
        return ""
    text = "".join(rng.choice(ALPHABET.strip()) for _ in range(rng.randint(1, width)))
    if shape == "leading":
        text = "  " + text
    return text[:width]


def _program(rng: random.Random) -> str:
    items = {}
    lines = []
    for index in range(3):
        width = rng.choice(WIDTHS)
        items[f"T{index}"] = width
        value = _value(rng, width)
        lines.append(f"       01 T{index} PIC X({width}) VALUE " + (f"'{value}'" if value.strip() else "SPACES") + ".\n")

    def argument() -> str:
        kind = rng.choice(["item", "item", "literal", "refmod"])
        name = rng.choice(list(items))
        if kind == "literal":
            return "'" + "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 9))) + "'"
        if kind == "refmod":
            width = items[name]
            start = rng.randint(1, width)
            return f"{name}({start}:{rng.randint(1, width - start + 1)})"
        return name

    def function() -> str:
        name = rng.choice(FUNCTIONS)
        if name.startswith("TRIM") and " " in name:
            return f"FUNCTION TRIM({argument()} {name.split()[1]})"
        return f"FUNCTION {name}({argument()})"

    body = []
    for step in range(rng.randint(3, 6)):
        kind = rng.choice(["display", "move", "move", "length"])
        if kind == "display":
            body.append(f"           DISPLAY 'd{step} [' {function()} ']'")
        elif kind == "move":
            body.append(f"           MOVE {function()} TO {rng.choice(['R1', 'R2', 'R3'])}")
            body.append(f"           DISPLAY 'm{step} [' R1 '][' R2 '][' R3 ']'")
        else:
            body.append(f"           MOVE FUNCTION LENGTH({rng.choice(list(items) + ['R1', 'R3'])}) TO "
                        f"{rng.choice(['N1', 'N2', 'R1'])}")
            body.append(f"           DISPLAY 'l{step} [' N1 '][' N2 '][' R1 ']'")
            body.append(f"           DISPLAY 'L{step} ' FUNCTION LENGTH({argument()})")
    body += ["           STOP RUN."]
    wrapped: list[str] = []
    for line in body:
        while len(line) > 72:
            cut = line.rfind(" ", 0, 70)
            wrapped.append(line[:cut])
            line = "               " + line[cut:].lstrip()
        wrapped.append(line)
    return HEAD.format(items="".join(lines)) + "\n".join(wrapped) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [201, 202, 203, 204])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(92)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

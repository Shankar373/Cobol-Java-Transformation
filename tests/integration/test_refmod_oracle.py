"""Roadmap unit 32 (Stage 1): reference modification ``name(start:length)``, GnuCOBOL 3.1.2 differential.

Generated programs address plain alphanumeric items and unsigned integer DISPLAY items with literal, variable and
``item + literal`` starts and lengths (every reference is in range by construction; the length is sometimes omitted),
as MOVE senders and receivers (literals, items, other references, SPACES, ZEROS, ALL literals), DISPLAY operands and
operands of IF relations (``=``, ``NOT =``, ``>``, ``<``, ``>=``, ``<=`` against literals, items, references, SPACES and
ZEROS). Standard output must be identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. RMD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TA PIC X(10) VALUE 'ABCDEFGHIJ'.
       01 TB PIC X(10) VALUE '0123456789'.
       01 TC PIC X(6) VALUE 'uvwxyz'.
       01 NUM PIC 9(6) VALUE 120345.
       01 VN PIC 99 VALUE 1.
       01 VL PIC 99 VALUE 1.
       PROCEDURE DIVISION.
       MAIN.
"""

ALNUM = {"TA": 10, "TB": 10, "TC": 6}
BASES = {**ALNUM, "NUM": 6}
ALPHABET = "abcXYZ019 *-"


def _literal(rng: random.Random) -> str:
    return "'" + "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 12))) + "'"


def _reference(rng: random.Random, names: dict[str, int], lines: list[str]) -> str:
    """A reference modification that is in range; variable forms first load VN / VL (which they use) into range."""
    name = rng.choice(sorted(names))
    size = names[name]
    form = rng.choice(["lit", "lit", "var", "expr", "rest"])
    if form == "lit":
        start = rng.randint(1, size)
        length = rng.randint(1, size - start + 1)
        return f"{name}({start}:{length})"
    if form == "rest":
        return f"{name}({rng.randint(1, size)}:)"
    start = rng.randint(1, 3)
    length = rng.randint(1, 3)
    if form == "var":
        lines += [f"           MOVE {start} TO VN", f"           MOVE {length} TO VL"]
        return f"{name}(VN:VL)"
    lines += [f"           MOVE {start} TO VN", f"           MOVE {length} TO VL"]
    return f"{name}(VN + 1:VL)"  # 2..4 + 1..3 - 1 <= 6: in range for every base


def _program(rng: random.Random) -> str:
    lines = HEAD.rstrip("\n").split("\n")
    for step in range(rng.randint(6, 14)):
        kind = rng.choice(["move_ref", "move_into", "move_into", "display", "display", "if", "figurative", "move_field"])
        label = f"s{step}"
        if kind == "move_ref":
            source = _reference(rng, BASES, lines)
            target = rng.choice(sorted(ALNUM))
            lines.append(f"           MOVE {source} TO {target}")
        elif kind == "move_into":
            target = _reference(rng, ALNUM, lines)
            source = rng.choice([_literal(rng), rng.choice(sorted(ALNUM)), _reference(rng, BASES, lines)])
            lines.append(f"           MOVE {source} TO {target}")
        elif kind == "figurative":
            target = _reference(rng, ALNUM, lines)
            lines.append(f"           MOVE {rng.choice(['SPACES', 'ZEROS', 'ALL ' + chr(39) + 'ab' + chr(39), 'ALL ' + chr(39) + '*' + chr(39)])} TO {target}")
        elif kind == "move_field":
            lines.append(f"           MOVE {rng.choice([_literal(rng), 'TC', 'TB'])} TO {rng.choice(sorted(ALNUM))}")
        elif kind == "display":
            operand = _reference(rng, BASES, lines)
            lines.append(f"           DISPLAY '{label}[' {operand} ']'")
        else:
            left = _reference(rng, BASES, lines)
            relation = rng.choice(["=", "=", "NOT =", ">", "<", ">=", "<="])
            right = rng.choice([_literal(rng), _literal(rng), rng.choice(sorted(ALNUM)), "SPACES", "ZEROS"])
            if rng.random() < 0.3:
                right = _reference(rng, ALNUM, lines)
            lines += [f"           IF {left} {relation} {right}", f"               DISPLAY '{label} yes'",
                      "           ELSE", f"               DISPLAY '{label} no'", "           END-IF"]
    lines += ["           DISPLAY '[' TA '][' TB '][' TC ']'", "           STOP RUN."]
    wrapped: list[str] = []
    for line in lines:
        while len(line) > 72:
            cut = line.rfind(" ", 0, 70)
            wrapped.append(line[:cut])
            line = "               " + line[cut:].lstrip()
        wrapped.append(line)
    return "\n".join(wrapped) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [121, 122, 123, 124])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(91)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

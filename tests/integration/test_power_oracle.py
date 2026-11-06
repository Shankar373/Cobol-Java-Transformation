"""Roadmap unit 34 (Stage 1): exponentiation ``**`` in COMPUTE, GnuCOBOL 3.1.2 differential.

Generated programs COMPUTE random expression trees of ``+ - * / **`` and parentheses over integer and decimal items and
literals, with non-negative integer exponents (literals, an unsigned item, sums, nested powers), into receivers of different size,
sign and scale, plain, ROUNDED and with ON SIZE ERROR. Precedence (``**`` above ``* /``, right associativity, a unary sign
binding tighter than ``**``), exact results, high-order truncation, ROUNDED and the size-error branch must all match.
Negative exponents (GnuCOBOL 3.1.2 returns unstable values for them) and fractional ones (floating-point ``pow``) are
refused by the platform and are not generated.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. POW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9(3) VALUE 7.
       01 B PIC S9(3) VALUE -4.
       01 C PIC 9(2)V99 VALUE 12.50.
       01 D PIC S9(3)V99 VALUE -3.25.
       01 E PIC 9 VALUE 3.
       01 R1 PIC 9(5) VALUE 0.
       01 R2 PIC S9(5) VALUE 0.
       01 R3 PIC S9(5)V99 VALUE 0.
       01 R4 PIC 9(3)V9 VALUE 0.
       01 R5 PIC S99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
"""

ITEMS = ["A", "B", "C", "D"]
RECEIVERS = ["R1", "R2", "R3", "R4", "R5"]


def _atom(rng: random.Random, nonzero: bool = False) -> str:
    kind = rng.choice(["int", "int", "dec", "item", "item"])
    if kind == "int":
        return str(rng.randint(1 if nonzero else 0, 9))
    if kind == "dec":
        return f"{rng.randint(1, 9)}.{rng.randint(1, 9)}"
    if nonzero:
        return rng.choice(["A", "C"])  # VALUE 7 / 12.50: never zero in these programs
    return rng.choice(ITEMS)


def _exponent(rng: random.Random, safe: bool = False) -> str:
    """A non-negative integer exponent (negative and fractional ones are refused by the platform). Under ON SIZE ERROR
    (``safe``) only a positive literal is generated: a run-time ``0 ** 0`` raises the size-error condition in GnuCOBOL
    yet stores 1, which the platform refuses to guess (the capability gate rejects such a statement)."""
    if safe:
        return str(rng.randint(1, 3))
    form = rng.choice(["lit", "lit", "lit", "item", "expr", "nested"])
    if form == "item":
        return "E"
    if form == "expr":
        return f"(E + {rng.randint(0, 2)})"
    if form == "nested":
        return f"{rng.randint(1, 2)} ** {rng.randint(0, 2)}"
    return str(rng.randint(0, 3))


def _expression(rng: random.Random, depth: int, safe: bool = False) -> str:
    if depth <= 0:
        return _atom(rng)
    kind = rng.choice(["pow", "pow", "pow", "bin", "paren", "neg", "div"])
    if kind == "pow":
        return f"{_atom(rng)} ** {_exponent(rng, safe)}"
    if kind == "bin":
        op = rng.choice(["+", "-", "*"])
        return f"{_expression(rng, depth - 1, safe)} {op} {_expression(rng, depth - 1, safe)}"
    if kind == "paren":
        inner = f"({_atom(rng)} {rng.choice(['+', '-', '*'])} {_atom(rng)})"
        return f"{inner} ** {_exponent(rng, safe)}"
    if kind == "div":
        # a power divided by (or dividing) a non-zero operand: exact decimal division of exact powers
        divisor_exponent = rng.randint(1 if safe else 0, 2)
        return rng.choice([f"{_atom(rng)} ** {_exponent(rng, safe)} / {_atom(rng, nonzero=True)}",
                           f"{_atom(rng, nonzero=True)} / {_atom(rng, nonzero=True)} ** {divisor_exponent}"])
    return f"-{_atom(rng)} ** {rng.randint(1 if safe else 0, 3)}"


def _program(rng: random.Random) -> str:
    lines = HEAD.rstrip("\n").split("\n")
    for step in range(rng.randint(5, 12)):
        receiver = rng.choice(RECEIVERS)
        sized = rng.random() < 0.3
        expression = _expression(rng, rng.randint(1, 3), safe=sized)
        rounded = " ROUNDED" if rng.random() < 0.25 else ""
        if sized:
            lines += [f"           COMPUTE {receiver}{rounded} = {expression}",
                      f"               ON SIZE ERROR DISPLAY 's{step} size'",
                      f"               NOT ON SIZE ERROR DISPLAY 's{step} ok'", "           END-COMPUTE"]
        else:
            lines.append(f"           COMPUTE {receiver}{rounded} = {expression}")
        lines.append(f"           DISPLAY 's{step} ' {receiver}")
    lines.append("           STOP RUN.")
    wrapped: list[str] = []
    for line in lines:
        while len(line) > 72:
            cut = line.rfind(" ", 0, 70)
            # a continuation line may not begin with ``*``/``**`` (it reads as a comment): keep the operator on the
            # line it follows
            while line[cut:].lstrip().startswith("*") and cut > 0:
                cut = line.rfind(" ", 0, cut)
            wrapped.append(line[:cut])
            line = "               " + line[cut:].lstrip()
        wrapped.append(line)
    return "\n".join(wrapped) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [151, 152, 153, 154])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(89)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

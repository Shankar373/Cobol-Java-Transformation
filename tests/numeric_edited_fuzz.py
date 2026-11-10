"""Random numeric-edited pictures and values for the oracle fuzz.

Shared by ``tests/integration/test_numeric_edited_oracle.py`` and the grammar
test (every picture generated here must be accepted by the parser: the
grammar covers exactly what the fuzz validates).
"""

from __future__ import annotations

import random
from decimal import Decimal

#: (picture, integer digits, scale, signed) of the sending item.
SENDERS = [
    ("S9(5)V99", 5, 2, True),
    ("9(5)V99", 5, 2, False),
    ("S9(3)", 3, 0, True),
    ("S9(2)V9(3)", 2, 3, True),
    ("9(4)", 4, 0, False),
    ("S9(7)V9", 7, 1, True),
]


def random_picture(rng: random.Random) -> str:
    lead = rng.choice(["", "", "$", "+", "-", "float$", "float+", "float-"])
    trail = rng.choice(["", "", "", "+", "-", "CR", "DB"])
    if lead in ("+", "-", "float+", "float-") and trail:
        trail = ""
    kind = rng.choice(["Z", "Z", "*", "9", "9"]) if not lead.startswith("float") else "9"

    def insertion() -> str:
        return rng.choice([",", ",", "B", "0", "/"])

    parts: list[str] = []
    if lead.startswith("float"):
        symbol = lead[-1]
        parts.append(symbol)
        for _ in range(rng.randint(2, 4) - 1):
            if rng.random() < 0.25:
                parts.append(",")
            parts.append(symbol)
    elif lead:
        parts.append(lead)
    suppressed = rng.randint(0, 4) if kind in ("Z", "*") else 0
    nines = rng.randint(1 if not suppressed or rng.random() < 0.8 else 0, 4)
    digits = [kind] * suppressed + ["9"] * nines or ["9"]
    for index, digit in enumerate(digits):
        if index and rng.random() < 0.2:
            parts.append(insertion())
        parts.append(digit)
    if rng.random() < 0.65:
        parts.append(rng.choice([".", ".", "V"]))
        parts.extend(["9"] * rng.randint(1, 3))
    parts.append(trail)
    return "".join(parts)


def random_value(rng: random.Random, integers: int, scale: int, signed: bool) -> str:
    roll = rng.random()
    if roll < 0.12:
        return "0"
    digits = rng.randint(1, integers)
    value = Decimal(rng.randint(0, 10 ** digits - 1))
    if scale:
        value += Decimal(rng.randint(0, 10 ** scale - 1)) / (10 ** scale)
    if roll > 0.88:  # the largest value the sender holds
        value = Decimal(10 ** integers - 1) + (
            Decimal(10 ** scale - 1) / 10 ** scale if scale else 0
        )
    if signed and rng.random() < 0.5:
        value = -value
    return format(value, "f")

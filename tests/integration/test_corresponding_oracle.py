"""Roadmap unit 41 (Stage 1): MOVE / ADD / SUBTRACT CORRESPONDING, GnuCOBOL 3.1.2 differential.

Generated programs declare two to three groups with overlapping field names, nested subgroups of the same name,
different sizes and kinds (alphanumeric, unsigned, signed and decimal numeric), names that exist in one group only and
names that sit at a different level in the other (these must not correspond). They run MOVE, ADD and SUBTRACT
CORRESPONDING between the groups and display every field. Standard output must be identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

NAMES = ("AMT", "QTY", "CDX", "DESC", "RATE", "TOT")
# a name keeps its class in every group: moving a decimal number into text is refused by the platform
TEXT_NAMES = {"CDX", "DESC"}
KINDS = {
    "n3": "PIC 9(3)", "n5": "PIC 9(5)", "sd": "PIC S9(3)V99", "x4": "PIC X(4)", "x8": "PIC X(8)",
}


def _kind(rng: random.Random, name: str) -> str:
    return rng.choice(["x4", "x8"] if name in TEXT_NAMES else ["n3", "n5", "sd"])


def _program(rng: random.Random) -> tuple[str, list[str]]:
    groups: dict[str, list[tuple[str, int, str, str]]] = {}
    declarations: list[str] = []
    for gi in range(rng.randint(2, 3)):
        group = f"GRP{gi + 1}"
        declarations.append(f"       01 {group}.")
        flat: list[tuple[str, int, str, str]] = []
        direct = rng.sample(NAMES, rng.randint(2, 4))
        for name in direct:
            kind = _kind(rng, name)
            declarations.append(f"          05 {name} {KINDS[kind]}{_value(kind)}.")
            flat.append((name, 5, kind, ""))
        if rng.random() < 0.7:
            declarations.append("          05 SUBG.")
            # a name is directly under a group or in its subgroup, never both (``A OF G`` would be ambiguous)
            rest = [n for n in NAMES if n not in direct]
            for name in rng.sample(rest, min(len(rest), rng.randint(1, 3))):
                kind = _kind(rng, name)
                declarations.append(f"             10 {name} {KINDS[kind]}{_value(kind)}.")
                flat.append((name, 10, kind, "SUBG"))
        groups[group] = flat
    lines = [
        "       IDENTIFICATION DIVISION.", "       PROGRAM-ID. COR.", "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.", *declarations, "       PROCEDURE DIVISION.", "       MAIN.",
    ]
    names = list(groups)
    shown: list[str] = []
    for step in range(rng.randint(3, 6)):
        source, target = rng.sample(names, 2)
        verb = rng.choice(["MOVE", "MOVE", "ADD", "SUBTRACT"])
        if not _pairs(groups, source, target, numeric=verb != "MOVE"):
            continue  # GnuCOBOL rejects a CORRESPONDING statement without a corresponding pair
        word = rng.choice(["CORRESPONDING", "CORR"])
        if verb == "SUBTRACT":
            lines.append(f"           SUBTRACT {word} {source} FROM {target}")
        else:
            lines.append(f"           {verb} {word} {source} TO {target}")
        lines.append(f"           DISPLAY 's{step} ' {_display(groups, target)}")
        shown.append(target)
    for name in names:
        lines.append(f"           DISPLAY 'end {name} ' {_display(groups, name)}")
    lines.append("           STOP RUN.")
    wrapped: list[str] = []
    for line in lines:
        while len(line) > 72:
            cut = line.rfind(" ", 0, 70)
            while cut > 0 and line[:cut].count("'") % 2:  # never cut inside a quoted literal
                cut = line.rfind(" ", 0, cut)
            wrapped.append(line[:cut])
            line = "               " + line[cut:].lstrip()
        wrapped.append(line)
    return "\n".join(wrapped) + "\n", shown


def _pairs(groups, source: str, target: str, *, numeric: bool) -> bool:
    a = {(name, sub): kind for name, _level, kind, sub in groups[source]}
    b = {(name, sub): kind for name, _level, kind, sub in groups[target]}
    return any(key in b and (not numeric or (a[key][0] in "ns" and b[key][0] in "ns")) for key in a)


def _value(kind: str) -> str:
    return " VALUE 'ab'" if kind.startswith("x") else {"n3": " VALUE 17", "n5": " VALUE 40000", "sd": " VALUE 12.5"}[kind]


def _display(groups, group: str) -> str:
    """The elementary items of a group (a signed decimal item cannot be shown through its group)."""
    parts = []
    for name, _level, _kind, sub in groups[group]:
        parts.append(f"{name} OF {sub} OF {group}" if sub else f"{name} OF {group}")
    return " ' ' ".join(parts)


@needs_docker
@pytest.mark.parametrize("seed", [601, 602, 603, 604])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng)[0] for _ in range(20)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(95)
    for _ in range(200):
        for line in _program(rng)[0].splitlines():
            assert len(line) <= 72, line

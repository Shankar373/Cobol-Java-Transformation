"""Roadmap unit 31 (Stage 1): CONTINUE, EXIT PERFORM and DISPLAY ... WITH NO ADVANCING, GnuCOBOL 3.1.2 differential.

Generated programs nest inline PERFORM loops (UNTIL, TIMES and VARYING, up to three deep) around IF / EVALUATE
statements whose arms are CONTINUE or ordinary statements, leave the loops with EXIT PERFORM from random nesting depths
(also inside IF and EVALUATE arms) and display with and without NO ADVANCING. Standard output must be byte-identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SMALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 VA PIC 99 VALUE 0.
       01 VB PIC 99 VALUE 0.
       01 VC PIC 99 VALUE 0.
       01 C1 PIC 99 VALUE 0.
       01 C2 PIC 99 VALUE 0.
       01 C3 PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
"""

VARS = ["VA", "VB", "VC"]
COUNTERS = ["C1", "C2", "C3"]


class _Gen:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.tag = 0

    def label(self) -> str:
        self.tag += 1
        return f"t{self.tag}"

    def display(self, pad: str) -> str:
        rng = self.rng
        tail = " WITH NO ADVANCING" if rng.random() < 0.4 else ""
        if rng.random() < 0.5:
            return f"{pad}DISPLAY '{self.label()}'{tail}"
        return f"{pad}DISPLAY '{self.label()}=' {rng.choice(VARS)}{tail}"

    def condition(self) -> str:
        rng = self.rng
        return f"{rng.choice(VARS)} {rng.choice(['=', '>', '<', 'NOT ='])} {rng.randint(0, 6)}"

    def block(self, pad: str, depth: int, loops: int) -> list[str]:
        rng = self.rng
        out: list[str] = []
        for _ in range(rng.randint(1, 3)):
            kind = rng.choice(["display", "display", "add", "if", "if", "evaluate", "loop", "exit", "continue"])
            if kind == "display":
                out.append(self.display(pad))
            elif kind == "add":
                out.append(f"{pad}ADD {rng.randint(1, 3)} TO {rng.choice(VARS)}")
            elif kind == "continue":
                out.append(f"{pad}CONTINUE")
            elif kind == "exit" and loops:
                out += [f"{pad}IF {self.condition()}", f"{pad}  EXIT PERFORM", f"{pad}END-IF"]
            elif kind == "if" and depth < 4:
                out.append(f"{pad}IF {self.condition()}")
                out += self.arm(pad + "  ", depth + 1, loops)
                if rng.random() < 0.6:
                    out.append(f"{pad}ELSE")
                    out += self.arm(pad + "  ", depth + 1, loops)
                out.append(f"{pad}END-IF")
            elif kind == "evaluate" and depth < 4:
                out.append(f"{pad}EVALUATE {rng.choice(VARS)}")
                for value in sorted(rng.sample(range(0, 7), rng.randint(1, 3))):
                    out.append(f"{pad}  WHEN {value}")
                    out += self.arm(pad + "    ", depth + 1, loops)
                out.append(f"{pad}  WHEN OTHER")
                out += self.arm(pad + "    ", depth + 1, loops)
                out.append(f"{pad}END-EVALUATE")
            elif kind == "loop" and loops < 3 and depth < 4:
                out += self.loop(pad, depth + 1, loops)
            else:
                out.append(self.display(pad))
        return out

    def arm(self, pad: str, depth: int, loops: int) -> list[str]:
        if self.rng.random() < 0.3:
            return [f"{pad}CONTINUE"]
        return self.block(pad, depth, loops)

    def loop(self, pad: str, depth: int, loops: int) -> list[str]:
        rng = self.rng
        counter = COUNTERS[loops]
        shape = rng.choice(["until", "times", "varying"])
        limit = rng.randint(2, 4)
        if shape == "until":
            head = [f"{pad}MOVE 0 TO {counter}", f"{pad}PERFORM UNTIL {counter} > {limit}",
                    f"{pad}  ADD 1 TO {counter}"]
        elif shape == "times":
            head = [f"{pad}PERFORM {limit} TIMES"]
        else:
            head = [f"{pad}PERFORM VARYING {counter} FROM 1 BY 1 UNTIL {counter} > {limit}"]
        body = self.block(pad + "  ", depth, loops + 1)
        return head + body + [f"{pad}END-PERFORM"]


def _program(rng: random.Random) -> str:
    gen = _Gen(rng)
    lines = HEAD.rstrip("\n").split("\n")
    lines += [f"           MOVE {rng.randint(0, 4)} TO {name}" for name in VARS]
    for _ in range(rng.randint(2, 4)):
        lines += gen.block("           ", 0, 0)
    lines += ["           DISPLAY 'END ' VA ' ' VB ' ' VC", "           STOP RUN."]
    return "\n".join(lines) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [111, 112, 113, 114])
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

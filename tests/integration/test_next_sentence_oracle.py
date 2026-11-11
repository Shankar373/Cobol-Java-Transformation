"""NEXT SENTENCE differential: seeded sentences, GnuCOBOL 3.1.2 vs the generated Java (same output bytes).

Each program holds a few sentences of the certified shape (a single IF ... ELSE whose branch ends in NEXT SENTENCE, written
inline or over several lines, in the THEN or the ELSE branch, after plain statements, or a bare NEXT SENTENCE), each
followed by a DISPLAY sentence that only runs when the jump lands after the period, for every value of the tested items.
Shapes outside it are refused by name (``tests/test_next_sentence.py``); the parser mis-lowers plain CONTINUE in a nested
IF ... ELSE ... ELSE and in an EVALUATE arm, which is why those are not routed through this rewrite.
"""

from __future__ import annotations

import random

import pytest

from engine.transformation.cobol_parser import CobolParser
from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9 VALUE {a}.
       01 B PIC 9 VALUE {b}.
       01 N PIC 99 VALUE 0.
       PROCEDURE DIVISION.
"""


def _sentence(rng: random.Random, index: int) -> str:
    cond = f"{rng.choice('AB')} {rng.choice(['=', '>', '<', '>=', 'NOT ='])} {rng.randint(0, 2)}"
    work = f'DISPLAY "W{index} " N'
    shape = rng.randrange(5)
    pre = f'           MOVE {rng.randint(0, 9)} TO N\n' if rng.random() < 0.4 else ""
    if shape == 0:
        body = f"           IF {cond} NEXT SENTENCE ELSE {work}.\n"
    elif shape == 1:
        body = f"           IF {cond}\n               NEXT SENTENCE\n           ELSE\n               {work}.\n"
    elif shape == 2:
        body = f"           IF {cond}\n               {work}\n           ELSE\n               NEXT SENTENCE.\n"
    elif shape == 3:
        body = f"           IF {cond} {work} ELSE NEXT SENTENCE.\n"
    else:
        body = f'           NEXT SENTENCE.\n           DISPLAY "BARE{index}".\n'
    return f'{pre}{body}           DISPLAY "S{index} " N.\n'


def _program(rng: random.Random) -> str:
    sentences = "".join(_sentence(rng, i) for i in range(rng.randint(2, 5)))
    return HEAD.format(a=rng.randint(0, 2), b=rng.randint(0, 2)) + sentences + "           STOP RUN.\n"


SEEDS = [11, 12, 13]


@needs_docker
@pytest.mark.parametrize("seed", SEEDS)
def test_next_sentence_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(20)]
    differing = [i for i, (cobol, java) in enumerate(run_batch(tmp_path, programs)) if cobol != java]
    assert differing == []


def test_the_generated_programs_are_inside_the_gate():
    for seed in SEEDS:
        rng = random.Random(seed)
        for _ in range(20):
            parser = CobolParser()
            parser.parse(_program(rng))
            assert not [d for d in parser.diagnostics.all if "NEXT SENTENCE" in d.message]

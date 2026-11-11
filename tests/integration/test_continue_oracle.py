"""CONTINUE inside nested IF ... ELSE ... ELSE and EVALUATE arms: GnuCOBOL 3.1.2 vs the generated Java.

Two parser defects this pins (both found while proving NEXT SENTENCE): the second ELSE of a nested
``IF a IF b x ELSE y ELSE z`` was swallowed by the inner IF, and ``WHEN 1 CONTINUE`` was stacked with the next WHEN so the
arm ran the next arm's statements.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC 9 VALUE {a}.
       01 B PIC 9 VALUE {b}.
       PROCEDURE DIVISION.
"""


def _cond(rng):
    return f"{rng.choice('AB')} {rng.choice(['=', '>', '<', 'NOT ='])} {rng.randint(0, 2)}"


def _stmt(rng, tag):
    return "CONTINUE" if rng.random() < 0.5 else f'DISPLAY "{tag}"'


def _sentence(rng, n):
    kind = rng.randrange(4)
    if kind == 0:  # nested IF with both ELSEs
        body = (f"           IF {_cond(rng)}\n               IF {_cond(rng)}\n                   {_stmt(rng, f'T{n}')}\n"
                f"               ELSE\n                   {_stmt(rng, f'IE{n}')}\n           ELSE\n"
                f"               {_stmt(rng, f'OE{n}')}.\n")
    elif kind == 1:  # nested IF, one ELSE: it belongs to the inner IF
        body = (f"           IF {_cond(rng)}\n               IF {_cond(rng)}\n                   {_stmt(rng, f'T{n}')}\n"
                f"               ELSE\n                   {_stmt(rng, f'IE{n}')}.\n")
    elif kind == 2:  # EVALUATE ending at the period
        arms = "".join(f"               WHEN {v} {_stmt(rng, f'W{n}{v}')}\n" for v in range(rng.randint(1, 3)))
        body = f"           EVALUATE {rng.choice('AB')}\n{arms}               WHEN OTHER {_stmt(rng, f'O{n}')}.\n"
    else:  # EVALUATE with END-EVALUATE and arms on their own lines
        arms = "".join(f"               WHEN {v}\n                   {_stmt(rng, f'W{n}{v}')}\n" for v in range(rng.randint(1, 3)))
        body = (f"           EVALUATE {rng.choice('AB')}\n{arms}               WHEN OTHER\n"
                f"                   {_stmt(rng, f'O{n}')}\n           END-EVALUATE\n           DISPLAY \"E{n}\".\n")
    return body + f'           DISPLAY "S{n}".\n'


def _program(rng):
    sentences = "".join(_sentence(rng, i) for i in range(rng.randint(2, 4)))
    return HEAD.format(a=rng.randint(0, 2), b=rng.randint(0, 2)) + sentences + "           STOP RUN.\n"


SEEDS = [31, 32, 33]


@needs_docker
@pytest.mark.parametrize("seed", SEEDS)
def test_continue_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(20)]
    differing = [i for i, (cobol, java) in enumerate(run_batch(tmp_path, programs)) if cobol != java]
    assert differing == []

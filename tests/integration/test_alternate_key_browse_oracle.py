"""Alternate-key browsing (START / READ NEXT on a file with alternate keys), GnuCOBOL 3.1.2 differential.

Seeded programs mix keyed READs (primary and alternate), START, READ NEXT, REWRITE, DELETE and WRITE on a file with a
primary key and two alternate keys (one WITH DUPLICATES, one unique), every field ``PIC X(2)``, ACCESS MODE DYNAMIC,
FILE STATUS only. The generated Java and GnuCOBOL must print the same bytes, and the capability gate must accept each
program (``engine/transformation/alternate_key.py``), so this is the product path and not a lifted switch.

Evidence behind the certification: 18 seeds of 25 programs (501-506, 601-606, 701-706), 450 programs, 0 mismatches with
the final lowering; the per-seed record (program, GnuCOBOL and Java output hashes) is in
``docs/audits/evidence/alternate_key_browse_sweep_2026-11-11.json``. Seeds 701-706 were run before any fix had seen
them. The CI lane runs a subset of them (a seed takes about 70 seconds).

Position rules the sweeps established, each of which also differs from what the Java model first did:

* OPEN INPUT / I-O puts the primary cursor on the first record, unread (``test_indexed_open_position_oracle.py``);
* the end-of-file condition survives a failed keyed READ and holds for the file whatever the key;
* a successful alternate READ, or a READ NEXT that returns a record along an alternate key, consumes that primary
  position; a successful primary READ consumes a pending alternate START;
* a failed alternate READ leaves the cursor where it was (a START-selected entry stays unread, a returned one stays
  consumed); a failed primary READ with an alternate START pending puts the primary cursor back on its current record,
  unread;
* a record whose alternate value changed after the START selected it (REWRITE) has left the entry: the READ NEXT
  continues after the entry's old place, like after a DELETE.

Outside the shape browsing stays refused by name (``tests/test_alternate_key.py``): other access modes, one or three
alternate keys, other key widths or record shapes, OPEN INPUT / EXTEND, AT END / INVALID KEY phrases, READ INTO, and the
START operators the sweeps did not cover.
"""

from __future__ import annotations

import random

import pytest

from engine.transformation.alternate_key import alternate_key_problem
from engine.transformation.cobol_parser import CobolParser
from tests.batch_oracle import images_available, run_batch
from tests.integration.test_alternate_key_oracle import _program

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

#: the CI subset of the 18 swept seeds (tuned, tuned-then-held-out and never-tuned-against)
SEEDS = [501, 502, 603, 604, 701, 702]


@needs_docker
@pytest.mark.parametrize("seed", SEEDS)
def test_browsing_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng, browsing=True) for _ in range(25)]
    differing = [i for i, (cobol, java) in enumerate(run_batch(tmp_path, programs)) if cobol != java]
    assert differing == []


def test_the_swept_programs_are_inside_the_gate():
    """The generator and the gate agree on the proven shape: no swept program is refused."""
    for seed in SEEDS:
        rng = random.Random(seed)
        for _ in range(25):
            parser = CobolParser()
            program = parser.parse(_program(rng, browsing=True))
            assert alternate_key_problem(program, program.file_definitions[0]) == ""

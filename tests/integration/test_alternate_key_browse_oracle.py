"""Alternate-key browsing (START / READ NEXT on a file with alternate keys): the frontier, not a certification.

Browsing is refused by the capability gate (``engine/transformation/alternate_key.py``) because the generated Java
still differs from GnuCOBOL 3.1.2 on a few programs. This test lifts the gate for the sweep, runs seeded programs that
mix keyed READs, START and READ NEXT on a file with a primary key and two alternate keys, and pins the exact programs
that still differ. It therefore fails both when a regression adds a divergence and when a fix removes one (then update
``KNOWN_DIVERGENT`` and, once it is empty for a wide set of seeds, remove the gate).

Rules the sweep established (each also pinned for primary-only files in ``test_indexed_open_position_oracle.py``):
OPEN puts the cursor on the first record, unread; a successful alternate READ consumes that position; a failed
alternate READ leaves the cursor of its key where it was (a START-selected entry stays unread, a returned one stays
consumed); the end-of-file condition survives a failed keyed READ and holds whatever the key.

Open, with the shortest known cases: after ``START ... KEY AKD`` and a ``READ NEXT``, a failed keyed READ makes
GnuCOBOL return the same record again while the Java model continues on the primary key (seed 503 program 1,
seed 504 program 8); seed 502 program 7 differs after a failed START followed by a keyed READ.
"""

from __future__ import annotations

import random

import pytest

import engine.transformation.alternate_key as alternate_key
from tests.batch_oracle import images_available, run_batch
from tests.integration.test_alternate_key_oracle import _program

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

#: seed -> indexes of the generated programs that still differ from the oracle
KNOWN_DIVERGENT = {501: [], 502: [7], 503: [1], 504: [8], 505: [], 506: []}


@needs_docker
@pytest.mark.parametrize("seed", sorted(KNOWN_DIVERGENT))
def test_browsing_frontier_is_pinned(tmp_path, monkeypatch, seed):
    monkeypatch.setattr(alternate_key, "BROWSING_GATE_ENABLED", False)
    rng = random.Random(seed)
    programs = [_program(rng, browsing=True) for _ in range(25)]
    differing = [i for i, (cobol, java) in enumerate(run_batch(tmp_path, programs)) if cobol != java]
    assert differing == KNOWN_DIVERGENT[seed]


def test_browsing_is_still_refused_by_default():
    assert alternate_key.BROWSING_GATE_ENABLED is True

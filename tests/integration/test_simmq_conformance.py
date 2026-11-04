"""Roadmap unit 14: the Java SIMMQ-1 library equals the Python reference model.

The same scripts run through both implementations -- fixed scenarios that cover every call and reason
code, plus seeded random scripts that deliberately include invalid options and handles -- and the
canonical traces must be identical line for line.  Equality earns ``SIMULATOR_VERIFIED``: equivalence to
the specification, not to IBM MQ.
"""

from __future__ import annotations

import os
import random
import subprocess

import pytest

from engine.simulators import SIMULATOR_VERIFIED
from engine.simulators.mq import run_script
from engine.simulators.trace import JAVA_IMAGE, compare_traces, run_java_trace

FIXED = """QMGR QM1 Q1,Q2,Q3
CONN QM1
OPEN 1 Q1 18
PUT 1 1 6161 0
PUT 1 1 6262 2
CONN QM1
OPEN 2 Q1 2
DEPTH Q1
GET 2 2 10 0
CMIT 1
GET 2 2 1 64
GET 2 2 10 0
GET 2 2 10 0
BACK 1
OPEN 1 Q2 24
PUT 1 3 61 0
GET 1 3 10 16
GET 1 3 10 32
GET 1 3 10 32
OPEN 2 Q2 4
OPEN 2 NOPE 2
CLOSE 1 3
CLOSE 1 3
SETQ Q1 1 0 0
PUT 1 1 63 0
SETQ Q1 5 1 1
PUT 1 1 64 0
GET 2 2 10 0
DISC 1
DISC 1
GET 1 1 5 0
CONN OTHER
DISC 2
"""


def _image_present() -> bool:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        return False
    try:
        done = subprocess.run(["docker", "image", "inspect", JAVA_IMAGE], capture_output=True, timeout=60)
        return done.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_java = pytest.mark.skipif(not _image_present(), reason="set RUN_DOCKER_TESTS=1 with the Java image present")


def _fuzz(seed: int, steps: int = 220) -> str:
    """A random script that tracks the live handles through the model, so most calls are valid and
    a minority are deliberately invalid (wrong handle, bad option, wrong open mode)."""
    from engine.simulators.mq import SimMq, _step

    rng = random.Random(seed)
    mq = SimMq("QM1", ("Q1", "Q2", "Q3"))
    lines = ["QMGR QM1 Q1,Q2,Q3"]
    conns: list[int] = []
    objs: list[tuple[int, int]] = []

    def emit(line: str) -> str:
        op, *args = line.split(" ")
        result = _step(mq, op, args)
        lines.append(line)
        return result

    def conn() -> int:
        return rng.choice(conns) if conns and rng.random() < 0.9 else rng.choice([1, 9])

    def handle() -> tuple[int, int]:
        if objs and rng.random() < 0.9:
            return rng.choice(objs)
        return rng.choice([1, 2, 9]), rng.choice([1, 4, 9])

    queues = ["Q1", "Q2", "Q3", "Q1", "Q2", "NOPE"]
    for _ in range(steps):
        kind = rng.choices(
            ["CONN", "OPEN", "PUT", "GET", "CLOSE", "CMIT", "BACK", "DISC", "SETQ", "DEPTH"],
            [5, 12, 24, 22, 4, 6, 6, 2, 8, 4])[0]
        if kind == "CONN":
            result = emit(rng.choice(["CONN QM1", "CONN QM1", "CONN", "CONN XX"]))
            hconn = int(result.split("h=")[1])
            if result.startswith("0 0") and hconn:
                conns.append(hconn)
        elif kind == "OPEN":
            c = conn()
            options = rng.choice([2, 4, 8, 16, 18, 24, 10, 16, 18, 0, 1, 6, 20, 64])
            result = emit(f"OPEN {c} {rng.choice(queues)} {options}")
            hobj = int(result.split("h=")[1])
            if result.startswith("0 0") and hobj:
                objs.append((c, hobj))
        elif kind == "PUT":
            c, o = handle()
            data = rng.choice(["-", "61", "6162", "616263", "68656c6c6f", "00ff"])
            emit(f"PUT {c} {o} {data} {rng.choice([0, 0, 2, 4, 6, 8])}")
        elif kind == "GET":
            c, o = handle()
            emit(f"GET {c} {o} {rng.choice([0, 1, 2, 5, 10])} "
                 f"{rng.choice([0, 0, 0, 1, 2, 4, 16, 32, 64, 66, 3, 48, 128])}")
        elif kind == "CLOSE":
            c, o = handle()
            result = emit(f"CLOSE {c} {o}")
            if result == "0 0" and (c, o) in objs:
                objs.remove((c, o))
        elif kind in ("CMIT", "BACK"):
            emit(f"{kind} {conn()}")
        elif kind == "DISC":
            c = conn()
            result = emit(f"DISC {c}")
            if result == "0 0":
                conns.remove(c)
                objs[:] = [pair for pair in objs if pair[0] != c]
        elif kind == "SETQ":
            emit(f"SETQ {rng.choice(queues[:3])} {rng.choice([1, 2, 3, 5000, 5000])} "
                 f"{rng.choice([0, 0, 0, 0, 1])} {rng.choice([0, 0, 0, 0, 1])}")
        else:
            emit(f"DEPTH {rng.choice(queues[:3])}")
    return "\n".join(lines) + "\n"


def _assert_conformant(script: str) -> None:
    reference = run_script(script)
    candidate = run_java_trace(script)
    diff = compare_traces(reference, candidate)
    assert diff.equal, f"line {diff.index}: python={diff.left!r} java={diff.right!r}"
    assert diff.verdict == SIMULATOR_VERIFIED


@needs_java
def test_the_fixed_scenarios_conform():
    _assert_conformant(FIXED)


@needs_java
def test_seeded_random_scripts_conform():
    # one JVM run: every QMGR line starts a fresh queue manager
    script = "".join(_fuzz(seed) for seed in range(1, 13))
    assert script.count("QMGR") == 12 and len(script.splitlines()) > 2500
    _assert_conformant(script)


@needs_java
@pytest.mark.parametrize("old,new", [
    ("RC_NO_MSG = 2033", "RC_NO_MSG = 2034"),
    ("if (m.owner != null && m.owner == hconn) continue;", "if (false) continue;"),
    ("h.cursor = (options & OPT_BROWSE_FIRST) != 0 ? 0 : h.cursor + 1;",
     "h.cursor = (options & OPT_BROWSE_FIRST) != 0 ? 0 : h.cursor + 2;"),
])
def test_a_divergent_java_library_is_detected(old, new):
    from engine.simulators.mq_java import SIMMQ_JAVA

    assert old in SIMMQ_JAVA
    script = FIXED + "".join(_fuzz(seed) for seed in range(1, 6))
    diff = compare_traces(run_script(script), run_java_trace(script, source=SIMMQ_JAVA.replace(old, new, 1)))
    assert not diff.equal and diff.verdict == "MISMATCH"


def test_the_fuzz_reaches_the_interesting_reason_codes():
    # hermetic guard: the generator really exercises the error paths it claims to
    trace = "\n".join(run_script("".join(_fuzz(seed) for seed in range(1, 13))))
    for fragment in ("2085", "2018", "2019", "2033", "2046", "2042", "2053", "2051", "2016", "2037",
                     "2039", "2079", "2080", "2058", "2036"):
        assert f" {fragment}" in trace, fragment

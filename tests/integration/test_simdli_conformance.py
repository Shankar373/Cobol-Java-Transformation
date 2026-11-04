"""Roadmap unit 15: the Java SIMDLI-1 library equals the Python reference model.

Fixed scenarios and seeded random scripts (valid and deliberately invalid calls) run through both
implementations; the canonical traces must be identical line for line.  Equality earns
``SIMULATOR_VERIFIED`` -- equivalence to the specification, not to IMS.
"""

from __future__ import annotations

import os
import random
import subprocess

import pytest

from engine.simulators import SIMULATOR_VERIFIED
from engine.simulators.dli import run_script
from engine.simulators.dli_java import SIMDLI_JAVA
from engine.simulators.trace import JAVA_IMAGE, compare_traces, run_java_script

DBD = "DBD COMPANY::2:10 DEPT:COMPANY:2:8 EMP:DEPT:3:12 PROJ:DEPT:2:6"

FIXED = DBD + """
ISRT COMPANY ACMECORP01
ISRT COMPANY(=AC)/DEPT D2LEGAL1
ISRT COMPANY(=AC)/DEPT D1SALES1
ISRT COMPANY(=AC)/DEPT(=D1)/PROJ P1ALPH
ISRT COMPANY(=AC)/DEPT(=D1)/PROJ A1BETA
ISRT COMPANY(=AC)/DEPT(=D1)/EMP E02JONES0002
ISRT COMPANY(=AC)/DEPT(=D1)/EMP E01SMITH0001
ISRT COMPANY(=AC)/DEPT(=D1)/EMP E01SMITH0001
ISRT COMPANY(=ZZ)/DEPT D3XXXXXX
GU COMPANY(=AC)/DEPT(=D1)
GNP
GNP
GNP
GNP
GN
GN
GN
GU COMPANY(=AC)/DEPT(=D1)/EMP(=E01)
REPL E01SMITH0099
REPL E09SMITH0099
DLET
DLET
GN EMP
GN EMP
GU COMPANY(=AC)/DEPT(=D1)
DLET
GU COMPANY(=AC)/DEPT(=D1)
GN
GU COMPANY(=AC)/EMP(=E01)
FOO
"""

KEYS = {"COMPANY": ["AA", "BB"], "DEPT": ["D1", "D2", "D3"], "EMP": ["E01", "E02", "E03"],
        "PROJ": ["A1", "A2"]}
PARENT = {"COMPANY": "", "DEPT": "COMPANY", "EMP": "DEPT", "PROJ": "DEPT"}
DATA_LEN = {"COMPANY": 10, "DEPT": 8, "EMP": 12, "PROJ": 6}


def _image_present() -> bool:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        return False
    try:
        done = subprocess.run(["docker", "image", "inspect", JAVA_IMAGE], capture_output=True, timeout=60)
        return done.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_java = pytest.mark.skipif(not _image_present(), reason="set RUN_DOCKER_TESTS=1 with the Java image present")


def _data(rng: random.Random, name: str, key: str) -> str:
    return (key + "".join(rng.choice("0123456789ABCDEF") for _ in range(DATA_LEN[name])))[: DATA_LEN[name]]


def _path(rng: random.Random, name: str, qualify_last: bool, valid: bool = True) -> list[str]:
    chain = []
    cursor = name
    while cursor:
        chain.append(cursor)
        cursor = PARENT[cursor]
    chain.reverse()
    parts = []
    for i, seg in enumerate(chain):
        last = i == len(chain) - 1
        if last and not qualify_last:
            parts.append(seg)
        elif rng.random() < (0.93 if valid else 0.5):
            parts.append(f"{seg}(={rng.choice(KEYS[seg])})")
        else:
            parts.append(seg)
    return parts


def _fuzz(seed: int, steps: int = 240) -> str:
    rng = random.Random(seed)
    lines = [DBD]
    for _ in range(steps):
        kind = rng.choices(["ISRT", "GU", "GN", "GNP", "DLET", "REPL", "ODD"], [38, 14, 14, 12, 9, 9, 4])[0]
        if kind == "ISRT":
            name = rng.choices(list(KEYS), [3, 5, 8, 4])[0]
            key = rng.choice(KEYS[name])
            lines.append("ISRT " + "/".join(_path(rng, name, False)) + " " + _data(rng, name, key))
        elif kind == "GU":
            name = rng.choice(list(KEYS))
            lines.append("GU " + "/".join(_path(rng, name, rng.random() < 0.8, valid=rng.random() < 0.9)))
        elif kind in ("GN", "GNP"):
            lines.append(kind + rng.choice(["", "", " EMP", " PROJ", " DEPT", " COMPANY", " (=X"]))
        elif kind == "DLET":
            lines.append("DLET")
        elif kind == "REPL":
            name = rng.choice(list(KEYS))
            lines.append("REPL " + _data(rng, name, rng.choice(KEYS[name])))
        else:
            lines.append(rng.choice(["FOO", "GU", "GN A/B", "ISRT", "ISRT COMPANY", "REPL"]))
    return "\n".join(lines) + "\n"


def _assert_conformant(script: str) -> None:
    reference = run_script(script)
    candidate = run_java_script("SimDli", SIMDLI_JAVA, script)
    diff = compare_traces(reference, candidate)
    assert diff.equal, f"line {diff.index}: python={diff.left!r} java={diff.right!r}"
    assert diff.verdict == SIMULATOR_VERIFIED


@needs_java
def test_the_fixed_scenario_conforms():
    _assert_conformant(FIXED)


@needs_java
def test_seeded_random_scripts_conform():
    script = "".join(_fuzz(seed) for seed in range(1, 13))
    assert script.count("DBD ") == 12 and len(script.splitlines()) > 2800
    _assert_conformant(script)


@needs_java
@pytest.mark.parametrize("old,new", [
    ("return new Result(\"II\", null);", "return new Result(\"GE\", null);"),
    ("index = idx - 1;", "index = idx;"),
    ("if (!isDescendant(n, parent)) break;", "if (false) break;"),
    ("int c = Integer.compare(order.get(a.type.name), order.get(b.type.name));", "int c = 0;"),
])
def test_a_divergent_java_library_is_detected(old, new):
    assert old in SIMDLI_JAVA
    script = FIXED + "".join(_fuzz(seed) for seed in range(1, 6))
    diff = compare_traces(run_script(script),
                          run_java_script("SimDli", SIMDLI_JAVA.replace(old, new, 1), script))
    assert not diff.equal and diff.verdict == "MISMATCH"


def test_the_fuzz_reaches_every_status_code():
    trace = "\n".join(run_script("".join(_fuzz(seed) for seed in range(1, 13))))
    for status in (" -> OK", " -> GE", " -> GB", " -> GP", " -> II", " -> DJ", " -> DA", " -> AK", " -> AD"):
        assert status in trace, status
    assert " -> OK seg=" in trace

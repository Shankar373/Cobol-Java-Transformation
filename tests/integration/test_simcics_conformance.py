"""Roadmap unit 16: the Java SIMCICS-1 library equals the Python reference model.

Fixed scenarios and seeded random scripts (valid and deliberately invalid commands) run through both
implementations; the canonical traces must be identical line for line.  Equality earns
``SIMULATOR_VERIFIED`` -- equivalence to the specification, not to CICS.
"""

from __future__ import annotations

import os
import random
import subprocess

import pytest

from engine.simulators import SIMULATOR_VERIFIED
from engine.simulators.cics import run_script
from engine.simulators.cics_java import SIMCICS_JAVA
from engine.simulators.trace import JAVA_IMAGE, compare_traces, run_java_script

SETUP = "FILE ACCT 4 13 open\nFILE OLD 4 13 closed\nLOAD ACCT 0001ALICE0100\nLOAD ACCT 0003CAROL0300\n"

FIXED = SETUP + """READ ACCT 0001
READ ACCT 0002
READ ACCT 01
READ NOPE 0001
READ OLD 0001
WRITE ACCT 0002 0002BOB000200
WRITE ACCT 0002 0002BOB000200
WRITE ACCT 0005 0005XX
WRITE ACCT 0006 0007ERIC06000
READ ACCT 0001 UPDATE
REWRITE ACCT 0001ALICE0150
REWRITE ACCT 0001ALICE0151
READ ACCT 0003 UPDATE
DELETE ACCT
DELETE ACCT 0009
STARTBR ACCT 0002 GTEQ
READNEXT ACCT
READNEXT ACCT
READNEXT ACCT
ENDBR ACCT
STARTBR ACCT 0099 GTEQ
STARTBR ACCT 0002 EQUAL
STARTBR ACCT 0002 GTEQ
STARTBR ACCT 0002 GTEQ
READPREV ACCT
READPREV ACCT
READPREV ACCT
ENDBR ACCT
ENDBR ACCT
SYNCPOINT ROLLBACK
READ ACCT 0002
READ ACCT 0003
WRITEQ Q1 aaa
WRITEQ Q1 bbb
READQ Q1 NEXT
READQ Q1 NEXT
READQ Q1 NEXT
READQ Q1 2
READQ NOQ 1
DELETEQ Q1
DELETEQ Q1
SYNCPOINT ROLLBACK
READQ Q1 1
FROB ACCT
"""

KEYS = ["0001", "0002", "0003", "0004", "0005", "0006"]


def _image_present() -> bool:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        return False
    try:
        done = subprocess.run(["docker", "image", "inspect", JAVA_IMAGE], capture_output=True, timeout=60)
        return done.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_java = pytest.mark.skipif(not _image_present(), reason="set RUN_DOCKER_TESTS=1 with the Java image present")


def _record(rng: random.Random, key: str, valid: bool = True) -> str:
    body = "".join(rng.choice("ABCDEF0123456789") for _ in range(9))
    if not valid:
        return rng.choice([key + body[:5], key + body + "X", "9999" + body])
    return key + body


def _fuzz(seed: int, steps: int = 260) -> str:
    rng = random.Random(seed)
    lines = [SETUP.strip()]
    files = ["ACCT", "ACCT", "ACCT", "ACCT", "OLD", "NOPE"]
    for _ in range(steps):
        kind = rng.choices(
            ["READ", "WRITE", "REWRITE", "DELETE", "STARTBR", "READNEXT", "READPREV", "ENDBR", "WRITEQ",
             "READQ", "DELETEQ", "SYNC", "ODD"],
            [16, 14, 9, 8, 7, 11, 8, 6, 6, 8, 3, 8, 2])[0]
        file = rng.choice(files)
        key = rng.choice(KEYS)
        if kind == "READ":
            lines.append(f"READ {file} {rng.choice([key, key, key, key[:2]])}" + rng.choice(["", "", " UPDATE"]))
        elif kind == "WRITE":
            valid = rng.random() < 0.85
            data = _record(rng, key, valid)
            lines.append(f"WRITE {file} {key} {data}")
        elif kind == "REWRITE":
            lines.append(f"REWRITE {file} {_record(rng, rng.choice(KEYS), rng.random() < 0.85)}")
        elif kind == "DELETE":
            lines.append(f"DELETE {file}" + rng.choice(["", " " + key, " " + key, " 99"]))
        elif kind == "STARTBR":
            lines.append(f"STARTBR {file} {key} {rng.choice(['GTEQ', 'EQUAL'])}")
        elif kind in ("READNEXT", "READPREV", "ENDBR"):
            lines.append(f"{kind} {file}")
        elif kind == "WRITEQ":
            lines.append(f"WRITEQ {rng.choice(['Q1', 'Q2'])} {rng.choice(['aa', 'bbb', 'c'])}")
        elif kind == "READQ":
            lines.append(f"READQ {rng.choice(['Q1', 'Q2', 'NOQ'])} {rng.choice(['NEXT', 'NEXT', '1', '2', '3', '0'])}")
        elif kind == "DELETEQ":
            lines.append(f"DELETEQ {rng.choice(['Q1', 'Q2', 'NOQ'])}")
        elif kind == "SYNC":
            lines.append("SYNCPOINT" + rng.choice(["", " ROLLBACK", " ROLLBACK"]))
        else:
            lines.append(rng.choice(["FROB ACCT", "SYNCPOINT NOW"]))
    return "\n".join(lines) + "\n"


def _assert_conformant(script: str) -> None:
    reference = run_script(script)
    candidate = run_java_script("SimCics", SIMCICS_JAVA, script)
    diff = compare_traces(reference, candidate)
    assert diff.equal, f"line {diff.index}: python={diff.left!r} java={diff.right!r}"
    assert diff.verdict == SIMULATOR_VERIFIED


@needs_java
def test_the_fixed_scenario_conforms():
    _assert_conformant(FIXED)


@needs_java
def test_seeded_random_scripts_conform():
    # FILE lines redefine the files; temporary-storage queues carry over, identically in both
    script = "".join(_fuzz(seed) for seed in range(1, 13))
    assert len(script.splitlines()) > 3000
    _assert_conformant(script)


@needs_java
@pytest.mark.parametrize("old,new", [
    ("if (f.records.containsKey(key)) return DUPREC;", "if (false) return DUPREC;"),
    ("undo.push(() -> f.records.put(k, previous));", "undo.push(() -> { });"),
    ("String k = f.cursor == null ? f.records.ceilingKey(f.position) : f.records.higherKey(f.cursor);",
     "String k = f.cursor == null ? f.records.ceilingKey(f.position) : f.records.ceilingKey(f.cursor);"),
    ("for (FileDef f : files.values()) f.held = null;", ""),
])
def test_a_divergent_java_library_is_detected(old, new):
    assert old in SIMCICS_JAVA
    script = FIXED + "".join(_fuzz(seed) for seed in range(1, 6))
    diff = compare_traces(run_script(script),
                          run_java_script("SimCics", SIMCICS_JAVA.replace(old, new, 1), script))
    assert not diff.equal and diff.verdict == "MISMATCH"


def test_the_fuzz_reaches_every_resp_code():
    trace = "\n".join(run_script("".join(_fuzz(seed) for seed in range(1, 13))))
    for resp in (" -> NORMAL", " -> NOTFND", " -> DUPREC", " -> INVREQ", " -> NOTOPEN", " -> ENDFILE",
                 " -> LENGERR", " -> ITEMERR", " -> QIDERR", " -> FILENOTFOUND"):
        assert resp in trace, resp

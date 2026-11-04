"""GnuCOBOL oracle differential proof for INSPECT (certified literal subset).

Each program holds many independent blocks (load a field, run one INSPECT, DISPLAY the field
and the counter); the generated Java must print exactly what GnuCOBOL 3.1.2 prints.  Fixed
blocks pin the documented forms; a seeded fuzz draws TALLYING/REPLACING/CONVERTING statements
with several phrases, BEFORE/AFTER bounds, overlapping patterns and counter overflow, so
the mark-based scan order of the oracle is reproduced, not assumed.
"""

from __future__ import annotations

import random
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator

GNUCOBOL_IMAGE = "gnucobol-ocesql:latest"
JAVA_IMAGE = "eclipse-temurin:21-jdk"


def _images_available() -> bool:
    try:
        done = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                              capture_output=True, timeout=30)
        text = done.stdout.decode(errors="replace")
        return done.returncode == 0 and GNUCOBOL_IMAGE in text and JAVA_IMAGE in text
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(not _images_available(), reason="docker images unavailable")


def _program(blocks: list[str]) -> str:
    body = "\n".join(blocks)
    return textwrap.dedent("""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. INSPTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 F PIC X(12).
        01 C PIC 9(3).
        01 S PIC 9(1).
        PROCEDURE DIVISION.
        MAIN.
        """) + body + "\n    STOP RUN.\n"


def _oracle(tmp: Path, source: str) -> list[str]:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "t.cob").write_text(source, encoding="utf-8")
    done = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{tmp}:/src", "-w", "/src", GNUCOBOL_IMAGE,
         "bash", "-c", "cobc -free -x -o t t.cob && ./t"], capture_output=True, timeout=240)
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    return done.stdout.decode().splitlines()


def _java(tmp: Path, source: str) -> list[str]:
    generated = JavaGenerator().generate(CobolParser().parse(source))[0]
    name = re.search(r"public\s+class\s+(\w+)", generated.source_code).group(1)
    out = tmp / "java"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.java").write_text(generated.source_code, encoding="utf-8", newline="\n")
    done = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{out}:/app", "-w", "/app", JAVA_IMAGE,
         "bash", "-c", f"javac {name}.java && java {name}"], capture_output=True, timeout=240)
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    return done.stdout.decode().splitlines()


def _block(index: int, data: str, statement: str) -> str:
    return (f'    MOVE "{data}" TO F.\n    MOVE 0 TO C.\n    MOVE 0 TO S.\n'
            f"    {statement}\n"
            f'    DISPLAY "{index}:" F "|" C "|" S.')


FIXED = [
    ("AABBAABB    ", 'INSPECT F TALLYING C FOR ALL "AB"'),
    ("AAAB  AAAB  ", 'INSPECT F TALLYING C FOR LEADING "A"'),
    ("AAAB  AAAB  ", 'INSPECT F TALLYING C FOR CHARACTERS'),
    ("HELLO WORLD ", 'INSPECT F TALLYING C FOR ALL "L" "O"'),
    ("HELLO WORLD ", 'INSPECT F TALLYING C FOR ALL "O" BEFORE INITIAL "W"'),
    ("HELLO WORLD ", 'INSPECT F TALLYING C FOR ALL "O" AFTER INITIAL "W"'),
    ("HELLO WORLD ", 'INSPECT F TALLYING C FOR CHARACTERS AFTER INITIAL " " BEFORE INITIAL "L"'),
    ("ABABABABABAB", 'INSPECT F TALLYING S FOR ALL "AB"'),
    ("HELLO WORLD ", 'INSPECT F REPLACING ALL "L" BY "X"'),
    ("HELLO WORLD ", 'INSPECT F REPLACING FIRST "L" BY "X"'),
    ("LLLO WORLD  ", 'INSPECT F REPLACING LEADING "L" BY "X"'),
    ("HELLO WORLD ", 'INSPECT F REPLACING CHARACTERS BY "*" AFTER INITIAL " "'),
    ("HELLO WORLD ", 'INSPECT F REPLACING ALL "O" BY "0" ALL "L" BY "1"'),
    ("HELLO WORLD ", 'INSPECT F CONVERTING "LO" TO "01"'),
    ("HELLO WORLD ", 'INSPECT F CONVERTING "ABCDEFGHIJKLMNOPQRSTUVWXYZ" TO "abcdefghijklmnopqrstuvwxyz"'),
    ("A  B  C     ", 'INSPECT F REPLACING ALL SPACES BY ZEROS'),
]

ALPHABET = ["A", "B", "AB", "BA", "ABA", " ", "AA"]
SWAP = {1: ["X", "Y", "Z"], 2: ["XY", "YX", "ZZ"], 3: ["XYZ", "ZZZ", "123"]}


def _fuzz_statement(rng: random.Random) -> str:
    def bound() -> str:
        parts = []
        for word in rng.sample(["AFTER", "BEFORE"], rng.choice([0, 0, 1, 2])):
            parts.append(f'{word} INITIAL "{rng.choice(ALPHABET)}"')
        return " ".join(parts)

    kind = rng.choice(["TALLYING", "TALLYING", "REPLACING", "CONVERTING"])
    if kind == "CONVERTING":
        width = rng.choice([1, 2, 3])
        src = "".join(rng.choice("AB ") for _ in range(width))
        dst = "".join(rng.choice("XYZ") for _ in range(width))
        return f'INSPECT F CONVERTING "{src}" TO "{dst}" {bound()}'
    phrases = []
    for _ in range(rng.choice([1, 1, 2, 3])):
        what = rng.choice(["CHARACTERS", "ALL", "LEADING"] + (["FIRST"] if kind == "REPLACING" else []))
        if what == "CHARACTERS":
            text = "CHARACTERS" + (' BY "' + rng.choice("XYZ") + '"' if kind == "REPLACING" else "")
        else:
            lit = rng.choice(ALPHABET)
            text = f'{what} "{lit}"'
            if kind == "REPLACING":
                text += f' BY "{rng.choice(SWAP[len(lit)])}"'
        phrases.append(f"{text} {bound()}".strip())
        if kind == "TALLYING" and what == "CHARACTERS":
            break  # cobc rejects a further TALLYING phrase after CHARACTERS
    head = "TALLYING " + rng.choice(["C", "C", "S"]) + " FOR" if kind == "TALLYING" else "REPLACING"
    return f"INSPECT F {head} " + " ".join(phrases)


def _check(tmp_path: Path, blocks: list[str]) -> None:
    source = _program(blocks)
    want = _oracle(tmp_path / "gnucobol", source)
    got = _java(tmp_path, source)
    assert len(want) == len(blocks)
    assert got == want


@needs_docker
def test_documented_forms_match_the_oracle(tmp_path):
    _check(tmp_path, [_block(i, data, st) for i, (data, st) in enumerate(FIXED)])


@needs_docker
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    blocks = []
    for i in range(60):
        data = "".join(rng.choice("AB  ") for _ in range(12))
        blocks.append(_block(i, data, _fuzz_statement(rng)))
    _check(tmp_path, blocks)

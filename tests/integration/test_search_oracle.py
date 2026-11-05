"""GnuCOBOL oracle differential proof for SEARCH and SET on indexes (certified linear subset).

Each generated program fills an ``OCCURS ... INDEXED BY`` table, then runs a random sequence of ``SET idx``
(TO, UP BY, DOWN BY), linear ``SEARCH`` statements (one to three single-relation WHEN clauses, optional AT END, optional
``VARYING`` an integer item, alphanumeric or numeric tables, an index already past the table) and displays of the
index.  The program runs under GnuCOBOL 3.1.2 and, as generated Java, under the Java image; standard output must
be identical.  An index below 1 is not generated: it is outside the certified subset.
"""

from __future__ import annotations

import os
import random
import re
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator

GNUCOBOL_IMAGE = "gnucobol-ocesql:latest"
JAVA_IMAGE = "eclipse-temurin:21-jdk"


def _images_available() -> bool:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        return False
    try:
        done = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                              capture_output=True, timeout=30)
        text = done.stdout.decode(errors="replace")
        return done.returncode == 0 and GNUCOBOL_IMAGE in text and JAVA_IMAGE in text
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(not _images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SRCH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TABLE.
          05 WS-ENTRY {pic} OCCURS {n} TIMES INDEXED BY IDX JDX.
       01 WS-V PIC 99 VALUE 0.
       01 WS-N PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
"""


def _literal(kind: str, width: int, rng: random.Random) -> str:
    if kind == "9":
        return "".join(rng.choice("012") for _ in range(width))
    return "".join(rng.choice("ABC") for _ in range(width))


def _quote(kind: str, value: str) -> str:
    return str(int(value)) if kind == "9" else f"'{value}'"


def _condition(kind: str, width: int, rng: random.Random) -> str:
    # one relation per WHEN: the shared condition mapper refuses OR over subscripted items (fails closed)
    op = rng.choice(["=", "=", "=", "NOT =", ">", "<"])
    return f"WS-ENTRY(IDX) {op} {_quote(kind, _literal(kind, width, rng))}"


def _search(kind: str, width: int, rng: random.Random, tag: int) -> list[str]:
    lines = ["           SEARCH WS-ENTRY" + ("" if rng.random() < 0.7 else " VARYING WS-V")]
    if rng.random() < 0.7:
        lines.append(f"               AT END DISPLAY 'S{tag} END'")
    for number in range(rng.randint(1, 3)):
        lines.append(f"               WHEN {_condition(kind, width, rng)}")
        style = rng.random()
        if style < 0.5:
            lines.append(f"                   DISPLAY 'S{tag} W{number}'")
        elif style < 0.8:
            lines += [f"                   MOVE {number + 1} TO WS-N",
                      f"                   DISPLAY 'S{tag} W{number} ' WS-N"]
        else:
            lines += ["                   IF WS-V = 0",
                      f"                       DISPLAY 'S{tag} W{number} V0'",
                      "                   ELSE",
                      f"                       DISPLAY 'S{tag} W{number} V' WS-V",
                      "                   END-IF"]
    lines.append("           END-SEARCH." if rng.random() < 0.5 else "           END-SEARCH")
    return lines


def _program(rng: random.Random) -> str:
    n = rng.randint(2, 7)
    kind = rng.choice(["X", "9"])
    width = rng.choice([1, 2])
    pic = f"PIC X({width})" if kind == "X" else f"PIC 9({width})"
    lines = HEAD.format(pic=pic, n=n).rstrip("\n").split("\n")
    for position in range(1, n + 1):
        lines.append(f"           MOVE {_quote(kind, _literal(kind, width, rng))} TO WS-ENTRY({position}).")
    lines.append("           SET IDX TO 1.")  # an unset index is below 1: outside the certified subset
    for step in range(rng.randint(3, 9)):
        op = rng.choice(["set", "set", "up", "down", "search", "search", "search"])
        if op == "set":
            lines.append(f"           SET IDX TO {rng.randint(1, n + 3)}.")
        elif op == "up":
            lines.append(f"           SET IDX UP BY {rng.randint(1, 3)}.")
        elif op == "down":
            # an absolute SET first, so the result stays >= 1 whatever the previous SEARCH did
            top = rng.randint(4, n + 4)
            lines += [f"           SET IDX TO {top}.", f"           SET IDX DOWN BY {rng.randint(1, 3)}."]
        else:
            lines += _search(kind, width, rng, step)
        lines += ["           SET WS-N TO IDX.", f"           DISPLAY 'I{step} ' WS-N ' V' WS-V."]
    lines.append("           STOP RUN.")
    return "\n".join(lines) + "\n"


def _run_all(tmp: Path, programs: list[str]) -> list[tuple[bytes, bytes]]:
    names = []
    for index, source in enumerate(programs):
        directory = tmp / f"c{index:03d}"
        (directory / "cob").mkdir(parents=True)
        (directory / "jv").mkdir()
        (directory / "cob" / "p.cob").write_text(source, encoding="ascii", newline="\n")
        generated = JavaGenerator().generate(CobolParser().parse(source))[0].source_code
        name = re.search(r"public\s+class\s+(\w+)", generated).group(1)
        (directory / "jv" / f"{name}.java").write_text(generated, encoding="utf-8", newline="\n")
        names.append(name)
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    cobol = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/t", GNUCOBOL_IMAGE, "bash", "-c",
         "for d in /t/c*/cob; do (cd $d && cobc -free -x -o p p.cob && ./p > stdout.txt); done"],
        capture_output=True, timeout=900, env=env)
    assert cobol.returncode == 0, cobol.stderr.decode(errors="replace")[-2000:]
    script = ("for d in /t/c*/jv; do (cd $d && javac -nowarn *.java && "
              "java -cp . $(ls *.java | head -1 | sed 's/.java//') > stdout.txt); done")
    java = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/t", JAVA_IMAGE, "bash", "-c", script],
        capture_output=True, timeout=1500, env=env)
    assert java.returncode == 0, java.stderr.decode(errors="replace")[-2000:]
    results = []
    for index in range(len(programs)):
        directory = tmp / f"c{index:03d}"
        pair = [(directory / sub / "stdout.txt").read_bytes() if (directory / sub / "stdout.txt").exists()
                else b"<none>" for sub in ("cob", "jv")]
        results.append((pair[0], pair[1]))
    return results


FIXED = [
    """       IDENTIFICATION DIVISION.
       PROGRAM-ID. S.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TABLE.
          05 WS-ENTRY PIC X(3) OCCURS 5 TIMES INDEXED BY IDX.
       01 WS-V PIC 9 VALUE 0.
       01 WS-N PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
           MOVE 'AAA' TO WS-ENTRY(1).
           MOVE 'BBB' TO WS-ENTRY(2).
           MOVE 'CCC' TO WS-ENTRY(3).
           MOVE 'BBB' TO WS-ENTRY(4).
           MOVE 'EEE' TO WS-ENTRY(5).
           SET IDX TO 1.
           SEARCH WS-ENTRY
               AT END DISPLAY 'T1 NOT FOUND'
               WHEN WS-ENTRY(IDX) = 'BBB' DISPLAY 'T1 FOUND'
           END-SEARCH.
           SET WS-N TO IDX.
           DISPLAY 'IDX=' WS-N.
           SEARCH WS-ENTRY
               AT END DISPLAY 'T2 NOT FOUND'
               WHEN WS-ENTRY(IDX) = 'BBB' DISPLAY 'T2 FOUND'
           END-SEARCH.
           SET IDX UP BY 1.
           SEARCH WS-ENTRY
               AT END DISPLAY 'T3 NOT FOUND'
               WHEN WS-ENTRY(IDX) = 'ZZZ' DISPLAY 'T3 FOUND'
           END-SEARCH.
           SET WS-N TO IDX.
           DISPLAY 'IDX=' WS-N.
           SET IDX TO 9.
           SEARCH WS-ENTRY
               AT END DISPLAY 'T4 OUT OF RANGE'
               WHEN WS-ENTRY(IDX) = 'AAA' DISPLAY 'T4 FOUND'
           END-SEARCH.
           SET IDX TO 3.
           SEARCH WS-ENTRY VARYING WS-V
               AT END DISPLAY 'T5 NOT FOUND'
               WHEN WS-ENTRY(IDX) = 'EEE' DISPLAY 'T5 FOUND'
           END-SEARCH.
           DISPLAY 'V=' WS-V.
           STOP RUN.
""",
]


@needs_docker
def test_documented_forms_match_the_oracle(tmp_path):
    for cobol_out, java_out in _run_all(tmp_path, FIXED):
        assert cobol_out.startswith(b"T1 FOUND")
        assert java_out == cobol_out


@needs_docker
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(_run_all(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(99)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

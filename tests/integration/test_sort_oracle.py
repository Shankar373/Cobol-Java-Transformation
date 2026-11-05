"""GnuCOBOL oracle differential proof for SORT (certified file-to-file subset).

Every case is a generated program ``SORT sd ON ... KEY ... USING in GIVING out`` plus an input file.  The
program runs under GnuCOBOL 3.1.2 and, as generated Java, under the Java image; the GIVING files must be
byte-identical.  Cases cover alphanumeric and unsigned numeric keys, one to three keys in either direction,
keys inside groups, heavy duplication (stability), short records, empty input and a missing USING file.
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


def _program(fields: list[tuple[str, str, int]], keys: list[tuple[str, str]], missing: bool, dups: bool,
             grouped: bool, inputs: int = 1, verb: str = "SORT") -> str:
    length = sum(width for _, _, width in fields)
    layout = []
    for name, kind, width in fields:
        pic = f"X({width})" if kind == "X" else f"9({width})"
        layout.append(f"{name} PIC {pic}.")
    if grouped:
        half = max(1, len(layout) // 2)
        body = ["          05 GRP-A.", *[f"             10 {item}" for item in layout[:half]],
                "          05 GRP-B.", *[f"             10 {item}" for item in layout[half:]]]
        if not layout[half:]:
            body = body[:-1]
    else:
        body = [f"          05 {item}" for item in layout]
    # one key per line: the platform reads fixed-format source (columns 8-72), GnuCOBOL -free does not care
    key_lines = [f"               ON {direction} KEY {name}" for name, direction in keys]
    names = [f"IN{n}-FILE" for n in range(inputs)]
    selects, fds = [], []
    for n, name in enumerate(names):
        source = f"in{n}.dat" if not (missing and n == 0) else "absent.dat"
        selects += [f"           SELECT {name} ASSIGN TO '{source}'", "               ORGANIZATION IS LINE SEQUENTIAL."]
        fds += [f"       FD {name}.", f"       01 IN{n}-REC PIC X({length})."]
    return "\n".join([
        "       IDENTIFICATION DIVISION.", "       PROGRAM-ID. SRT.", "       ENVIRONMENT DIVISION.",
        "       INPUT-OUTPUT SECTION.", "       FILE-CONTROL.", *selects,
        "           SELECT OUT-FILE ASSIGN TO 'out.dat'", "               ORGANIZATION IS LINE SEQUENTIAL.",
        "           SELECT SORT-FILE ASSIGN TO 'sort.tmp'.",
        "       DATA DIVISION.", "       FILE SECTION.", *fds,
        "       FD OUT-FILE.", f"       01 OUT-REC PIC X({length}).",
        "       SD SORT-FILE.", "       01 SORT-REC.", *body,
        "       PROCEDURE DIVISION.", "       MAIN.",
        f"           {verb} SORT-FILE", *key_lines,
        *(["               WITH DUPLICATES IN ORDER"] if dups else []),
        "               USING " + " ".join(names), "               GIVING OUT-FILE.",
        "           DISPLAY 'DONE'.", "           STOP RUN.", ""])


def _rows(rng: random.Random, fields, count: int) -> str:
    length = sum(width for _, _, width in fields)
    rows = []
    for _ in range(count):
        record = ""
        for _, kind, width in fields:
            if kind == "9":
                record += "".join(rng.choice("012") for _ in range(width))
            else:
                record += "".join(rng.choice("ABab ") for _ in range(width))
        rows.append(record[:length].rstrip() if rng.random() < 0.5 else record)
    return "\n".join(rows) + ("\n" if rows else "")


def _case(rng: random.Random):
    count = rng.choice([1, 2, 3, 4])
    fields = []
    for index in range(count + rng.choice([0, 1])):
        kind = rng.choice(["X", "9"])
        width = rng.choice([1, 2, 3]) if kind == "9" else rng.choice([1, 2, 3, 4])
        fields.append((f"F{index}", kind, width))
    chosen = rng.sample(fields, rng.randint(1, min(3, len(fields))))
    keys = [(name, rng.choice(["ASCENDING", "DESCENDING"])) for name, _, _ in chosen]
    inputs = rng.choice([1, 1, 2, 3])
    verb = "MERGE" if inputs > 1 and rng.random() < 0.5 else "SORT"
    data = [_rows(rng, fields, rng.choice([0, 1, 2, 5, 30, 80])) for _ in range(inputs)]
    return (_program(fields, keys, missing=rng.random() < 0.08, dups=rng.random() < 0.4,
                     grouped=rng.random() < 0.3, inputs=inputs, verb=verb), data)


def _run_all(tmp: Path, cases: list[tuple[str, "str | list[str]"]]) -> list[tuple[bytes, bytes]]:
    java_dirs = []
    for index, (source, data) in enumerate(cases):
        directory = tmp / f"c{index:03d}"
        (directory / "cob").mkdir(parents=True)
        (directory / "jv").mkdir()
        for sub in ("cob", "jv"):
            for n, text in enumerate([data] if isinstance(data, str) else data):
                (directory / sub / f"in{n}.dat").write_text(text, encoding="ascii", newline="\n")
        (directory / "cob" / "p.cob").write_text(source, encoding="ascii", newline="\n")
        generated = JavaGenerator().generate(CobolParser().parse(source))[0].source_code
        name = re.search(r"public\s+class\s+(\w+)", generated).group(1)
        (directory / "jv" / f"{name}.java").write_text(generated, encoding="utf-8", newline="\n")
        java_dirs.append(name)
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    cobol = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/t", GNUCOBOL_IMAGE, "bash", "-c",
         "for d in /t/c*/cob; do (cd $d && cobc -free -x -o p p.cob && ./p > stdout.txt); done"],
        capture_output=True, timeout=900, env=env)
    assert cobol.returncode == 0, cobol.stderr.decode(errors="replace")[-2000:]
    script = "for d in /t/c*/jv; do (cd $d && javac -nowarn *.java && java -cp . $(ls *.java | head -1 | sed 's/.java//') > stdout.txt); done"
    java = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/t", JAVA_IMAGE, "bash", "-c", script],
        capture_output=True, timeout=1500, env=env)
    assert java.returncode == 0, java.stderr.decode(errors="replace")[-2000:]
    results = []
    for index in range(len(cases)):
        directory = tmp / f"c{index:03d}"
        pair = []
        for sub in ("cob", "jv"):
            out = directory / sub / "out.dat"
            pair.append((out.read_bytes() if out.exists() else b"<none>")
                        + b"|" + (directory / sub / "stdout.txt").read_bytes())
        results.append((pair[0], pair[1]))
    return results


@needs_docker
def test_documented_forms_match_the_oracle(tmp_path):
    fixed = [
        # alphanumeric ascending, duplicates keep input order
        (_program([("K", "X", 1), ("R", "X", 4)], [("K", "ASCENDING")], False, False, False),
         "B0001\nA0002\nB0003\nA0004\nC0005\n"),
        # descending numeric, then a tie-breaking ascending key
        (_program([("N", "9", 2), ("T", "X", 2)], [("N", "DESCENDING"), ("T", "ASCENDING")], False, True, False),
         "10zz\n10aa\n02bb\n99cc\n02aa\n"),
        # empty input and a missing USING file both give an empty GIVING file and the program goes on
        (_program([("K", "X", 2)], [("K", "ASCENDING")], False, False, False), ""),
        (_program([("K", "X", 2)], [("K", "ASCENDING")], True, False, False), "zz\n"),
        # MERGE of three inputs, two of them NOT in key order: the oracle concatenates in USING order
        # and sorts stably
        (_program([("K", "X", 1), ("R", "X", 1)], [("K", "ASCENDING")], False, False, False, inputs=3,
                  verb="MERGE"), ["A1\nC1\nB9\nA2\n", "B1\nA3\nC2\n", "A4\nB2\n"]),
        # MERGE descending with ties across files, and a SORT over two USING files
        (_program([("K", "X", 1), ("R", "X", 1)], [("K", "DESCENDING")], False, True, False, inputs=2,
                  verb="MERGE"), ["C1\nB1\nA1\n", "C2\nB2\nA2\n"]),
        (_program([("K", "9", 1), ("R", "X", 2)], [("K", "ASCENDING")], False, False, False, inputs=2),
         ["2xx\n0yy\n", "1zz\n0aa\n"]),
    ]
    for (cobol_out, java_out) in _run_all(tmp_path, fixed):
        assert java_out == cobol_out


@needs_docker
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    cases = [_case(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(_run_all(tmp_path, cases)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"

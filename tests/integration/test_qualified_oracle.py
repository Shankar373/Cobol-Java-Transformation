"""Roadmap unit 36 (Stage 1): qualified data names ``field OF group`` / ``field IN group``, GnuCOBOL 3.1.2 differential.

Generated programs declare the same field names under several 01 groups and nested subgroups (alphanumeric, unsigned
and signed numeric, different sizes), then reference them with complete and partial qualification (``A OF S OF G``,
``A OF G``, ``A IN G``) in MOVE, ADD, COMPUTE, IF and DISPLAY, including group MOVEs between two groups of the same
layout. Standard output must be identical.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

POOL = ("A", "B", "C", "D")
KINDS = {
    "n3": ("PIC 9(3)", "num", "{n}"),
    "n5": ("PIC 9(5)", "num", "{n}"),
    "sd": ("PIC S9(3)V99", "num", "{n}"),
    "x4": ("PIC X(4)", "txt", "'{t}'"),
    "x8": ("PIC X(8)", "txt", "'{t}'"),
}


def _layout(rng: random.Random):
    """[(group name, [(path tuple outermost-last, kind)])]: path is (field, subgroup?, group)."""
    groups = []
    for index in range(rng.randint(2, 3)):
        top = f"G{index + 1}"
        fields = []
        # a name is directly under a group or in its subgroup, never both: ``A OF G`` would be ambiguous in COBOL
        names = rng.sample(POOL, rng.randint(2, 3))
        for name in names:
            fields.append(((name, top), rng.choice(list(KINDS))))
        rest = [n for n in POOL if n not in names]
        sub_names = rng.sample(rest, rng.randint(1, len(rest))) if rest and rng.random() < 0.7 else []
        for name in sub_names:
            fields.append(((name, "S", top), rng.choice(list(KINDS))))
        groups.append((top, fields, bool(sub_names)))
    return groups


def _declarations(groups) -> list[str]:
    lines = []
    for top, fields, has_sub in groups:
        lines.append(f"       01 {top}.")
        for path, kind in fields:
            if len(path) == 2:
                lines.append(f"          05 {path[0]} {KINDS[kind][0]} VALUE {_default(kind)}.")
        if has_sub:
            lines.append("          05 S.")
            for path, kind in fields:
                if len(path) == 3:
                    lines.append(f"             10 {path[0]} {KINDS[kind][0]} VALUE {_default(kind)}.")
    return lines


def _default(kind: str) -> str:
    return "'ab'" if KINDS[kind][1] == "txt" else "0"


def _qualified(rng: random.Random, path, groups) -> str:
    """The name of ``path`` qualified completely, or partially when that is still unambiguous."""
    name, *chain = path
    keyword = lambda: rng.choice(["OF", "OF", "IN"])  # noqa: E731
    full = f"{name} " + " ".join(f"{keyword()} {q}" for q in chain)
    top = chain[-1]
    if len(chain) == 2 and rng.random() < 0.5:
        # ``A OF G`` is ambiguous when A is also directly under G
        direct = [p for p, _ in dict((g, f) for g, f, _ in groups)[top] if p[0] == name and len(p) == 2]
        if not direct:
            return f"{name} {keyword()} {top}"
    return full


def _literal(rng: random.Random, kind: str) -> str:
    if KINDS[kind][1] == "txt":
        return "'" + "".join(rng.choice("abcXYZ019") for _ in range(rng.randint(1, 8))) + "'"
    return str(rng.randint(0, 99)) if kind != "sd" else f"{rng.randint(0, 99)}.{rng.randint(0, 99):02d}"


def _program(rng: random.Random) -> str:
    groups = _layout(rng)
    flat = [(path, kind) for _, fields, _ in groups for path, kind in fields]
    lines = [
        "       IDENTIFICATION DIVISION.", "       PROGRAM-ID. QUA.", "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.", *_declarations(groups), "       PROCEDURE DIVISION.", "       MAIN.",
    ]
    for step in range(rng.randint(4, 9)):
        kind = rng.choice(["move_lit", "move_item", "add", "compute", "if", "move_lit"])
        path, pkind = rng.choice(flat)
        same = [(p, k) for p, k in flat if KINDS[k][1] == KINDS[pkind][1] and p != path]
        ref = _qualified(rng, path, groups)
        if kind == "move_lit":
            lines.append(f"           MOVE {_literal(rng, pkind)} TO {ref}")
        elif kind == "move_item" and same:
            other = rng.choice(same)[0]
            lines.append(f"           MOVE {_qualified(rng, other, groups)} TO {ref}")
        elif kind == "add" and KINDS[pkind][1] == "num":
            lines.append(f"           ADD {_literal(rng, 'n3')} TO {ref}")
        elif kind == "compute" and KINDS[pkind][1] == "num":
            other = [p for p, k in flat if KINDS[k][1] == "num"]
            lines.append(f"           COMPUTE {ref} = {_qualified(rng, rng.choice(other), groups)} + 3")
        elif kind == "if":
            lines.append(f"           IF {ref} = {_literal(rng, pkind)}")
            lines.append("               DISPLAY 'eq'")
            lines.append("           ELSE")
            lines.append("               DISPLAY 'ne'")
            lines.append("           END-IF")
        else:
            lines.append(f"           MOVE {_literal(rng, pkind)} TO {ref}")
        shown = _qualified(rng, rng.choice(flat)[0], groups)
        lines.append(f"           DISPLAY 's{step} [' {shown} ']'")
    if len(groups) >= 2 and groups[0][1] == groups[1][1] and False:
        lines.append("           MOVE G1 TO G2")
    for top, fields, _ in groups:
        if all(kind != "sd" for _, kind in fields):  # a group holding a signed decimal item is not displayed (refused)
            lines.append(f"           DISPLAY 'end {top} [' {top} ']'")
    lines.append("           STOP RUN.")
    wrapped: list[str] = []
    for line in lines:
        while len(line) > 72:
            cut = line.rfind(" ", 0, 70)
            wrapped.append(line[:cut])
            line = "               " + line[cut:].lstrip()
        wrapped.append(line)
    return "\n".join(wrapped) + "\n"


@needs_docker
@pytest.mark.parametrize("seed", [301, 302, 303, 304])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(93)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line


FILE_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. QFD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-F ASSIGN TO "QFD.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT OUT-F ASSIGN TO "QFD.OUT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD IN-F.
       01 IN-REC.
           05 ACCT PIC X(4).
           05 AMT PIC 9(4).
       FD OUT-F.
       01 OUT-REC.
           05 ACCT PIC X(4).
           05 AMT PIC 9(5).
       WORKING-STORAGE SECTION.
       01 EOF-FLAG PIC X VALUE 'N'.
       01 TOTAL PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       MAIN.
           OPEN OUTPUT OUT-F
           MOVE 'AAAA' TO ACCT OF OUT-REC
           MOVE 17 TO AMT OF OUT-REC
           WRITE OUT-REC
           MOVE 'BBBB' TO ACCT IN OUT-REC
           COMPUTE AMT OF OUT-REC = AMT OF OUT-REC + 100
           WRITE OUT-REC
           CLOSE OUT-F
           DISPLAY 'wrote ' ACCT OF OUT-REC ' ' AMT OF OUT-REC
           STOP RUN.
"""


@needs_docker
def test_two_file_records_sharing_field_names_match_the_oracle(tmp_path):
    (cobol, java), = run_batch(tmp_path, [FILE_PROGRAM])
    assert cobol == java and b"wrote BBBB 00117" in cobol


def test_a_duplicated_name_without_a_resolvable_qualification_still_fails_closed():
    from engine.transformation.cobol_parser import CobolParser

    source = FILE_PROGRAM.replace("MOVE 'BBBB' TO ACCT IN OUT-REC", "MOVE 'BBBB' TO ACCT")
    parser = CobolParser()
    parser.parse(source)
    assert any("declared more than once" in d.message for d in parser.diagnostics.all)
    parser = CobolParser()
    parser.parse(FILE_PROGRAM.replace("ACCT IN OUT-REC", "ACCT OF NOWHERE"))
    assert any("designates 0 data items" in d.message for d in parser.diagnostics.all)

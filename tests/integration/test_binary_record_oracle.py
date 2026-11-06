"""Roadmap unit 28 (Stage 1): COMP-3 and COMP leaves in RECORD SEQUENTIAL and INDEXED file records, GnuCOBOL differential.

Each generated program declares a record of 2-6 leaves (alphanumeric, unsigned DISPLAY, and COMP / COMP-3 of 1-18 digits,
signed or unsigned, with or without an implied decimal point), writes 1-5 records with random values (overflowing
values, negative values into unsigned fields, fractions beyond the scale) and reads them back, displaying FILE STATUS
and every field. Standard output must be identical between GnuCOBOL 3.1.2 and the generated Java; for RECORD SEQUENTIAL
files the two data files must also be byte-identical (the packed and binary encodings are the contract).
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

SEQUENTIAL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT BF ASSIGN TO "BR.DAT"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD BF.
       01 BF-REC.
"""

INDEXED = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT BF ASSIGN TO "BR.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS F0
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD BF.
       01 BF-REC.
"""

TAIL = """       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
"""


def _leaf(rng: random.Random, index: int) -> tuple[str, str, int, int, bool, str]:
    """(declaration, kind, digits, scale, signed, usage) of leaf F<index>."""
    kind = rng.choice(["x", "d", "comp3", "comp3", "comp", "comp"])
    name = f"F{index}"
    if kind == "x":
        n = rng.randint(1, 6)
        return f"           05 {name} PIC X({n}).", kind, n, 0, False, ""
    if kind == "d":
        n = rng.randint(1, 6)
        return f"           05 {name} PIC 9({n}).", kind, n, 0, False, ""
    digits = rng.choice([1, 2, 3, 4, 5, 7, 9, 10, 12, 18])
    scale = rng.choice([0, 0, 0, 1, 2]) if digits > 2 else 0
    signed = rng.random() < 0.6
    pic = ("S" if signed else "") + (f"9({digits - scale})" if digits - scale > 0 else "") + (
        f"V9({scale})" if scale else "")
    if digits - scale <= 0:
        pic = ("S" if signed else "") + f"V9({scale})"
    usage = "COMP-3" if kind == "comp3" else "COMP"
    return f"           05 {name} PIC {pic} {usage}.", kind, digits, scale, signed, usage


def _literal(rng: random.Random, kind: str, digits: int, scale: int, signed: bool) -> str:
    if kind == "x":
        return '"' + "".join(rng.choice("ABCxyz09 ") for _ in range(rng.randint(0, digits + 2))) + '"'
    # integer part of up to digits + 3 positions (overflow), fraction up to scale + 1
    # a literal of more than 18 digits wraps in GnuCOBOL's 64-bit arithmetic (numeric MOVE semantics, a separate
    # limit documented in the capability matrix): keep every literal within 18 digits
    int_digits = max(0, digits - scale)
    has_fraction = kind != "d" and (scale or rng.random() < 0.2)
    fraction_digits = (scale + rng.randint(0, 1) or 1) if has_fraction else 0
    whole_length = min(rng.randint(0, int_digits + 3), 18 - fraction_digits)
    whole = "".join(rng.choice("0123456789") for _ in range(whole_length)) or "0"
    text = whole
    if has_fraction:
        text += "." + "".join(rng.choice("0123456789") for _ in range(fraction_digits))
    if kind != "d" and rng.random() < 0.5:
        # "negative zero" (a negative value truncated to zero) keeps its minus sign in GnuCOBOL (packed nibble D),
        # which the Java numeric model cannot represent: a documented limit, so such values are not generated
        kept = (whole + (text.split(".")[1][:scale] if has_fraction else "").ljust(scale, "0"))[-digits:]
        if kept.strip("0"):
            text = "-" + text
    return text


def _program(rng: random.Random, indexed: bool) -> str:
    leaves = [_leaf(rng, i) for i in range(1, rng.randint(2, 6))]
    lines = (INDEXED if indexed else SEQUENTIAL).rstrip("\n").split("\n")
    if indexed:
        lines.append("           05 F0 PIC X(4).")
    lines += [decl for decl, *_ in leaves]
    lines += TAIL.rstrip("\n").split("\n")
    records = rng.randint(1, 5)
    lines += ["           OPEN OUTPUT BF", '           DISPLAY "open " FS']
    for number in range(records):
        if indexed:
            lines.append(f'           MOVE "K{number}00" TO F0')
        for index, (_decl, kind, digits, scale, signed, _usage) in enumerate(leaves, 1):
            lines.append(f"           MOVE {_literal(rng, kind, digits, scale, signed)} TO F{index}")
        lines += ["           WRITE BF-REC", f'           DISPLAY "w{number} " FS']
    lines += ["           CLOSE BF", "           OPEN INPUT BF"]
    shown = " ".join(f'" " F{i}' for i in range(1, len(leaves) + 1))
    for number in range(records + 1):
        lines += ["           READ BF", f'           DISPLAY "r{number} " FS {shown}']
    lines += ["           CLOSE BF", "           STOP RUN."]
    # one DISPLAY per line would exceed the margin for wide records; wrap any long line at a field boundary
    wrapped: list[str] = []
    for line in lines:
        while len(line) > 72:
            cut = line.rfind(' " "', 0, 70)
            if cut < 20:
                cut = line.rfind(" ", 0, 70)
            wrapped.append(line[:cut])
            line = "               " + line[cut:].lstrip()
        wrapped.append(line)
    return "\n".join(wrapped) + "\n"


def _run(tmp_path, seed: int, indexed: bool, count: int = 25):
    rng = random.Random(seed)
    programs = [_program(rng, indexed) for _ in range(count)]
    results = run_batch(tmp_path, programs)
    bad = []
    for number, (cobol_out, java_out) in enumerate(results):
        if cobol_out != java_out:
            bad.append(number)
            continue
        if not indexed:
            directory = tmp_path / f"c{number:03d}"
            if (directory / "cob" / "BR.DAT").read_bytes() != (directory / "jv" / "BR.DAT").read_bytes():
                bad.append(number)
    return bad


@needs_docker
@pytest.mark.parametrize("seed", [41, 42, 43])
def test_record_sequential_matches_the_oracle_byte_for_byte(tmp_path, seed):
    assert _run(tmp_path, seed, indexed=False) == []


@needs_docker
@pytest.mark.parametrize("seed", [51, 52, 53])
def test_indexed_records_match_the_oracle(tmp_path, seed):
    assert _run(tmp_path, seed, indexed=True) == []


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(95)
    for _ in range(150):
        for indexed in (False, True):
            for line in _program(rng, indexed).splitlines():
                assert len(line) <= 72, line

"""Numeric-edited PIC against GnuCOBOL 3.1.2 (Docker lane).

Programs go through the real producer; the generated Java and the oracle must
print the same bytes.

* the invoice fixture (``fixtures/workload-numeric-edited``), which is also
  part of the four-runtime certification corpus;
* seeded fuzzes of random certified pictures x values x sender formats (PIC
  S9(5)V99, 9(5)V99, S9(3), S9(2)V9(3), 9(4), S9(7)V9), one of them with
  ``BLANK WHEN ZERO`` on every picture.

The picture grammar (``engine.transformation.numeric_edited``) is the set the
generator produces; ``tests/test_numeric_edited_picture.py`` checks that the
parser accepts all of it.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from tests.numeric_edited_fuzz import SENDERS, random_picture, random_value
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

FIXTURE = Path("fixtures/workload-numeric-edited/cobol/EDITED.cob")


def _same_output(source: str, program_id: str, tmp_path: Path) -> str:
    oracle_dir, java_dir = tmp_path / "oracle", tmp_path / "java"
    oracle_dir.mkdir()
    java_dir.mkdir()
    expected = run_gnucobol(source, program_id, oracle_dir)  # skips off the Docker lane
    actual = run_generated_java(source, program_id, java_dir)
    assert actual == expected
    return expected


def test_invoice_fixture_matches_the_oracle(tmp_path):
    output = _same_output(FIXTURE.read_text(encoding="utf-8"), "EDITED", tmp_path)
    # The fixture exercises what it claims to: suppression, CR, truncation.
    assert "CR" in output and "$" in output and "UNINITIALISED:      0.00|" in output


def _fuzz_program(rng: random.Random, count: int, blank_when_zero: bool):
    pictures: list[str] = []
    while len(pictures) < count:
        picture = random_picture(rng)
        if re.fullmatch(r"9+(V9+)?", picture) or picture in pictures:
            continue  # plain numeric, or a repeat
        if blank_when_zero and "*" in picture:
            continue  # BLANK WHEN ZERO cannot be combined with *
        pictures.append(picture)
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. NEFUZZ.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
    ]
    lines += [f"       01 S{i} PIC {pic}." for i, (pic, *_rest) in enumerate(SENDERS)]
    suffix = " BLANK WHEN ZERO" if blank_when_zero else ""
    lines += [f"       01 F{k} PIC {pic}{suffix}." for k, pic in enumerate(pictures)]
    lines.append("       PROCEDURE DIVISION.")
    lines += [f"           PERFORM P{k}" for k in range(count)]
    lines.append("           STOP RUN.")
    for k in range(count):
        lines.append(f"       P{k}.")
        cases = sorted({
            (si, random_value(rng, SENDERS[si][1], SENDERS[si][2], SENDERS[si][3]))
            for si in (rng.randrange(len(SENDERS)) for _ in range(14))
        })
        for si, value in cases:
            lines.append(f"           MOVE {value} TO S{si}")
            lines.append(f"           MOVE S{si} TO F{k}")
            lines.append(f'           DISPLAY "{k}|{si}|{value}|" F{k} "|"')
        lines[-1] += "."  # a paragraph ends with a period, or GnuCOBOL reads the next header as an operand
    return "\n".join(lines) + "\n", pictures


@pytest.mark.parametrize(
    "seed,blank_when_zero",
    [(31, False), (32, False), (33, True)],
)
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed, blank_when_zero):
    source, pictures = _fuzz_program(random.Random(seed), 36, blank_when_zero)
    output = _same_output(source, "NEFUZZ", tmp_path)
    assert len(pictures) == 36
    assert output.count("\n") > 36 * 5  # every case printed


def test_blank_when_zero_blanks_an_edited_zero(tmp_path):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. BWZ.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 N PIC S9(3)V99 VALUE 0.\n"
        "       01 E1 PIC ZZ9.99 BLANK WHEN ZERO.\n"
        "       01 E2 PIC ZZ9.99.\n"
        "       PROCEDURE DIVISION.\n"
        "           DISPLAY '[' E1 '][' E2 ']'\n"
        "           MOVE N TO E1\n"
        "           MOVE N TO E2\n"
        "           DISPLAY '[' E1 '][' E2 ']'\n"
        "           MOVE -0.01 TO N\n"
        "           MOVE N TO E1\n"
        "           DISPLAY '[' E1 ']'\n"
        "           STOP RUN.\n"
    )
    output = _same_output(source, "BWZ", tmp_path)
    assert output.splitlines()[0] == "[      ][  0.00]"

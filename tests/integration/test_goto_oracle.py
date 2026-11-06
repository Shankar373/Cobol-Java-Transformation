"""GnuCOBOL oracle differential proof for ``GO TO`` (certified subset, roadmap unit 26).

Generated programs mix main-line paragraphs (fall-through, forward and backward ``GO TO`` bounded by a step counter,
``PERFORM ... THRU`` ranges, ``STOP RUN`` inside an IF) with PERFORM THRU ranges whose paragraphs jump forward to a
later paragraph or to the range exit. The program runs under GnuCOBOL 3.1.2 and, as generated Java, on the JVM;
standard output must be identical for every program.
"""

from __future__ import annotations

import random

import pytest

from tests.batch_oracle import images_available, run_batch

needs_docker = pytest.mark.skipif(not images_available(), reason="set RUN_DOCKER_TESTS=1 with both images")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. GT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STEPS PIC 99 VALUE 0.
       01 WS-X PIC 99 VALUE {x}.
       PROCEDURE DIVISION.
"""


def _program(rng: random.Random) -> str:
    mains = rng.randint(2, 5)
    ranges = [rng.randint(2, 4) for _ in range(rng.randint(0, 2))]
    main_names = [f"M{i}" for i in range(mains)]
    range_names = [[f"R{r}{chr(65 + p)}" for p in range(count - 1)] + [f"R{r}X"] for r, count in enumerate(ranges)]
    all_targets = main_names + [n for group in range_names for n in group] + ["FINISH"]
    lines = HEAD.format(x=rng.randint(0, 9)).rstrip("\n").split("\n")

    def body(i: int) -> list[str]:
        out = [f"           DISPLAY '{main_names[i]} ' WS-X."]
        for _ in range(rng.randint(1, 3)):
            kind = rng.choice(["add", "goto", "goto", "perform", "stop", "display"])
            if kind == "add":
                out.append(f"           ADD {rng.randint(1, 4)} TO WS-X.")
            elif kind == "goto":
                target = rng.choice(all_targets)
                out += [f"           IF WS-X > {rng.randint(0, 12)}",
                        f"               GO TO {target}", "           END-IF."]
            elif kind == "perform" and ranges:
                group = rng.choice(range_names)
                out.append(f"           PERFORM {group[0]} THRU {group[-1]}.")
            elif kind == "stop":
                out += [f"           IF WS-X > {rng.randint(3, 14)}", "               DISPLAY 'STOP'",
                        "               STOP RUN", "           END-IF."]
            else:
                out.append("           DISPLAY 'MID'.")
        return out

    for i, name in enumerate(main_names):
        lines += [f"       {name}.", "           ADD 1 TO WS-STEPS.", "           IF WS-STEPS > 25",
                  "               GO TO FINISH", "           END-IF."] + body(i)
    if ranges and rng.random() < 0.6:
        lines.append("           GO TO FINISH.")  # keep the ranges from being reached by fall-through
    for group in range_names:
        for position, name in enumerate(group):
            lines += [f"       {name}.", f"           DISPLAY '{name} ' WS-X."]
            if name.endswith("X"):
                lines.append("           EXIT.")
                continue
            if rng.random() < 0.6:
                lines.append(f"           ADD {rng.randint(1, 3)} TO WS-X.")
            later = group[position + 1:]
            if rng.random() < 0.8:
                if rng.random() < 0.3:
                    lines.append(f"           IF WS-X > {rng.randint(0, 9)} GO TO {rng.choice(later)}.")
                else:
                    lines += [f"           IF WS-X > {rng.randint(0, 9)}",
                              f"               GO TO {rng.choice(later)}", "           END-IF."]
            lines.append("           DISPLAY 'FALL'.")
    lines += ["       FINISH.", "           DISPLAY 'END ' WS-STEPS ' ' WS-X.", "           STOP RUN."]
    return "\n".join(lines) + "\n"


FIXED = [
    """       IDENTIFICATION DIVISION.
       PROGRAM-ID. GT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'START'.
           PERFORM CALC-A THRU CALC-EXIT.
           DISPLAY 'AFTER N=' N.
       LOOP-PARA.
           ADD 1 TO N.
           IF N < 5
               GO TO LOOP-PARA
           END-IF.
           GO TO FINISH.
       CALC-A.
           ADD 7 TO N.
           IF N > 0
               GO TO CALC-EXIT
           END-IF.
           DISPLAY 'NOT SHOWN'.
       CALC-EXIT.
           EXIT.
       FINISH.
           DISPLAY 'DONE N=' N.
           STOP RUN.
""",
]


@needs_docker
def test_documented_forms_match_the_oracle(tmp_path):
    for cobol_out, java_out in run_batch(tmp_path, FIXED):
        assert cobol_out.startswith(b"START")
        assert java_out == cobol_out


@needs_docker
@pytest.mark.parametrize("seed", [21, 22, 23, 24])
def test_seeded_fuzz_matches_the_oracle(tmp_path, seed):
    rng = random.Random(seed)
    programs = [_program(rng) for _ in range(25)]
    mismatches = [i for i, (c, j) in enumerate(run_batch(tmp_path, programs)) if c != j]
    assert mismatches == [], f"cases differ from the oracle: {mismatches}"


def test_generated_programs_fit_the_fixed_format_margin():
    rng = random.Random(97)
    for _ in range(200):
        for line in _program(rng).splitlines():
            assert len(line) <= 72, line

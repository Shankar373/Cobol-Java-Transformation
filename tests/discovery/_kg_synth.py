"""Deterministic synthetic COBOL estate generator for the knowledge-graph scale benchmark (criterion 11)."""

from __future__ import annotations

import random
from pathlib import Path

from tests.discovery.helpers import _fixed

#: Share of the corpus that each file class takes; the remainder are programs.
COPYBOOK_EVERY = 20
JOB_EVERY = 10
TABLE_COUNT = 50


def synth_files(count: int, seed: int = 20260101) -> dict[str, str]:
    """``count`` files: programs (CALL, COPY, EXEC SQL, file verbs, PERFORM), copybooks, JCL jobs and one SQL schema.

    The result is a pure function of ``(count, seed)``; no clock, no host state."""
    rng = random.Random(seed)
    copybooks = max(2, count // COPYBOOK_EVERY)
    jobs = max(1, count // JOB_EVERY)
    programs = max(2, count - copybooks - jobs - 1)
    files: dict[str, str] = {}
    for c in range(copybooks):
        nested = f"    COPY CPY{rng.randrange(c):05d}." if c and rng.random() < 0.3 else ""
        body = [f"01  REC-{c:05d}.", f"    05  FLD-{c:05d}-A PIC X(10).", f"    05  FLD-{c:05d}-B PIC 9(5)."]
        if nested:
            body.append(nested)
        files[f"copy/pkg{c % 20:02d}/CPY{c:05d}.cpy"] = _fixed(*body)
    for p in range(programs):
        n_calls = rng.randrange(0, 3)
        calls = [f"    CALL 'PGM{rng.randrange(programs):05d}' USING WS-A." for _ in range(n_calls)]
        copies = [f"    COPY CPY{rng.randrange(copybooks):05d}." for _ in range(rng.randrange(1, 3))]
        table = f"SCH.TBL{rng.randrange(TABLE_COUNT):03d}"
        verb = rng.choice(("READ", "WRITE", "REWRITE"))
        files[f"app{p % 40:02d}/PGM{p:05d}.cbl"] = _fixed(
            "IDENTIFICATION DIVISION.", f"PROGRAM-ID. PGM{p:05d}.",
            "ENVIRONMENT DIVISION.", "INPUT-OUTPUT SECTION.", "FILE-CONTROL.",
            f"    SELECT F{p:05d} ASSIGN TO DD{p % 97:03d}.",
            "DATA DIVISION.", "FILE SECTION.", f"FD  F{p:05d}.", f"01  F{p:05d}-REC PIC X(80).",
            "WORKING-STORAGE SECTION.", "01  WS-A PIC X.", *copies,
            "PROCEDURE DIVISION.", "MAIN-PARA.", "    PERFORM WORK-PARA.", "    GO TO DONE-PARA.",
            "WORK-PARA.", f"    {verb} F{p:05d}-REC.",
            f"    EXEC SQL SELECT C INTO :WS-A FROM {table} END-EXEC.",
            f"    EXEC SQL UPDATE {table} SET C = 1 END-EXEC.", *calls,
            "DONE-PARA.", "    GOBACK.")
    for j in range(jobs):
        steps = [f"//S{s}       EXEC PGM=PGM{(j * 3 + s) % programs:05d}\n"
                 f"//DD{((j * 3 + s) % programs) % 97:03d}    DD DSN=PROD.DS{j:05d}{s},DISP=SHR\n"
                 for s in range(rng.randrange(1, 4))]
        files[f"jcl/JOB{j:05d}.jcl"] = f"//JOB{j:05d}  JOB (ACCT),'X',CLASS=A\n" + "".join(steps)
    files["db/schema.sql"] = "".join(f"CREATE TABLE SCH.TBL{t:03d} (C INTEGER);\n" for t in range(TABLE_COUNT))
    return files


def write_synth(root: Path, count: int, seed: int = 20260101) -> int:
    files = synth_files(count, seed)
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return len(files)

"""Roadmap unit 8: the generated launcher runs utilities, dispositions and GDGs.

No IBM utility or JES is available, so there is no mainframe oracle: the expected values
below are the documented behaviours of IEFBR14, IEBGENER, IDCAMS and generation data groups
(DISP defaults, DELETE of a missing entry is condition code 8, a duplicate DEFINE is 12,
``(+1)`` is the next generation and ``(0)``/``(-n)`` count back from the generation current
when the job started, roll-off beyond LIMIT, a JCL error ends the job). This is
simulator-grade evidence for the launcher's own semantics; it does not claim z/OS equivalence.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.jcl.orchestrator import orchestrate
from engine.transformation.jcl_parser import JclParser

JAVA_IMAGE = "eclipse-temurin:21-jdk"

STEP_CLASSES = {
    "GenWrite.java": (
        "import java.nio.file.*;\n"
        "public class GenWrite { public static void main(String[] a) throws Exception {\n"
        "  Path p = Paths.get(System.getenv(\"DD_OUTDD\"));\n"
        "  Files.write(p, (p.getFileName() + \"\\n\").getBytes()); } }\n"
    ),
    "GenRead.java": (
        "import java.nio.file.*;\n"
        "public class GenRead { public static void main(String[] a) throws Exception {\n"
        "  for (String dd : new String[] {\"DD_INDD\", \"DD_PREV\"}) {\n"
        "    String p = System.getenv(dd);\n"
        "    if (p != null) System.out.println(dd + \" \" + new String(Files.readAllBytes(Paths.get(p))).trim());\n"
        "  } } }\n"
    ),
}

JOBS = """\
//UTILJ    JOB CLASS=A
//S1       EXEC PGM=IEFBR14
//NEWDS    DD DSN=HR.EMPTY,DISP=(NEW,CATLG)
//GONE     DD DSN=HR.GONE,DISP=(NEW,DELETE)
//S2       EXEC PGM=IEBGENER
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD *
AAA
  BBB
/*
//SYSUT2   DD DSN=HR.COPY,DISP=(NEW,CATLG)
//S3       EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//IN       DD DSN=HR.COPY,DISP=SHR
//OUT      DD DSN=HR.REPRO,DISP=(NEW,CATLG)
//SYSIN    DD *
  DELETE HR.NOSUCH PURGE
  REPRO INFILE(IN) OUTFILE(OUT)
/*
//UTILK    JOB CLASS=A
//S1       EXEC PGM=IDCAMS
//SYSIN    DD *
  DELETE HR.NOSUCH
  SET MAXCC = 0
/*
//DUPJ     JOB CLASS=A
//S1       EXEC PGM=IDCAMS
//SYSIN    DD *
  DEFINE GDG (NAME(HR.GDG) LIMIT(2))
/*
//DEFJ     JOB CLASS=A
//S1       EXEC PGM=IDCAMS
//SYSIN    DD *
  DEFINE GDG (NAME(HR.GDG) LIMIT(2) NOEMPTY SCRATCH)
/*
//WRITEJ   JOB CLASS=A
//S1       EXEC PGM=GENWRITE
//OUTDD    DD DSN=HR.GDG(+1),DISP=(NEW,CATLG)
//READJ    JOB CLASS=A
//S1       EXEC PGM=GENREAD
//INDD     DD DSN=HR.GDG(0),DISP=SHR
//PREV     DD DSN=HR.GDG(-1),DISP=SHR
//KEEPJ    JOB CLASS=A
//S1       EXEC PGM=GENWRITE
//OUTDD    DD DSN=HR.KEEP,DISP=(NEW,KEEP)
//S2       EXEC PGM=GENWRITE
//OUTDD    DD DSN=HR.KEEP,DISP=(OLD,DELETE)
//LOSTJ    JOB CLASS=A
//S1       EXEC PGM=GENREAD
//INDD     DD DSN=HR.MISSING,DISP=OLD
"""


def _build(tmp_path: Path):
    app = JclParser().parse_application({"JOBS.jcl": JOBS})
    result = orchestrate(app, {"GENWRITE": "GenWrite", "GENREAD": "GenRead"})
    for plan in result.plans:
        assert plan.runnable, (plan.job, plan.refusals)
    root = tmp_path / "w"
    (root / "src").mkdir(parents=True)
    os.chmod(root, 0o777)
    os.chmod(root / "src", 0o777)
    for name, source in STEP_CLASSES.items():
        (root / "src" / name).write_text(source, encoding="utf-8", newline="\n")
    for name, source in result.files.items():
        (root / "src" / f"{name}.java").write_text(source, encoding="utf-8", newline="\n")
    return root


def _run(root: Path, script: str):
    prelude = "mkdir -p /tmp/c && javac -nowarn -d /tmp/c /w/src/*.java && "
    cmd = ["docker", "run", "--rm", "--network", "none", "-w", "/w", "-v", f"{root}:/w",
           JAVA_IMAGE, "sh", "-c", prelude + script]
    done = subprocess.run(cmd, capture_output=True, timeout=900)
    assert done.returncode == 0, done.stderr.decode(errors="replace") + done.stdout.decode(errors="replace")
    return done.stdout.decode().splitlines()


def _runner(job: str, data: str) -> str:
    return f"java -cp /tmp/c Job{job.title()}Runner /w/{data} /tmp/c; echo \"exit=$?\"; "


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    return _build(tmp_path_factory.mktemp("jcl-utilities"))


def test_utilities_and_dispositions(root):
    lines = _run(root, _runner("UTILJ", "d1") + _runner("UTILK", "d2") + (
        "echo files; (cd /w/d1 && ls -A | sort); echo copy; cat /w/d1/HR.COPY; echo repro; cat /w/d1/HR.REPRO;"
        " echo size; wc -c < /w/d1/HR.EMPTY"))
    assert lines[:5] == [
        "JCL step S1 RC=0", "JCL step S2 RC=0", "JCL step S3 RC=8", "JCL job UTILJ MAXRC=8", "exit=8"]
    # SET MAXCC = 0 overrides the condition code 8 of the DELETE of a missing entry
    assert lines[5:8] == ["JCL step S1 RC=0", "JCL job UTILK MAXRC=0", "exit=0"]
    rest = lines[lines.index("files"):]
    # HR.GONE (NEW,DELETE) is gone, the inline SYSUT1 left no trace, HR.EMPTY is allocated empty
    assert rest[1:4] == ["HR.COPY", "HR.EMPTY", "HR.REPRO"]
    assert rest[rest.index("copy") + 1: rest.index("repro")] == ["AAA", "  BBB"]
    assert rest[rest.index("repro") + 1: rest.index("size")] == ["AAA", "  BBB"]
    assert rest[-1] == "0"


def test_generation_data_group_lifecycle(root):
    lines = _run(root, (
        _runner("DEFJ", "g") + _runner("DUPJ", "g")
        + _runner("WRITEJ", "g") + _runner("WRITEJ", "g") + _runner("WRITEJ", "g")
        + _runner("READJ", "g") + "ls /w/g | sort; cat /w/g/_catalog/HR.GDG.gdg"))
    write = ["JCL step S1 RC=0", "JCL job WRITEJ MAXRC=0", "exit=0"]
    listing, catalog = lines[-4:-1], lines[-1]  # `ls` order depends on the container locale
    assert sorted(listing) == ["HR.GDG.G0002V00", "HR.GDG.G0003V00", "_catalog"]
    assert catalog == "LIMIT=2"
    assert lines[:-4] == [
        # DEFINE GDG, then the duplicate DEFINE: condition code 12
        "JCL step S1 RC=0", "JCL job DEFJ MAXRC=0", "exit=0",
        "JCL step S1 RC=12", "JCL job DUPJ MAXRC=12", "exit=12",
        # three (+1) runs with LIMIT(2): generation 1 rolled off after the third
        *write, *write, *write,
        # (0) is the newest generation, (-1) the one before it
        "DD_INDD HR.GDG.G0003V00", "DD_PREV HR.GDG.G0002V00",
        "JCL step S1 RC=0", "JCL job READJ MAXRC=0", "exit=0",
    ]


def test_jcl_errors_end_the_job(root):
    lines = _run(root, (
        _runner("LOSTJ", "e1")      # OLD dataset that does not exist
        + _runner("READJ", "e2")    # GDG base never defined
        + _runner("KEEPJ", "e3")))  # NEW,KEEP then OLD,DELETE of the same dataset
    assert lines[0].startswith("JCL ERROR dataset HR.MISSING") and lines[1] == "exit=255"
    assert lines[2] == "JCL ERROR GDG base HR.GDG is not defined" and lines[3] == "exit=255"
    assert lines[4:] == ["JCL step S1 RC=0", "JCL step S2 RC=0", "JCL job KEEPJ MAXRC=0", "exit=0"]

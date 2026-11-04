"""Roadmap unit 6: the generated job runner executes a JCL job end to end.

Two proofs, both in containers:

1. A two-program job hands a dataset from step to step. GnuCOBOL runs the same programs in
   the same order with the same ``DD_<name>`` bindings (a shell script that mirrors the
   JCL); the Java runner must print the same program output and step return codes and
   leave the same dataset bytes behind.
2. The ``COND=(code,op[,step])`` bypass rules run on a live JVM with steps whose return
   codes are fixed, and must match the rules as IBM documents them ("bypass when
   ``code op rc`` holds").

JES itself is not available; the shell script is the reference for what a job step does,
not a JES oracle.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.jcl.orchestrator import orchestrate
from engine.transformation.jcl_parser import JclParser
from engine.transformation.producer import TransformationProducer
from tests.oracle_java_helpers import ORACLE_IMAGE

JAVA_IMAGE = "eclipse-temurin:21-jdk"

PRODUCER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRODUCER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO OUTDD
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD OUT-FILE.
       01 OUT-REC PIC X(10).
       PROCEDURE DIVISION.
           OPEN OUTPUT OUT-FILE
           MOVE "ALPHA" TO OUT-REC
           WRITE OUT-REC
           MOVE "BETA" TO OUT-REC
           WRITE OUT-REC
           CLOSE OUT-FILE
           DISPLAY "PRODUCED"
           MOVE 4 TO RETURN-CODE
           STOP RUN.
"""

CONSUMER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONSUMER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INDD
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE
           PERFORM UNTIL EOF-FLAG = "Y"
               READ IN-FILE
                   AT END MOVE "Y" TO EOF-FLAG
                   NOT AT END DISPLAY "GOT [" IN-REC "]"
               END-READ
           END-PERFORM
           CLOSE IN-FILE
           STOP RUN.
"""

JOB = """\
//SEQJOB   JOB CLASS=A
//STEP1    EXEC PGM=PRODUCER
//OUTDD    DD DSN=HR.DATA,DISP=(NEW,CATLG)
//STEP2    EXEC PGM=CONSUMER,COND=(8,LT)
//INDD     DD DSN=HR.DATA,DISP=SHR
//STEP3    EXEC PGM=CONSUMER,COND=(3,LT)
//INDD     DD DSN=HR.DATA,DISP=SHR
"""

# What the job does, written as the shell steps it stands for (STEP3 is bypassed: 3 < 4).
REFERENCE = """\
cd /w
mkdir -p data
DD_OUTDD=/w/data/HR.DATA /tmp/producer; rc=$?
echo "JCL step STEP1 RC=$rc"
DD_INDD=/w/data/HR.DATA /tmp/consumer; rc2=$?
echo "JCL step STEP2 RC=$rc2"
echo "JCL step STEP3 BYPASSED"
echo "JCL job SEQJOB MAXRC=$rc"
exit $rc
"""


def _docker(image: str, workdir: Path, script: str):
    cmd = ["docker", "run", "--rm", "--network", "none", "-w", "/w", "-v", f"{workdir}:/w",
           image, "sh", "-c", script]
    return subprocess.run(cmd, capture_output=True, timeout=600)


def _prepare(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    os.chmod(root, 0o777)
    os.chmod(root / "src", 0o777)


def _transform(source: str, name: str):
    result = TransformationProducer().transform(source, name)
    assert result.success is True, result.errors
    return result.generated_files


def _needs_docker() -> None:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")


def test_job_runner_matches_the_reference_run(tmp_path):
    _needs_docker()
    producer, consumer = _transform(PRODUCER, "PRODUCER"), _transform(CONSUMER, "CONSUMER")
    classes = {"PRODUCER": producer[0].class_name, "CONSUMER": consumer[0].class_name}
    app = JclParser().parse_application({"SEQJOB.jcl": JOB})
    result = orchestrate(app, classes)
    assert result.plans[0].runnable, result.plans[0].refusals
    (runner_name, runner_source), = result.files.items()

    cobol_dir, java_dir = tmp_path / "cobol", tmp_path / "java"
    _prepare(cobol_dir)
    _prepare(java_dir)
    (cobol_dir / "src" / "PRODUCER.cob").write_text(PRODUCER, encoding="utf-8", newline="\n")
    (cobol_dir / "src" / "CONSUMER.cob").write_text(CONSUMER, encoding="utf-8", newline="\n")
    (cobol_dir / "ref.sh").write_text(REFERENCE, encoding="utf-8", newline="\n")
    for generated in (*producer, *consumer):
        (java_dir / "src" / generated.filename).write_text(
            generated.source_code, encoding="utf-8", newline="\n")
    (java_dir / "src" / f"{runner_name}.java").write_text(runner_source, encoding="utf-8", newline="\n")

    cobol = _docker(
        ORACLE_IMAGE, cobol_dir,
        "cobc -x /w/src/PRODUCER.cob -o /tmp/producer && cobc -x /w/src/CONSUMER.cob -o /tmp/consumer"
        " && sh /w/ref.sh")
    java = _docker(
        JAVA_IMAGE, java_dir,
        f"mkdir -p /tmp/c && javac -nowarn -d /tmp/c /w/src/*.java && java -cp /tmp/c {runner_name} /w/data /tmp/c")

    # the job's highest return code (4) is the exit status on both sides
    assert cobol.returncode == 4, cobol.stderr.decode(errors="replace")
    assert java.returncode == 4, java.stderr.decode(errors="replace")
    assert java.stdout == cobol.stdout
    assert cobol.stdout.decode().splitlines() == [
        "PRODUCED", "JCL step STEP1 RC=4",
        "GOT [ALPHA     ]", "GOT [BETA      ]", "JCL step STEP2 RC=0",
        "JCL step STEP3 BYPASSED", "JCL job SEQJOB MAXRC=4",
    ]
    assert (java_dir / "data" / "HR.DATA").read_bytes() == (cobol_dir / "data" / "HR.DATA").read_bytes()


def test_cond_rules_on_a_live_jvm(tmp_path):
    _needs_docker()
    steps = {f"RC{n}": f"public class Rc{n} {{ public static void main(String[] a) {{ System.exit({n}); }} }}\n"
             for n in (0, 4, 8)}
    jcl = (
        "//CONDJOB  JOB CLASS=A\n"
        "//S1 EXEC PGM=RC4\n"
        "//S2 EXEC PGM=RC0,COND=(4,LT)\n"           # 4 < 4 false  -> runs
        "//S3 EXEC PGM=RC0,COND=(3,LT)\n"           # 3 < 4 true   -> bypassed
        "//S4 EXEC PGM=RC8,COND=(4,EQ,S1)\n"        # 4 = 4 true   -> bypassed
        "//S5 EXEC PGM=RC0,COND=((0,NE),(8,GT))\n"  # 0 <> 4 true  -> bypassed
        "//S6 EXEC PGM=RC0,COND=(9,LT,S2)\n"        # 9 < 0 false  -> runs
        "//S7 EXEC PGM=RC8,COND=(8,GE)\n"           # 8 >= 4 true  -> bypassed
    )
    classes = {name: f"Rc{name[2:]}" for name in steps}
    result = orchestrate(JclParser().parse_application({"CONDJOB.jcl": jcl}), classes)
    assert result.plans[0].runnable, result.plans[0].refusals
    (runner_name, runner_source), = result.files.items()

    root = tmp_path / "java"
    _prepare(root)
    for name, source in steps.items():
        (root / "src" / f"Rc{name[2:]}.java").write_text(source, encoding="utf-8", newline="\n")
    (root / "src" / f"{runner_name}.java").write_text(runner_source, encoding="utf-8", newline="\n")
    run = _docker(
        JAVA_IMAGE, root,
        f"mkdir -p /tmp/c && javac -nowarn -d /tmp/c /w/src/*.java && java -cp /tmp/c {runner_name} /w/data /tmp/c")

    assert run.stdout.decode().splitlines() == [
        "JCL step S1 RC=4", "JCL step S2 RC=0", "JCL step S3 BYPASSED", "JCL step S4 BYPASSED",
        "JCL step S5 BYPASSED", "JCL step S6 RC=0", "JCL step S7 BYPASSED", "JCL job CONDJOB MAXRC=4",
    ]
    assert run.returncode == 4

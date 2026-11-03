"""Roadmap unit 4: ``ASSIGN TO ddname`` resolves exactly as GnuCOBOL's libcob does.

A mainframe program names its files by DD name (``SELECT F ASSIGN TO CUSTFILE``)
and the JCL step binds the DD to a dataset. GnuCOBOL resolves that name from the
environment; the oracle probe (GnuCOBOL 3.1.2) established the rules this test pins:

- the name is looked up as ``DD_<name>``, then ``dd_<name>``, then ``<name>``
  (first one found wins);
- an absolute result is used as is; a relative result (or the plain name) goes under
  ``COB_FILE_PATH`` when set, else the working directory.

Both sides run the same program in containers with identical mounts and environment;
the files each leaves behind and what they print must match.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.producer import TransformationProducer
from tests.oracle_java_helpers import ORACLE_IMAGE

JAVA_IMAGE = "eclipse-temurin:21-jdk"

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DDP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO CUSTFILE
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD F.
       01 REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT F
           DISPLAY "out " FS
           MOVE "HELLO" TO REC
           WRITE REC
           CLOSE F
           OPEN INPUT F
           DISPLAY "in  " FS
           READ F
           DISPLAY "got [" REC "]"
           CLOSE F
           STOP RUN.
"""

SCENARIOS = {
    "no environment": {},
    "DD_ name": {"DD_CUSTFILE": "/w/a.out"},
    "dd_ name": {"dd_CUSTFILE": "/w/b.out"},
    "bare name": {"CUSTFILE": "/w/c.out"},
    "DD_ beats dd_": {"DD_CUSTFILE": "/w/a.out", "dd_CUSTFILE": "/w/b.out"},
    "dd_ beats bare": {"dd_CUSTFILE": "/w/b.out", "CUSTFILE": "/w/c.out"},
    "DD_ beats bare": {"DD_CUSTFILE": "/w/a.out", "CUSTFILE": "/w/c.out"},
    "COB_FILE_PATH only": {"COB_FILE_PATH": "/w/fp"},
    "relative DD_ under COB_FILE_PATH": {"DD_CUSTFILE": "rel.out", "COB_FILE_PATH": "/w/fp"},
    "absolute DD_ ignores COB_FILE_PATH": {"DD_CUSTFILE": "/w/d.out", "COB_FILE_PATH": "/w/fp"},
    "relative DD_ without COB_FILE_PATH": {"DD_CUSTFILE": "rel.out"},
}


def _docker(image: str, mounts: dict[Path, str], env: dict[str, str], script: str):
    cmd = ["docker", "run", "--rm", "--network", "none", "-w", "/w"]
    for host, target in mounts.items():
        cmd += ["-v", f"{host}:{target}"]
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [image, "sh", "-c", script]
    return subprocess.run(cmd, capture_output=True, timeout=300)


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root).parts[0] != "src"
    }


@pytest.fixture(scope="module")
def java_sources():
    result = TransformationProducer().transform(PROGRAM, "DDP")
    assert result.success is True, result.errors
    return result.generated_files


@pytest.mark.parametrize("label", sorted(SCENARIOS))
def test_resolution_matches_gnucobol(tmp_path, java_sources, label):
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    env = SCENARIOS[label]
    oracle_dir, java_dir = tmp_path / "oracle", tmp_path / "java"
    for root in (oracle_dir, java_dir):
        (root / "fp").mkdir(parents=True)
        os.chmod(root, 0o777)
        os.chmod(root / "fp", 0o777)
    (oracle_dir / "src").mkdir()
    (oracle_dir / "src" / "DDP.cob").write_text(PROGRAM, encoding="utf-8", newline="\n")
    (java_dir / "src").mkdir()
    for generated in java_sources:
        (java_dir / "src" / generated.filename).write_text(
            generated.source_code, encoding="utf-8", newline="\n")
    os.chmod(oracle_dir / "src", 0o777)
    os.chmod(java_dir / "src", 0o777)

    cobol = _docker(ORACLE_IMAGE, {oracle_dir: "/w"}, env,
                    "cobc -x /w/src/DDP.cob -o /tmp/ddp && /tmp/ddp")
    main = java_sources[0].class_name
    java = _docker(JAVA_IMAGE, {java_dir: "/w"}, env,
                   f"mkdir -p /tmp/c && javac -nowarn -d /tmp/c /w/src/*.java && java -cp /tmp/c {main}")

    assert cobol.returncode == 0, cobol.stderr.decode(errors="replace")
    assert java.returncode == 0, java.stderr.decode(errors="replace")
    assert java.stdout == cobol.stdout
    assert _tree(java_dir) == _tree(oracle_dir)
    assert cobol.stdout.decode().splitlines()[-1] == "got [HELLO     ]"


# --- hermetic: the parser certifies the plain ddname form and nothing more ------------

HEAD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
)
TAIL = (
    "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n       01 REC PIC X(10).\n"
    "       PROCEDURE DIVISION.\n           STOP RUN.\n"
)


def _parse(select: str):
    parser = CobolParser()
    program = parser.parse(HEAD + select + TAIL)
    return program, [d.message for d in parser.diagnostics.all]


def test_plain_ddname_is_certified_and_marked():
    program, diagnostics = _parse("           SELECT F ASSIGN TO CUSTFILE.\n")
    fd = program.file_definitions[0]
    assert (fd.container_path, fd.assign_kind) == ("CUSTFILE", "DDNAME")
    assert not [d for d in diagnostics if "no literal file name" in d]


def test_literal_names_keep_their_kind():
    program, _ = _parse('           SELECT F ASSIGN TO "/data/in.dat".\n')
    fd = program.file_definitions[0]
    assert (fd.container_path, fd.assign_kind) == ("/data/in.dat", "LITERAL")


@pytest.mark.parametrize("select", [
    "           SELECT F ASSIGN TO custfile.\n",            # lower case: libcob case rule not probed
    "           SELECT F ASSIGN TO SYSOUT.\n",              # would be lowered as stdout
    "           SELECT F ASSIGN TO PRINTER.\n",             # device
    "           SELECT F ASSIGN TO DISK.\n",
    "           SELECT F ASSIGN TO EXTERNAL CUSTFILE.\n",   # EXTERNAL/DYNAMIC forms
    "           SELECT F ASSIGN USING WS-NAME.\n",
])
def test_other_forms_stay_uncertified(select):
    program, diagnostics = _parse(select)
    assert program.file_definitions[0].assign_kind != "DDNAME"
    assert any("no literal file name" in d or "has no certified" in d for d in diagnostics), diagnostics


def test_generated_java_resolves_through_the_runtime():
    program = HEAD + "           SELECT F ASSIGN TO CUSTFILE.\n" + TAIL.replace(
        "           STOP RUN.\n",
        "           OPEN OUTPUT F\n           CLOSE F\n           STOP RUN.\n")
    result = TransformationProducer().transform(program, "T")
    assert result.success is True, result.errors
    source = result.generated_files[0].source_code
    assert 'CobolFileIo.open("CUSTFILE"' in source
    assert "static String map(String name)" in source
    assert 'System.getenv("DD_" + name)' in source


def test_a_target_that_is_also_a_data_item_is_not_a_ddname():
    # GnuCOBOL reads ``ASSIGN TO <data-item>`` as a variable file name (dynamic assignment).
    parser = CobolParser()
    program = parser.parse(
        HEAD + "           SELECT F ASSIGN TO WS-NAME.\n"
        + TAIL.replace("       PROCEDURE", "       WORKING-STORAGE SECTION.\n       01 WS-NAME PIC X(8).\n       PROCEDURE")
    )
    fd = program.file_definitions[0]
    assert fd.assign_kind != "DDNAME"
    assert any("no literal file name" in d.message for d in parser.diagnostics.all)

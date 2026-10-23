"""GnuCOBOL oracle proof for indexed and relative file transformation.

Both shipped fixtures are transformed by the real ``ApplicationGenerator`` and
executed in the Temurin image; the original COBOL is compiled and executed by
GnuCOBOL 3.1.2.  The compared contract is stdout (every FILE STATUS value is
printed by the programs) and exit status.

Scope of the claim: the *generated program behaviour* is byte-identical for
these workloads.  The on-disk representation is an emulation (a keyed side
file), not VSAM, so file-image equivalence is NOT claimed.  ALTERNATE RECORD
KEY has no lowering and is a separate fail-closed diagnostic.

Docker-gated; the deterministic capability contracts live in
``tests/transformation/test_indexed_relative_transformation.py``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator

ROOT = Path(__file__).resolve().parents[2]
GNUCobol_IMAGE = "gnucobol-ocesql:latest"
JAVA_IMAGE = "eclipse-temurin:21-jdk"

INDEXED_DIR = ROOT / "fixtures" / "workload-indexed-file" / "cobol"
RELATIVE_DIR = ROOT / "fixtures" / "workload-relative-file" / "cobol"


def _docker_images_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return False
        images = result.stdout.decode(errors="replace")
        return GNUCobol_IMAGE in images and JAVA_IMAGE in images
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(
    not _docker_images_available(),
    reason="docker and GnuCOBOL/temurin images unavailable",
)


def _copy_sources(src_dir: Path, workdir: Path) -> None:
    for cob in sorted(src_dir.glob("*.cob")):
        shutil.copy2(cob, workdir / cob.name)


def _run_gnucobol(workdir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none",
            "-v", f"{workdir}:/src", "-w", "/src",
            GNUCobol_IMAGE,
            "bash", "-c", "cobc -free -x -o prog MAIN.cob && ./prog",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )


def _run_generated_java(
    src_dir: Path, workdir: Path, application_id: str
) -> subprocess.CompletedProcess:
    app = ApplicationDiscovery().discover(str(src_dir), application_id=application_id)
    generated = ApplicationGenerator().generate(app, source_root=src_dir)
    assert generated.success, generated.errors
    ApplicationGenerator.write_to_directory(generated, workdir)
    entry = generated.entrypoint
    assert entry
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{workdir}:/app", "-w", "/app",
            JAVA_IMAGE,
            "bash", "-c", f"javac *.java && java {entry}",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )


def _stdout(result: subprocess.CompletedProcess) -> list[str]:
    return result.stdout.decode(errors="replace").splitlines()


def _prove(tmp_path: Path, src_dir: Path, application_id: str) -> list[str]:
    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir()
    _copy_sources(src_dir, oracle_dir)
    oracle = _run_gnucobol(oracle_dir)
    assert oracle.returncode == 0, oracle.stderr.decode(errors="replace")

    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    java = _run_generated_java(src_dir, candidate_dir, application_id)
    assert java.returncode == 0, java.stderr.decode(errors="replace")

    assert _stdout(java) == _stdout(oracle)
    return _stdout(oracle)


@needs_docker
def test_indexed_file_transformation_is_byte_identical(tmp_path: Path) -> None:
    out = _prove(tmp_path, INDEXED_DIR, "indexed-file")
    assert out == [
        "INDEXED FILE DEMO STARTED",
        "OPEN OUTPUT STATUS=00",
        "WRITE K001 STATUS=00",
        "WRITE K002 STATUS=00",
        "WRITE K003 STATUS=00",
        "CLOSE STATUS=00",
        "OPEN I-O STATUS=00",
        "REWRITE K002 STATUS=00",
        "DELETE K001 STATUS=00",
        "START K001 STATUS=00",
        "READ: KEY=K002 DATA=REC-TWO-UPDATED----  STATUS=00",
        "READ: KEY=K003 DATA=RECORD-THREE-DATA--- STATUS=00",
        "RECORDS READ=02",
        "FINAL CLOSE STATUS=00",
    ]


@needs_docker
def test_relative_file_transformation_is_byte_identical(tmp_path: Path) -> None:
    out = _prove(tmp_path, RELATIVE_DIR, "relative-file")
    assert out == [
        "RELATIVE FILE DEMO STARTED",
        "OPEN OUTPUT STATUS=00",
        "WRITE RRN=1 STATUS=00",
        "WRITE RRN=2 STATUS=00",
        "WRITE RRN=3 STATUS=00",
        "CLOSE STATUS=00",
        "OPEN I-O STATUS=00",
        "REWRITE RRN=2 STATUS=00",
        "DELETE RRN=1 STATUS=00",
        "READ RRN=0001 INVALID KEY STATUS=23",
        "READ: RRN=0002 DATA=REL-REC-TWO-UPD----  STATUS=00",
        "READ: RRN=0003 DATA=REL-RECORD-THREE---- STATUS=00",
        "RECORDS READ=02",
        "FINAL CLOSE STATUS=00",
    ]

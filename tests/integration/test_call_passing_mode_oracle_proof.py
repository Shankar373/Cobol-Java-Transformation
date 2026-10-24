"""GnuCOBOL oracle proof (and blocker pin) for CALL parameter-passing modes.

Certified lane
--------------
``CALL ... USING BY CONTENT`` must leave the caller's item unchanged while the
callee works on its own copy.  Two independent workloads are compared byte for
byte between GnuCOBOL 3.1.2 and the generated Java:

1. the shipped ``fixtures/workload-by-content`` pair (single BY CONTENT);
2. ``tests/fixtures/call_byref`` (mixed ``BY REFERENCE`` + ``BY CONTENT``),
   which proves BY CONTENT does not disable BY REFERENCE write-back.

Blocked lane
------------
``CALL ... USING BY VALUE`` cannot be certified against the only available
COBOL runtime: GnuCOBOL 3.1.2's BY VALUE implementation is unfinished and
aborts with SIGSEGV while reading the callee's parameter.  The test below pins
that exact blocker instead of fabricating an equivalence claim, and separately
shows the generated Java implements the documented no-write-back rule.  This
is why the registry keeps ``BY VALUE`` PARTIAL, never SUPPORTED.
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

BY_CONTENT_DIR = ROOT / "fixtures" / "workload-by-content" / "cobol"
BY_VALUE_DIR = ROOT / "fixtures" / "workload-by-value" / "cobol"
MIXED_DIR = ROOT / "tests" / "fixtures" / "call_byref"


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


def _run_gnucobol(workdir: Path, modules: tuple[str, ...]) -> subprocess.CompletedProcess:
    """Compile the module list with MAIN first, then run it."""
    return subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none",
            "-v", f"{workdir}:/src", "-w", "/src",
            GNUCobol_IMAGE,
            "bash", "-c",
            "cobc -free -x -o prog " + " ".join(modules) + " && ./prog",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )


def _run_generated_java(
    src_dir: Path, workdir: Path, application_id: str
) -> subprocess.CompletedProcess:
    app = ApplicationDiscovery().discover(str(src_dir), application_id=application_id)
    generated = ApplicationGenerator().generate(
        app, entrypoint="MAIN", source_root=src_dir
    )
    assert generated.success, generated.errors
    ApplicationGenerator.write_to_directory(generated, workdir)
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{workdir}:/app", "-w", "/app",
            JAVA_IMAGE,
            "bash", "-c", "javac *.java && java Main",
        ],
        capture_output=True,
        timeout=240,
        check=False,
    )


def _stdout(result: subprocess.CompletedProcess) -> list[str]:
    return result.stdout.decode(errors="replace").splitlines()


def _stderr(result: subprocess.CompletedProcess) -> str:
    return result.stderr.decode(errors="replace")


@needs_docker
def test_shipped_by_content_fixture_is_byte_identical(tmp_path: Path) -> None:
    src = tmp_path / "cobol"
    src.mkdir()
    _copy_sources(BY_CONTENT_DIR, src)

    oracle = _run_gnucobol(src, ("MAIN.cob", "MODIFY.cob"))
    assert oracle.returncode == 0, _stderr(oracle)

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    java = _run_generated_java(src, candidate, "by-content")
    assert java.returncode == 0, _stderr(java)

    assert _stdout(java) == _stdout(oracle)
    assert _stdout(oracle) == [
        "MAIN STARTED",
        "BEFORE CALL VALUE=0100",
        "MODIFY STARTED",
        "MODIFY RECEIVED VALUE=0100",
        "MODIFY CHANGED LOCAL COPY=0150",
        "AFTER CALL VALUE=0100",
    ]


@needs_docker
def test_mixed_reference_and_content_is_byte_identical(tmp_path: Path) -> None:
    """BY CONTENT must not disturb BY REFERENCE write-back in the same call."""
    src = tmp_path / "cobol"
    src.mkdir()
    _copy_sources(MIXED_DIR, src)

    oracle = _run_gnucobol(
        src, ("MAIN.cob", "DOUBLE.cob", "TRIPLE.cob")
    )
    assert oracle.returncode == 0, _stderr(oracle)

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    java = _run_generated_java(src, candidate, "call-byref")
    assert java.returncode == 0, _stderr(java)

    assert _stdout(java) == _stdout(oracle)
    assert _stdout(oracle) == [
        "CALL-START",
        "A0=0005",
        "A=1105",
        "B=0007",
        "CALL-END",
    ]


@needs_docker
def test_gnucobol_cannot_serve_as_a_by_value_oracle(tmp_path: Path) -> None:
    """Pin the exact blocker that keeps BY VALUE below SUPPORTED.

    GnuCOBOL's unfinished BY VALUE parameter support passes an unallocated
    pointer, so the oracle itself aborts.  A test that "passed" by comparing
    against truncated output would fabricate runtime proof; this test asserts
    the abort instead, and checks the Java lowering against the language rule
    only.
    """
    src = tmp_path / "cobol"
    src.mkdir()
    _copy_sources(BY_VALUE_DIR, src)

    oracle = _run_gnucobol(src, ("MAIN.cob", "MODIFY.cob"))
    assert oracle.returncode != 0
    stderr = _stderr(oracle)
    assert "SIGSEGV" in stderr or "unallocated memory" in stderr
    # The callee never receives the caller's value: no oracle observation is
    # possible, so no equivalence claim may be derived from this run.
    assert "MODIFY CHANGED LOCAL COPY=0150" not in _stdout(oracle)

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    java = _run_generated_java(src, candidate, "by-value")
    assert java.returncode == 0, _stderr(java)
    # Documented lowering: callee mutates its own copy; caller is unchanged.
    assert _stdout(java) == [
        "MAIN STARTED",
        "BEFORE CALL VALUE=0100",
        "MODIFY STARTED",
        "MODIFY RECEIVED VALUE=0100",
        "MODIFY CHANGED LOCAL COPY=0150",
        "AFTER CALL VALUE=0100",
    ]

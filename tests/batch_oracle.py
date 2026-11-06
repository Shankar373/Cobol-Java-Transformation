"""Batch differential runner: many generated COBOL programs, one GnuCOBOL container and one JVM container.

``run_batch(tmp, programs)`` writes each program, compiles it with GnuCOBOL 3.1.2 (``cobc -free``) and as generated
Java (``JavaGenerator``), runs both with the network disabled and returns ``(cobol_stdout, java_stdout)`` per program.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator

GNUCOBOL_IMAGE = "gnucobol-ocesql:latest"
JAVA_IMAGE = "eclipse-temurin:21-jdk"


def images_available() -> bool:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        return False
    try:
        done = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                              capture_output=True, timeout=30)
        text = done.stdout.decode(errors="replace")
        return done.returncode == 0 and GNUCOBOL_IMAGE in text and JAVA_IMAGE in text
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_batch(tmp: Path, programs: list[str]) -> list[tuple[bytes, bytes]]:
    for index, source in enumerate(programs):
        directory = tmp / f"c{index:03d}"
        (directory / "cob").mkdir(parents=True)
        (directory / "jv").mkdir()
        (directory / "cob" / "p.cob").write_text(source, encoding="ascii", newline="\n")
        parser = CobolParser()
        program = parser.parse(source)
        blocking = [d.message for d in parser.diagnostics.all if d.code.name == "UNSUPPORTED_CONSTRUCT"]
        assert not blocking, blocking
        generated = JavaGenerator().generate(program)[0].source_code
        name = re.search(r"public\s+class\s+(\w+)", generated).group(1)
        (directory / "jv" / f"{name}.java").write_text(generated, encoding="utf-8", newline="\n")
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    cobol = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/t", GNUCOBOL_IMAGE, "bash", "-c",
         "for d in /t/c*/cob; do (cd $d && cobc -free -x -o p p.cob && timeout 20 ./p > stdout.txt); done"],
        capture_output=True, timeout=900, env=env)
    assert cobol.returncode == 0, cobol.stderr.decode(errors="replace")[-2000:]
    script = ("for d in /t/c*/jv; do (cd $d && javac -nowarn *.java && "
              "timeout 20 java -cp . $(ls *.java | head -1 | sed 's/.java//') > stdout.txt); done")
    java = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/t", JAVA_IMAGE, "bash", "-c", script],
        capture_output=True, timeout=1500, env=env)
    assert java.returncode == 0, java.stderr.decode(errors="replace")[-2000:]
    results = []
    for index in range(len(programs)):
        directory = tmp / f"c{index:03d}"
        pair = [(directory / sub / "stdout.txt").read_bytes() if (directory / sub / "stdout.txt").exists()
                else b"<none>" for sub in ("cob", "jv")]
        results.append((pair[0], pair[1]))
    return results

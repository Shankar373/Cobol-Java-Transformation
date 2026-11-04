"""Canonical simulator traces, their comparator, the Java runner and the verdict.

A trace is a list of text lines, one per scripted operation (see ``engine.simulators.mq.run_script``).
Two traces are equal only if they have the same lines in the same order; the comparator reports the
first divergence with its line number.  A verdict is ``SIMULATOR_VERIFIED`` only for equal, non-empty
traces; anything else is ``MISMATCH`` -- there is no partial credit and no IBM verdict.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from engine.execution.container_hardening import (
    container_run_hardening_flags,
    prepare_host_tree,
)
from engine.simulators import SIMULATOR_VERIFIED
from engine.simulators.mq_java import SIMMQ_JAVA

JAVA_IMAGE = "eclipse-temurin:21-jdk"
MISMATCH = "MISMATCH"


@dataclass(frozen=True)
class TraceDiff:
    equal: bool
    index: int = -1  # 0-based line of the first divergence
    left: str = ""
    right: str = ""
    left_count: int = 0
    right_count: int = 0

    @property
    def verdict(self) -> str:
        return SIMULATOR_VERIFIED if self.equal and self.left_count > 0 else MISMATCH


def compare_traces(left: list[str], right: list[str]) -> TraceDiff:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return TraceDiff(False, index, a, b, len(left), len(right))
    if len(left) != len(right):
        index = min(len(left), len(right))
        a = left[index] if index < len(left) else "<end of trace>"
        b = right[index] if index < len(right) else "<end of trace>"
        return TraceDiff(False, index, a, b, len(left), len(right))
    return TraceDiff(True, -1, "", "", len(left), len(right))


def run_java_script(
    class_name: str, source: str, script: str, *, timeout: int = 300, image: str = JAVA_IMAGE,
) -> list[str]:
    """Compile ``source`` (one class ``class_name``) and run ``script`` in a hardened, network-less container."""
    work = Path(tempfile.mkdtemp(prefix="sim-"))
    try:
        (work / f"{class_name}.java").write_text(source, encoding="utf-8", newline="\n")
        (work / "script.txt").write_text(script, encoding="utf-8", newline="\n")
        prepare_host_tree(work, writable=True)
        done = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", *container_run_hardening_flags("sim-java"),
             "-v", f"{work}:/w", "-w", "/w", image, "sh", "-c",
             f"mkdir -p /tmp/c && javac -nowarn -d /tmp/c {class_name}.java"
             f" && java -cp /tmp/c {class_name} script.txt"],
            capture_output=True, timeout=timeout, check=False, env=_env(),
        )
        if done.returncode != 0:
            raise RuntimeError(f"{class_name} Java run failed: " + done.stderr.decode("utf-8", "replace")[-2000:])
        return done.stdout.decode("utf-8").splitlines()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_java_trace(
    script: str, *, timeout: int = 300, image: str = JAVA_IMAGE, source: str = SIMMQ_JAVA,
) -> list[str]:
    """Run an MQ script through the Java SIMMQ-1 library."""
    return run_java_script("SimMq", source, script, timeout=timeout, image=image)


def _env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    return env

"""Suite-wide Docker lane gate.

Two lanes, chosen only by ``RUN_DOCKER_TESTS``:

- default (unset): hermetic.  ``DOCKER_HOST`` points at an unreachable
  endpoint for the whole session, so tests that probe ``docker info`` skip
  instead of launching containers merely because a daemon happens to be up,
  and the tests listed in ``tests/docker_lane.txt`` (Docker-dependent with no
  guard of their own) are skipped with an explicit reason.  The result of a
  default run therefore no longer depends on the host.
- ``RUN_DOCKER_TESTS=1``: the Docker lane (CI ``backend-oracle``).  Nothing is
  skipped by this gate; a missing daemon makes those tests fail, never skip.
"""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path

import pytest

_DOCKER_LANE = os.environ.get("RUN_DOCKER_TESTS") == "1"
_LANE_FILE = Path(__file__).with_name("docker_lane.txt")
_UNREACHABLE_DOCKER_HOST = "tcp://127.0.0.1:1"

if not _DOCKER_LANE:
    # Set at import time: module-level ``_docker_available()`` probes run
    # during collection, before any hook could change the environment.
    os.environ["DOCKER_HOST"] = _UNREACHABLE_DOCKER_HOST
    os.environ.pop("DOCKER_CONTEXT", None)


def _lane_prefixes() -> tuple[str, ...]:
    lines = _LANE_FILE.read_text(encoding="utf-8").splitlines()
    return tuple(
        line.strip() for line in lines if line.strip() and not line.startswith("#")
    )


def pytest_report_header(config):
    if _DOCKER_LANE:
        return "docker lane: ON (RUN_DOCKER_TESTS=1)"
    return (
        "docker lane: OFF (hermetic; DOCKER_HOST unreachable, "
        "docker_lane.txt tests skipped; set RUN_DOCKER_TESTS=1 to run them)"
    )


def pytest_collection_modifyitems(config, items):
    if _DOCKER_LANE:
        return
    prefixes = _lane_prefixes()
    used: set[str] = set()
    skip = pytest.mark.skip(
        reason="Docker lane test: set RUN_DOCKER_TESTS=1 to run it"
    )
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        hit = next(
            (
                p for p in prefixes
                if nodeid == p or nodeid.startswith((p + "::", p + "["))
            ),
            None,
        )
        if hit is not None or item.get_closest_marker("docker") is not None:
            item.add_marker(skip)
            if hit is not None:
                used.add(hit)
    collected_modules = {item.nodeid.split("::", 1)[0] for item in items}
    stale = [
        p for p in prefixes
        if p not in used and p.split("::", 1)[0] in collected_modules
    ]
    if stale:
        warnings.warn(
            pytest.PytestWarning(
                "tests/docker_lane.txt entries match no collected test: "
                + ", ".join(stale)
            )
        )


# Audit B1: on the Docker lane a missing daemon, image or JDK must fail, not
# skip. About 54 tests guard themselves with their own skipif/skip ("Docker
# not available", "javac/java not on PATH", ...) and would otherwise turn a
# broken CI image into a green run with fewer tests. One rule for all of them:
# with RUN_DOCKER_TESTS=1, such a skip is reported as a failure.
_INFRASTRUCTURE_SKIP = re.compile(
    r"docker|image|java|jdk|jvm|temurin|daemon|cobc|gnucobol|mvn|maven",
    re.IGNORECASE,
)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if not _DOCKER_LANE:
        return
    report = outcome.get_result()
    if not report.skipped or hasattr(report, "wasxfail"):
        return
    longrepr = report.longrepr
    reason = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    if _INFRASTRUCTURE_SKIP.search(reason or ""):
        report.outcome = "failed"
        report.longrepr = (
            "Docker lane (RUN_DOCKER_TESTS=1) requires this test to run, but it "
            f"skipped for missing infrastructure: {reason}"
        )

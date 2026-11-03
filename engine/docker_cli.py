"""Shared Docker CLI helpers for the execution, oracle, and candidate adapters.

The bodies are the historical inline adapter implementations verbatim --
same commands, timeouts, exception handling, and forensic detail strings --
so delegating to them changes no observable behavior.  ``check_docker_available``
is parameterized only where the adapters already differed (spring probes
``docker ps`` with a 30s timeout; the others probe ``docker info`` with 10s).
"""

from __future__ import annotations

import os
import subprocess
import time


#: Exit statuses the docker CLI itself uses: 125 the daemon refused the run,
#: 126 the container command cannot be invoked, 127 it was not found.
DOCKER_CLI_EXIT_CODES = frozenset({125, 126, 127})


def is_docker_infrastructure_exit(
    returncode: int | None, stderr: bytes | str, *, build: bool = False
) -> bool:
    """Whether a ``docker run`` failed in Docker itself, not in the program.

    Audit 2026-11-03 (V4). A build step (javac, Maven) never exits 125-127,
    so for ``build=True`` the code alone decides. A program run may end
    with any status (a COBOL RETURN-CODE of 125 is legitimate), so there
    the docker CLI's own message must be present as well.
    """
    if returncode not in DOCKER_CLI_EXIT_CODES:
        return False
    if build:
        return True
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    return text.lstrip().startswith("docker:") or "Error response from daemon" in text


def check_docker_available(subcommand: str = "info", timeout: int = 10) -> bool:
    """Probe the Docker daemon with ``docker <subcommand>``; False when unavailable."""
    try:
        result = subprocess.run(
            ["docker", subcommand],
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except OSError:
        # A broken/unreachable daemon socket raises OSError, not
        # FileNotFoundError.  A probe that errors must fail closed (absent),
        # never propagate — otherwise a half-dead daemon reads as present.
        return False


def docker_available_with_retry(attempts: int = 3, delay_seconds: float = 1.0) -> bool:
    """``check_docker_available`` with retries, for decisions a run depends on.

    A single slow ``docker info`` (a busy daemon right after image builds)
    made one CI certification run classify the Docker infrastructure
    UNAVAILABLE and refuse an application it certifies everywhere else
    (2026-11-03). A daemon that is really down still answers False after
    the last attempt - fail closed, only less sensitive to timing.
    """
    for attempt in range(attempts):
        if check_docker_available():
            return True
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return False


def cleanup_container(container_name: str) -> tuple[bool, str]:
    """Stop and force-remove a container, then verify removal.

    Returns (removed, detail) where removed indicates success and
    detail provides forensic information about what happened.
    """
    _flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    # Step 1: Stop the container (SIGTERM, then SIGKILL after grace)
    try:
        stop_result = subprocess.run(
            ["docker", "stop", "--time", "5", container_name],
            capture_output=True,
            timeout=15,
            creationflags=_flags,
        )
        stop_ok = stop_result.returncode == 0
    except Exception:
        stop_ok = False

    # Step 2: Remove the container (force remove)
    try:
        rm_result = subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=10,
            creationflags=_flags,
        )
        rm_ok = rm_result.returncode == 0
    except Exception:
        rm_ok = False

    # Step 3: Verify removal
    try:
        inspect_result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            timeout=10,
            creationflags=_flags,
        )
        exists = inspect_result.returncode == 0
    except Exception:
        exists = True  # Assume it exists if we can't check

    removed = rm_ok and not exists
    detail = f"stop={stop_ok}, rm={rm_ok}, exists_after={exists}"
    return removed, detail

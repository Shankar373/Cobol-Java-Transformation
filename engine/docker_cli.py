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

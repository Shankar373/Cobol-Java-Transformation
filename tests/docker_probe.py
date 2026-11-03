"""One Docker-daemon probe for the test suite (audit D3 / CI-F8).

Sixteen test modules carried their own copy of this check, with different
commands, timeouts and caught exceptions. The answer cannot change during a
run, so it is computed once.
"""

from __future__ import annotations

import functools
import os
import subprocess


@functools.lru_cache(maxsize=1)
def docker_daemon_available() -> bool:
    """True when ``docker info`` reaches a running daemon."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0

"""A bash that really runs POSIX scripts, for tests that shell out on the host.

On Windows ``bash`` on PATH is often the WSL launcher (``C:\\Windows\\System32\\bash.exe``).  With no distribution
installed it exits non-zero or zero regardless of the script, which makes any test about a script's exit
status meaningless.  A candidate is accepted only if it prints its own ``BASH_VERSION``; otherwise the test is
skipped with a reason, never failed or passed on the stub's answer.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest


def posix_bash() -> str:
    candidates = [shutil.which("bash") or "bash"]
    for root in ("C:/Program Files/Git", "C:/Program Files (x86)/Git"):
        candidates += [f"{root}/bin/bash.exe", f"{root}/usr/bin/bash.exe"]
    for candidate in candidates:
        try:
            probe = subprocess.run([candidate, "-c", "echo $BASH_VERSION"], capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0 and probe.stdout.strip():
            return candidate
    pytest.skip("no POSIX bash on this host (the 'bash' found is not a working bash)")

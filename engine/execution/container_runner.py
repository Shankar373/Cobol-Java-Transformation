"""One container-run lifecycle for the candidate adapters (audit V15 / C2).

Runs a prepared ``docker run`` command with controlled stdin under a host
timeout. A run that outlives its budget has its client killed and its
container explicitly stopped and removed (killing the client alone leaves
the container running on the daemon). A ``docker`` refusal (daemon error,
missing image) is an ``error``, never a program result to compare (audit V4).

The caller builds the command (mounts, hardening flags, limits); this
module owns only the lifecycle.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable

from engine.docker_cli import is_docker_infrastructure_exit

#: Seconds added to the program's budget for container start-up and teardown.
START_UP_SLACK_SECONDS = 5


@dataclass(frozen=True)
class ContainerRun:
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    #: ``normal`` | ``nonzero_exit`` | ``timeout`` | ``error``
    termination: str


def run_container(
    docker_cmd: list[str],
    *,
    input_data: bytes | None,
    timeout_seconds: int,
    container_name: str,
    label: str,
    cleanup: Callable[[str], tuple[bool, str]],
) -> ContainerRun:
    """Run ``docker_cmd`` and classify how it ended.

    ``label`` names the stage in the timeout message (``"Java"``);
    ``cleanup`` stops and removes the named container.
    """
    proc = None
    try:
        proc = subprocess.run(
            docker_cmd,
            input=input_data or b"",
            capture_output=True,
            timeout=timeout_seconds + START_UP_SLACK_SECONDS,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if getattr(exc, "stdout", None) is not None else b""
        _removed, detail = cleanup(container_name)
        return ContainerRun(
            stdout,
            f"{label} execution timeout; cleanup={detail}".encode(),
            None,
            "timeout",
        )
    except Exception as exc:  # noqa: BLE001 - any launch failure is an error
        return ContainerRun(b"", str(exc).encode(), None, "error")

    exit_code = proc.returncode
    if is_docker_infrastructure_exit(exit_code, proc.stderr):
        # Docker refused the run: no program behaviour to compare.
        return ContainerRun(proc.stdout, proc.stderr, None, "error")
    termination = "normal" if exit_code == 0 else "nonzero_exit"
    return ContainerRun(proc.stdout, proc.stderr, exit_code, termination)

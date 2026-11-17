"""Bounded execution of a git subprocess.

Every git invocation made by the ingestion code goes through
:func:`run_process`, which enforces three independent bounds:

* a wall-clock **timeout** (the whole process tree is killed, and a tree that
  will not release its pipes is reported as a timeout instead of hanging);
* a cap on **captured output** (stdout and stderr are read by threads and the
  process is killed once either exceeds the cap, so a hostile server cannot
  make us buffer unbounded text);
* an optional **size watchdog** (:class:`SizeWatch`) that kills git when a
  directory grows past a byte or entry bound while the process runs.

No shell is involved and stdin is closed.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .errors import LimitExceededError

__all__ = ["SizeWatch", "kill_tree", "run_process"]

#: Watchdog polling starts fast and backs off, so a short command is watched
#: closely while a long fetch does not re-walk the tree every few milliseconds.
_POLL_START_SECONDS = 0.05
_POLL_MAX_SECONDS = 1.0
_POLL_BACKOFF = 1.5

#: Grace period for a killed process tree to release its pipes.
KILL_DRAIN_SECONDS = 10

_READ_CHUNK = 64 * 1024


@dataclass(frozen=True)
class SizeWatch:
    """Directory bound enforced *while* a git process runs.

    ``skip`` names top-level directories (relative to ``root``) that are not
    counted, e.g. ``(".git",)`` when only the working tree is bounded.
    ``max_entries`` (files plus directories) is unbounded when ``None``.
    """

    root: Path
    max_bytes: int
    skip: tuple[str, ...] = ()
    max_entries: int | None = None


def _exceeded(watch: SizeWatch) -> str:
    """Return a description of the bound *watch* is over, or ``""``."""

    total = 0
    entries = 0
    skip = set(watch.skip)
    for dirpath, dirnames, filenames in os.walk(watch.root):
        if Path(dirpath) == watch.root:
            dirnames[:] = [d for d in dirnames if d not in skip]
        entries += len(dirnames) + len(filenames)
        if watch.max_entries is not None and entries > watch.max_entries:
            return f"more than {watch.max_entries} entries"
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue  # file vanished between listing and stat
            if total > watch.max_bytes:
                return f"more than {watch.max_bytes} bytes"
    return ""


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill *proc* and its children (git spawns helper processes)."""

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                shell=False,
                timeout=30,
            )
        else:  # pragma: no cover - POSIX branch
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


class _Capture(threading.Thread):
    """Reads one pipe into memory, killing the process past ``cap`` bytes."""

    def __init__(self, stream, cap: int, proc: subprocess.Popen) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._cap = cap
        self._proc = proc
        self.chunks: list[bytes] = []
        self.overflow = False

    def run(self) -> None:
        total = 0
        while True:
            chunk = self._stream.read(_READ_CHUNK)
            if not chunk:
                return
            total += len(chunk)
            if total > self._cap:
                self.overflow = True
                kill_tree(self._proc)
                return
            self.chunks.append(chunk)

    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")


def _watchdog(
    proc: subprocess.Popen,
    watch: SizeWatch,
    stop: threading.Event,
    tripped: list[str],
) -> None:
    interval = _POLL_START_SECONDS
    while not stop.wait(interval):
        reason = _exceeded(watch)
        if reason:
            tripped.append(reason)
            kill_tree(proc)
            return
        interval = min(interval * _POLL_BACKOFF, _POLL_MAX_SECONDS)


def _wait(proc: subprocess.Popen, timeout: float) -> bool:
    """Wait for *proc*; kill its tree on timeout.  True when it timed out."""

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        return True
    return False


def run_process(
    cmd: list[str],
    cwd: Path | None,
    env: dict[str, str],
    *,
    timeout: float,
    output_cap: int,
    watch: SizeWatch | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd* under the timeout, output cap and optional size watchdog.

    Raises ``subprocess.TimeoutExpired`` on timeout, :class:`LimitExceededError`
    (``LIMIT_EXCEEDED``) on output or size overflow, ``FileNotFoundError`` when
    the program is missing.
    """

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=(sys.platform != "win32"),
    )
    readers = [_Capture(proc.stdout, output_cap, proc),
               _Capture(proc.stderr, output_cap, proc)]
    stop = threading.Event()
    tripped: list[str] = []
    for reader in readers:
        reader.start()
    watchdog = None
    if watch is not None:
        watchdog = threading.Thread(
            target=_watchdog, args=(proc, watch, stop, tripped), daemon=True
        )
        watchdog.start()
    timed_out = _wait(proc, timeout)
    for reader in readers:
        reader.join(KILL_DRAIN_SECONDS)
    stop.set()
    if watchdog is not None:
        watchdog.join()
    if any(reader.is_alive() for reader in readers):
        kill_tree(proc)
        raise subprocess.TimeoutExpired(cmd, timeout)
    if tripped:
        raise LimitExceededError(
            f"git output exceeded the staging bound ({tripped[0]}); "
            "process killed",
            code="LIMIT_EXCEEDED",
        )
    if any(reader.overflow for reader in readers):
        raise LimitExceededError(
            f"git output exceeded {output_cap} bytes; process killed",
            code="LIMIT_EXCEEDED",
        )
    if timed_out:
        raise subprocess.TimeoutExpired(cmd, timeout)
    return subprocess.CompletedProcess(
        cmd, proc.returncode, readers[0].text(), readers[1].text()
    )

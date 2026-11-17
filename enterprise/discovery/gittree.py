"""Bounded pre-checkout inspection of a commit's tree.

``git ls-tree -r -z --long`` lists every blob of a commit *without*
materialising anything.  The listing is streamed record by record into a
:class:`~enterprise.discovery.treelimits.TreeBudget`; the moment a limit (entry count, depth,
name/path length, blob size, declared total) or a case/Unicode path collision
is found, the git process is killed and the error raised.  Memory use is
bounded by one record, never by the size of the tree, so a "tree bomb" (a few
tree objects that fan out into millions of paths) is refused in a fraction of
a second, before a single file is written.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterator

from .errors import IngestionError, UnsafePathError
from .gitproc import KILL_DRAIN_SECONDS, kill_tree
from .limits import Limits
from .treelimits import TreeBudget

__all__ = ["check_tree_listing"]

_READ_CHUNK = 64 * 1024
#: Slack added to the longest legal path when bounding one record.
_RECORD_SLACK = 256


def _records(stream, max_record: int) -> Iterator[bytes]:
    """Yield NUL-terminated records, never buffering more than *max_record*."""

    buffer = b""
    while True:
        chunk = stream.read(_READ_CHUNK)
        if not chunk:
            break
        buffer += chunk
        *complete, buffer = buffer.split(b"\0")
        yield from complete
        if len(buffer) > max_record:
            raise UnsafePathError(
                "tree entry longer than any permitted path",
                code="UNSAFE_PATH",
            )
    if buffer:
        yield buffer


def _parse(record: bytes) -> tuple[str, int]:
    """Split one ``--long`` record into ``(path, size)``."""

    meta, _, raw_path = record.partition(b"\t")
    fields = meta.split()
    if len(fields) != 4 or not raw_path:
        raise IngestionError(
            "unparseable git ls-tree record", code="GIT_FAILED"
        )
    size = int(fields[3]) if fields[3].isdigit() else 0  # "-" for gitlinks
    return raw_path.decode("utf-8", errors="surrogateescape"), size


def check_tree_listing(
    git_command: tuple[str, ...],
    dest: Path,
    pinned: str,
    env: dict[str, str],
    limits: Limits,
    *,
    timeout: float,
) -> None:
    """Stream the tree of *pinned* in *dest* through the limit accountant."""

    cmd = [*git_command, "ls-tree", "-r", "-z", "--long", "--full-tree", pinned]
    proc = subprocess.Popen(
        cmd,
        cwd=str(dest),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        start_new_session=(sys.platform != "win32"),
    )
    timed_out = threading.Event()

    def _expire() -> None:
        timed_out.set()
        kill_tree(proc)

    timer = threading.Timer(timeout, _expire)
    timer.start()
    budget = TreeBudget(limits, check_collisions=True)
    max_record = 4 * limits.max_path_length + _RECORD_SLACK
    try:
        for record in _records(proc.stdout, max_record):
            budget.add_file(*_parse(record))
    except IngestionError:
        kill_tree(proc)
        raise
    finally:
        timer.cancel()
        try:
            proc.wait(timeout=KILL_DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
        proc.stdout.close()
    if timed_out.is_set():
        raise IngestionError("git ls-tree timed out", code="GIT_TIMEOUT")
    if proc.returncode != 0:
        raise IngestionError("git ls-tree failed", code="GIT_FAILED")

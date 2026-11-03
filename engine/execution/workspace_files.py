"""Files an execution left behind, shared by the oracle and candidate lanes.

Programs run with ``/workspace`` as their working directory.  A file named
with an absolute ``/workspace/output/...`` path lands in the output mount;
a relative name (``ASSIGN TO "IDX.DAT"``) lands in the working directory
itself.  Both are observable effects, so both are collected: output files
keep their bare name (the historical key), working-directory files are
keyed ``workspace/<relative path>`` so the two places can never collide.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

#: Key prefix for files written relative to the working directory.
WORKSPACE_PREFIX = "workspace/"


#: Bounds on what the host reads back from a sandbox: the program that wrote
#: these files is untrusted, so neither a huge file nor many of them may
#: exhaust the API process.
MAX_SANDBOX_FILE_BYTES = 64 * 1024 * 1024
MAX_SANDBOX_TOTAL_BYTES = 256 * 1024 * 1024


class UnsafeSandboxOutput(RuntimeError):
    """A sandbox left something the host must not read as program output.

    Raised (never skipped) so the run fails closed: an effect that cannot
    be read safely cannot be compared either.
    """


def read_sandbox_file(path: Path, limit: int = MAX_SANDBOX_FILE_BYTES) -> bytes:
    """Read one regular file written by a sandbox, never following a link.

    The container can replace any name in a writable mount with a symbolic
    link (to the API's own ``/proc/self/environ`` or database, say); the host
    would follow it with its own privileges.  ``lstat`` refuses links and
    special files, ``O_NOFOLLOW`` closes the race where the name is swapped
    after the check, and ``fstat`` re-checks what was actually opened.
    """
    try:
        info = os.lstat(path)
    except OSError as exc:
        # e.g. a Linux symlink seen through a Windows bind mount (a reparse
        # point the host cannot stat): not a readable regular file.
        raise UnsafeSandboxOutput(
            f"sandbox output {path.name!r} cannot be inspected safely "
            f"({type(exc).__name__}; possibly a symbolic link)"
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        kind = "symbolic link" if stat.S_ISLNK(info.st_mode) else "special file"
        raise UnsafeSandboxOutput(f"sandbox output {path.name!r} is a {kind}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:  # ELOOP: swapped for a link after the check
        raise UnsafeSandboxOutput(
            f"sandbox output {path.name!r} could not be opened without "
            f"following links ({type(exc).__name__})"
        ) from exc
    with os.fdopen(fd, "rb") as fh:
        opened = os.fstat(fh.fileno())
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev):
            raise UnsafeSandboxOutput(f"sandbox output {path.name!r} changed while read")
        if opened.st_size > limit:
            raise UnsafeSandboxOutput(
                f"sandbox output {path.name!r} is {opened.st_size} bytes "
                f"(limit {limit})"
            )
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise UnsafeSandboxOutput(f"sandbox output {path.name!r} exceeds {limit} bytes")
    return data


def _walk_regular_files(root: Path) -> list[Path]:
    """Files under ``root`` in sorted order, refusing any linked directory."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for name in dirnames:
            if os.path.islink(here / name):
                raise UnsafeSandboxOutput(
                    f"sandbox output directory {name!r} is a symbolic link"
                )
        found.extend(here / name for name in filenames)
    return sorted(found)


def collect_generated_files(
    output_dir: Path,
    workspace_dir: Path | None,
    mount_points: tuple[str, ...] = (),
) -> dict[str, bytes]:
    """Every file in ``output_dir`` plus every file in ``workspace_dir``.

    ``mount_points`` are top-level names inside the working directory that
    other mounts occupy (source, jars, input, output ...); they are skipped
    so no staged input or build artifact is mistaken for program output.
    Every file is read with :func:`read_sandbox_file`; links, special files
    and oversized output raise :class:`UnsafeSandboxOutput`.
    """
    files: dict[str, bytes] = {}
    total = 0

    def _take(key: str, path: Path) -> None:
        nonlocal total
        data = read_sandbox_file(path)
        total += len(data)
        if total > MAX_SANDBOX_TOTAL_BYTES:
            raise UnsafeSandboxOutput(
                f"sandbox output exceeds {MAX_SANDBOX_TOTAL_BYTES} bytes in total"
            )
        files[key] = data

    if output_dir.is_dir() and not output_dir.is_symlink():
        for f in _walk_regular_files(output_dir):
            # Keyed by relative path (audit V8): keyed by base name,
            # ``a/x.txt`` and ``b/x.txt`` collided and one was never
            # compared.  A top-level file keeps its bare name.
            _take(f.relative_to(output_dir).as_posix(), f)
    if workspace_dir is not None and workspace_dir.is_dir():
        for f in _walk_regular_files(workspace_dir):
            rel = f.relative_to(workspace_dir)
            if rel.parts[0] not in mount_points:
                _take(WORKSPACE_PREFIX + rel.as_posix(), f)
    return files

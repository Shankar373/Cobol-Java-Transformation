"""Files an execution left behind, shared by the oracle and candidate lanes.

Programs run with ``/workspace`` as their working directory.  A file named
with an absolute ``/workspace/output/...`` path lands in the output mount;
a relative name (``ASSIGN TO "IDX.DAT"``) lands in the working directory
itself.  Both are observable effects, so both are collected: output files
keep their bare name (the historical key), working-directory files are
keyed ``workspace/<relative path>`` so the two places can never collide.
"""

from __future__ import annotations

from pathlib import Path

#: Key prefix for files written relative to the working directory.
WORKSPACE_PREFIX = "workspace/"


def collect_generated_files(
    output_dir: Path,
    workspace_dir: Path | None,
    mount_points: tuple[str, ...] = (),
) -> dict[str, bytes]:
    """Every file in ``output_dir`` plus every file in ``workspace_dir``.

    ``mount_points`` are top-level names inside the working directory that
    other mounts occupy (source, jars, input, output ...); they are skipped
    so no staged input or build artifact is mistaken for program output.
    """
    files: dict[str, bytes] = {}
    if output_dir.is_dir():
        for f in sorted(output_dir.rglob("*")):
            if f.is_file():
                files[f.name] = f.read_bytes()
    if workspace_dir is not None and workspace_dir.is_dir():
        for f in sorted(workspace_dir.rglob("*")):
            rel = f.relative_to(workspace_dir)
            if f.is_file() and rel.parts[0] not in mount_points:
                files[WORKSPACE_PREFIX + rel.as_posix()] = f.read_bytes()
    return files

"""Container execution hardening shared by every ``docker run`` site.

Two concerns live here, both P0 production-hardening requirements:

1. **Hardening flags.** Every workload container the product starts must run
   with ``--security-opt no-new-privileges=true`` (no privilege escalation
   via setuid/file capabilities), ``--cap-drop ALL`` (empty capability set),
   and an explicit non-root ``--user``.  The flags are produced by a single
   function so no run site can silently drift from the others — the P0 audit
   found 9 of 10 run sites missing ``no-new-privileges`` entirely.

2. **Host mount preparation.** Bind mounts are resolved on the *host*
   filesystem (see :mod:`engine.execution.sandbox_paths`).  A non-root
   container user must be able to read (and, for writable mounts, write)
   those host trees regardless of the creating process's umask.  On Linux
   the staging temp dirs are created mode ``0700``; without preparation the
   container user could not read them at all.  On Windows the chmod bits
   are advisory at best (Docker Desktop maps identities), so preparation is
   deliberately best-effort there.

No silent root fallback: callers must pass the flags from
:func:`container_run_hardening_flags` verbatim.  A lane that genuinely
cannot run non-root has to record that limitation explicitly in
``docs/verification/RUNTIME_PROOF_MATRIX.md`` and in this module's
``NON_ROOT_EXEMPT_LANES`` — it must never drop ``--user`` at runtime.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Final

#: Dedicated non-root identity for every workload container.  Matches the
#: ``systemaops`` user in ``Dockerfile.production`` (uid/gid 10001) so
#: production staging directories created by the API container are owned by
#: the same numeric identity the workload containers run as.
CONTAINER_UID: Final[int] = 10001
CONTAINER_GID: Final[int] = 10001
CONTAINER_USER: Final[str] = f"{CONTAINER_UID}:{CONTAINER_GID}"

#: Lanes exempt from non-root execution.  Empty by default: every current
#: lane (oracle, javac, java exec, maven build, spring-boot exec, producer)
#: is verified to run as ``CONTAINER_USER`` — see the P0 hardening evidence
#: in ``docs/verification/RUNTIME_PROOF_MATRIX.md``.  Adding an entry here
#: requires a documented, tested reason; silently omitting ``--user`` from a
#: run command is a defect.
NON_ROOT_EXEMPT_LANES: Final[frozenset[str]] = frozenset()


def container_run_hardening_flags(lane: str) -> list[str]:
    """Return the hardening flags every ``docker run`` must carry.

    Returns ``--security-opt no-new-privileges=true``, ``--cap-drop ALL``
    and ``--user <uid:gid>`` (unless ``lane`` is listed in
    :data:`NON_ROOT_EXEMPT_LANES`, which is currently empty and requires a
    documented justification to extend).

    The returned list is a fresh list; callers may extend it freely.
    """
    if lane in NON_ROOT_EXEMPT_LANES:  # pragma: no cover - no exempt lanes
        return ["--security-opt", "no-new-privileges=true", "--cap-drop", "ALL"]
    return [
        "--security-opt", "no-new-privileges=true",
        "--cap-drop", "ALL",
        "--user", CONTAINER_USER,
    ]


def prepare_host_tree(path: str | Path, *, writable: bool) -> None:
    """Make a host staging tree readable (and writable) by the container user.

    Directories gain ``o+rx`` — plus ``o+w`` when ``writable`` — and files
    gain ``o+r``.  Only permission bits are touched; content is never
    modified.  Errors are ignored deliberately: on hosts where the chmod
    cannot apply (Windows ACL semantics, read-only volumes) the container
    run itself is the authority — a permission failure there surfaces as a
    failed execution with its real stderr, never as a silent success.

    This must be called for **every** host path that is bind-mounted into a
    hardened container before the ``docker run`` is issued.
    """
    root = Path(path)
    if not root.exists():
        return
    dir_bits = 0o005 | (0o002 if writable else 0o000)
    file_bits = 0o004
    try:
        for entry in (root, *root.rglob("*")):
            try:
                mode = stat.S_IMODE(entry.stat().st_mode)
                if entry.is_dir():
                    os.chmod(entry, mode | dir_bits)
                elif entry.is_file():
                    os.chmod(entry, mode | file_bits)
            except OSError:
                continue
    except OSError:
        return

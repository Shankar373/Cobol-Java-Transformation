"""Host-visible sandbox staging for Docker bind mounts.

Production topology problem this solves
----------------------------------------
The API container reaches the Docker daemon through the mounted daemon
socket, so ``docker run -v <path>:...`` bind sources are resolved by the
**host** daemon on the **host** filesystem — not inside the API container.

Staging sandbox inputs under the container-private ``$TMPDIR`` (``/app/tmp``,
a container-local tmpfs) or under a named volume therefore fails closed on
the host daemon: the source path does not exist there and the oracle /
candidate lanes can never execute in production, even though the identical
chain works when the engine runs directly on the host.

Contract
--------
* ``SANDBOX_STAGING_DIR`` — container-visible directory under which every
  Docker adapter stages bind-mounted inputs/outputs.  Unset (dev/host runs)
  preserves the historical behaviour: staging under the platform temp dir,
  where container path == host path.
* ``SANDBOX_HOST_STAGING_DIR`` — host-visible directory bound to
  ``SANDBOX_STAGING_DIR`` in production
  (``${HOST_DIR}:/app/sandbox-staging``).  Every ``-v`` argument is
  translated through :func:`to_host_path` before the ``docker run``
  command is built, so the daemon sees a path that exists on the host.
  Unset means identity mapping (same-path bind or engine on the host).

The translation only rewrites paths located under the configured staging
root; every other path (system temp on dev hosts, image-internal container
destinations) passes through byte-identical, so behaviour without the
production bind mount is unchanged.

Security / determinism notes
----------------------------
* This module only computes paths.  It does not relax any sandbox control:
  ``--network none``, memory/CPU/PID caps, read-only mounts, image pins and
  ``no-new-privileges`` remain the caller's responsibility.
* A configured staging root that does not exist is created; a root that
  exists but is not writable fails closed (``RuntimeError``) instead of
  silently falling back to the container-private tmpfs, which would
  reintroduce the invisible-workspace failure as a silent no-op.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: Container-visible staging root (production: a host-bound directory).
STAGING_DIR_ENV = "SANDBOX_STAGING_DIR"

#: Host-visible counterpart of the staging root (production bind source).
HOST_STAGING_DIR_ENV = "SANDBOX_HOST_STAGING_DIR"


def get_staging_root() -> Path | None:
    """Return the configured container-visible staging root, if any."""
    raw = os.environ.get(STAGING_DIR_ENV, "").strip()
    if not raw:
        return None
    return Path(raw)


def get_host_staging_root() -> Path | None:
    """Return the configured host-visible staging root, if any."""
    raw = os.environ.get(HOST_STAGING_DIR_ENV, "").strip()
    if not raw:
        return None
    return Path(raw)


def ensure_staging_root() -> Path:
    """Create (if needed) and validate the configured staging root.

    Returns the root.  Raises ``RuntimeError`` when the root cannot be
    used for host-visible staging, so production misconfiguration fails
    loudly instead of silently staging into an invisible tmpfs.
    """
    root = get_staging_root()
    if root is None:  # pragma: no cover - no configured root
        raise RuntimeError(
            f"{STAGING_DIR_ENV} is not configured: no host-visible "
            "staging root to ensure"
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"sandbox staging root {root} cannot be created: {exc}"
        ) from exc
    if not os.access(root, os.W_OK | os.X_OK):
        raise RuntimeError(
            f"sandbox staging root {root} is not writable (uid/gid "
            "ownership mismatch — see docs/deployment/PRODUCTION.md)"
        )
    return root


def sandbox_staging_dir(prefix: str = "sandbox-") -> tempfile.TemporaryDirectory[str]:
    """Create a per-execution staging directory for Docker bind mounts.

    When ``SANDBOX_STAGING_DIR`` is configured the directory is created
    inside that host-visible root (after :func:`ensure_staging_root`
    validation); otherwise it falls back to the platform temp dir,
    preserving dev/host behaviour where container path == host path.
    """
    root = get_staging_root()
    if root is None:
        return tempfile.TemporaryDirectory(prefix=prefix)
    ensure_staging_root()
    return tempfile.TemporaryDirectory(prefix=prefix, dir=str(root))


def _is_within(path: str, root: str) -> bool:
    """True when absolute ``path`` equals ``root`` or lies beneath it."""
    if path == root:
        return True
    return path.startswith(root + os.sep)


def to_host_path(container_path: str | Path) -> str:
    """Map a container-visible staging path to the host-visible bind source.

    Identity mapping unless **both** ``SANDBOX_STAGING_DIR`` and
    ``SANDBOX_HOST_STAGING_DIR`` are configured and the (absolute,
    normalised) path lies under the staging root.  Paths outside the
    staging root are returned absolute and unchanged.
    """
    absolute = os.path.abspath(os.fspath(container_path))
    staging = get_staging_root()
    host_root = get_host_staging_root()
    if staging is None or host_root is None:
        return absolute
    staging_abs = os.path.abspath(str(staging))
    host_abs = os.path.abspath(str(host_root))
    if not _is_within(absolute, staging_abs):
        return absolute
    relative = os.path.relpath(absolute, staging_abs)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return absolute  # pragma: no cover - defensive; _is_within excluded this
    if relative == ".":
        return host_abs
    return os.path.join(host_abs, relative)


def docker_volume_arg(
    container_visible_path: str | Path,
    container_dest: str,
    readonly: bool = True,
) -> list[str]:
    """Build a ``-v host:dest[:ro]`` pair with host-path translation applied."""
    host_path = to_host_path(container_visible_path)
    spec = f"{host_path}:{container_dest}"
    if readonly:
        spec += ":ro"
    return ["-v", spec]

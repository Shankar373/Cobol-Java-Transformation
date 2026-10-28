"""Durable placement for uploaded sources and generated applications.

Two kinds of directory are created at runtime:

* **scratch** (zip unpacking, probe temp files) — belongs in ``$TMPDIR``,
  which production mounts as the ``/app/tmp`` tmpfs (``noexec,nosuid``).
* **durable artifacts** — the ingest workspace holding uploaded COBOL, the
  upload workspace, and the pipeline output bundle holding the generated
  Java project. These are referenced by absolute path in the database
  (``cobol_source_path``, ``generated_app_path``) and are hashed by the
  evidence seal, so they must survive a container restart and be captured
  by ``scripts/backup/backup.sh``.

Historically all three durable sites called ``tempfile.mkdtemp()`` with no
``dir``, so in production they landed in ``$TMPDIR`` — the tmpfs. The named
``control-plane-work`` volume (``/app/workspaces``) therefore received no
writes: backups captured an empty volume and every restart silently deleted
the bytes the seal referred to (download 404, revalidation failure).

``CONTROL_PLANE_WORKSPACE_DIR`` selects the durable root. When it is unset —
the default for development and the whole test suite — behaviour is
byte-identical to the historical code: ``tempfile.mkdtemp`` with no ``dir``
argument, i.e. the platform temp directory.

Docker bind mounts are unaffected: the engine only mounts paths under
``SANDBOX_STAGING_DIR`` (see ``engine/execution/sandbox_paths.py``) and the
adapters *copy* the bundle into staging, so a workspace on a named volume is
never passed to ``docker run -v`` directly.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: Environment variable selecting the durable workspace root.
WORKSPACE_DIR_ENV = "CONTROL_PLANE_WORKSPACE_DIR"


def workspace_root() -> Path | None:
    """Return the configured durable root, or ``None`` for temp-dir default."""
    raw = os.environ.get(WORKSPACE_DIR_ENV, "").strip()
    if not raw:
        return None
    return Path(raw)


def new_workspace(prefix: str) -> Path:
    """Create a fresh workspace directory for a durable artifact.

    Falls back to the platform temp directory when the root is not
    configured. A configured-but-unusable root fails loudly (naming the
    variable) instead of silently degrading to a tmpfs that restarts erase.
    """
    root = workspace_root()
    if root is None:
        return Path(tempfile.mkdtemp(prefix=prefix))
    try:
        root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    except OSError as exc:
        raise OSError(
            f"cannot create workspace under {WORKSPACE_DIR_ENV}="
            f"{root}: {exc}"
        ) from exc


def workspace_root_problems() -> list[str]:
    """Readiness probe for the durable root (empty list == healthy).

    An unset root is not a problem: it is the supported development
    configuration. A configured root must exist and be writable, otherwise
    uploads, generation and backup are all broken.
    """
    root = workspace_root()
    if root is None:
        return []
    problems: list[str] = []
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [f"{WORKSPACE_DIR_ENV}={root} is not creatable: {exc}"]
    probe = root / ".readiness-probe"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        problems.append(f"{WORKSPACE_DIR_ENV}={root} is not writable: {exc}")
    return problems

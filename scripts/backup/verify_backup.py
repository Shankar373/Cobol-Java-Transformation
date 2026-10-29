#!/usr/bin/env python3
"""Verify that a backup directory produced by ``backup.sh`` is restorable.

``backup.sh`` writes three things a restore depends on: ``control-plane.db``
(SQLite online backup), ``workspaces.tar.gz`` (uploads, generated apps),
and release identity files. A backup that *exists* is not a backup that
*works* — the R10-era failure mode was a tar of an empty volume, which
looked healthy (file present, gzip valid) until restore time.

Checks performed (each returns a ``FAIL:`` line; any FAIL exits non-zero):

* ``control-plane.db`` exists, opens read-only, passes
  ``PRAGMA integrity_check``, carries the ``applications``/``runs``
  tables, and its ``PRAGMA user_version`` is not *newer* than this code's
  schema (a newer schema means a restore would hand the running API a
  database it cannot read — ``Store`` fails closed on exactly that);
* ``workspaces.tar.gz`` exists and is a readable gzip tar containing at
  least one member (the empty-archive case that started this script);
* warnings (printed, never fatal): missing release-identity files, which
  cost you provenance but not the restore itself.

No third-party dependency, no Docker: stdlib only, so it can run on the
host *and* inside the pinned ``python:3.11-slim`` container that
``backup.sh`` uses for the SQLite copy.

Usage::

    python3 scripts/backup/verify_backup.py <BACKUP_DIR>

Exit codes: 0 verified, 1 verification failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tarfile
from pathlib import Path

#: Must track ``api.store.DB_SCHEMA_VERSION`` (asserted by the unit test,
#: which imports ``api.store`` rather than copying the number).
SCHEMA_VERSION_CEILING = 8

DB_NAME = "control-plane.db"
TARBALL_NAME = "workspaces.tar.gz"
RELEASE_IDENTITY_FILES = ("STAMP.txt", "api-image.json")


def verify_sqlite(path: Path, failures: list[str]) -> None:
    """Open the backup DB read-only and check it is restorable."""
    if not path.is_file():
        failures.append(f"{DB_NAME} is missing (nothing to restore)")
        return
    if path.stat().st_size == 0:
        failures.append(f"{DB_NAME} is empty (0 bytes)")
        return
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        failures.append(f"{DB_NAME} does not open as SQLite: {exc}")
        return
    try:
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            failures.append(f"{DB_NAME} fails integrity_check: {exc}")
            return
        if result is None or result[0] != "ok":
            detail = result[0] if result else "no result"
            failures.append(f"{DB_NAME} fails integrity_check: {detail}")
            return

        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        except sqlite3.DatabaseError as exc:
            failures.append(f"{DB_NAME} schema unreadable: {exc}")
            return
        missing = sorted({"applications", "runs"} - tables)
        if missing:
            failures.append(
                f"{DB_NAME} is not a control-plane database "
                f"(missing tables: {', '.join(missing)})"
            )

        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        except (sqlite3.Error, TypeError, IndexError):
            failures.append(f"{DB_NAME} has no readable user_version")
            return
        if version > SCHEMA_VERSION_CEILING:
            failures.append(
                f"{DB_NAME} schema is version {version} but this build only "
                f"understands up to {SCHEMA_VERSION_CEILING} — restoring it "
                "would hand the API a database it fails closed on"
            )
    finally:
        conn.close()


def verify_workspaces(path: Path, failures: list[str]) -> None:
    """Check the workspace archive is readable and non-empty."""
    if not path.is_file():
        failures.append(f"{TARBALL_NAME} is missing (nothing to restore)")
        return
    if path.stat().st_size == 0:
        failures.append(f"{TARBALL_NAME} is empty (0 bytes)")
        return
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
    except (tarfile.TarError, OSError, EOFError) as exc:
        failures.append(f"{TARBALL_NAME} is not a readable gzip tar: {exc}")
        return
    if not members:
        failures.append(
            f"{TARBALL_NAME} contains no entries — an empty workspace "
            "volume was archived (the exact R10 failure this check exists "
            "to catch)"
        )


def verify_backup(root: Path) -> tuple[list[str], list[str]]:
    """Return ``(failures, warnings)`` for the backup directory at *root*."""
    failures: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        return [f"{root} is not a directory"], warnings

    verify_sqlite(root / DB_NAME, failures)
    verify_workspaces(root / TARBALL_NAME, failures)

    for name in RELEASE_IDENTITY_FILES:
        if not (root / name).is_file():
            warnings.append(
                f"{name} missing — release identity/provenance lost "
                "(the data itself still restores)"
            )
    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a backup directory produced by backup.sh."
    )
    parser.add_argument("backup_dir", help="backup directory to verify")
    args = parser.parse_args(argv)

    root = Path(args.backup_dir)
    failures, warnings = verify_backup(root)

    for message in warnings:
        print(f"WARN: {message}")
    for message in failures:
        print(f"FAIL: {message}", file=sys.stderr)
    if failures:
        print(f"VERIFY-BACKUP: FAILED ({len(failures)} problem(s))", file=sys.stderr)
        return 1

    db_size = (root / DB_NAME).stat().st_size
    tar_size = (root / TARBALL_NAME).stat().st_size
    print(
        f"VERIFY-BACKUP: OK ({DB_NAME}={db_size} B, "
        f"{TARBALL_NAME}={tar_size} B, schema<=v{SCHEMA_VERSION_CEILING})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

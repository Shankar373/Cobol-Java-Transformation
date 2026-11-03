"""Backup integrity verification (P2: ``backup.sh`` output must restore).

``scripts/backup/backup.sh`` now chains ``scripts/backup/verify_backup.py``
inside the pinned Python image, so an unverifiable backup fails the backup
command instead of surfacing at restore time. The historic failure mode was
exactly this: a *present* artifact that is not *restorable* — the R10-era
tar of an empty volume, a truncated SQLite copy, or a database written by a
newer schema the running API fails closed on.

What is pinned:

* a well-formed backup verifies clean (exit 0, ``VERIFY-BACKUP: OK``);
* missing / empty / corrupt ``control-plane.db`` and ``workspaces.tar.gz``
  each fail with a specific reason (exit 1);
* an empty-but-valid gzip tar fails (the R10 case);
* a database missing the ``applications``/``runs`` tables fails (it is not
  a control-plane database);
* a ``user_version`` newer than this build's schema fails (restore would
  hand the API a database it cannot read);
* ``SCHEMA_VERSION_CEILING`` tracks ``api.store.DB_SCHEMA_VERSION`` — the
  ceiling must move with the schema or the check silently lies;
* missing release-identity files warn but never fail (provenance loss is
  not data loss).

The module is loaded from ``scripts/backup/`` by path: it is a standalone
stdlib-only script meant to run both on the host and inside the container,
so it is not part of the ``api`` package.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import shutil
import tarfile
from pathlib import Path

import pytest

from api.store import DB_SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "systemaops_verify_backup",
    REPO_ROOT / "scripts" / "backup" / "verify_backup.py",
)
assert _SPEC is not None and _SPEC.loader is not None
verify_backup_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify_backup_module)

verify_backup = verify_backup_module.verify_backup
main = verify_backup_module.main


def _make_valid_backup(root: Path) -> None:
    """Create a backup directory shaped exactly like backup.sh's output."""
    db = root / "control-plane.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE applications (id TEXT PRIMARY KEY);"
        "CREATE TABLE runs (id TEXT PRIMARY KEY);"
    )
    conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
    conn.commit()
    conn.close()

    payload = root / "_workspace_payload"
    payload.mkdir()
    (payload / "program.cob").write_text("IDENTIFICATION DIVISION.\n")
    with tarfile.open(root / "workspaces.tar.gz", "w:gz") as archive:
        archive.add(payload / "program.cob", arcname="program.cob")
    shutil.rmtree(payload)

    (root / "STAMP.txt").write_text("20260101T000000Z\n", encoding="utf-8")
    (root / "api-image.json").write_text('{"Id": "sha256:deadbeef"}\n', encoding="utf-8")


@pytest.fixture()
def backup_dir(tmp_path: Path) -> Path:
    _make_valid_backup(tmp_path)
    return tmp_path


class TestValidBackup:
    def test_verifies_clean(self, backup_dir: Path):
        failures, warnings = verify_backup(backup_dir)
        assert failures == [], failures
        assert warnings == [], warnings

    def test_main_exits_zero_and_reports_ok(self, backup_dir: Path, capsys):
        assert main([str(backup_dir)]) == 0
        out = capsys.readouterr().out
        assert "VERIFY-BACKUP: OK" in out

    def test_schema_ceiling_tracks_the_store(
        self, backup_dir: Path
    ) -> None:
        """The ceiling must equal the live schema version, not a stale copy."""
        assert verify_backup_module.SCHEMA_VERSION_CEILING == DB_SCHEMA_VERSION
        # And a backup written at exactly the current version must pass.
        failures, _ = verify_backup(backup_dir)
        assert failures == []


class TestMissingOrCorrupt:
    def test_missing_database_fails(self, backup_dir: Path):
        (backup_dir / "control-plane.db").unlink()
        failures, _ = verify_backup(backup_dir)
        assert any("control-plane.db is missing" in f for f in failures)

    def test_empty_database_file_fails(self, backup_dir: Path):
        (backup_dir / "control-plane.db").write_bytes(b"")
        failures, _ = verify_backup(backup_dir)
        assert any("empty" in f for f in failures)

    def test_corrupt_database_fails(self, backup_dir: Path):
        (backup_dir / "control-plane.db").write_bytes(b"not a database at all" * 10)
        failures, _ = verify_backup(backup_dir)
        assert failures, "garbage bytes must not pass as a database"
        assert any("control-plane.db" in f for f in failures)

    def test_database_without_control_plane_tables_fails(
        self, backup_dir: Path
    ):
        db = backup_dir / "control-plane.db"
        db.unlink()
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE unrelated (x TEXT)")
        conn.commit()
        conn.close()
        failures, _ = verify_backup(backup_dir)
        assert any("not a control-plane database" in f for f in failures)

    def test_database_from_a_newer_schema_fails(self, backup_dir: Path):
        conn = sqlite3.connect(backup_dir / "control-plane.db")
        conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION + 1}")
        conn.commit()
        conn.close()
        failures, _ = verify_backup(backup_dir)
        assert any("newer" in f or "version" in f for f in failures)

    def test_missing_workspaces_tarball_fails(self, backup_dir: Path):
        (backup_dir / "workspaces.tar.gz").unlink()
        failures, _ = verify_backup(backup_dir)
        assert any("workspaces.tar.gz is missing" in f for f in failures)

    def test_empty_workspace_archive_fails(self, backup_dir: Path):
        """The R10 failure: a valid gzip of an empty workspace volume."""
        with tarfile.open(backup_dir / "workspaces.tar.gz", "w:gz"):
            pass  # archive with zero members
        failures, _ = verify_backup(backup_dir)
        assert any("no entries" in f for f in failures)

    def test_truncated_workspace_archive_fails(self, backup_dir: Path):
        (backup_dir / "workspaces.tar.gz").write_bytes(b"\x1f\x8bnot-really-gzip")
        failures, _ = verify_backup(backup_dir)
        assert any("workspaces.tar.gz" in f for f in failures)

    def test_non_directory_fails(self, tmp_path: Path):
        failures, _ = verify_backup(tmp_path / "does-not-exist")
        assert failures and "not a directory" in failures[0]


class TestReleaseIdentityIsWarningOnly:
    def test_missing_identity_files_warn_but_do_not_fail(
        self, backup_dir: Path, capsys
    ):
        (backup_dir / "STAMP.txt").unlink()
        (backup_dir / "api-image.json").unlink()

        failures, warnings = verify_backup(backup_dir)
        assert failures == [], "provenance loss must not fail a valid backup"
        assert len(warnings) == 2

        assert main([str(backup_dir)]) == 0
        captured = capsys.readouterr()
        assert "WARN:" in captured.out
        assert "VERIFY-BACKUP: OK" in captured.out


class TestCli:
    def test_invalid_backup_exits_one_with_fail_lines(
        self, backup_dir: Path, capsys
    ):
        (backup_dir / "control-plane.db").unlink()
        assert main([str(backup_dir)]) == 1
        captured = capsys.readouterr()
        assert "FAIL: control-plane.db is missing" in captured.err
        assert "VERIFY-BACKUP: FAILED" in captured.err

    def test_multiple_problems_are_all_reported(self, backup_dir: Path, capsys):
        (backup_dir / "control-plane.db").unlink()
        (backup_dir / "workspaces.tar.gz").unlink()
        assert main([str(backup_dir)]) == 1
        captured = capsys.readouterr()
        assert captured.err.count("FAIL:") == 2

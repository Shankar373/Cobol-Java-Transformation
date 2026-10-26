"""P0 upload-safety regression suite (hostile inputs, isolation, cleanup).

Pins the approved hardening plan item 3 for ``api.ingestion`` and the
temp-dir helpers around it:

* Windows/UNC/extended-length ZIP entry names are rejected — drive
  letters (``C:\\evil``, ``C:/evil``, drive-relative ``C:evil``), UNC
  shares (``\\\\server\\share``, ``//server/share``), ``\\\\?\\``
  extended paths, mixed-separator traversal and nested traversal all
  fail closed before a single byte is written outside the workspace;
* symlink entries (``external_attr`` file-type bits) are rejected;
* the configurable limits (entry count, archive bytes, total extracted
  bytes) actually fire via their ``CONTROL_PLANE_MAX_*`` env vars;
* ``application_id`` is validated against a path-safe alphabet BEFORE it
  is used as the ``tempfile.mkdtemp`` prefix — values like ``../evil``
  or ``a/b`` must never be able to aim the workspace outside the temp
  root;
* a rejected archive leaves no workspace directory behind (the previous
  code created the workspace before validation and leaked it);
* concurrent ingestions get isolated, distinct workspaces;
* ``_cleanup_temp_dir`` removes only its own temp-prefixed directories
  and tolerates ``None`` / missing paths.

Every rejection test also asserts the error is ``IngestionError`` — a
hostile archive must produce a controlled refusal, never a 500.
"""

from __future__ import annotations

import io
import shutil
import stat
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from api.ingestion import IngestionError, ingest_zip

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    """Build an in-memory ZIP from (name, content) pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


def _zip_with_symlink(name: str = "link.cob", target: str = "../x") -> bytes:
    """Build a ZIP containing a symlink entry (POSIX file-type bits)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(name)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, target)
    return buf.getvalue()


VALID_ZIP = _zip_bytes([("MAIN.cob", b"       PROGRAM-ID. X.\n")])


# ---------------------------------------------------------------------------
# Hostile entry names — Windows drives, UNC, extended paths, traversal
# ---------------------------------------------------------------------------


class TestHostileZipEntryNames:
    @pytest.mark.parametrize(
        "hostile",
        [
            pytest.param("C:\\evil\\pwn.cbl", id="drive-backslash"),
            pytest.param("C:/evil/pwn.cbl", id="drive-forward-slash"),
            pytest.param("C:pwn.cbl", id="drive-relative"),
            pytest.param("\\\\server\\share\\pwn.cbl", id="unc-backslash"),
            pytest.param("//server/share/pwn.cbl", id="unc-forward-slash"),
            pytest.param("\\\\?\\C:\\pwn.cbl", id="extended-length"),
            pytest.param("dir/../../../../tmp/pwn.cbl", id="nested-traversal"),
            pytest.param("..\\..\\pwn.cbl", id="mixed-separator-traversal"),
            pytest.param("/etc/passwd", id="absolute-unix"),
            pytest.param("src/..\\..\\pwn.cbl", id="separator-mixed-inside-dir"),
        ],
    )
    def test_hostile_entry_is_rejected(self, hostile):
        with pytest.raises(IngestionError) as excinfo:
            ingest_zip(_zip_bytes([(hostile, b"pwn")]), "app-hostile")

        # Controlled refusal — the message names the unsafe entry.
        assert "pwn" in str(excinfo.value) or "Unsafe" in str(excinfo.value)

    def test_hostile_entry_writes_nothing_outside_workspace(self, tmp_path):
        """A traversal entry must be rejected before extraction starts."""
        watch = tmp_path / "watch"
        watch.mkdir()
        with pytest.raises(IngestionError):
            ingest_zip(
                _zip_bytes([("../watch/escaped.cbl", b"pwn")]), "app-escape"
            )
        assert list(watch.iterdir()) == []

    def test_symlink_entry_is_rejected(self):
        with pytest.raises(IngestionError, match="[Ss]ymlink"):
            ingest_zip(_zip_with_symlink(), "app-symlink")

    def test_valid_relative_zip_still_ingests(self):
        """No over-rejection: a well-formed archive extracts."""
        workspace = ingest_zip(VALID_ZIP, "app-valid")
        try:
            assert (workspace / "MAIN.cob").read_bytes() == (
                b"       PROGRAM-ID. X.\n"
            )
            assert workspace.name.startswith("ingest-app-valid-")
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Configurable limits actually fire
# ---------------------------------------------------------------------------


class TestZipLimitsFire:
    def test_entry_count_limit(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_ZIP_ENTRIES", "3")
        entries = [(f"F{i}.cob", b"x") for i in range(4)]

        with pytest.raises(IngestionError, match="entry limit"):
            ingest_zip(_zip_bytes(entries), "app-entries")

    def test_archive_byte_limit(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_ZIP_ARCHIVE_BYTES", "64")
        big = _zip_bytes([("MAIN.cob", b"x" * 4096)])

        with pytest.raises(IngestionError, match="size limit"):
            ingest_zip(big, "app-bytes")

    def test_total_extracted_limit(self, monkeypatch):
        # Stored entries: compression ratio stays 1:1 so the ratio guard
        # cannot mask the total-extracted-size guard.
        monkeypatch.setenv("CONTROL_PLANE_MAX_TOTAL_EXTRACTED_BYTES", "100")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("A.cob", b"x" * 60)
            zf.writestr("B.cob", b"x" * 60)

        with pytest.raises(IngestionError, match="extracted size limit"):
            ingest_zip(buf.getvalue(), "app-extracted")


# ---------------------------------------------------------------------------
# application_id must never aim mkdtemp outside the temp root
# ---------------------------------------------------------------------------


class TestApplicationIdIsPathSafe:
    @pytest.mark.parametrize(
        "unsafe",
        [
            pytest.param("../evil", id="parent-traversal"),
            pytest.param("a/b", id="nested-slash"),
            pytest.param("a\\b", id="nested-backslash"),
            pytest.param("..", id="dotdot"),
            pytest.param(".hidden", id="leading-dot"),
            pytest.param("", id="empty"),
            pytest.param("x" * 200, id="too-long"),
            pytest.param("sp ace", id="space"),
            pytest.param("id\u00e9", id="non-ascii"),
        ],
    )
    def test_unsafe_id_rejected_before_any_workspace_is_created(
        self, monkeypatch, unsafe
    ):
        created: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created.append(Path(path))
            return path

        monkeypatch.setattr(tempfile, "mkdtemp", spy)

        with pytest.raises(IngestionError, match="Unsafe application id"):
            ingest_zip(VALID_ZIP, unsafe)

        assert created == [], (
            "an unsafe application id must be refused before mkdtemp"
        )

    @pytest.mark.parametrize("safe", ["app-x", "app-123", "wl_x.2", "A" * 128])
    def test_safe_ids_accepted(self, safe):
        workspace = ingest_zip(VALID_ZIP, safe)
        try:
            assert workspace.is_dir()
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Rejected archives leave no workspace behind
# ---------------------------------------------------------------------------


class TestRejectedIngestCleansUp:
    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(
                _zip_bytes([("../../escape.cbl", b"x")]),
                id="traversal",
            ),
            pytest.param(b"not a zip at all", id="bad-zip"),
        ],
    )
    def test_rejected_ingest_removes_its_workspace(self, monkeypatch, payload):
        created: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created.append(Path(path))
            return path

        monkeypatch.setattr(tempfile, "mkdtemp", spy)

        with pytest.raises(IngestionError):
            ingest_zip(payload, "app-cleanup")

        assert len(created) == 1, "the workspace should have been created"
        assert not created[0].exists(), (
            "a rejected ingest must not leave its workspace on disk"
        )

    def test_limit_rejection_also_cleans_up(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_ZIP_ENTRIES", "1")
        created: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created.append(Path(path))
            return path

        monkeypatch.setattr(tempfile, "mkdtemp", spy)

        with pytest.raises(IngestionError, match="entry limit"):
            ingest_zip(
                _zip_bytes([("A.cob", b"x"), ("B.cob", b"y")]), "app-limit"
            )

        assert len(created) == 1
        assert not created[0].exists()


# ---------------------------------------------------------------------------
# Concurrent isolation and temp-dir cleanup helpers
# ---------------------------------------------------------------------------


class TestConcurrentWorkspaceIsolation:
    def test_concurrent_ingestions_get_distinct_workspaces(self):
        payload = _zip_bytes([("MAIN.cob", b"       PROGRAM-ID. X.\n")])

        def ingest(index: int) -> Path:
            workspace = ingest_zip(payload, f"app-conc-{index}")
            # Read back inside the worker: a collision would overwrite.
            assert (workspace / "MAIN.cob").read_bytes() == (
                b"       PROGRAM-ID. X.\n"
            )
            return workspace

        with ThreadPoolExecutor(max_workers=4) as pool:
            workspaces = list(pool.map(ingest, range(4)))

        try:
            assert len({w.resolve() for w in workspaces}) == 4, (
                "concurrent ingestions must not share a workspace"
            )
        finally:
            for workspace in workspaces:
                shutil.rmtree(workspace, ignore_errors=True)


class TestCleanupTempDir:
    def test_removes_prefixed_directories(self, tmp_path):
        from api.service import _cleanup_temp_dir

        victim = Path(tempfile.mkdtemp(prefix="ingest-app-x-", dir=tmp_path))
        (victim / "file.cob").write_bytes(b"x")

        _cleanup_temp_dir(victim)

        assert not Path(victim).exists()

    def test_skips_directories_without_a_temp_prefix(self, tmp_path):
        from api.service import _cleanup_temp_dir

        keep = tmp_path / "important"
        keep.mkdir()
        (keep / "file.cob").write_bytes(b"x")

        _cleanup_temp_dir(keep)

        assert keep.is_dir()
        assert (keep / "file.cob").exists()

    def test_none_and_missing_paths_are_tolerated(self, tmp_path):
        from api.service import _cleanup_temp_dir

        _cleanup_temp_dir(None)
        _cleanup_temp_dir(tmp_path / "does-not-exist")

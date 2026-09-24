"""Unit tests for application name derivation from ZIP archives.

Covers:
  - normalize_application_name: slug normalization
  - derive_application_name_from_zip: workspace-based detection
  - derive_application_name_from_zip_bytes: peek-based detection
  - Store.unique_name: duplicate handling
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from api.name_derivation import (
    normalize_application_name,
    derive_application_name_from_zip,
    derive_application_name_from_zip_bytes,
)
from api.store import Store, ApplicationRecord


# ---------------------------------------------------------------------------
# normalize_application_name
# ---------------------------------------------------------------------------

class TestNormalizeApplicationName:
    def test_lowercase(self):
        assert normalize_application_name("MyApp") == "myapp"

    def test_spaces_to_hyphens(self):
        assert normalize_application_name("My Cool App") == "my-cool-app"

    def test_underscores_to_hyphens(self):
        assert normalize_application_name("my_cool_app") == "my-cool-app"

    def test_strips_special_chars(self):
        assert normalize_application_name("app@v2.1!") == "appv21"

    def test_collapses_multiple_hyphens(self):
        assert normalize_application_name("my---app") == "my-app"

    def test_strips_leading_trailing_hyphens(self):
        assert normalize_application_name("-my-app-") == "my-app"

    def test_empty_fallback(self):
        assert normalize_application_name("") == "application"

    def test_only_special_chars(self):
        assert normalize_application_name("!@#$%") == "application"

    def test_preserves_hyphens(self):
        assert normalize_application_name("my-app") == "my-app"

    def test_preserves_numbers(self):
        assert normalize_application_name("app2024") == "app2024"

    def test_whitespace_only(self):
        assert normalize_application_name("   ") == "application"

    def test_mixed_case_with_spaces(self):
        assert normalize_application_name("  Legacy COBOL App  ") == "legacy-cobol-app"


# ---------------------------------------------------------------------------
# derive_application_name_from_zip
# ---------------------------------------------------------------------------

class TestDeriveApplicationNameFromZip:
    def test_from_zip_filename(self):
        name = derive_application_name_from_zip("payroll-system.zip")
        assert name == "payroll-system"

    def test_from_zip_filename_normalizes(self):
        name = derive_application_name_from_zip("My COBOL App.zip")
        assert name == "my-cobol-app"

    def test_single_top_level_dir_overrides(self, tmp_path):
        # Create a workspace with a single top-level dir
        workspace = tmp_path / "ws"
        workspace.mkdir()
        app_dir = workspace / "legacy-mainframe"
        app_dir.mkdir()
        (app_dir / "prog.cob").write_text("hello")

        name = derive_application_name_from_zip("upload.zip", workspace)
        assert name == "legacy-mainframe"

    def test_multiple_top_level_dirs_fallback(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "dir1").mkdir()
        (workspace / "dir2").mkdir()

        name = derive_application_name_from_zip("my-app.zip", workspace)
        assert name == "my-app"

    def test_ingest_prefix_ignored(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "ingest-abc123").mkdir()

        name = derive_application_name_from_zip("app.zip", workspace)
        assert name == "app"

    def test_workspace_none_fallback(self):
        name = derive_application_name_from_zip("cobol-project.zip", None)
        assert name == "cobol-project"

    def test_workspace_not_dir(self, tmp_path):
        name = derive_application_name_from_zip("app.zip", tmp_path / "nonexistent")
        assert name == "app"


# ---------------------------------------------------------------------------
# derive_application_name_from_zip_bytes
# ---------------------------------------------------------------------------

class TestDeriveApplicationNameFromZipBytes:
    def _make_zip(self, entries: list[str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for entry in entries:
                zf.writestr(entry, "content")
        return buf.getvalue()

    def test_single_top_level_dir(self):
        data = self._make_zip(["mainframe/prog.cob", "mainframe/data.txt"])
        name, entries = derive_application_name_from_zip_bytes(data, "upload.zip")
        assert name == "mainframe"
        assert entries == ["mainframe"]

    def test_multiple_top_level_entries(self):
        data = self._make_zip(["prog.cob", "data.txt"])
        name, entries = derive_application_name_from_zip_bytes(data, "my-app.zip")
        assert name == "my-app"
        assert entries == ["data.txt", "prog.cob"]

    def test_fallback_to_filename(self):
        data = self._make_zip([])
        name, entries = derive_application_name_from_zip_bytes(data, "legacy-app.zip")
        assert name == "legacy-app"
        assert entries == []

    def test_ingest_prefix_ignored(self):
        data = self._make_zip(["ingest-abc123/prog.cob"])
        name, entries = derive_application_name_from_zip_bytes(data, "upload.zip")
        # Single dir is "ingest-abc123" but starts with ingest- prefix → fallback
        assert name == "upload"
        assert entries == ["ingest-abc123"]

    def test_invalid_zip(self):
        name, entries = derive_application_name_from_zip_bytes(b"not a zip", "app.zip")
        assert name == "app"
        assert entries == []

    def test_zip_filename_normalization(self):
        data = self._make_zip(["a", "b", "c"])
        name, _ = derive_application_name_from_zip_bytes(data, "My COBOL System.zip")
        assert name == "my-cobol-system"


# ---------------------------------------------------------------------------
# Store.unique_name
# ---------------------------------------------------------------------------

class TestStoreUniqueName:
    def test_unique_name_first_available(self):
        store = Store()
        assert store.unique_name("my-app") == "my-app"

    def test_unique_name_appends_2(self):
        store = Store()
        store.add_application(ApplicationRecord(
            id="a1", name="my-app", description="", workload_id="w1", java_entrypoint="Main",
        ))
        assert store.unique_name("my-app") == "my-app-2"

    def test_unique_name_appends_3(self):
        store = Store()
        store.add_application(ApplicationRecord(
            id="a1", name="my-app", description="", workload_id="w1", java_entrypoint="Main",
        ))
        store.add_application(ApplicationRecord(
            id="a2", name="my-app-2", description="", workload_id="w2", java_entrypoint="Main",
        ))
        assert store.unique_name("my-app") == "my-app-3"

    def test_unique_name_skips_existing(self):
        store = Store()
        store.add_application(ApplicationRecord(
            id="a1", name="my-app", description="", workload_id="w1", java_entrypoint="Main",
        ))
        store.add_application(ApplicationRecord(
            id="a2", name="my-app-3", description="", workload_id="w3", java_entrypoint="Main",
        ))
        # my-app taken, my-app-2 free
        assert store.unique_name("my-app") == "my-app-2"

    def test_unique_name_ignores_different_app(self):
        store = Store()
        store.add_application(ApplicationRecord(
            id="a1", name="other-app", description="", workload_id="w1", java_entrypoint="Main",
        ))
        assert store.unique_name("my-app") == "my-app"

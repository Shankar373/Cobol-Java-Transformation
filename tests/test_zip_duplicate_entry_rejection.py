"""BL-097: ZIP ingestion must reject duplicate/ambiguous entry names.

Red-first contract (Master README 14/60/61 and the audit's Phase-6 risk list:
"ZIP path validation, duplicate entries, extraction cleanup, resource limits"):

* An archive containing the same entry name twice used to extract silently
  last-wins — the extracted tree then disagrees with the entry list a
  validator saw, and the ambiguity is invisible to evidence hashing.
* An entry using a backslash (``src\\A.cob``) and one using a slash
  (``src/A.cob``) name the SAME file on Windows but TWO files on Linux,
  so the ingested source tree was platform-dependent.
* Names differing only by case collide on case-insensitive filesystems
  (Windows/macOS) with silent last-wins overwrite, again making the
  extracted tree platform-dependent.

Fail-closed rule under test: after separator normalization and case
folding, every non-directory entry name must be unique within the
archive. Repeated *directory* entries remain allowed (harmless,
mkdir(exist_ok=True)); distinct names are never rejected.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from api import ingestion


def _zip_bytes(entries: list[tuple[str, str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


class TestDuplicateEntryRejection:
    def test_exact_duplicate_entry_names_rejected(self):
        payload = _zip_bytes(
            [
                ("src/ALPHA.cob", "first payload"),
                ("src/ALPHA.cob", "second payload"),
            ]
        )
        with pytest.raises(ingestion.IngestionError, match="Duplicate ZIP entry"):
            ingestion.ingest_zip(payload, "app-dup-exact")

    def test_backslash_slash_alias_rejected(self):
        # Same target on Windows, two files on Linux -> platform-dependent
        # extraction; must be rejected everywhere.
        payload = _zip_bytes(
            [
                ("src\\BETA.cob", "windows-style name"),
                ("src/BETA.cob", "posix-style name"),
            ]
        )
        with pytest.raises(ingestion.IngestionError, match="Duplicate ZIP entry"):
            ingestion.ingest_zip(payload, "app-dup-alias")

    def test_case_variant_collision_rejected(self):
        # Collides on case-insensitive filesystems with silent overwrite.
        payload = _zip_bytes(
            [
                ("SRC/GAMMA.cob", "upper name"),
                ("src/gamma.cob", "lower name"),
            ]
        )
        with pytest.raises(ingestion.IngestionError, match="Duplicate ZIP entry"):
            ingestion.ingest_zip(payload, "app-dup-case")


class TestNoOverRejection:
    def test_repeated_directory_entries_still_allowed(self):
        # Some archivers emit the same directory entry twice; that is
        # harmless and must keep working.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("src/", "")
            zf.writestr("src/", "")
            zf.writestr("src/MAIN.cob", "       IDENTIFICATION DIVISION.")
        workspace = ingestion.ingest_zip(buf.getvalue(), "app-dirs")
        try:
            assert (workspace / "src" / "MAIN.cob").is_file()
        finally:
            _cleanup(workspace)

    def test_distinct_entries_extract_full_tree(self):
        payload = _zip_bytes(
            [
                ("src/MAIN.cob", "       IDENTIFICATION DIVISION."),
                ("copybooks/CUSTREC.cpy", "       01 CUST-REC."),
            ]
        )
        workspace = ingestion.ingest_zip(payload, "app-distinct")
        try:
            assert (workspace / "src" / "MAIN.cob").read_text() == (
                "       IDENTIFICATION DIVISION."
            )
            assert (workspace / "copybooks" / "CUSTREC.cpy").read_text() == (
                "       01 CUST-REC."
            )
        finally:
            _cleanup(workspace)


def _cleanup(workspace) -> None:
    import shutil

    shutil.rmtree(workspace, ignore_errors=True)

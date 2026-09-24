"""Application name derivation from legacy source archives.

Reusable naming abstraction for future Git/local ingestion.
Only ZIP is active for now.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path


def normalize_application_name(raw: str) -> str:
    """Normalize a raw name into a safe application slug.

    Rules:
    - Lowercase
    - Replace spaces, underscores with hyphens
    - Remove characters that are not alphanumeric, hyphen, or dot
    - Collapse multiple hyphens
    - Strip leading/trailing hyphens
    - Fallback to 'application' if result is empty
    """
    name = raw.strip().lower()
    name = name.replace("_", "-").replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name or "application"


def derive_application_name_from_zip(
    zip_filename: str,
    workspace: Path | None = None,
) -> str:
    """Derive application name from a ZIP archive.

    Priority:
    1. If workspace has a single meaningful top-level directory, use its name.
    2. Otherwise use the ZIP filename without .zip extension.

    Always normalized via normalize_application_name().
    """
    # Try single top-level directory first
    if workspace is not None and workspace.is_dir():
        children = [c for c in workspace.iterdir()]
        dirs = [c for c in children if c.is_dir()]
        if len(dirs) == 1 and len(children) == 1:
            candidate = dirs[0].name
            if candidate and not candidate.startswith("ingest-"):
                return normalize_application_name(candidate)

    # Fall back to ZIP filename
    stem = Path(zip_filename).stem
    return normalize_application_name(stem)


def derive_application_name_from_zip_bytes(
    zip_data: bytes,
    zip_filename: str,
) -> tuple[str, list[str]]:
    """Derive application name by inspecting ZIP contents without full extraction.

    Returns (detected_name, top_level_entries).
    Only peeks at directory structure — does not extract.
    """
    top_level: set[str] = set()
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(zip_data)) as zf:
            for info in zf.infolist():
                parts = info.filename.replace("\\", "/").split("/")
                if parts and parts[0]:
                    top_level.add(parts[0])
    except Exception:
        # If ZIP is unreadable, fall back to filename only
        return normalize_application_name(Path(zip_filename).stem), []

    entries = sorted(top_level)

    # Single meaningful top-level directory
    if len(entries) == 1:
        candidate = entries[0]
        if candidate and not candidate.startswith("ingest-"):
            return normalize_application_name(candidate), entries

    return normalize_application_name(Path(zip_filename).stem), entries

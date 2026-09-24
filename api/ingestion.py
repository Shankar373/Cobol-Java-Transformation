"""Application ingestion abstraction.

Handles importing legacy application source from:
  - ZIP archive upload
  - Git repository URL (interface only -- not implemented for safety)

Extracts source into an isolated application workspace and runs
application discovery using the existing engine components.
"""

from __future__ import annotations

import io
import re
import zipfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class IngestionError(Exception):
    """Raised when ingestion fails."""


MAX_ZIP_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000
MAX_TOTAL_EXTRACTED_BYTES = 500 * 1024 * 1024


def _is_traversal(name: str) -> bool:
    """Reject absolute paths, drive letters and parent-dir traversal."""
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return True
    if re.match(r"^[A-Za-z]:", normalized):
        return True
    return any(part == ".." for part in normalized.split("/"))


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


@dataclass
class DiscoveryResult:
    """Structured discovery output from the engine."""
    application_id: str
    cobol_programs: list[dict] = field(default_factory=list)
    copybooks: list[str] = field(default_factory=list)
    jcl_jobs: list[dict] = field(default_factory=list)
    file_dependencies: list[dict] = field(default_factory=list)
    call_dependencies: list[dict] = field(default_factory=list)
    dependency_edges: list[dict] = field(default_factory=list)
    source_file_count: int = 0
    total_size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "cobol_programs": self.cobol_programs,
            "copybooks": self.copybooks,
            "jcl_jobs": self.jcl_jobs,
            "file_dependencies": self.file_dependencies,
            "call_dependencies": self.call_dependencies,
            "dependency_edges": self.dependency_edges,
            "source_file_count": self.source_file_count,
            "total_size_bytes": self.total_size_bytes,
        }


def ingest_zip(data: bytes, application_id: str) -> Path:
    """Extract a ZIP archive into an isolated workspace directory.

    Returns the workspace path containing the extracted source tree.
    Preserves the original directory structure from the ZIP.

    Security: extraction is path-traversal safe (Zip Slip protected), rejects
    absolute paths and symlink entries, and enforces archive entry/size limits.
    """
    if len(data) > MAX_ZIP_ARCHIVE_BYTES:
        raise IngestionError(
            f"ZIP archive exceeds size limit of {MAX_ZIP_ARCHIVE_BYTES} bytes"
        )

    workspace = Path(tempfile.mkdtemp(prefix=f"ingest-{application_id}-"))

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = zf.infolist()
            if len(members) > MAX_ZIP_ENTRIES:
                raise IngestionError(
                    f"ZIP archive exceeds entry limit of {MAX_ZIP_ENTRIES} files"
                )

            total_size = 0
            for info in members:
                if _is_traversal(info.filename):
                    raise IngestionError(
                        f"Unsafe ZIP entry path: {info.filename!r}"
                    )
                if _is_symlink(info):
                    raise IngestionError(
                        f"Symlink ZIP entries are not allowed: {info.filename!r}"
                    )
                total_size += info.file_size
                if total_size > MAX_TOTAL_EXTRACTED_BYTES:
                    raise IngestionError(
                        f"ZIP exceeds total extracted size limit of "
                        f"{MAX_TOTAL_EXTRACTED_BYTES} bytes"
                    )

            workspace_resolved = workspace.resolve()
            for info in members:
                target = workspace.joinpath(info.filename)
                resolved = target.resolve()
                if not resolved.is_relative_to(workspace_resolved):
                    raise IngestionError(
                        f"Unsafe ZIP entry escapes workspace: {info.filename!r}"
                    )
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
    except zipfile.BadZipFile as exc:
        raise IngestionError(f"Invalid ZIP archive: {exc}") from exc
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(f"Failed to extract ZIP: {exc}") from exc

    return workspace


def discover_application(workspace: Path, application_id: str) -> DiscoveryResult:
    """Run application discovery on an imported workspace.

    Uses ApplicationDiscovery for COBOL programs and JclDiscovery for JCL.
    Returns a structured DiscoveryResult with all discovered artifacts.
    """
    from engine.transformation.application_discovery import ApplicationDiscovery
    from engine.transformation.jcl_discovery import JclDiscovery

    result = DiscoveryResult(application_id=application_id)

    for f in workspace.rglob("*"):
        if f.is_file():
            result.total_size_bytes += f.stat().st_size
            result.source_file_count += 1

    # Discover COBOL programs
    try:
        cobol_discovery = ApplicationDiscovery()
        cobol_app = cobol_discovery.discover(str(workspace), application_id=application_id)

        for unit in cobol_app.programs:
            prog_info = {
                "program_id": unit.program_id,
                "source_path": unit.source_path,
                "file_dependencies": [
                    {"name": fd.file_name, "operation": fd.operation, "mode": fd.mode}
                    for fd in unit.file_dependencies
                ],
                "calls": [
                    {"target": c.target, "arguments": list(c.arguments)}
                    for c in unit.calls
                ],
                "copybooks": [cb.copybook_name for cb in unit.copybooks],
                "entry_points": list(unit.entry_points),
            }
            result.cobol_programs.append(prog_info)

            for fd in unit.file_dependencies:
                result.file_dependencies.append({
                    "program_id": unit.program_id,
                    "file_name": fd.file_name,
                    "operation": fd.operation,
                })

            for c in unit.calls:
                result.call_dependencies.append({
                    "caller": unit.program_id,
                    "target": c.target,
                })

        result.copybooks = list(cobol_app.copybooks)

        for edge in cobol_app.edges:
            result.dependency_edges.append({
                "source": edge.source,
                "target": edge.target,
                "edge_type": edge.edge_type,
            })
    except Exception:
        pass

    # Discover JCL
    try:
        jcl_discovery = JclDiscovery()
        jcl_app = jcl_discovery.discover(str(workspace))

        for job in jcl_app.jobs:
            job_info = {
                "name": job.name,
                "steps": [
                    {
                        "name": step.name,
                        "program": step.exec_.program if step.exec_ else None,
                        "procedure": step.exec_.procedure if step.exec_ else None,
                    }
                    for step in job.steps
                ],
            }
            result.jcl_jobs.append(job_info)

        # Link JCL with COBOL if both exist
        if result.cobol_programs:
            from engine.transformation.ir import CobolApplication
            cobol_discovery2 = ApplicationDiscovery()
            cobol_app2 = cobol_discovery2.discover(str(workspace), application_id=application_id)
            jcl_app = jcl_discovery.link_with_cobol(jcl_app, cobol_app2)

            for dep in jcl_app.dependencies:
                result.dependency_edges.append({
                    "source": dep.source,
                    "target": dep.target,
                    "edge_type": dep.dependency_type,
                })
    except Exception:
        pass

    return result

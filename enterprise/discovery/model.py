"""Shared ingestion results and the plain-directory ingest path.

``ingest_directory`` is the common tail of every other path: ZIP ingestion
validates then extracts into a staging root, Git clones then verifies, and
both finish by walking the staged tree, hashing every file and recording it
with a source-derived timestamp.  Sharing that tail guarantees the manifest
cannot differ between input kinds for identical bytes.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .errors import DiagnosticSink, IngestionError, LimitExceededError
from .hashing import sha256_file
from .limits import DEFAULT_LIMITS, Limits
from .treelimits import TreeBudget

__all__ = [
    "IngestedFile",
    "IngestionResult",
    "walk_files",
    "ingest_directory",
    "rmtree_force",
]


def rmtree_force(path: Path) -> None:
    """Delete *path* even when its files are read-only.

    ``shutil.rmtree(..., ignore_errors=True)`` **silently leaves read-only
    files behind**.  Git stores pack files as ``0o444``, so a plain rmtree on
    Windows would leave ``.git/objects`` inside the staged tree and the
    inventory would hash VCS metadata as if it were source.  This helper
    clears the write bit bottom-up first, then removes; failures after that
    are still ignored because cleanup is best-effort by contract (the caller
    is discarding the tree, never inspecting it).
    """

    if not path.exists():
        return

    def _on_walk_error(_error: OSError) -> None:
        return None

    for root, _dirs, files in os.walk(path, topdown=False,
                                      onerror=_on_walk_error):
        for name in files:
            target = Path(root) / name
            try:
                target.chmod(0o666)
            except OSError:
                pass
        for name in _dirs:
            target = Path(root) / name
            try:
                target.chmod(0o777)
            except OSError:
                pass
    try:
        path.chmod(0o777)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


@dataclass(frozen=True)
class IngestedFile:
    """One staged file, with everything the manifest needs."""

    path: str  # POSIX, relative to the staging root
    sha256: str
    size: int
    #: Source-derived timestamp, never wall-clock: ZIP DOS time or the Git
    #: commit time.  ``""`` when the source carries none.
    source_timestamp: str = ""
    #: True when the path is excluded from the analysis (e.g. VCS metadata).
    excluded: bool = False
    exclusion_reason: str = ""

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
        }
        if self.source_timestamp:
            out["source_timestamp"] = self.source_timestamp
        if self.excluded:
            out["excluded"] = self.exclusion_reason
        return out


@dataclass
class IngestionResult:
    """Everything an ingestion run produced, before any analysis."""

    kind: str  # "zip" | "git" | "directory"
    origin: str
    staging_root: Path
    files: list[IngestedFile] = field(default_factory=list)
    commit: str | None = None
    #: Git commit time of the pinned commit; never wall-clock.
    commit_timestamp: str = ""
    #: Requested ref (branch/tag/SHA) for remote Git; ``""`` otherwise.
    ref: str = ""
    #: Git tree object id of the pinned commit; ``""`` for non-Git inputs.
    tree_id: str = ""
    #: Credential-free display URL of a remote Git source; ``""`` otherwise.
    remote: str = ""
    #: ZIP inputs: the single staged copy of the archive that was extracted and is preserved verbatim.
    original_archive: Path | None = None
    entry_count: int = 0
    total_bytes: int = 0
    diagnostics: list[dict[str, object]] = field(default_factory=list)
    limits: Limits = DEFAULT_LIMITS

    @property
    def source_timestamp(self) -> str:
        """Deterministic source timestamp for the run.

        The pinned commit time when there is one, otherwise the earliest
        source-carried timestamp.  Never the current clock.
        """

        if self.commit_timestamp:
            return self.commit_timestamp
        times = sorted(f.source_timestamp for f in self.files if f.source_timestamp)
        return times[0] if times else ""

    def paths(self) -> list[str]:
        return [f.path for f in self.files]

    def get(self, path: str) -> IngestedFile | None:
        for f in self.files:
            if f.path == path:
                return f
        return None


#: Windows reparse tags that redirect to another location (symlink, junction).
_REDIRECTING_REPARSE_TAGS = frozenset({0xA000000C, 0xA0000003})


def is_redirecting_entry(path: Path) -> bool:
    """True for a symlink or Windows junction/mount point at *path*.

    ``os.walk`` does not follow symlinks but **does** descend Windows
    junctions, and ``Path.is_file`` follows file symlinks; either would pull
    bytes from outside the input into the inventory.  Cloud-sync placeholders
    are reparse points too but are not redirects, so only the symlink and
    mount-point tags count.  An unreadable entry counts as redirecting: the
    check fails closed.
    """

    try:
        info = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    return getattr(info, "st_reparse_tag", 0) in _REDIRECTING_REPARSE_TAGS


def walk_files(
    root: Path,
    *,
    skip: tuple[str, ...] = (),
    limits: Limits = DEFAULT_LIMITS,
) -> list[tuple[str, Path]]:
    """Return ``(posix_relative_path, absolute_path)`` for every file under *root*.

    Deterministic: sorted by relative path.  ``skip`` holds path prefixes
    (POSIX, directory names such as ``".git"``) that are not inventoried —
    callers must record why, so the exclusion is explicit rather than silent.

    A symlink, junction or mount point anywhere in the tree is **refused**
    (``SYMLINK_ENTRY``) rather than followed or skipped, matching the ZIP and
    Git policies: an input must be self-contained.

    ``limits`` is enforced **while walking** (entry count, depth, name and path
    length): the walk stops at the first violation instead of listing a
    hostile tree first.
    """

    budget = TreeBudget(limits)

    skip_set = {s.lower() for s in skip}
    out: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place so os.walk does not descend.
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in skip_set)
        current = Path(dirpath)
        for name in (*dirnames, *filenames):
            if is_redirecting_entry(current / name):
                rel = (current / name).relative_to(root).as_posix()
                raise IngestionError(
                    f"symlink or junction entry refused in input tree: {rel}",
                    code="SYMLINK_ENTRY",
                    path=rel,
                )
        for name in dirnames:
            budget.add_dir((current / name).relative_to(root).as_posix())
        for filename in sorted(filenames):
            absolute = current / filename
            if not absolute.is_file():
                continue  # sockets/fifos/etc. are never inventoried
            rel = absolute.relative_to(root).as_posix()
            budget.add_file(rel)
            out.append((rel, absolute))
    out.sort(key=lambda pair: pair[0])
    return out


def ingest_directory(
    root: Path,
    *,
    origin: str,
    kind: str = "directory",
    skip: tuple[str, ...] = (),
    skip_reason: str = "",
    sink: DiagnosticSink | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> IngestionResult:
    """Hash and inventory an already-staged directory tree.

    Excluded prefixes are reported through *sink* as an ``INFO`` diagnostic so
    the omission appears in the manifest instead of vanishing.
    """

    root = root.resolve()
    if not root.is_dir():
        raise IngestionError(
            f"staging root is not a directory: {root}", code="STAGING_INVALID"
        )

    result = IngestionResult(
        kind=kind, origin=origin, staging_root=root, limits=limits
    )
    sink = sink or DiagnosticSink(limits.max_diagnostics)

    files = walk_files(root, skip=skip, limits=limits)
    # Only report an exclusion that actually occurred: announcing that `.git`
    # was skipped when the tree has no `.git` would put a phantom entry in
    # every manifest (and make two identical inputs differ).
    actually_skipped = sorted(
        prefix for prefix in skip if (root / prefix).exists()
    )
    if actually_skipped and sink is not None:
        sink.info(
            "PATH_EXCLUDED_FROM_INVENTORY",
            f"prefix(es) {', '.join(actually_skipped)} not inventoried"
            + (f": {skip_reason}" if skip_reason else ""),
        )

    total = 0
    for rel, absolute in files:
        try:
            size = absolute.stat().st_size
        except OSError:
            raise IngestionError("an input file could not be read", code="INPUT_UNREADABLE", path=rel) from None
        if size > limits.max_entry_bytes:
            raise LimitExceededError(
                f"file size {size} exceeds max_entry_bytes="
                f"{limits.max_entry_bytes}",
                code="ENTRY_TOO_LARGE",
                path=rel,
            )
        total += size
        if total > limits.max_total_bytes:
            raise IngestionError(
                f"staged tree exceeds max_total_bytes="
                f"{limits.max_total_bytes} ({total} bytes observed)",
                code="LIMIT_EXCEEDED",
                path=rel,
            )
        try:
            digest = sha256_file(absolute)
        except OSError:
            raise IngestionError("an input file could not be read", code="INPUT_UNREADABLE", path=rel) from None
        result.files.append(
            IngestedFile(
                path=rel,
                sha256=digest,
                size=size,
            )
        )

    result.entry_count = len(result.files)
    result.total_bytes = total
    result.diagnostics = sink.to_list()
    return result

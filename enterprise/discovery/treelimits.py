"""Incremental limit and collision accounting for file trees.

ZIP ingestion enforces entry count, path depth and name/path length itself
(``zipingest`` / ``pathsafe``).  A Git repository or a plain directory is just
as capable of being a bomb, so the same bounds are enforced for them through
one small accountant that is fed entries *one at a time* and fails as soon as
a bound is crossed.  Nothing here builds a full list first, which is what makes
a refusal fast on a hostile input.

Error codes are the ZIP ones: ``TOO_MANY_ENTRIES``, ``ENTRY_TOO_LARGE`` and
``TOTAL_TOO_LARGE`` (all :class:`LimitExceededError`) and ``UNSAFE_PATH`` for
depth / name length / path length.  ``PATH_COLLISION`` is new: two paths that
fold to the same name (case or Unicode normalisation) cannot be materialised
faithfully on every host, so the input is refused instead of silently keeping
one of them.

Entry accounting matches the ZIP convention, "files plus directories": each
distinct ancestor directory counts once, then each file.
"""

from __future__ import annotations

import unicodedata

from .errors import IngestionError, LimitExceededError, UnsafePathError
from .limits import DEFAULT_LIMITS, Limits

__all__ = ["TreeBudget", "fold_path"]


def fold_path(path: str) -> str:
    """Key under which two paths collide: NFC-normalised and case-folded."""

    composed = unicodedata.normalize("NFC", path)
    return unicodedata.normalize("NFC", composed.casefold())


class TreeBudget:
    """Feed it paths; it raises the moment a limit or collision is found."""

    def __init__(
        self, limits: Limits = DEFAULT_LIMITS, *, check_collisions: bool = False
    ) -> None:
        self._limits = limits
        self._check_collisions = check_collisions
        self._dirs: set[str] = set()
        self._dir_keys: dict[str, str] = {}
        self._file_keys: dict[str, str] = {}
        self._entries = 0
        self._total = 0

    @property
    def entries(self) -> int:
        return self._entries

    def add_dir(self, path: str) -> None:
        """Account for directory *path* and every ancestor not yet seen."""

        parts = path.split("/")
        self._check_shape(path, parts)
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            if prefix not in self._dirs:
                self._register_dir(prefix)

    def add_file(self, path: str, size: int = 0) -> None:
        """Account for file *path* of *size* bytes (and its ancestors)."""

        parts = path.split("/")
        self._check_shape(path, parts)
        for index in range(1, len(parts)):
            prefix = "/".join(parts[:index])
            if prefix not in self._dirs:
                self._register_dir(prefix)
        self._count(path)
        if size > self._limits.max_entry_bytes:
            raise LimitExceededError(
                f"declared size {size} exceeds max_entry_bytes="
                f"{self._limits.max_entry_bytes}",
                code="ENTRY_TOO_LARGE",
                path=path,
            )
        self._total += size
        if self._total > self._limits.max_total_bytes:
            raise LimitExceededError(
                f"declared total {self._total} exceeds max_total_bytes="
                f"{self._limits.max_total_bytes}",
                code="TOTAL_TOO_LARGE",
                path=path,
            )
        if self._check_collisions:
            self._register_file_key(path)

    def _check_shape(self, path: str, parts: list[str]) -> None:
        limits = self._limits
        if len(path) > limits.max_path_length:
            raise UnsafePathError(
                f"path exceeds {limits.max_path_length} characters",
                code="UNSAFE_PATH",
                path=path[:80] + "...",
            )
        if len(parts) > limits.max_path_depth:
            raise UnsafePathError(
                f"path depth {len(parts)} exceeds {limits.max_path_depth}",
                code="UNSAFE_PATH",
                path=path[:80],
            )
        for part in parts:
            if len(part) > limits.max_name_length:
                raise UnsafePathError(
                    f"path component exceeds {limits.max_name_length} "
                    "characters",
                    code="UNSAFE_PATH",
                    path=part[:80] + "...",
                )

    def _count(self, path: str) -> None:
        self._entries += 1
        if self._entries > self._limits.max_entries:
            raise LimitExceededError(
                f"more than max_entries={self._limits.max_entries} entries",
                code="TOO_MANY_ENTRIES",
                path=path,
            )

    def _register_dir(self, prefix: str) -> None:
        self._dirs.add(prefix)
        self._count(prefix)
        if not self._check_collisions:
            return
        key = fold_path(prefix)
        if key in self._file_keys:
            raise self._collision(prefix, self._file_keys[key])
        known = self._dir_keys.setdefault(key, prefix)
        if known != prefix:
            raise self._collision(prefix, known)

    def _register_file_key(self, path: str) -> None:
        key = fold_path(path)
        if key in self._file_keys:
            raise self._collision(path, self._file_keys[key])
        if key in self._dir_keys:
            raise self._collision(path, "a directory of the same folded name")
        self._file_keys[key] = path

    @staticmethod
    def _collision(path: str, other: str) -> IngestionError:
        return UnsafePathError(
            f"path {path!r} collides with {other!r} under case-folding or "
            "Unicode normalisation; it cannot be materialised faithfully on "
            "every host",
            code="PATH_COLLISION",
            path=path,
        )

"""Deterministic COPYBOOK file resolution — M7 (Lane C).

Maps a ``COPY <name>`` reference (as discovered by ``ApplicationDiscovery``)
to the actual ``.cpy`` source file on disk.

Conflict note: this module is intentionally isolated. It creates no new
program semantics and modifies no existing file. Integration into
discovery/generation is documented in ``copybook_model.INTEGRATION`` and
must be applied by the owning lane.

Resolution rules (deterministic, no first-match guessing):
  1. The copybook stem is matched case-insensitively
     (``COPY common`` resolves ``COMMON.cpy``).
  2. Candidate extensions, in precedence order: ``.cpy``, ``.cbl``, ``.cob``
     (any letter case). A ``.cpy`` hit always beats other extensions.
  3. Search directories are scanned in the order given; the program's own
     source directory should be passed first.
  4. Ambiguity is a controlled error, never a silent pick: two different
     files with equal precedence (same stem and extension class in
     different directories, or ``.cbl`` vs ``.cob`` for the same stem)
     raise ``AmbiguousCopybookError`` listing every candidate.
  5. No candidate at all yields a ``MissingCopybook`` diagnostic
     (``collect`` API) or raises ``CopybookResolutionError`` (``strict`` API).

A ``.cpy`` file is a data definition, never an executable program: this
module only locates copybook files and never treats them as programs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class CopybookResolutionError(Exception):
    """Raised when a COPY reference cannot be resolved deterministically."""


class AmbiguousCopybookError(CopybookResolutionError):
    """Two or more files match a COPY reference with equal precedence."""

    def __init__(self, copybook_name: str, candidates: tuple[Path, ...]) -> None:
        self.copybook_name = copybook_name
        self.candidates = candidates
        listed = ", ".join(str(c) for c in candidates)
        super().__init__(
            f"Ambiguous COPY target {copybook_name!r}: {listed}"
        )


@dataclass(frozen=True)
class MissingCopybook:
    """Controlled diagnostic for an unresolvable COPY reference."""
    program_id: str
    copybook_name: str
    searched_dirs: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        return (
            f"Missing COPY target: {self.copybook_name} "
            f"(in {self.program_id})"
        )


@dataclass(frozen=True)
class ResolvedCopybook:
    """A COPY reference bound to its on-disk source file (provenance)."""
    program_id: str
    copybook_name: str
    path: Path


# Extension precedence: .cpy first; .cbl/.cob are accepted legacy spellings.
_EXTENSION_PRECEDENCE: tuple[str, ...] = (".cpy", ".cbl", ".cob")


def _candidate_files(search_dirs: tuple[Path, ...], stem_upper: str) -> list[Path]:
    """Collect files whose stem matches (case-insensitive), unsorted."""
    found: list[Path] = []
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            if entry.stem.upper() != stem_upper:
                continue
            if entry.suffix.lower() not in _EXTENSION_PRECEDENCE:
                continue
            found.append(entry)
    return found


def resolve_copybook(
    copybook_name: str,
    search_dirs: tuple[Path, ...] | list[Path],
    *,
    program_id: str = "",
) -> ResolvedCopybook:
    """Resolve one COPY reference to its source file (strict).

    Raises:
        CopybookResolutionError: no candidate file exists.
        AmbiguousCopybookError: candidates tie on precedence.
    """
    dirs = tuple(search_dirs)
    stem_upper = copybook_name.upper()
    candidates = _candidate_files(dirs, stem_upper)

    if not candidates:
        raise CopybookResolutionError(
            f"Missing COPY target: {copybook_name}"
            + (f" (in {program_id})" if program_id else "")
        )

    def precedence(path: Path) -> int:
        return _EXTENSION_PRECEDENCE.index(path.suffix.lower())

    best = min(precedence(c) for c in candidates)
    winners = tuple(
        sorted(
            (c for c in candidates if precedence(c) == best),
            key=lambda p: str(p),
        )
    )
    if len(winners) > 1:
        raise AmbiguousCopybookError(copybook_name, winners)
    return ResolvedCopybook(
        program_id=program_id, copybook_name=copybook_name, path=winners[0]
    )


def resolve_application_copybooks(
    copy_refs: tuple[tuple[str, str], ...],
    search_dirs: tuple[Path, ...] | list[Path],
) -> tuple[tuple[ResolvedCopybook, ...], tuple[MissingCopybook, ...]]:
    """Resolve many (program_id, copybook_name) references (collecting).

    Returns ``(resolved, missing)``. Missing references become
    ``MissingCopybook`` diagnostics; ambiguous references are also
    reported as missing with the ambiguity detail preserved in the
    searched-dirs record — callers surface them as controlled errors.
    No exception is raised for missing targets.
    """
    dirs = tuple(search_dirs)
    resolved: list[ResolvedCopybook] = []
    missing: list[MissingCopybook] = []
    for program_id, copybook_name in copy_refs:
        try:
            resolved.append(
                resolve_copybook(copybook_name, dirs, program_id=program_id)
            )
        except AmbiguousCopybookError as exc:
            missing.append(
                MissingCopybook(
                    program_id=program_id,
                    copybook_name=copybook_name,
                    searched_dirs=tuple(str(c) for c in exc.candidates),
                )
            )
        except CopybookResolutionError:
            missing.append(
                MissingCopybook(
                    program_id=program_id,
                    copybook_name=copybook_name,
                    searched_dirs=tuple(str(d) for d in dirs),
                )
            )
    return tuple(resolved), tuple(missing)

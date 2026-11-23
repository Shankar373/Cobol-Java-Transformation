"""Shared library-order authority (layer 4, acceptance criterion 9).

Discovery records what an estate contains; generation materialises what a
program copies in.  Both must agree on which same-named copybook wins when
several libraries provide it, and on the losers that remain candidates.

This module is the single authority for that decision: discovery derives the
applicable orders from JCL (``enterprise/discovery/resolve._library_orders``)
and both faces call :func:`library_winner`.  Agreement is enforced by fixture
parity, not by documentation.
"""

from __future__ import annotations

from typing import Sequence

from posixpath import dirname as _posix_dirname


#: Match strength of a library against a copybook path: the dataset (or directory) name matches the directory
#: path component-for-component (``PROD.COPYLIB`` -> ``.../prod/copylib``), or only its last qualifier matches the
#: copybook's directory name (``PROD.COPYLIB`` -> ``.../anything/copylib``).  Case-insensitive.
FULL_MATCH = 2
QUALIFIER_MATCH = 1
NO_MATCH = 0


def _normalise_library(library: str) -> str:
    lib = library.lower().replace("\\", "/").strip().split("(", 1)[0].strip("/")  # drop a ``(MEMBER)`` suffix
    return lib[2:] if lib.startswith("./") else lib


def library_match(path: str, library: str) -> int:
    """How strongly the copybook at ``path`` belongs to ``library`` (a dataset ``PROD.COPYLIB`` or a directory
    ``libs/lib2``): :data:`FULL_MATCH`, :data:`QUALIFIER_MATCH` or :data:`NO_MATCH`.

    Dataset names map to directories deterministically: the dotted name is read as a path
    (``PROD.COPYLIB`` == ``prod/copylib``) and must equal the end of the copybook's directory on component
    boundaries; failing that, the dataset's last qualifier is compared with the directory's own name.
    """
    folder = _posix_dirname(path.replace("\\", "/")).lower()
    lib = _normalise_library(library)
    if not lib:
        return NO_MATCH
    dataset_path = lib.replace(".", "/") if "/" not in lib else lib
    if folder == dataset_path or folder.endswith("/" + dataset_path):
        return FULL_MATCH
    if "/" not in lib and "." in lib and folder.rsplit("/", 1)[-1] == lib.rsplit(".", 1)[-1]:
        return QUALIFIER_MATCH
    return NO_MATCH


def in_library(path: str, library: str) -> bool:
    """Whether the copybook at ``path`` lives in ``library`` at any match strength (see :func:`library_match`).
    Identical logic on both faces."""
    return library_match(path, library) != NO_MATCH


def _library_hits(candidates: Sequence[str], library: str) -> list[str]:
    """The candidates ``library`` holds, at the strongest match strength present (a full dotted-name match beats
    the last-qualifier fallback, so ``PROD.COPYLIB`` and ``TEST.COPYLIB`` never both claim each other's directory)."""
    ranked = [(library_match(c, library), c) for c in candidates]
    best = max((rank for rank, _c in ranked), default=NO_MATCH)
    return [c for rank, c in ranked if rank == best and best != NO_MATCH]


def library_winner(candidates: list[str] | tuple[str, ...],
                   orders: Sequence[Sequence[str]]) -> str:
    """The candidate every applicable library order agrees on, or ``""`` when no order decides.

    ``candidates`` are copybook paths (posix-style).  ``orders`` is a list of
    library concatenations (one per step that runs the program, or the compile
    command's ``-I`` order).  Within each order the first library containing a
    candidate wins; an order decides only when exactly one library hits.  All
    orders must agree (same winner) for the decision to stand; an empty
    ``orders`` never decides.
    """
    winners: set[str] = set()
    if not orders:
        return ""
    for order in orders:
        picked = ""
        for library in order:
            hits = _library_hits(candidates, library)
            if hits:
                picked = hits[0] if len(hits) == 1 else ""
                break
        if not picked:
            return ""
        winners.add(picked)
    return next(iter(winners)) if len(winners) == 1 else ""

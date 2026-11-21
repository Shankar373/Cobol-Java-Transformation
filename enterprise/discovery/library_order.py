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


def in_library(path: str, library: str) -> bool:
    """Whether the copybook at ``path`` lives in ``library`` (a dataset
    ``LIBS.LIB2`` or a directory ``libs/lib2``).  Identical logic on both
    faces."""
    folder = _posix_dirname(path.replace("\\", "/")).lower()
    lib = library.lower().replace("\\", "/").strip("/")
    lib = lib[2:] if lib.startswith("./") else lib
    dataset_path = lib.replace(".", "/") if "/" not in lib else lib
    if folder == dataset_path or folder.endswith("/" + dataset_path):
        return True
    return "/" not in lib and "." in lib and folder.rsplit("/", 1)[-1] == lib.rsplit(".", 1)[-1]


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
            hits = [c for c in candidates if in_library(c, library)]
            if hits:
                picked = hits[0] if len(hits) == 1 else ""
                break
        if not picked:
            return ""
        winners.add(picked)
    return next(iter(winners)) if len(winners) == 1 else ""

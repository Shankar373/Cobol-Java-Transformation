"""Origin map of expanded COPY text: which file and line every expanded line came from (Layer 4).

``copybook_model._expand_copybook_text`` and ``fd_copybooks.expand_fd_copybooks`` splice copybook text
into a larger text in memory.  The spliced text is what the parser reads, so without a map a finding on
expanded line 57 cannot be traced back to ``COPYLIB/CUSTREC.cpy:3`` (the copybook line) or to the
``COPY`` statement in the program that pulled it in.  The map is built beside the expansion — it never
changes the expanded text.

Shape (all frozen, deterministic, no hashing of absolute host data beyond the paths the caller passes):

* :class:`CopyHop` — one ``COPY`` statement: the file and 1-based line that holds it and the member it names.
* :class:`OriginSpan` — the origin of one expanded line: ``file``/``line`` where the text physically sits
  and ``via``, the hops (outermost first) it was expanded through.  ``chain`` renders it as
  ``file:line`` strings, outermost COPY statement first, the physical line last.
* :class:`CopyOriginMap` — ``lines[i]`` is the origin of expanded line ``i + 1``; ``origin_of(n)``
  answers for one line and fails loudly (``IndexError``) outside the text.

A ``REPLACING`` clause rewrites words inside lines and keeps the line structure, so the map stays exact.
When a replacement text itself contains newlines the expanded line count no longer matches the member's;
every line of that member is then attributed to its ``COPY`` statement and flagged ``exact=False`` —
never a guessed copybook line.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CopyHop:
    """A ``COPY`` statement: ``file`` and 1-based ``line`` of the statement, and the ``target`` it names."""

    file: str
    line: int
    target: str


@dataclass(frozen=True)
class OriginSpan:
    """Where one expanded line came from."""

    file: str                      # file that physically holds the text of this line
    line: int                      # 1-based line in ``file`` (the COPY statement's line when not exact)
    via: tuple[CopyHop, ...] = ()  # COPY statements it was expanded through, outermost first
    exact: bool = True

    @property
    def chain(self) -> tuple[str, ...]:
        """``file:line`` of every COPY statement on the way, then of the physical line itself."""
        return (*(f"{hop.file}:{hop.line}" for hop in self.via), f"{self.file}:{self.line}")


@dataclass(frozen=True)
class CopyOriginMap:
    """The origin of every line of an expanded text."""

    lines: tuple[OriginSpan, ...] = ()

    def origin_of(self, expanded_line: int) -> OriginSpan:
        """Origin of 1-based ``expanded_line``; ``IndexError`` when the text has no such line."""
        if not 1 <= expanded_line <= len(self.lines):
            raise IndexError(f"expanded line {expanded_line} is outside the {len(self.lines)}-line text")
        return self.lines[expanded_line - 1]


class OriginBuilder:
    """Accumulates pieces of an expansion and the origin of each of their lines.

    ``add(text, origin_of_line)`` appends ``text``; ``origin_of_line(k)`` is the origin of the ``k``-th
    line *segment* of ``text`` (segment 0 continues the line already open, later segments start new
    lines).  The final line origin is the origin of that line's first non-blank character, so a line that starts
    in the program and continues inside an expansion is attributed to the program.
    """

    def __init__(self) -> None:
        self._origins: list[OriginSpan] = []
        self._fresh = True            # the open line has no character yet
        self._pending: OriginSpan | None = None  # origin of an empty line start (resolved by the next char)

    def add(self, text: str, origin_of_line) -> None:  # noqa: ANN001 - a small callable, kept untyped on purpose
        for index, segment in enumerate(text.split("\n")):
            if index > 0:
                if self._fresh and self._pending is not None:
                    self._origins.append(self._pending)  # the previous line was empty
                self._fresh = True
                self._pending = None
            origin = origin_of_line(index)
            if self._fresh:
                self._pending = origin  # an all-blank line is attributed to the last piece that touched it
            if segment.strip() and self._fresh:
                self._origins.append(origin)
                self._fresh = False
                self._pending = None

    def build(self) -> CopyOriginMap:
        if self._fresh and self._pending is not None:
            self._origins.append(self._pending)
        return CopyOriginMap(tuple(self._origins))

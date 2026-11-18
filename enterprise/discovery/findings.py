"""Value types the discovery scanners produce.  Every one carries ``file``, ``line`` and ``column``.

Nothing here knows how a finding was found; scanners emit :class:`Ref` (something one artefact points at) and
:class:`Fact` (something the artefact is or declares).  Both are frozen and sort deterministically so the same
source always yields byte-identical reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Detail = tuple[tuple[str, str], ...]


def detail(**items: object) -> Detail:
    """A sorted, string-valued detail tuple (empty values dropped) so findings hash and compare stably."""
    return tuple(sorted((key, str(value)) for key, value in items.items() if value not in (None, "", ())))


@dataclass(frozen=True, order=True)
class Ref:
    """A reference from one artefact to another.

    ``target`` is the referenced name, upper-cased; ``""`` with ``dynamic=True`` means the target is computed at
    run time (``CALL WS-PROGRAM``) and cannot be resolved statically.  ``owner`` is the referencing artefact
    (a program id, a job step, ...) as ``kind:name``.
    """

    file: str
    line: int
    column: int
    relation: str
    target_kind: str
    target: str
    owner: str = ""
    clause: str = ""
    dynamic: bool = False
    #: The variable that carries a dynamic target, e.g. ``WS-PROGRAM-NAME``.
    variable: str = ""
    detail: Detail = ()
    #: Names the library/qualifier the reference was written with (``COPY X OF LIB``).
    qualifier: str = ""
    #: The operation the reference performs for data-access relations (``read``/``write``/...); ``""`` when the
    #: relation carries no operation.  Validated against :data:`enterprise.discovery.graph.EDGE_MODES` when the edge is
    #: built, so a scanner can never invent a mode.
    mode: str = ""


@dataclass(frozen=True, order=True)
class Fact:
    """Something an artefact declares: a program id, a dialect signal, a file organisation, a compiler option."""

    file: str
    line: int
    column: int
    category: str
    name: str
    owner: str = ""
    detail: Detail = ()


@dataclass(frozen=True, order=True)
class ScanProblem:
    """A scanner could not fully read an artefact.  Always reported; never silently dropped."""

    file: str
    line: int
    code: str
    message: str


@dataclass
class FileScan:
    """Everything one scanner learned from one file."""

    path: str
    refs: list[Ref] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    problems: list[ScanProblem] = field(default_factory=list)
    #: Reference format of the file (``fixed``/``free``/``mixed``) for COBOL-family sources.
    source_format: str = ""
    line_count: int = 0

    def sorted(self) -> "FileScan":
        self.refs.sort()
        self.facts.sort()
        self.problems.sort()
        return self

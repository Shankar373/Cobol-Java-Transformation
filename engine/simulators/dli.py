"""SIMDLI-1: a deterministic, in-memory model of the IMS DL/I calls a batch COBOL program makes.

Specification version ``SIMDLI-1.0``.  One hierarchical database, defined by a DBD of segment types
(each with a parent, a key length and a data length); calls GU, GN, GNP, ISRT, DLET and REPL, each
returning a two-character status code (``"  "`` for success, shown as ``OK`` in traces).

What is modelled
    * Hierarchical sequence: depth first, children ordered by segment-type position in the DBD and then
      by key, keys unique under a parent.
    * Segment search arguments (SSAs): ``NAME`` unqualified or ``NAME(=key)`` qualified by key equality.
      GU walks the SSA path from the root; GN / GNP take zero or one SSA restricting the segment type.
    * Positioning: GN continues after the current position; GNP continues inside the parent set by the last
      GU or GN (never by a GNP); ISRT places a segment by key under the parent named by the SSA path and
      becomes the current segment; DLET removes the current segment with all its dependents; REPL replaces
      the current segment's data (the key may not change).
    * Status codes: GE segment not found; GB end of database; GP no parent established; II segment already
      exists; DJ no current segment for DLET / REPL (the previous call must have retrieved or inserted one);
      DA key changed by REPL; AK invalid segment name or SSA; AD invalid function.

What is not modelled: secondary indexes, logical relationships, PCBs and I/O areas as storage, command
codes, Boolean qualification, relational operators other than equality, path calls, checkpoint/restart,
HALDB, locking and multiple PCBs.  Status codes are IBM's documented values; none has been compared with
an IMS subsystem (none is available), so equivalence to this model is ``SIMULATOR_VERIFIED``, never
``IBM_VERIFIED``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SPEC_VERSION = "SIMDLI-1.0"
OK = "  "


@dataclass(frozen=True)
class SegmentType:
    name: str
    parent: str  # "" for the root
    key_length: int
    data_length: int


@dataclass(eq=False)
class _Node:
    type: SegmentType
    data: str
    children: list = field(default_factory=list)
    parent: "_Node | None" = None

    @property
    def key(self) -> str:
        return self.data[: self.type.key_length]


_SSA = re.compile(r"^([A-Za-z0-9]+)(?:\(=([^)]*)\))?$")


class SimDli:
    def __init__(self, types: tuple[SegmentType, ...]) -> None:
        if not types or types[0].parent:
            raise ValueError("the first segment type is the root")
        self.types = {t.name: t for t in types}
        self.order = {t.name: i for i, t in enumerate(types)}
        self.root_type = types[0]
        self.roots: list[_Node] = []
        self._index = -1  # position in the hierarchical sequence; -1 = before the first segment
        self._current: _Node | None = None  # segment a DLET / REPL may act on
        self._parent: _Node | None = None  # set by the last GU / GN

    # -- hierarchy helpers ------------------------------------------------------------------
    def _sequence(self) -> list[_Node]:
        out: list[_Node] = []

        def walk(nodes: list[_Node]) -> None:
            for node in nodes:
                out.append(node)
                walk(node.children)

        walk(self.roots)
        return out

    def _sibling_key(self, node: _Node) -> tuple[int, str]:
        return (self.order[node.type.name], node.key)

    def _siblings(self, parent: "_Node | None") -> list[_Node]:
        return self.roots if parent is None else parent.children

    @staticmethod
    def _parse(ssa: str):
        match = _SSA.match(ssa)
        if not match:
            return None
        return match.group(1).upper(), match.group(2)

    def _matches(self, node: _Node, name: str, key: "str | None") -> bool:
        return node.type.name == name and (key is None or node.key == key)

    # -- calls ------------------------------------------------------------------------------
    def gu(self, ssas: list[str]) -> tuple[str, "_Node | None"]:
        if not ssas:
            return "AK", None
        parsed = [self._parse(s) for s in ssas]
        if any(p is None or p[0] not in self.types for p in parsed):
            return "AK", None
        # the path must be root .. target, each the parent of the next
        expected_parent = ""
        for name, _ in parsed:
            if self.types[name].parent != expected_parent:
                return "AK", None
            expected_parent = name
        siblings = self.roots
        node: _Node | None = None
        for name, key in parsed:
            node = next((n for n in siblings if self._matches(n, name, key)), None)
            if node is None:
                return "GE", None
            siblings = node.children
        self._set_position(node, establish_parent=True)
        return OK, node

    def gn(self, ssas: list[str]) -> tuple[str, "_Node | None"]:
        if len(ssas) > 1:
            return "AK", None
        target = None
        if ssas:
            parsed = self._parse(ssas[0])
            if parsed is None or parsed[0] not in self.types:
                return "AK", None
            target = parsed
        sequence = self._sequence()
        for index in range(self._index + 1, len(sequence)):
            node = sequence[index]
            if target is None or self._matches(node, *target):
                self._index = index
                self._current = node
                self._parent = node
                return OK, node
        self._current = None
        return "GB", None

    def gnp(self, ssas: list[str]) -> tuple[str, "_Node | None"]:
        if len(ssas) > 1:
            return "AK", None
        if self._parent is None:
            return "GP", None
        target = None
        if ssas:
            parsed = self._parse(ssas[0])
            if parsed is None or parsed[0] not in self.types:
                return "AK", None
            target = parsed
        sequence = self._sequence()
        for index in range(self._index + 1, len(sequence)):
            node = sequence[index]
            if not self._is_descendant(node, self._parent):
                break
            if target is None or self._matches(node, *target):
                self._index = index
                self._current = node
                return OK, node
        self._current = None
        return "GE", None

    @staticmethod
    def _is_descendant(node: _Node, ancestor: _Node) -> bool:
        cursor = node.parent
        while cursor is not None:
            if cursor is ancestor:
                return True
            cursor = cursor.parent
        return False

    def isrt(self, ssas: list[str], data: str) -> tuple[str, "_Node | None"]:
        if not ssas:
            return "AK", None
        parsed = [self._parse(s) for s in ssas]
        if any(p is None or p[0] not in self.types for p in parsed):
            return "AK", None
        expected_parent = ""
        for name, _ in parsed:
            if self.types[name].parent != expected_parent:
                return "AK", None
            expected_parent = name
        seg_name, seg_key = parsed[-1]
        if seg_key is not None:
            return "AK", None  # the segment being inserted is unqualified
        seg_type = self.types[seg_name]
        if len(data) != seg_type.data_length:
            return "AK", None
        parent: _Node | None = None
        siblings = self.roots
        for name, key in parsed[:-1]:
            if key is None:
                return "AK", None  # every parent on the path is qualified
            parent = next((n for n in siblings if self._matches(n, name, key)), None)
            if parent is None:
                return "GE", None
            siblings = parent.children
        node = _Node(seg_type, data, parent=parent)
        if any(s.type is seg_type and s.key == node.key for s in siblings):
            return "II", None
        siblings.append(node)
        siblings.sort(key=self._sibling_key)
        self._set_position(node, establish_parent=False)
        return OK, node

    def dlet(self) -> str:
        if self._current is None:
            return "DJ"
        node = self._current
        sequence = self._sequence()
        index = sequence.index(node)
        self._siblings(node.parent).remove(node)
        self._index = index - 1  # the next GN returns what now stands at this place
        self._current = None
        if self._parent is node or (self._parent is not None and self._is_descendant(self._parent, node)):
            self._parent = None
        return OK

    def repl(self, data: str) -> tuple[str, "_Node | None"]:
        if self._current is None:
            return "DJ", None
        node = self._current
        if len(data) != node.type.data_length:
            return "AK", None
        if data[: node.type.key_length] != node.key:
            return "DA", None
        node.data = data
        return OK, node

    def _set_position(self, node: _Node, *, establish_parent: bool) -> None:
        self._index = self._sequence().index(node)
        self._current = node
        if establish_parent:
            self._parent = node


# ------------------------------------------------------------------------------------------
# Scripts and the canonical trace
# ------------------------------------------------------------------------------------------

def run_script(script: str) -> list[str]:
    """Run a script and return its canonical trace, one line per operation.

    The first line is ``DBD NAME:PARENT:KEYLEN:DATALEN NAME:PARENT:KEYLEN:DATALEN ...`` (the root has an
    empty parent).  Operations: ``GU ssa/ssa/..``, ``GN [ssa]``, ``GNP [ssa]``, ``ISRT ssa/../NAME data``,
    ``DLET``, ``REPL data``.  Segment data is ASCII without spaces.  A trace line is the operation, `` -> ``,
    the status (``OK`` for blank), and for a returned segment `` seg=NAME data=...``.
    """
    dli: SimDli | None = None
    trace: list[str] = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        op, *args = line.split(" ")
        if op == "DBD":
            types = []
            for spec in args:
                name, parent, key_len, data_len = spec.split(":")
                types.append(SegmentType(name.upper(), parent.upper(), int(key_len), int(data_len)))
            dli = SimDli(tuple(types))
            trace.append(f"{line} -> {SPEC_VERSION}")
            continue
        if dli is None:
            raise ValueError("a script starts with DBD")
        trace.append(f"{line} -> {_step(dli, op, args)}")
    return trace


def _show(status: str, node: "_Node | None") -> str:
    shown = "OK" if status == OK else status
    return shown if node is None else f"{shown} seg={node.type.name} data={node.data}"


def _step(dli: SimDli, op: str, args: list[str]) -> str:
    ssas = [s for s in (args[0].split("/") if args else []) if s]
    if op == "GU":
        return _show(*dli.gu(ssas))
    if op == "GN":
        return _show(*dli.gn(ssas))
    if op == "GNP":
        return _show(*dli.gnp(ssas))
    if op == "ISRT":
        return _show(*dli.isrt(ssas, args[1] if len(args) > 1 else ""))
    if op == "DLET":
        return _show(dli.dlet(), None)
    if op == "REPL":
        return _show(*dli.repl(args[0] if args else ""))
    return _show("AD", None)

"""Group items as views over their subordinate fields (certified subset).

Subordinate items are lowered to independent Java fields, so a group has no
storage of its own.  For a DISPLAY-usage group whose leaves all store
exactly their DISPLAY characters, the group's bytes are nevertheless fully
determined by its leaves, in order:

* ``PIC X(n)``          -> the value, space padded / truncated to ``n``;
* unsigned ``PIC 9(n)`` -> ``n`` zero-filled digits (``n <= 18``);
* ``FILLER PIC X(n)``   -> its VALUE (or spaces), which nothing can change
  while the group is never a MOVE receiver.

That makes two operations provable (oracle: GnuCOBOL 3.1.2):

* **reading** the group (``DISPLAY group``, ``MOVE group TO alnum-field``)
  is the concatenation of the leaves' characters;
* **writing** the group (``MOVE src TO group``) is an alphanumeric move of
  ``src`` padded/truncated to the group length and split back into the
  leaves - provable only when every leaf is a named ``PIC X`` field, because
  arbitrary characters cannot be stored in a numeric Java field.

Anything else (OCCURS, REDEFINES, USAGE other than DISPLAY, signed or
scaled numerics, ambiguous names, ...) has no layout here and stays fail
closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.transformation.figurative import (
    ALL,
    QUOTES,
    SPACES,
    ZERO,
    figurative_to_width,
    parse_figurative_constant,
)
from engine.transformation.ir import DataItem


@dataclass(frozen=True)
class GroupLeaf:
    """One elementary item of a group, in storage order."""

    name: str | None  # None for FILLER
    offset: int
    length: int
    numeric: bool
    constant: str | None = None  # FILLER characters


@dataclass(frozen=True)
class GroupLayout:
    name: str
    leaves: tuple[GroupLeaf, ...]

    @property
    def length(self) -> int:
        return sum(leaf.length for leaf in self.leaves)

    @property
    def leaf_names(self) -> frozenset[str]:
        return frozenset(l.name.upper() for l in self.leaves if l.name)

    @property
    def writable(self) -> bool:
        """True when every leaf is a named alphanumeric field."""
        return all(l.name and not l.numeric for l in self.leaves)


def iter_data_items(items):
    """Every data item in ``items``, depth first, each object once."""
    seen: set[int] = set()

    def walk(nodes):
        for node in nodes:
            if id(node) in seen:
                continue
            seen.add(id(node))
            yield node
            yield from walk(node.children)

    yield from walk(items)


def is_group(item: DataItem) -> bool:
    return item.level != 88 and any(c.level != 88 for c in item.children)


def find_item(items, name: str) -> DataItem | None:
    """The single data item called ``name`` (case-insensitive), else None."""
    key = name.strip().upper()
    found = [i for i in iter_data_items(items) if i.name.upper() == key]
    unique = {id(i) for i in found}
    return found[0] if len(unique) == 1 else None


def _filler_constant(item: DataItem) -> str | None:
    if item.value is None:
        return " " * item.pic_length
    raw = item.value.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        text = raw[1:-1]
    else:
        text = printable_fill(raw, item.pic_length)
        if text is None:
            return None
    return text[: item.pic_length].ljust(item.pic_length)


#: Figurative constants whose characters are printable text.  LOW-VALUE and
#: HIGH-VALUE are bytes outside the Java String model and stay unsupported.
_PRINTABLE_FIGURATIVES = frozenset({SPACES, ZERO, QUOTES, ALL})


def printable_fill(text: str, width: int) -> str | None:
    """Characters a printable figurative constant supplies for ``width``."""
    figurative = parse_figurative_constant(text)
    if figurative is None or figurative[0] not in _PRINTABLE_FIGURATIVES:
        return None
    return figurative_to_width(figurative[0], figurative[1], width)


def group_layout(items, name: str) -> tuple[GroupLayout | None, str | None]:
    """Layout of group ``name`` within ``items``, or ``(None, reason)``."""
    group = find_item(items, name)
    if group is None or not is_group(group):
        return None, f"{name} is not a uniquely named group item"
    names = [i.name.upper() for i in iter_data_items(items)]
    redefined = {
        (i.redefines or "").upper() for i in iter_data_items(items) if i.redefines
    }
    leaves: list[GroupLeaf] = []
    offset = 0

    def visit(item: DataItem) -> str | None:
        nonlocal offset
        if item.level == 88:
            return None
        upper = item.name.upper()
        if item.occurs or item.occurs_depending_on:
            return f"{item.name} has OCCURS"
        if item.redefines or upper in redefined:
            return f"{item.name} takes part in REDEFINES"
        if item.usage:
            return f"{item.name} has USAGE {item.usage}"
        if is_group(item):
            for child in item.children:
                problem = visit(child)
                if problem:
                    return problem
            return None
        if item.pic_length <= 0:
            return f"{item.name} has no PIC"
        if upper == "FILLER":
            if not item.is_alphanumeric:
                return "FILLER must be PIC X"
            constant = _filler_constant(item)
            if constant is None:
                return f"FILLER VALUE {item.value} is not certified"
            leaves.append(GroupLeaf(None, offset, item.pic_length, False, constant))
        elif names.count(upper) != 1:
            return f"{item.name} is not uniquely named"
        elif item.is_alphanumeric:
            leaves.append(GroupLeaf(item.name, offset, item.pic_length, False))
        elif (
            item.is_numeric
            and not item.signed
            and item.decimal_places == 0
            and item.pic_length <= 18
        ):
            leaves.append(GroupLeaf(item.name, offset, item.pic_length, True))
        else:
            return (
                f"{item.name} is not PIC X or an unsigned integer PIC 9(1..18)"
            )
        offset += item.pic_length
        return None

    if (group.redefines or "").upper() or group.name.upper() in redefined:
        return None, f"{group.name} takes part in REDEFINES"
    if group.occurs or group.usage:
        return None, f"{group.name} has OCCURS or USAGE"
    for child in group.children:
        problem = visit(child)
        if problem:
            return None, problem
    if not leaves:
        return None, f"{group.name} has no elementary items"
    return GroupLayout(group.name, tuple(leaves)), None


def _is_quoted(text: str) -> bool:
    text = text.strip()
    return len(text) >= 2 and text[0] == text[-1] and text[0] in "'\""


def _base(ref: str) -> tuple[str, bool]:
    """``(name, qualified)`` - qualified when subscripted/reference-modified."""
    text = str(ref or "").strip().rstrip(".")
    return text.split("(", 1)[0].strip().upper(), "(" in text


def group_reference_problem(items, ref: str) -> str | None:
    """Reason a read of group ``ref`` (DISPLAY / MOVE source) is unsupported."""
    name, qualified = _base(ref)
    if qualified:
        return f"subscripted or reference-modified group {name}"
    return group_layout(items, name)[1]


def group_move_problem(items, source: str, target: str) -> str | None:
    """Reason ``MOVE source TO target`` involving a group is unsupported."""
    target_name, target_qualified = _base(target)
    target_item = find_item(items, target_name)
    if target_item is not None and is_group(target_item):
        if target_qualified:
            return f"subscripted or reference-modified group {target_name}"
        layout, problem = group_layout(items, target_name)
        if problem:
            return problem
        if not layout.writable:
            return (
                f"MOVE into group {target_name} needs every subordinate item"
                " to be a named PIC X field"
            )
        if _is_quoted(source) or printable_fill(source, 1) is not None:
            return None
        source_name, source_qualified = _base(source)
        source_item = find_item(items, source_name)
        if source_item is None or source_qualified:
            return f"MOVE source {source} into group {target_name} is not certified"
        if is_group(source_item):
            source_layout, problem = group_layout(items, source_name)
            if problem:
                return problem
            if source_layout.leaf_names & layout.leaf_names:
                return f"MOVE between overlapping groups {source_name} and {target_name}"
            return None
        if (
            source_item.is_alphanumeric
            and source_item.pic_length > 0
            and source_name not in layout.leaf_names
        ):
            return None
        return f"MOVE source {source} into group {target_name} is not certified"
    source_name, _ = _base(source)
    source_item = find_item(items, source_name)
    if source_item is not None and is_group(source_item):
        problem = group_reference_problem(items, source)
        if problem:
            return problem
        if (
            target_item is None
            or target_qualified
            or not target_item.is_alphanumeric
            or target_item.pic_length <= 0
            or target_name in group_layout(items, source_name)[0].leaf_names
        ):
            return f"MOVE of group {source_name} into {target} is not certified"
    return None

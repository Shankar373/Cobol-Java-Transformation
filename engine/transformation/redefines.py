"""REDEFINES overlay analysis and the certified overlay subset.

COBOL ``REDEFINES`` makes two data descriptions share one storage area: a
write through any view is visible through every other view.  The deterministic
Java lane models that with *synchronised fields* plus one canonical byte-string
per certified overlay chain:

* the certified subset: an elementary base that is alphanumeric (``PIC
  X``/``A``) or an unsigned DISPLAY integer (``PIC 9(n)``, whose bytes are
  its digits), redefined by items of the same two kinds or by a group of
  them (leaves at their offsets — ``YYYY``/``MM``/``DD`` over a ``PIC
  9(8)`` date), unsubscripted, written only by ``MOVE`` (Phase 3,
  increment 10; ``tests/test_redefines_digit_views.py``);
* a numeric view holds what the shared bytes say only while they are
  digits.  GnuCOBOL's DISPLAY of a PIC 9 field whose bytes were overwritten
  with non-digits applies an EBCDIC-style overpunch decode (probe:
  ``MOVE "ABCDEF"`` prints ``A CDEF``) — compiler-specific undefined data,
  not a COBOL semantic this lane will fabricate — so the generated Java
  stops (``NumberFormatException``) when a numeric view's bytes are not
  digits after a write;
* signed, scaled or non-DISPLAY numerics, nested groups, OCCURS, chained
  REDEFINES and a redefining item wider than its base are rejected with a
  named problem, so the capability analyzer reports them UNSUPPORTED
  instead of silently generating independent fields.

This module is shared by the parser (which turns ``problems`` into
``UNSUPPORTED_CONSTRUCT`` diagnostics) and the mapper (which lowers the
certified ``views``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from engine.transformation.figurative import figurative_to_width, parse_figurative_constant
from engine.transformation.ir import DataItem


@dataclass(frozen=True)
class RedefinesView:
    """One view over a certified overlay chain."""

    name: str       # COBOL spelling
    base: str       # canonical storage name (COBOL spelling)
    length: int     # view width in bytes
    initial: str    # raw initial bytes, already padded to ``length``
    offset: int = 0       # position in the shared storage
    numeric: bool = False  # unsigned DISPLAY integer (bytes are its digits)

    @property
    def java_name(self) -> str:
        return self.name.replace("-", "_")


@dataclass(frozen=True)
class RedefinesPlan:
    views: dict[str, RedefinesView]   # UPPER name -> view
    problems: dict[str, str]          # UPPER name -> reason
    hidden: frozenset[str] = frozenset()  # UPPER names that must not be declared


def _is_certified_member(item: DataItem) -> str | None:
    """Return a rejection reason when ``item`` is outside the subset."""
    if item.children:
        return f"{item.name} is a group"
    if item.occurs is not None:
        return f"{item.name} has OCCURS"
    if item.usage:
        return f"{item.name} declares USAGE {item.usage}"
    if item.is_numeric and (item.signed or item.decimal_places):
        return (
            f"{item.name} is a signed or scaled numeric; its stored encoding "
            "(sign overpunch, implied point) is not a certified overlay"
        )
    if item.pic_length <= 0:
        return f"{item.name} has no PIC width"
    return None


def _group_members(item: DataItem) -> tuple[list[tuple[DataItem, int]], str | None]:
    """(leaf, offset) of a redefining group, or a rejection reason."""
    members: list[tuple[DataItem, int]] = []
    offset = 0
    for child in item.children:
        if child.is_condition_name:
            continue
        reason = _is_certified_member(child)
        if reason is not None:
            return [], reason
        if child.name.upper() != "FILLER":
            members.append((child, offset))
        offset += child.pic_length
    return members, None


def _initial_bytes(item: DataItem) -> str | None:
    """Initial storage bytes of a base item (``None``: not representable)."""
    if not item.is_numeric:
        return _alphanumeric_initial(item)
    raw = (item.value or "0").strip()
    parsed = parse_figurative_constant(raw)
    if parsed is not None:
        raw = "0"
    if not raw.isdigit():
        return None
    return raw[-item.pic_length:].rjust(item.pic_length, "0")


def _alphanumeric_initial(item: DataItem) -> str:
    """Raw initial bytes of an alphanumeric item, padded to its PIC width."""
    if item.value:
        parsed = parse_figurative_constant(item.value)
        if parsed is not None:
            filled = figurative_to_width(parsed[0], parsed[1], item.pic_length)
            if filled is None:
                return " " * item.pic_length
            return filled[: item.pic_length].ljust(item.pic_length)
        raw = item.value.strip("'\"")
        return raw[: item.pic_length].ljust(item.pic_length)
    return " " * item.pic_length


def build_redefines_plan(items: Sequence[DataItem]) -> RedefinesPlan:
    """Analyse every ``REDEFINES`` clause in a (possibly hierarchical) list."""
    by_name: dict[str, DataItem] = {}

    def visit(nodes) -> None:
        for node in nodes:
            if node.is_condition_name:
                continue
            by_name.setdefault(node.name.upper(), node)
            visit(node.children)

    visit(items)

    views: dict[str, RedefinesView] = {}
    problems: dict[str, str] = {}
    hidden: set[str] = set()

    def hide(item: DataItem) -> None:
        hidden.add(item.name.upper())
        for child in item.children:
            hide(child)

    for key in sorted(by_name):
        item = by_name[key]
        if not item.redefines:
            continue
        base_key = item.redefines.upper()
        base = by_name.get(base_key)
        if base is None:
            problems[key] = (
                f"REDEFINES {item.redefines} on {item.name} does not resolve "
                "to a data item"
            )
            hide(item)
            continue
        reason = None
        members: list[tuple[DataItem, int]] = []
        if base.redefines:
            reason = (
                f"chained REDEFINES on {item.name} (base {base.name} itself "
                "redefines another item)"
            )
        else:
            reason = _is_certified_member(base)
            if reason is None and item.children:
                members, reason = _group_members(item)
            elif reason is None:
                reason = _is_certified_member(item)
                members = [(item, 0)]
        width = sum(c.pic_length for c in item.children if not c.is_condition_name) \
            if item.children else item.pic_length
        if reason is None and width > base.pic_length:
            reason = (
                f"redefining item {item.name} is wider than its base "
                f"{base.name}"
            )
        initial = _initial_bytes(base) if reason is None else None
        if reason is None and initial is None:
            reason = f"base {base.name} has a VALUE that is not its digits"
        if reason is None:
            for member, offset in members:
                text = initial[offset:offset + member.pic_length]
                if member.is_numeric and not text.isdigit():
                    reason = (
                        f"numeric view {member.name} starts on bytes that are "
                        "not digits"
                    )
                    break
        if reason is not None:
            problems[key] = reason
            problems.setdefault(base_key, reason)
            hide(item)
            continue

        views[base_key] = RedefinesView(
            name=base.name,
            base=base.name,
            length=base.pic_length,
            initial=initial,
            numeric=base.is_numeric,
        )
        if item.children:
            # The group itself has no field: its leaves are the views.
            hidden.add(key)
        for member, offset in members:
            views[member.name.upper()] = RedefinesView(
                name=member.name,
                base=base.name,
                length=member.pic_length,
                initial=initial[offset:offset + member.pic_length],
                offset=offset,
                numeric=member.is_numeric,
            )

    # A chain is all-or-nothing: if any view of the same storage is outside
    # the certified subset, the certified-looking siblings must not be kept
    # (their sync would ignore the unsupported view's bytes).
    unsupported_bases = {
        by_name[key].redefines.upper()
        for key, reason in problems.items()
        if key in by_name and by_name[key].redefines
    }
    still_certified: dict[str, RedefinesView] = {}
    for key, view in views.items():
        if view.base.upper() in unsupported_bases:
            problems.setdefault(
                key,
                f"REDEFINES chain of {view.base} contains an uncertified view",
            )
            continue
        still_certified[key] = view
    for key in list(problems):
        item = by_name.get(key)
        if item is not None:
            hide(item)
    views = still_certified

    return RedefinesPlan(
        views=views,
        problems=problems,
        hidden=frozenset(hidden),
    )


def overlay_members(plan: RedefinesPlan) -> Iterable[RedefinesView]:
    """Every certified view, one entry per COBOL name."""
    return plan.views.values()


def write_targets(stmt: object) -> tuple[str, ...]:
    """COBOL names a statement writes, whatever its verb.

    Duck-typed so this module stays free of the statement-class import graph.
    Only MOVE is certified for overlay members; the parser uses this list to
    reject every other writer explicitly.
    """
    name = type(stmt).__name__
    if name == "MoveStatement":
        targets = tuple(getattr(stmt, "targets", ()) or ())
        single = getattr(stmt, "target", "") or ""
        return tuple(t for t in (*targets, single) if t)
    if name == "ComputeStatement":
        return tuple(t for t in (getattr(stmt, "target", ""),) if t)
    if name == "AddStatement":
        giving = getattr(stmt, "giving_target", None)
        if giving:
            return (giving,)
        return tuple(t for t in (getattr(stmt, "target", ""),) if t)
    if name == "SubtractStatement":
        return tuple(
            t for t in (getattr(stmt, "to_field", "") or "",) if t
        )
    if name in ("MultiplyStatement", "DivideStatement"):
        return tuple(t for t in (getattr(stmt, "target", "") or "",) if t)
    if name == "StringStatement":
        return tuple(t for t in (getattr(stmt, "target", "") or "",) if t)
    if name == "UnstringStatement":
        return tuple(getattr(stmt, "targets", ()) or ())
    if name == "ReadStatement":
        return tuple(t for t in (getattr(stmt, "into_field", "") or "",) if t)
    return ()



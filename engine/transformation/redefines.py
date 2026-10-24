"""REDEFINES overlay analysis and the certified overlay subset.

COBOL ``REDEFINES`` makes two data descriptions share one storage area: a
write through any view is visible through every other view.  The deterministic
Java lane models that with *synchronised fields* plus one canonical byte-string
per certified overlay chain:

* the certified subset is elementary alphanumeric (``PIC X``/``A``) DISPLAY
  items over an elementary alphanumeric base, unsubscripted, written only by
  ``MOVE``;
* numeric views are rejected: GnuCOBOL's DISPLAY of a PIC 9 field whose bytes
  were overwritten with non-digits applies an EBCDIC-style overpunch decode
  (probe: ``MOVE "ABCDEF"`` prints ``A CDEF``), which is compiler-specific
  undefined data, not a COBOL semantic this lane will fabricate;
* groups, OCCURS, chained REDEFINES, non-DISPLAY USAGE and a redefining item
  wider than its base are rejected with a named problem, so the capability
  analyzer reports them UNSUPPORTED instead of silently generating
  independent fields.

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
    if item.is_numeric:
        return (
            f"{item.name} is numeric; byte-level numeric/value reinterpretation "
            "is not a certified deterministic lowering"
        )
    if item.pic_length <= 0:
        return f"{item.name} has no PIC width"
    return None


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
        if base.redefines:
            reason = (
                f"chained REDEFINES on {item.name} (base {base.name} itself "
                "redefines another item)"
            )
        else:
            reason = _is_certified_member(base)
            if reason is None:
                reason = _is_certified_member(item)
        if reason is None and item.pic_length > base.pic_length:
            reason = (
                f"redefining item {item.name} is wider than its base "
                f"{base.name}"
            )
        if reason is not None:
            problems[key] = reason
            problems.setdefault(base_key, reason)
            hide(item)
            continue

        initial = _alphanumeric_initial(base)
        views[base_key] = RedefinesView(
            name=base.name,
            base=base.name,
            length=base.pic_length,
            initial=initial,
        )
        views[key] = RedefinesView(
            name=item.name,
            base=base.name,
            length=item.pic_length,
            initial=initial[: item.pic_length],
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



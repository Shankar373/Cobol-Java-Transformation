"""Derive a record layout from the COBOL record description, or refuse by name (ADR-0009).

A migration must not depend on a hand-typed layout.  ``derive_layout`` walks a ``DataItem``
record (``FileDefinition.record_groups``, or a materialised copybook record) and returns
the ordered byte fields the converter needs, with the COBOL path of every field, a stable
identity, and a named diagnostic for everything it cannot size:

* sizes follow the documented storage rules - DISPLAY: digits or characters, ``SIGN SEPARATE``
  adds a byte, an inline sign adds none; COMP-3: digits // 2 + 1; COMP / COMP-5: the explicit
  ``BinaryWidthModel`` (IBM 2/4/8 bytes, GnuCOBOL default 1/2/4/8).  They are
  DOCUMENTED_SEMANTICS evidence: no GnuCOBOL or IBM run in this repository proves a byte layout;
* the binary width model is a required argument with no default;
* ``REDEFINES`` is derived only for the alternative the caller names; without one the layout is
  refused (never the first alternative by declaration order);
* fixed ``OCCURS`` (also nested) is expanded element by element;
* refused by name: ``OCCURS DEPENDING ON``, ``SYNCHRONIZED``, ``COMP-1`` / ``COMP-2``, a
  separate sign on packed or binary items, binary items wider than 18 digits, unknown usages,
  items with no storage, an FD with no record or several (without a choice), and an unusable
  overlay selection.

An unsupported layout can never drive a conversion: ``field_specs`` raises.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from engine.transformation.ir import DataItem, FileDefinition
from engine.vsam.convert import FieldKind, FieldSpec


# Hostile or accidental layouts must be refused by arithmetic, before any field object exists.
MAX_LAYOUT_FIELDS = 100_000  # fields after OCCURS expansion
MAX_DIAGNOSTICS = 200
MAX_RECORD_BYTES = 1_048_576  # far above the 32,760-byte record of a typical VSAM/QSAM data set


class BinaryWidthModel(str, Enum):
    IBM_2_4_8 = "IBM_2_4_8"  # 1-4 digits: 2 bytes, 5-9: 4, 10-18: 8
    GNUCOBOL_1_2_4_8 = "GNUCOBOL_1_2_4_8"  # 1-2 digits: 1 byte, 3-4: 2, 5-9: 4, 10-18: 8


_WIDTHS = {
    BinaryWidthModel.IBM_2_4_8: ((4, 2), (9, 4), (18, 8)),
    BinaryWidthModel.GNUCOBOL_1_2_4_8: ((2, 1), (4, 2), (9, 4), (18, 8)),
}


@dataclass(frozen=True)
class LayoutField:
    path: str  # dotted COBOL path, with (n) subscripts for OCCURS elements
    source: str  # the data item's own name
    level: int
    offset: int
    length: int
    kind: FieldKind
    # COBOL USAGE ("" = DISPLAY).  Kept because it carries byte-order semantics the size does not:
    # COMP is big-endian, COMP-5 is native byte order.  Binary bytes are copied, never reordered.
    usage: str = ""
    # numeric facts the platform conversion needs: signedness, PIC digits (including decimals), decimals
    signed: bool = False
    digits: int = 0
    decimals: int = 0


@dataclass(frozen=True)
class LayoutDiagnostic:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class RecordLayout:
    record_name: str
    record_length: int
    fields: tuple[LayoutField, ...]
    diagnostics: tuple[LayoutDiagnostic, ...]
    binary_width_model: str
    overlay_selection: tuple[tuple[str, str], ...]
    identity: str

    @property
    def supported(self) -> bool:
        return not self.diagnostics

    def field_specs(self) -> tuple[FieldSpec, ...]:
        """The converter's field list; raises if the layout is not fully supported."""
        if self.diagnostics:
            raise ValueError("layout is not supported: " + "; ".join(
                f"{d.code} at {d.path or self.record_name}" for d in self.diagnostics))
        return tuple(FieldSpec(f.path, f.offset, f.length, f.kind) for f in self.fields)

    def to_dict(self) -> dict:
        return {
            "record_name": self.record_name, "record_length": self.record_length,
            "binary_width_model": self.binary_width_model,
            "overlay_selection": [list(pair) for pair in self.overlay_selection],
            "fields": [{"path": f.path, "source": f.source, "level": f.level, "offset": f.offset,
                        "length": f.length, "kind": f.kind.value, "usage": f.usage, "signed": f.signed,
                        "digits": f.digits, "decimals": f.decimals} for f in self.fields],
            "diagnostics": [{"code": d.code, "path": d.path, "message": d.message} for d in self.diagnostics],
            "identity": self.identity,
        }


def _identity(record_name: str, length: int, model: str, selection: tuple[tuple[str, str], ...],
              fields: tuple[LayoutField, ...], diagnostics: tuple[LayoutDiagnostic, ...]) -> str:
    canonical = json.dumps({
        "record": record_name, "length": length, "model": model, "selection": [list(p) for p in selection],
        "fields": [[f.path, f.offset, f.length, f.kind.value, f.usage, f.signed, f.digits, f.decimals]
                   for f in fields],
        "diagnostics": [[d.code, d.path] for d in diagnostics],
    }, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _Deriver:
    def __init__(self, model: BinaryWidthModel, selection: Mapping[str, str]) -> None:
        self.model = model
        self.selection = dict(selection)
        self.used: set[str] = set()
        self.diagnostics: list[LayoutDiagnostic] = []
        self._seen: set[LayoutDiagnostic] = set()

    def diag(self, code: str, path: str, message: str) -> None:
        entry = LayoutDiagnostic(code, path, message)
        if entry in self._seen:  # the sizing passes revisit items; report each problem once
            return
        self._seen.add(entry)
        if len(self.diagnostics) < MAX_DIAGNOSTICS:  # bounded: a hostile record cannot grow the report without limit
            self.diagnostics.append(entry)
        elif len(self.diagnostics) == MAX_DIAGNOSTICS:
            self.diagnostics.append(LayoutDiagnostic(
                "DIAGNOSTICS_TRUNCATED", "", f"more than {MAX_DIAGNOSTICS} problems; the rest are not listed"))

    # -- sizes -------------------------------------------------------------------------------
    def _elementary(self, item: DataItem, path: str) -> tuple[int, FieldKind] | None:
        usage = item.usage
        if item.synchronized:
            self.diag("SYNCHRONIZED", path, "SYNCHRONIZED adds alignment slack that is not modelled")
            return None
        if usage in ("COMP-1", "COMP-2"):
            self.diag("FLOATING_POINT", path, f"{usage} (floating point) has no modelled layout")
            return None
        if usage not in (None, "COMP", "COMP-3", "COMP-5"):
            self.diag("USAGE_UNSUPPORTED", path, f"USAGE {usage} has no modelled layout")
            return None
        if item.pic_length <= 0:
            self.diag("NO_STORAGE", path, "the item has no PIC clause, so its storage size is unknown")
            return None
        if usage is None:
            return item.pic_length + (1 if item.sign_separate else 0), FieldKind.DISPLAY
        if item.sign_separate:
            self.diag("SIGN_SEPARATE_USAGE", path, f"SIGN SEPARATE with USAGE {usage} is not valid storage")
            return None
        if usage == "COMP-3":
            return item.pic_length // 2 + 1, FieldKind.PACKED
        for limit, width in _WIDTHS[self.model]:
            if item.pic_length <= limit:
                return width, FieldKind.BINARY
        self.diag("BINARY_TOO_WIDE", path, f"{item.pic_length} binary digits exceed the 18 the width model covers")
        return None

    def _total(self, item: DataItem, path: str) -> int | None:
        """Storage of the item including its OCCURS repetitions (None after a diagnostic)."""
        if item.occurs_depending_on:
            self.diag("OCCURS_DEPENDING_ON", path,
                      f"OCCURS DEPENDING ON {item.occurs_depending_on}: the length depends on data, not on the record description")
            return None
        element = self._element(item, path, 0, emit=None)
        return None if element is None else element * (item.occurs or 1)

    def _element(self, item: DataItem, path: str, offset: int, emit: list[LayoutField] | None) -> int | None:
        """Size of one occurrence of ``item``; appends its fields to ``emit`` when given."""
        if item.children and (item.usage or item.sign_position or item.sign_separate or item.synchronized):
            clause = item.usage or ("SYNCHRONIZED" if item.synchronized else "SIGN")
            self.diag("SYNCHRONIZED" if clause == "SYNCHRONIZED" else "GROUP_CLAUSE_INHERITED", path,
                      f"{clause} on the group {item.name} would apply to every child; the IR cannot tell a child's own "
                      "DISPLAY from an inherited usage, so the layout is refused")
            return None
        if not item.children:
            sized = self._elementary(item, path)
            if sized is None:
                return None
            length, kind = sized
            if emit is not None:
                numeric = item.pic_type.value == "NUMERIC" and item.edit_pic is None
                emit.append(LayoutField(path, item.name, item.level, offset, length, kind, item.usage or "",
                                        item.signed if numeric else False,
                                        item.pic_length if numeric else 0,
                                        item.decimal_places if numeric else 0))
            return length

        slots: list[dict] = []
        by_name: dict[str, dict] = {}
        cursor = offset
        failed = False
        seen_names: dict[str, int] = {}
        paths: dict[int, str] = {}
        for child in item.children:
            if child.level in (66, 88):
                continue
            seen_names[child.name] = seen_names.get(child.name, 0) + 1
            nth = seen_names[child.name]
            paths[id(child)] = f"{path}.{child.name}" + (f"#{nth}" if nth > 1 else "")  # FILLER, FILLER#2, ...
        for child in item.children:
            if child.level in (66, 88):
                continue
            child_path = paths[id(child)]
            total = self._total(child, child_path)
            if total is None:
                failed = True
                continue
            if child.redefines:
                slot = by_name.get(child.redefines)
                if slot is None:
                    self.diag("REDEFINES_TARGET", child_path, f"REDEFINES {child.redefines}: no such earlier item at this level")
                    failed = True
                    continue
                if total > slot["size"]:
                    self.diag("REDEFINES_LONGER", child_path,
                              f"{child.name} ({total} bytes) is longer than {slot['alts'][0].name} ({slot['size']} bytes)")
                    failed = True
                slot["alts"].append(child)
                by_name.setdefault(child.name, slot)
            else:
                slot = {"start": cursor, "size": total, "alts": [child]}
                slots.append(slot)
                by_name.setdefault(child.name, slot)
                cursor += total
        for slot in slots:
            alts: list[DataItem] = slot["alts"]
            if len(alts) == 1:
                active = alts[0]
            else:
                picked = self._choose(alts, slot, path, paths)
                if picked is None:
                    failed = True
                    continue
                active = picked
            if emit is not None:
                self._place(active, paths[id(active)], slot["start"], emit)
        return None if failed else cursor - offset

    def _choose(self, alts: list[DataItem], slot: dict, path: str, paths: dict[int, str]) -> DataItem | None:
        target = alts[0].name
        names = ", ".join(a.name for a in alts)
        choice = self.selection.get(target)
        if choice is None:
            self.diag("OVERLAY_UNSELECTED", paths[id(alts[0])],
                      f"{target} is redefined (alternatives: {names}); name the active one - the first is never assumed")
            return None
        self.used.add(target)
        chosen = next((a for a in alts if a.name == choice), None)
        if chosen is None:
            self.diag("OVERLAY_SELECTION_INVALID", paths[id(alts[0])],
                      f"{choice} is not one of the alternatives for {target} ({names})")
            return None
        size = self._total(chosen, paths[id(chosen)])
        if size is not None and size < slot["size"]:
            self.diag("OVERLAY_PARTIAL_COVER", paths[id(chosen)],
                      f"{chosen.name} covers {size} of the {slot['size']} redefined bytes; the rest would be untranslated")
            return None
        return chosen

    def _place(self, item: DataItem, path: str, offset: int, emit: list[LayoutField]) -> None:
        count = item.occurs or 1
        element = self._element(item, path, 0, emit=None)
        if element is None:
            return
        for index in range(1, count + 1):
            element_path = f"{path}({index})" if item.occurs else path
            self._element(item, element_path, offset + (index - 1) * element, emit)


def _field_count(item: DataItem, cap: int) -> int:
    """Upper bound of the fields ``item`` expands to, stopping early above ``cap`` (no field is created)."""
    repeat = item.occurs or 1
    if not item.children:
        return min(repeat, cap)
    inner = 0
    for child in item.children:
        if child.level in (66, 88):
            continue
        inner += _field_count(child, cap)
        if inner > cap:
            return cap + 1
    return min(inner * repeat, cap + 1) if inner else 0


def derive_layout(record: DataItem, *, binary_width_model: BinaryWidthModel,
                  overlay_selection: Mapping[str, str] | None = None) -> RecordLayout:
    """Derive the byte layout of one 01 record (``binary_width_model`` is required)."""
    model = BinaryWidthModel(binary_width_model)
    selection = dict(overlay_selection or {})
    deriver = _Deriver(model, selection)
    fields: list[LayoutField] = []
    total = deriver._total(record, record.name)
    if total is not None and _field_count(record, MAX_LAYOUT_FIELDS + 1) > MAX_LAYOUT_FIELDS:
        deriver.diag("OCCURS_TOO_LARGE", record.name,
                     f"OCCURS expansion would create more than {MAX_LAYOUT_FIELDS} fields; refused before expansion")
        total = None
    if total is not None and total > MAX_RECORD_BYTES:
        deriver.diag("RECORD_TOO_LARGE", record.name,
                     f"the record is {total} bytes, above the {MAX_RECORD_BYTES}-byte limit")
        total = None
    if total is not None:
        deriver._place(record, record.name, 0, fields)
    for target in sorted(set(selection) - deriver.used):
        deriver.diag("OVERLAY_SELECTION_INVALID", record.name,
                     f"{target} is not a redefined item of {record.name}; a selection for it has no effect")
    diagnostics = tuple(deriver.diagnostics)
    ordered = tuple(sorted(fields, key=lambda f: (f.offset, f.path)))
    pairs = tuple(sorted(selection.items()))
    length = total or 0
    return RecordLayout(record.name, length, ordered, diagnostics, model.value, pairs,
                        _identity(record.name, length, model.value, pairs, ordered, diagnostics))


def _refused(record_name: str, model: BinaryWidthModel, selection: Mapping[str, str],
             diagnostic: LayoutDiagnostic) -> RecordLayout:
    pairs = tuple(sorted((selection or {}).items()))
    return RecordLayout(record_name, 0, (), (diagnostic,), model.value, pairs,
                        _identity(record_name, 0, model.value, pairs, (), (diagnostic,)))


def derive_file_layout(file_definition: FileDefinition, *, binary_width_model: BinaryWidthModel,
                       overlay_selection: Mapping[str, str] | None = None,
                       record_name: str = "") -> RecordLayout:
    """Derive the layout of one record of an FD; several records require ``record_name``."""
    model = BinaryWidthModel(binary_width_model)
    selection = overlay_selection or {}
    groups = file_definition.record_groups
    fd = file_definition.name
    if not groups:
        return _refused(fd, model, selection, LayoutDiagnostic(
            "FD_NO_RECORD", fd,
            f"FD {fd} declares no record (an unresolved COPY inside the FD leaves it without one; "
            "resolve the copybook so discovery can expand it)"))
    names = ", ".join(g.name for g in groups)
    if len(groups) > 1 and not record_name:
        return _refused(fd, model, selection, LayoutDiagnostic(
            "RECORD_AMBIGUOUS", fd,
            f"FD {fd} has several records ({names}) sharing one area; name the one to convert - the first is never assumed"))
    chosen = next((g for g in groups if g.name == record_name), None) if record_name else groups[0]
    if chosen is None:
        return _refused(fd, model, selection, LayoutDiagnostic(
            "RECORD_UNKNOWN", fd, f"FD {fd} has no record {record_name} (records: {names})"))
    return derive_layout(chosen, binary_width_model=model, overlay_selection=selection)

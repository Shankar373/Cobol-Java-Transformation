"""Which file records may carry COMP / COMP-3 leaves, and how each leaf is laid out in the record bytes.

Certified (roadmap unit 28, proven against GnuCOBOL 3.1.2 in ``tests/integration/test_binary_record_oracle.py``):

* the file is RECORD SEQUENTIAL or INDEXED (a LINE SEQUENTIAL file cannot carry binary bytes; RELATIVE is not covered);
* the FD has one record description whose leaves are all named, none with OCCURS or REDEFINES, and each leaf is
  alphanumeric DISPLAY, unsigned unscaled numeric DISPLAY, or COMP / COMP-3 of at most 18 digits (signed, unsigned or
  with an implied decimal point); COMP-5, COMP-1, COMP-2 and FILLER are refused;
* an INDEXED file's RECORD KEY is a DISPLAY leaf.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.transformation.ir import DataItem, FileDefinition, FileOrganization

BINARY_USAGES = frozenset({"COMP", "COMP-3"})


@dataclass(frozen=True)
class LeafEncoding:
    kind: str  # "packed" | "binary"
    digits: int
    scale: int
    signed: bool
    width: int  # bytes in the record


def leaf_encoding(item: DataItem) -> LeafEncoding | None:
    """Byte layout of a COMP / COMP-3 numeric leaf, or None for any other leaf."""
    if item.usage not in BINARY_USAGES or not item.is_numeric:
        return None
    digits = item.pic_length
    if item.usage == "COMP-3":
        return LeafEncoding("packed", digits, item.decimal_places, item.signed, digits // 2 + 1)
    width = 1 if digits <= 2 else 2 if digits <= 4 else 4 if digits <= 9 else 8
    return LeafEncoding("binary", digits, item.decimal_places, item.signed, width)


def has_binary_leaves(fd: FileDefinition | None) -> bool:
    return fd is not None and any(leaf_encoding(i) is not None for i in fd.record_items)


def record_problem(fd: FileDefinition) -> str:
    """Why this FD's record cannot carry binary leaves ("" when it can); only meaningful when it has some."""
    if fd.organization is FileOrganization.SEQUENTIAL and not fd.record_sequential:
        return "a LINE SEQUENTIAL file cannot carry binary (packed or COMP) bytes"
    if fd.organization not in (FileOrganization.SEQUENTIAL, FileOrganization.INDEXED):
        return "only RECORD SEQUENTIAL and INDEXED files are certified for binary records"
    if len(fd.record_groups) != 1:
        return "several (or no) record descriptions make records variable-length"
    # the flat ``record_items`` list carries no REDEFINES / OCCURS: walk the full record tree for them
    def walk(node):
        yield node
        for child in node.children:
            yield from walk(child)

    for node in walk(fd.record_groups[0]):
        if node.redefines is not None or node.occurs is not None:
            return f"{node.name} has OCCURS or REDEFINES"
        if node.name is None or node.name.upper() == "FILLER":
            return "FILLER leaves are not certified in a binary record"
    for item in fd.record_items:
        if item.is_condition_name or item.is_group:
            continue
        if item.usage in BINARY_USAGES:
            if not item.is_numeric or item.pic_length > 18 or item.pic_length <= 0:
                return f"leaf {item.name} ({item.usage}) is not a numeric field of 1 to 18 digits"
        elif item.usage not in (None, "", "DISPLAY"):
            return f"leaf {item.name} has USAGE {item.usage}, which is not certified in a binary record"
        elif item.is_numeric and (item.signed or item.decimal_places):
            return f"DISPLAY numeric leaf {item.name} is signed or scaled"
    if fd.organization is FileOrganization.INDEXED and fd.record_key is not None:
        key = next((i for i in fd.record_items if i.name == fd.record_key.field_name), None)
        if key is not None and key.usage in BINARY_USAGES:
            return "a binary RECORD KEY is not certified"
    return ""


def certified_binary_record(fd: FileDefinition | None) -> bool:
    """The FD has binary leaves and sits inside the certified subset."""
    return fd is not None and has_binary_leaves(fd) and not record_problem(fd)

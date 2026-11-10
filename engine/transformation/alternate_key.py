"""ALTERNATE RECORD KEY on INDEXED files (roadmap unit 30): which programs are inside the certified subset.

Certified, proven against GnuCOBOL 3.1.2 in ``tests/integration/test_alternate_key_oracle.py``:

* an INDEXED file with ACCESS MODE DYNAMIC or RANDOM and a FILE STATUS clause, at most three alternate keys, each a
  DISPLAY leaf of the record (WITH DUPLICATES or not) that is not the primary key;
* WRITE (status 02 for a duplicate of a WITH DUPLICATES key, 22 for a duplicate of a unique one), REWRITE, DELETE and
  ``READ ... KEY IS <primary or alternate key>`` (the first duplicate, in write order);
* refused by name: other access modes, no FILE STATUS, binary (COMP / COMP-3) records, a key that is not a leaf, a
  numeric alternate key, ``READ ... KEY IS`` naming a field that is not a record key, and **any START or READ NEXT on
  the file**. Browsing along an alternate key is implemented in ``CobolFileIo`` but not certified: a wider differential
  sweep (150 programs) found about 5% whose READ NEXT after a *failed* keyed READ or START lands on a different record
  or status (46 versus 10) than GnuCOBOL, because the position state of its per-key cursors is not fully reproduced.
"""

from __future__ import annotations

from engine.transformation.control_flow import walk_statements
from engine.transformation.ir import (
    FileAccessMode,
    FileDefinition,
    FileOrganization,
    ReadStatement,
    StartStatement,
)

MAX_ALTERNATE_KEYS = 3

#: Browsing (START / READ NEXT) is refused until its differential sweep is clean; the sweep lifts this switch.
BROWSING_GATE_ENABLED = True


def alternate_key_names(fd: FileDefinition) -> list[str]:
    return [key.field_name.upper() for key in fd.alternate_keys]


def alternate_ordinal(fd: FileDefinition, name: str) -> int:
    """1-based ordinal of the alternate key named ``name`` (0 when it is not an alternate key)."""
    wanted = (name or "").strip().upper()
    names = alternate_key_names(fd)
    return names.index(wanted) + 1 if wanted in names else 0


def alternate_key_problem(program: object, fd: FileDefinition) -> str:
    """Why this file's alternate keys are outside the certified subset ("" when inside it or when there are none)."""
    from engine.transformation.binary_record import has_binary_leaves

    if not fd.alternate_keys:
        return ""
    if fd.organization is not FileOrganization.INDEXED:
        return "ALTERNATE RECORD KEY on a file that is not INDEXED"
    if fd.access_mode not in (FileAccessMode.DYNAMIC, FileAccessMode.RANDOM):
        return "ALTERNATE RECORD KEY is certified only with ACCESS MODE DYNAMIC or RANDOM"
    if not fd.file_status_field:
        return "no FILE STATUS clause (the duplicate-key statuses 02 and 22 are observed through it)"
    if len(fd.alternate_keys) > MAX_ALTERNATE_KEYS:
        return f"more than {MAX_ALTERNATE_KEYS} alternate keys"
    if has_binary_leaves(fd):
        return "alternate keys are not certified in a record with COMP / COMP-3 leaves"
    leaves = [i for i in fd.record_items if not i.is_condition_name and not i.is_group]
    names = alternate_key_names(fd)
    if len(set(names)) != len(names):
        return "the same alternate key is declared twice"
    primary = fd.record_key.field_name.upper() if fd.record_key is not None else ""
    for name in names:
        leaf = next((i for i in leaves if (i.name or "").upper() == name), None)
        if leaf is None:
            return f"alternate key {name} is not a single elementary field of the record"
        if name == primary:
            return f"alternate key {name} is also the primary key"
        if leaf.usage not in (None, "", "DISPLAY"):
            return f"alternate key {name} has USAGE {leaf.usage}"
        if leaf.is_numeric:
            return f"alternate key {name} is numeric (only alphanumeric alternate keys are certified)"
    keys = {primary, *names}
    for paragraph in getattr(program, "paragraphs", ()):
        for stmt in walk_statements(paragraph.statements):
            if not isinstance(stmt, (ReadStatement, StartStatement)) or stmt.file_name != fd.name:
                continue
            if BROWSING_GATE_ENABLED and isinstance(stmt, StartStatement):
                return "START on a file with alternate keys is not certified (browsing along a key)"
            if BROWSING_GATE_ENABLED and stmt.read_next:
                return "READ NEXT on a file with alternate keys is not certified (browsing along a key)"
            key = (stmt.key or "").strip().upper()
            if key and key not in keys:
                return f"READ ... KEY IS {key} is not a record key"
    return ""

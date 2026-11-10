"""ALTERNATE RECORD KEY on INDEXED files (roadmap unit 30): which programs are inside the certified subset.

Certified, proven against GnuCOBOL 3.1.2 in ``tests/integration/test_alternate_key_oracle.py``:

* an INDEXED file with ACCESS MODE DYNAMIC or RANDOM and a FILE STATUS clause, at most three alternate keys, each a
  DISPLAY leaf of the record (WITH DUPLICATES or not) that is not the primary key;
* WRITE (status 02 for a duplicate of a WITH DUPLICATES key, 22 for a duplicate of a unique one), REWRITE, DELETE and
  ``READ ... KEY IS <primary or alternate key>`` (the first duplicate, in write order);
* browsing (START, READ NEXT) in the shape ``tests/integration/test_alternate_key_browse_oracle.py`` sweeps against
  GnuCOBOL 3.1.2 (18 seeds, 450 programs, 0 mismatches): ACCESS MODE DYNAMIC, exactly two alternate keys (one WITH
  DUPLICATES, one unique), every field of the record ``PIC X(2)``, FILE STATUS only (no AT END / INVALID KEY phrases, no
  READ INTO), files opened OUTPUT or I-O, START with ``= > >=`` on an alternate key and ``= > >= <`` on the primary key;
* refused by name: other access modes, no FILE STATUS, binary (COMP / COMP-3) records, a key that is not a leaf, a
  numeric alternate key, ``READ ... KEY IS`` naming a field that is not a record key, and every browsing program outside
  the shape above (the reason names what differs). Browsing was first refused after a 150-program sweep found about 5%
  of programs whose READ NEXT after a *failed* keyed READ or START landed on a different record or status than
  GnuCOBOL; the position rules the sweeps established are pinned in ``tests/integration``.
"""

from __future__ import annotations

from engine.transformation.control_flow import walk_statements
from engine.transformation.ir import (
    FileAccessMode,
    FileDefinition,
    FileOrganization,
    OpenStatement,
    ReadStatement,
    StartStatement,
)

MAX_ALTERNATE_KEYS = 3

#: START operators the browsing sweep covers, per key kind; any other operator is refused.
PROVEN_START_ON_ALTERNATE = ("=", ">", ">=")
PROVEN_START_ON_PRIMARY = ("=", ">", ">=", "<")
PROVEN_KEY_WIDTH = 2


def alternate_key_names(fd: FileDefinition) -> list[str]:
    return [key.field_name.upper() for key in fd.alternate_keys]


def alternate_ordinal(fd: FileDefinition, name: str) -> int:
    """1-based ordinal of the alternate key named ``name`` (0 when it is not an alternate key)."""
    wanted = (name or "").strip().upper()
    names = alternate_key_names(fd)
    return names.index(wanted) + 1 if wanted in names else 0


def _browsing_shape_problem(fd: FileDefinition, leaves: list, statements: list) -> str:
    """Why browsing (START / READ NEXT) on this file is outside the shape the sweep proved ("" when inside it)."""
    if fd.access_mode is not FileAccessMode.DYNAMIC:
        return "browsing along a key is certified only with ACCESS MODE DYNAMIC"
    if len(fd.alternate_keys) != 2 or sorted(k.is_duplicated for k in fd.alternate_keys) != [False, True]:
        return "browsing is certified only with exactly two alternate keys, one WITH DUPLICATES and one unique"
    if not 3 <= len(leaves) <= 4 or any(not (i.is_alphanumeric and i.pic_length == PROVEN_KEY_WIDTH) for i in leaves):
        return f"browsing is certified only for records of three or four PIC X({PROVEN_KEY_WIDTH}) fields"
    for stmt in statements:
        if isinstance(stmt, OpenStatement):
            if stmt.mode.upper() not in ("OUTPUT", "I-O"):
                return f"browsing is certified only for files opened OUTPUT or I-O, not {stmt.mode.upper()}"
        elif isinstance(stmt, ReadStatement):
            if stmt.at_end_body or stmt.not_at_end_body or stmt.invalid_key_body or stmt.not_invalid_key_body:
                return "browsing is certified with FILE STATUS only: AT END / INVALID KEY phrases are not"
            if stmt.into_field:
                return "browsing is certified without READ ... INTO"
        elif stmt.invalid_key_body or stmt.not_invalid_key_body:
            return "browsing is certified with FILE STATUS only: INVALID KEY phrases on START are not"
    return ""


def _start_problem(stmt: StartStatement, primary: str, alternate_names: list[str]) -> str:
    key = (stmt.key or "").strip().upper()
    operator = (stmt.operator or "=").strip()
    proven: tuple[str, ...]
    if key in alternate_names:
        proven = PROVEN_START_ON_ALTERNATE
    elif key == primary:
        proven = PROVEN_START_ON_PRIMARY
    else:
        return f"START KEY {key} is not a record key"
    if operator not in proven:
        return f"START ... KEY {operator} {key} is not certified (proven: {', '.join(proven)})"
    return ""


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
    statements = [
        stmt
        for paragraph in getattr(program, "paragraphs", ())
        for stmt in walk_statements(paragraph.statements)
        if isinstance(stmt, (ReadStatement, StartStatement, OpenStatement)) and stmt.file_name == fd.name
    ]
    browses = any(
        isinstance(stmt, StartStatement) or (isinstance(stmt, ReadStatement) and stmt.read_next)
        for stmt in statements
    )
    if browses:
        problem = _browsing_shape_problem(fd, leaves, statements)
        if problem:
            return problem
    for stmt in statements:
        if isinstance(stmt, OpenStatement):
            continue
        if isinstance(stmt, StartStatement):
            problem = _start_problem(stmt, primary, names)
            if problem:
                return problem
        key = (stmt.key or "").strip().upper()
        if key and key not in keys:
            return f"READ ... KEY IS {key} is not a record key"
    return ""

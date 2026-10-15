"""BL-058: WORKING-STORAGE group hierarchy must be preserved in the IR.

Defect proven first (Master README §76): these assertions fail against the
pre-fix parser (evidence: %TEMP%\\opencode\\phase7\\bl058_pre_fix.txt).

Agreed representation (design call recorded with BL-058):
- WORKING-STORAGE parses through the shared hierarchical data-description
  parser — same shape as LINKAGE/COPYBOOK: top level holds the declared
  roots (true COBOL level numbers, group nodes keep their ``children``).
- Elementary children stay declarable as top-level items (field generation
  and name lookups read the flat expansion, mirroring
  ``materialize_copybooks_into_program``).
- 88-level condition names are captured under their parent item in the IR
  but are not promoted to declarations (they are not storage).
- ``REDEFINES`` is captured on the ``DataItem``.
"""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser


def _parse(ws_lines: str):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. BL058.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{ws_lines}"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )
    return CobolParser().parse(source)


def _find(items, name):
    """Depth-first search over an IR subtree (top level + descendants)."""
    for item in items:
        if item.name == name:
            return item
        found = _find(item.children, name)
        if found is not None:
            return found
    return None


def _top_names(program) -> set[str]:
    return {item.name for item in program.working_storage}


def test_two_level_group_root_is_parsed_with_children_from_working_storage():
    program = _parse(
        "       01  WS-GRP.\n"
        "           05  WS-GRP-A PIC X(4).\n"
        "           05  WS-GRP-B PIC 9(3).\n"
    )
    root = _find(program.working_storage, "WS-GRP")
    assert root is not None, "group root must survive WORKING-STORAGE parsing"
    assert root.is_group, "WS-GRP must be a group node holding its children"
    assert [child.name for child in root.children] == ["WS-GRP-A", "WS-GRP-B"]


def test_group_children_keep_their_declared_level_numbers():
    program = _parse(
        "       01  WS-GRP.\n"
        "           05  WS-GRP-A PIC X(4).\n"
        "           05  WS-GRP-B PIC 9(3).\n"
    )
    root = _find(program.working_storage, "WS-GRP")
    assert root is not None
    assert [child.level for child in root.children] == [5, 5]


def test_elementary_group_children_remain_declarable_top_level_items():
    # Field generation and name lookups read the top-level list directly;
    # the children of a group must stay reachable there after the fix.
    program = _parse(
        "       01  WS-GRP.\n"
        "           05  WS-GRP-A PIC X(4).\n"
        "           05  WS-GRP-B PIC 9(3).\n"
    )
    names = _top_names(program)
    assert {"WS-GRP-A", "WS-GRP-B"} <= names


def test_occurs_group_children_at_level_10_are_preserved_and_declarable():
    program = _parse(
        "       01  WS-TBL.\n"
        "           05  WS-TBL-ENT OCCURS 3.\n"
        "               10  WS-TBL-CODE PIC 9(2).\n"
        "               10  WS-TBL-NAME PIC X(6).\n"
    )
    root = _find(program.working_storage, "WS-TBL")
    assert root is not None, "table group root must be preserved"
    entry = _find(root.children, "WS-TBL-ENT")
    assert entry is not None, "OCCURS group must be nested under its owner"
    assert entry.occurs == 3
    assert [child.name for child in entry.children] == ["WS-TBL-CODE", "WS-TBL-NAME"]
    assert [child.level for child in entry.children] == [10, 10]
    assert {"WS-TBL-ENT", "WS-TBL-CODE", "WS-TBL-NAME"} <= _top_names(program)


def test_condition_name_88_level_is_captured_under_its_parent():
    program = _parse(
        "       01  WS-FLAG PIC X.\n"
        "           88  WS-FLAG-SET VALUE 'Y'.\n"
    )
    flag = _find(program.working_storage, "WS-FLAG")
    assert flag is not None
    cond = _find(flag.children, "WS-FLAG-SET")
    assert cond is not None, "88-level condition name must be in the IR"
    assert cond.is_condition_name
    assert cond.value == "'Y'"


def test_condition_name_88_level_is_not_promoted_to_declarations():
    # Condition names are not storage: today they never reach declarations,
    # and the fix must keep them nested instead of emitting a Java field.
    program = _parse(
        "       01  WS-FLAG PIC X.\n"
        "           88  WS-FLAG-SET VALUE 'Y'.\n"
    )
    assert "WS-FLAG-SET" not in _top_names(program)


def test_working_storage_redefines_is_captured_on_the_data_item():
    program = _parse(
        "       01  WS-GRP.\n"
        "           05  WS-A PIC X(4).\n"
        "           05  WS-B REDEFINES WS-A PIC 9(4).\n"
    )
    overlay = _find(program.working_storage, "WS-B")
    assert overlay is not None, "REDEFINES item must be parsed"
    assert overlay.redefines == "WS-A"

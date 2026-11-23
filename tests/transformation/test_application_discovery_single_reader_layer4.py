"""Layer 4: application discovery reads COBOL only through the single reader.

A PROGRAM-ID / CALL / COPY / ENTRY / file verb that sits in a comment line, a debug ``D`` line, a dead
``>>IF`` branch or a free-format ``*>`` tail is not program text, so discovery must not report it.
"""

from __future__ import annotations

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery

_FIXED_HEAD = "       IDENTIFICATION DIVISION.\n"
_ONLY_NON_CODE = {
    "comment line": _FIXED_HEAD + "      * PROGRAM-ID. GHOST.\n",
    "debug line": _FIXED_HEAD + "      DPROGRAM-ID. GHOST.\n",
    "dead branch": _FIXED_HEAD + "       >>DEFINE ON AS 1\n       >>IF ON = 0\n       PROGRAM-ID. GHOST.\n       >>END-IF\n",
    "free tail": ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION. *> PROGRAM-ID. GHOST.\n",
}


@pytest.mark.parametrize("name", sorted(_ONLY_NON_CODE))
def test_a_program_id_outside_program_text_is_not_a_program(name):
    assert ApplicationDiscovery._extract_program_id_from_source(_ONLY_NON_CODE[name]) == ""


def test_a_live_program_id_after_non_code_ones_is_the_one_found():
    source = (_FIXED_HEAD + "      * PROGRAM-ID. COMMENTED.\n      DPROGRAM-ID. DEBUGGED.\n"
              "       >>DEFINE ON AS 1\n       >>IF ON = 0\n       PROGRAM-ID. DEAD.\n       >>END-IF\n"
              "       PROGRAM-ID. LIVE.\n")
    assert ApplicationDiscovery._extract_program_id_from_source(source) == "LIVE"


def test_a_plain_fixed_format_program_id_is_found():
    assert ApplicationDiscovery._extract_program_id_from_source(_FIXED_HEAD + "       PROGRAM-ID. REAL1.\n") == "REAL1"


_NOISE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HOST.
       ENVIRONMENT DIVISION.
       PROCEDURE DIVISION.
      * CALL 'CMTCALL'.  COPY CMTCOPY.  ENTRY 'CMTENTRY'.  OPEN INPUT CMTFILE.
      DCALL 'DBGCALL'.
      DCOPY DBGCOPY.
      DENTRY 'DBGENTRY'.
      DOPEN INPUT DBGFILE.
       >>DEFINE ON AS 1
       >>IF ON = 0
           CALL 'DEADCALL'.
           COPY DEADCOPY.
           ENTRY 'DEADENTRY'.
           OPEN INPUT DEADFILE.
       >>END-IF
           CALL 'LIVECALL'.
           ENTRY 'LIVEENTRY'.
           GOBACK.
"""

_FREE_NOISE = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. HOST.
PROCEDURE DIVISION.
    GOBACK. *> CALL 'TAILCALL'. COPY TAILCOPY. ENTRY 'TAILENTRY'. OPEN INPUT TAILFILE.
"""


def test_calls_and_entries_exclude_comment_debug_dead_and_tail_text():
    d = ApplicationDiscovery()
    assert [c.target for c in d._extract_calls(_NOISE, "HOST")] == ["LIVECALL"]
    assert d._extract_entry_points(_NOISE) == ["LIVEENTRY"]
    assert d._extract_calls(_FREE_NOISE, "HOST") == []
    assert d._extract_entry_points(_FREE_NOISE) == []


def test_copybooks_exclude_comment_debug_dead_and_tail_text():
    d = ApplicationDiscovery()
    assert d._extract_copybooks(_NOISE, "HOST") == []
    assert d._extract_copybooks(_FREE_NOISE, "HOST") == []


def test_file_verbs_exclude_comment_debug_dead_and_tail_text():
    d = ApplicationDiscovery()
    assert d._extract_file_dependencies(_NOISE, "HOST") == []
    assert d._extract_file_dependencies(_FREE_NOISE, "HOST") == []
    live = _NOISE.replace("           GOBACK.", "           OPEN INPUT LIVEFILE.\n           GOBACK.")
    assert [(f.file_name, f.operation) for f in d._extract_file_dependencies(live, "HOST")] == [("LIVEFILE", "OPEN")]

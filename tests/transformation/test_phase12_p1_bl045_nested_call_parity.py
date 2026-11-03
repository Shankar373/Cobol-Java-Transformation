"""Phase 12 P1 — BL-045: nested CALL parity with the equivalent top-level CALL.

A CALL inside IF or any inline PERFORM body must map exactly like the same
CALL at top level:

* value-result (BY REFERENCE sync-in / sync-out through the callee LINKAGE)
  must be emitted for nested calls, and
* paragraph-entry resolution (callee without LINKAGE -> first paragraph as
  the Java entry method) must match the top-level resolution.

The expected side of every parity assertion is derived by mapping the very
same CALL statement through the top-level path with ``called_programs``
threaded — not from hardcoded expected output strings.
"""

from __future__ import annotations

import dataclasses

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_statement
from engine.transformation.java_ir import (
    JavaAssignment,
    JavaBlock,
    JavaFor,
    JavaIf,
    JavaMethodCallStatement,
    JavaWhile,
)

INNER_LINKAGE_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INLINK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  W-WS        PIC X(4).
       LINKAGE SECTION.
       01  L-ARG       PIC X(4).
       PROCEDURE DIVISION USING L-ARG.
       MAIN-LOGIC.
           MOVE L-ARG TO W-WS
           GOBACK.
"""

INNER_PARAGRAPH_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INPARA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  W-WS        PIC X(4).
       PROCEDURE DIVISION.
       100-INIT.
           MOVE 'X' TO W-WS
           GOBACK.
"""

CALLER_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {pid}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  W-A         PIC X(4).
       01  W-FLAG      PIC 9.
       01  W-I         PIC 9(4).
       PROCEDURE DIVISION.
"""

# Equivalent callers: the top-level form and each nested wrapper form call
# the same callee with the same argument from the same data items.
_TOP_LINKAGE = CALLER_HEADER.format(pid="TOP01") + """\
           CALL 'INLINK' USING W-A.
           STOP RUN.
"""
_TOP_PARA = CALLER_HEADER.format(pid="TOP02") + """\
           CALL 'INPARA'.
           STOP RUN.
"""
_IF_LINKAGE = CALLER_HEADER.format(pid="IF01") + """\
           IF W-FLAG = 1
               CALL 'INLINK' USING W-A.
           END-IF
           STOP RUN.
"""
_IF_PARA = CALLER_HEADER.format(pid="IF02") + """\
           IF W-FLAG = 1
               CALL 'INPARA'.
           END-IF
           STOP RUN.
"""
_VARYING = CALLER_HEADER.format(pid="PV01") + """\
           PERFORM VARYING W-I FROM 1 BY 1 UNTIL W-I > 5
               CALL 'INLINK' USING W-A.
           END-PERFORM
           STOP RUN.
"""
_TIMES = CALLER_HEADER.format(pid="PT01") + """\
           PERFORM 3 TIMES
               CALL 'INLINK' USING W-A.
           END-PERFORM
           STOP RUN.
"""
_UNTIL = CALLER_HEADER.format(pid="PU01") + """\
           PERFORM UNTIL W-FLAG > 5
               CALL 'INLINK' USING W-A.
           END-PERFORM
           STOP RUN.
"""

_parser = CobolParser()
_CMAP = {
    "INLINK": _parser.parse(INNER_LINKAGE_SRC),
    "INPARA": _parser.parse(INNER_PARAGRAPH_SRC),
}


def _stmts_of(program):
    out = []
    for para in program.paragraphs:
        out.extend(getattr(para, "statements", ()) or ())
    return out


def _flatten(stmts):
    """Collapse wrapper statements (If/For/While/Block) to their leaf bodies."""
    out = []
    for s in stmts:
        if isinstance(s, JavaIf):
            out.extend(_flatten(s.then_body))
            out.extend(_flatten(s.else_body))
        elif isinstance(s, JavaFor):
            out.extend(_flatten(s.body))
        elif isinstance(s, JavaWhile):
            out.extend(_flatten(s.body))
        elif isinstance(s, JavaBlock):
            out.extend(_flatten(s.statements))
        else:
            out.append(s)
    return out


def _find(program, type_name: str):
    for s in _stmts_of(program):
        if type(s).__name__ == type_name:
            return s
    raise AssertionError(f"no {type_name} in parsed program {program.program_id}")


def _top_level_call(source: str):
    """Map the top-level CALL of ``source`` with called_programs threaded."""
    program = _parser.parse(source)
    for s in _stmts_of(program):
        if type(s).__name__ == "CallStatement":
            return map_cobol_statement(s, program, _CMAP)
    raise AssertionError("no top-level CallStatement found")


def _nested_call_leaves(source: str, wrapper_type: str):
    program = _parser.parse(source)
    wrapper = _find(program, wrapper_type)
    assert dataclasses.is_dataclass(type(wrapper)), "wrapper must be a dataclass"
    mapped = map_cobol_statement(wrapper, program, _CMAP)
    return _flatten(mapped)


def _assert_parity(nested_source: str, wrapper_type: str, top_source: str):
    nested = _nested_call_leaves(nested_source, wrapper_type)
    expected = _top_level_call(top_source)
    assert nested, "nested mapping produced no statements"
    assert nested == expected, (
        "BL-045: nested CALL mapping diverges from the equivalent top-level "
        "CALL mapping.\n"
        f"  nested: {nested!r}\n"
        f"  top   : {expected!r}"
    )


def _call_statements(stmts):
    return [s for s in stmts if isinstance(s, JavaMethodCallStatement)]


def _sync_assignments(stmts):
    return [s for s in stmts if isinstance(s, JavaAssignment)]


class TestBL045NestedCallParity:
    def test_if_body_value_result_matches_top_level(self):
        """CALL inside IF must emit the same value-result sync as top level."""
        _assert_parity(_IF_LINKAGE, "IfStatement", _TOP_LINKAGE)

    def test_if_body_paragraph_entry_matches_top_level(self):
        """CALL inside IF must resolve the callee's entry paragraph."""
        _assert_parity(_IF_PARA, "IfStatement", _TOP_PARA)

    def test_perform_varying_inline_value_result_matches_top_level(self):
        _assert_parity(_VARYING, "PerformStatement", _TOP_LINKAGE)

    def test_perform_times_inline_value_result_matches_top_level(self):
        _assert_parity(_TIMES, "PerformStatement", _TOP_LINKAGE)

    def test_perform_until_inline_value_result_matches_top_level(self):
        _assert_parity(_UNTIL, "PerformStatement", _TOP_LINKAGE)

    def test_nested_linkage_call_emits_sync_out_to_caller_field(self):
        """BY REFERENCE write-back must exist for a nested CALL (BL-045 core)."""
        nested = _nested_call_leaves(_IF_LINKAGE, "IfStatement")
        targets = [a.target for a in _sync_assignments(nested)]
        assert any(t.endswith("L_ARG") for t in targets), (
            "BL-045: nested CALL lost the value-result sync-in to the callee "
            f"LINKAGE field; sync targets seen: {targets}"
        )
        assert any(t == "W_A" for t in targets), (
            "BL-045: nested CALL lost the BY REFERENCE sync-out back to the "
            f"caller field; sync targets seen: {targets}"
        )

    def test_nested_paragraph_entry_does_not_fall_back_to_main_logic(self):
        """A callee without LINKAGE must not silently become MAIN_LOGIC."""
        nested = _nested_call_leaves(_IF_PARA, "IfStatement")
        nested_calls = _call_statements(nested)
        assert len(nested_calls) == 1
        top_calls = _call_statements(_top_level_call(_TOP_PARA))
        assert len(top_calls) == 1
        assert nested_calls[0].call.method_name == top_calls[0].call.method_name, (
            "BL-045: nested CALL entry method "
            f"{nested_calls[0].call.method_name!r} != top-level "
            f"{top_calls[0].call.method_name!r}"
        )
        assert nested_calls[0].call.method_name != "MAIN_LOGIC", (
            "BL-045: nested CALL fell back to MAIN_LOGIC although the callee "
            "has an entry paragraph"
        )
